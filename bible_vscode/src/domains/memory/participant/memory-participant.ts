import * as vscode from 'vscode';
import { ModuleDeps } from '../../types';
import { MemoryService } from '../memory-service';
import { formatHit, buildLoadedContextMarkdown, DEFAULT_LOAD_CONTEXT_MAX_CHARS } from '../memory-format';
import { selectOneOrTop } from '../../../core/ui/quick-pick';
import { LoadedContext, MemoryHit } from '../memory-types';

const LAST_LOADED_KEY = 'bible.memory.lastLoadedContext';

/**
 * @bible-memory chat participant：
 *   /save             — 保存当前对话到 memory：自动导出 Copilot Chat；失败时可选 JSON 导出文件 → submitImport
 *   /search <query>   — 检索并以 markdown 流式返回到 Chat
 *   /load             — 复用上一次「加载到上下文」的 memory（message.json 原对话写入本轮回复）
 *   /load <query>     — 立即检索 + 自动选 top-1 + 同上
 *   /help             — 帮助
 *
 * 流程：命令面板「Bible: Search Memory」→ 选中结果 → Load to @bible-memory
 *   → 对话在编辑器里打开（供阅读） → 用户在 Chat 里输入 `/load` → participant 把对话流入历史。
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
  stream.progress('Saving current chat to memory...');
  const resp = await service.importCurrentChat({ cancellationToken: token });
  const sessionId = resp.session_id ?? resp.memory_id ?? '(pending)';
  const kbIndex = resp.kb_index ?? '(default)';
  stream.markdown(`Memory queued for indexing.\n\n- task: \`${resp.task_id}\`\n- session_id: \`${sessionId}\`\n- kb_index: \`${kbIndex}\``);
  if (deps.config.memoryCopySessionIdOnSave() && resp.session_id) {
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
      stream.markdown(
        'No previously loaded memory.\n\n' +
        'Use **Bible: Search Memory** in the command palette → select a result → **Load to @bible-memory** ' +
        '(opens conversation in editor). Then come back here and use `/load` to inject it.\n\n' +
        'Or use `/load <query>` here to search and auto-inject top-1.',
      );
      return {};
    }
    stream.markdown(`_Memory \`${context.hit.session_id}\` · loaded at ${context.loadedAt}_\n\n`);
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
    stream.markdown(`Selected top-1: \`${hit.session_id}\` (score=${hit.score.toFixed(3)})\n\n`);

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

  // message.json 原对话（Markdown）；不含检索 abstract 摘要
  const body = await buildLoadedContextMarkdown(context.hit, context.sourceFilePath, DEFAULT_LOAD_CONTEXT_MAX_CHARS);
  stream.markdown(body);

  if (context.sourceFilePath) {
    stream.reference(vscode.Uri.file(context.sourceFilePath));
    deps.output.info('memory.participant.load.conversationStreamed', {
      sessionId: context.hit.session_id,
      messageJson: context.sourceFilePath,
    });
  }

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
    '- `/save` — save the current chat as a memory entry; if automatic Copilot export fails (e.g. in Cursor), pick a `.json` chat export file (same format as VS Code Copilot export)',
    '- `/search <query>` — search saved memory and show results',
    '- `/load` — paste the last **message.json conversation** (from "Search Memory → Load") into this chat as assistant output',
    "- `/load <query>` — search, pick top-1, then paste that entry's **message.json** conversation here",
    '- `/help` — this help',
  ].join('\n');
}
