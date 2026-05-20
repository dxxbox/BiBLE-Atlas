import * as vscode from 'vscode';
import { ModuleDeps } from '../../types';
import { MemoryService } from '../memory-service';
import { formatHit } from '../memory-format';
import { selectOneOrTop } from '../../../core/ui/quick-pick';
import { MemoryHit } from '../memory-types';

const LAST_LOADED_KEY = 'bible.memory.lastLoadedContext';

/**
 * @bible-memory chat participant：
 *   /save             — 导出当前 chat → buildMeta → submitImport（不消耗 LM token）
 *   /search <query>   — 检索并以 markdown 流式返回到 Chat
 *   /load             — 复用上一次成功检索的上下文
 *   /load <query>     — 立即检索 + 自动选 top-1 + 注入
 *   /help             — 帮助
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
  const source = await service.exportCurrentChat();
  stream.progress(`Building meta from ${source.messages.length} messages...`);
  const built = await service.buildMeta({
    source: { session_id: source.session_id, exported_at: source.exported_at, messages: source.messages, raw: source.raw },
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
  let hit: MemoryHit | undefined;

  if (!query) {
    hit = ctx.workspaceState.get<MemoryHit>(LAST_LOADED_KEY);
    if (!hit) {
      stream.markdown('No previously loaded memory. Use `/load <query>` to search and load top-1.');
      return {};
    }
    stream.markdown(`Re-loading last context: \`${hit.session_id}\`\n\n`);
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
    hit = picked.selected;
    await ctx.workspaceState.update(LAST_LOADED_KEY, hit);
    stream.markdown(`Auto-selected top-1: \`${hit.session_id}\` (score=${hit.score.toFixed(3)})\n\n`);
  }

  stream.markdown(formatHit(hit, 1));
  deps.output.info('memory.participant.load', { sessionId: hit.session_id });
  return {};
}

function helpMarkdown(): string {
  return [
    '## @bible-memory',
    '',
    '- `/save` — save the current chat as a memory entry (no LM tokens consumed)',
    '- `/search <query>` — search saved memory and show results',
    '- `/load` — re-inject the previously selected memory entry',
    '- `/load <query>` — search and auto-load top-1',
    '- `/help` — this help',
  ].join('\n');
}
