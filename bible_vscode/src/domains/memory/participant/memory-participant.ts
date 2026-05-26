import * as vscode from 'vscode';
import * as fs from 'node:fs/promises';
import { ModuleDeps } from '../../types';
import { MemoryService } from '../memory-service';
import { formatHit } from '../memory-format';
import { selectOneOrTop } from '../../../core/ui/quick-pick';
import { LoadedContext, MemoryHit } from '../memory-types';

const LAST_LOADED_KEY = 'bible.memory.lastLoadedContext';
/** stream 出来的 source 内容截断上限，避免巨大文件爆掉 chat。 */
const MAX_SOURCE_CHARS = 60_000;

/**
 * @bible-memory chat participant：
 *   /save             — 导出当前 chat → buildMeta → submitImport（不消耗 LM token）
 *   /search <query>   — 检索并以 markdown 流式返回到 Chat
 *   /load             — 复用上一次成功"加载"的上下文（命令路径或 participant 自身写入）
 *   /load <query>     — 立即检索 + 自动选 top-1 + 注入
 *   /help             — 帮助
 *
 * 「加载到上下文」的最终保证：/load 把 hit 摘要 + sourceFilePath 全文用
 * stream.markdown 输出 —— 这段输出即 chat 历史，下一轮 LM 必然能看到。
 */
export function registerMemoryParticipant(
  ctx: vscode.ExtensionContext,
  deps: ModuleDeps,
  service: MemoryService,
): vscode.Disposable {
  const participant = vscode.chat.createChatParticipant('bible.memoryParticipant', async (request, _ctxChat, stream, token) => {
    const cmd = request.command ?? 'help';
    try {
      switch (cmd) {
        case 'save':
          return await handleSave(deps, service, stream, token);
        case 'search':
          return await handleSearch(deps, service, request.prompt.trim(), stream);
        case 'load':
          return await handleLoad(ctx, deps, service, request.prompt.trim(), stream);
        case 'help':
        default:
          stream.markdown(helpMarkdown());
          return {};
      }
    } catch (err) {
      stream.markdown(`\n\n**Error**: ${(err as Error).message}`);
      return {};
    }
  });
  participant.iconPath = new vscode.ThemeIcon('database');
  return participant;
}

async function handleSave(
  deps: ModuleDeps,
  service: MemoryService,
  stream: vscode.ChatResponseStream,
  token: vscode.CancellationToken,
): Promise<vscode.ChatResult> {
  stream.progress('Exporting current chat...');
  const exported = await service.exportCurrentChat();
  stream.progress(`Building meta from ${exported.messages.length} messages...`);
  // toCleanSource is applied inside importCurrentChat; here we only need it for the progress message
  const built = await service.buildMeta({
    source: { source_format: 'bible-chat-v1', session_id: exported.session_id, exported_at: exported.exported_at, turns: exported.messages },
    cancellationToken: token,
  });
  stream.progress(`Submitting import (${built.via}-based)...`);
  const resp = await service.importCurrentChat({ cancellationToken: token });
  stream.markdown(`Memory queued for indexing.\n\n- task: \`${resp.task_id}\`\n- session_id: \`${resp.session_id}\`\n- kb_index: \`${resp.kb_index}\``);
  if (deps.config.memoryCopySessionIdOnSave()) {
    await vscode.env.clipboard.writeText(resp.session_id);
    stream.markdown(`\n\n_session_id copied to clipboard._`);
  }
  return {};
}

async function handleSearch(
  _deps: ModuleDeps,
  service: MemoryService,
  query: string,
  stream: vscode.ChatResponseStream,
): Promise<vscode.ChatResult> {
  if (!query) {
    stream.markdown('Usage: `@bible-memory /search <your query>`');
    return {};
  }
  stream.progress(`Searching memory: ${query}`);
  const result = await service.search({ query, topK: 5 });
  if (result.results.length === 0) {
    stream.markdown(`_No memory found for "${query}"._`);
    return {};
  }
  stream.markdown(`Found **${result.total}** entries (showing ${result.results.length}):\n`);
  result.results.forEach((hit, idx) => stream.markdown('\n' + formatHit(hit, idx + 1)));
  return {};
}

async function handleLoad(
  ctx: vscode.ExtensionContext,
  deps: ModuleDeps,
  service: MemoryService,
  query: string,
  stream: vscode.ChatResponseStream,
): Promise<vscode.ChatResult> {
  let context: LoadedContext | undefined;

  if (!query) {
    context = readLoadedContext(ctx);
    if (!context) {
      stream.markdown('No previously loaded memory. Use `/load <query>` to search and load top-1, or invoke "Bible: Search Memory → Load to @bible-memory" from the command palette.');
      return {};
    }
    stream.markdown(`Re-injecting last loaded context: \`${context.hit.session_id}\` (loaded at ${context.loadedAt}).\n\n`);
  } else {
    stream.progress(`Searching memory: ${query}`);
    const result = await service.search({ query, topK: 10 });
    const picked = await selectOneOrTop(result.results, {
      interactive: false,
      toQuickPickItem: (h) => ({ label: h.session_id, description: `score=${h.score.toFixed(3)}`, detail: h.abstract }),
    });
    if (picked.mode === 'no-results' || !picked.selected) {
      stream.markdown(`_No memory found for "${query}"._`);
      return {};
    }
    const hit = picked.selected;
    stream.markdown(`Auto-selected top-1: \`${hit.session_id}\` (score=${hit.score.toFixed(3)})\n\n`);

    // 自动 ensureLocalSource：缓存命中直接复用，否则触发后台下载并等待
    let sourceFilePath: string | undefined;
    try {
      stream.progress('Preparing source...');
      const ensured = await service.ensureLocalSource({ hit });
      sourceFilePath = ensured.path;
      stream.markdown(
        ensured.fromCache
          ? `_(source from cache: \`${ensured.path}\`)_\n\n`
          : `_(downloaded: \`${ensured.path}\`, ${ensured.sizeBytes} bytes)_\n\n`,
      );
    } catch (err) {
      stream.markdown(`_(source unavailable: ${(err as Error).message}; loading summary only)_\n\n`);
    }

    context = { hit, sourceFilePath, loadedAt: new Date().toISOString() };
    await ctx.workspaceState.update(LAST_LOADED_KEY, context);
  }

  // 1. 摘要（abstract / overview / 元数据）
  stream.markdown(formatHit(context.hit, 1));

  // 2. 如果绑了 sourceFilePath，把全文也流出来 —— 这是 LM 看到完整原文的唯一可靠途径
  if (context.sourceFilePath) {
    try {
      const raw = await fs.readFile(context.sourceFilePath, 'utf-8');
      const body = raw.length > MAX_SOURCE_CHARS
        ? raw.slice(0, MAX_SOURCE_CHARS) + `\n\n... [truncated ${raw.length - MAX_SOURCE_CHARS} chars]`
        : raw;
      stream.markdown('\n\n---\n\n### Full source content\n\n');
      stream.markdown('```json\n' + body + '\n```\n');
      stream.reference(vscode.Uri.file(context.sourceFilePath));
      deps.output.info('memory.participant.load.sourceStreamed', {
        sessionId: context.hit.session_id,
        sourceFile: context.sourceFilePath,
        chars: body.length,
        truncated: raw.length > MAX_SOURCE_CHARS,
      });
    } catch (err) {
      stream.markdown(`\n\n_(Source file not readable: \`${context.sourceFilePath}\` — ${(err as Error).message}.)_`);
    }
  } else {
    stream.markdown('\n\n---\n\n_Source file not downloaded yet. Run **Bible: Download Memory File** to fetch the full content; the next `/load` will inject it._');
  }

  // 3. 同时把 loaded-context.md 作为 reference 列出，便用户回顾
  if (context.loadedContextMdPath) {
    stream.reference(vscode.Uri.file(context.loadedContextMdPath));
  }

  return {};
}

/** 读取 workspaceState，向前兼容老版本只存 MemoryHit 的格式。 */
function readLoadedContext(ctx: vscode.ExtensionContext): LoadedContext | undefined {
  const raw = ctx.workspaceState.get<LoadedContext | MemoryHit>(LAST_LOADED_KEY);
  if (!raw) return undefined;
  if ('hit' in raw && raw.hit && typeof raw.hit === 'object') return raw as LoadedContext;
  // 老格式：裸 MemoryHit
  return { hit: raw as MemoryHit, loadedAt: 'unknown' };
}

function helpMarkdown(): string {
  return [
    '## @bible-memory',
    '',
    '- `/save` — save the current chat as a memory entry (no LM tokens consumed)',
    '- `/search <query>` — search saved memory and show results',
    '- `/load` — re-inject the previously loaded memory entry (set via /load <query> here, or via the command palette "Bible: Search Memory → Load to @bible-memory")',
    '- `/load <query>` — search and auto-load top-1',
    '- `/help` — this help',
  ].join('\n');
}
