/**
 * Memory 命令路径共享动作（被 search / download 复用）。
 *
 * 设计目标：把"准备 source 文件 → 在编辑器里打开 → 注入到 Chat"这三个原子动作
 * 提取出来，使 search-memory 与 download-memory 表现一致，避免行为漂移。
 */
import * as vscode from 'vscode';
import * as fs from 'node:fs/promises';
import { ModuleDeps } from '../../types';
import { MemoryService } from '../memory-service';
import { LoadedContext, MemoryHit } from '../memory-types';
import { buildLoadedContextMarkdown, parseChatSource, renderChatMarkdown } from '../memory-format';

export const LAST_LOADED_KEY = 'bible.memory.lastLoadedContext';

/** 命令 ID：复制 @bible-memory /load 到剪贴板（由 memory-module 注册）。 */
export const CMD_COPY_LOAD_CMD = 'bible.memory.copyLoadCmd';

/** 模块级状态栏 item，loadHitToContext 调用后一直显示，直到下次加载或扩展停用。 */
let _loadedBar: vscode.StatusBarItem | undefined;

/**
 * 创建/更新状态栏条目，显示"已加载某 session，点击复制 @bible-memory /load"。
 * 每次 loadHitToContext 调用时刷新文本，旧 item 复用（不重复创建）。
 */
export function updateLoadedContextBar(sessionId: string): void {
  if (!_loadedBar) {
    _loadedBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 50);
    _loadedBar.command = CMD_COPY_LOAD_CMD;
  }
  _loadedBar.text = `$(bookmark) Memory: ${sessionId}`;
  _loadedBar.tooltip = new vscode.MarkdownString(
    `**Memory context loaded**: \`${sessionId}\`\n\nClick to copy \`@bible-memory /load\` to clipboard`,
  );
  _loadedBar.show();
}

/** 供 memory-module.ts 在停用时回收状态栏 item。 */
export function disposeLoadedContextBar(): void {
  _loadedBar?.dispose();
  _loadedBar = undefined;
}

/**
 * 把一条 hit 的"摘要视图"渲染成 markdown 并在编辑器里打开。
 *
 * 两种内容：
 *   - 始终显示：hit 字段（abstract / snippet / hit_field / storage_path / meta）
 *   - source 已缓存时：在 markdown 里附上对话全文渲染（bible-chat-v1 格式），
 *     并追加一个通知按钮"View as Chat"可以单独打开对话视图
 *
 * **不触发下载**——零副作用，QuickPick 不会卡。
 */
export async function previewHitSummary(
  service: MemoryService,
  hit: MemoryHit,
): Promise<void> {
  const cachedPath = service.getCachedSourcePath(hit);

  // --- 摘要部分（始终有）---
  const lines: string[] = [
    `# Memory Summary: \`${hit.session_id}\``,
    '',
    `- **score**: ${hit.score.toFixed(3)}`,
    `- **hit_field**: \`${hit.hit_field ?? '(none)'}\``,
    `- **storage_path**: \`${hit.storage_path}\``,
    '',
    '## Abstract',
    '',
    hit.abstract?.trim() || '_(empty)_',
  ];
  if (hit.snippet) {
    lines.push('', '## Snippet (server-highlighted)', '', '```', hit.snippet, '```');
  }
  if (hit.meta && Object.keys(hit.meta).length > 0) {
    lines.push('', '## Server-passthrough meta', '', '```json', JSON.stringify(hit.meta, null, 2), '```');
  }

  // --- source 部分 ---
  lines.push('', '---', '');
  if (cachedPath) {
    // 尝试读取并渲染对话内容（bible-chat-v1）
    let chatMarkdown: string | undefined;
    try {
      const raw = await fs.readFile(cachedPath, 'utf-8');
      const source = parseChatSource(raw);
      if (source) {
        chatMarkdown = renderChatMarkdown(source);
      }
    } catch {
      /* 读取失败不影响摘要显示 */
    }

    if (chatMarkdown) {
      lines.push('## Conversation', '', chatMarkdown);
    } else {
      lines.push(
        `_Source cached (format not bible-chat-v1 or unreadable):_`,
        '',
        `\`${cachedPath}\``,
      );
    }
  } else {
    lines.push(
      '_Source not downloaded yet._',
      '',
      'Pick **Load to @bible-memory** to download message.json and open it in the editor. Then type `@bible-memory /load` in Chat to inject.',
    );
  }

  const doc = await vscode.workspace.openTextDocument({
    language: 'markdown',
    content: lines.join('\n') + '\n',
  });
  await vscode.window.showTextDocument(doc, { preview: true, preserveFocus: true });
}

/**
 * 调 service.ensureLocalSource，包一层 withProgress + 用户提示 + 异常降级。
 *
 *   - 缓存命中：不弹通知，仅打日志，返回路径
 *   - 缓存未命中：走完整下载，完成后弹一条 "Downloaded ..." 通知
 *   - 失败 + allowDegrade=true：弹 Continue/Cancel；Continue 返回 undefined（让上层降级，例如只 Load summary）
 *   - 失败 + allowDegrade=false：弹 error，返回 undefined
 */
export async function ensureSourceWithProgress(
  deps: ModuleDeps,
  service: MemoryService,
  hit: MemoryHit,
  opts: { allowDegrade?: boolean } = {},
): Promise<string | undefined> {
  try {
    const result = await deps.notify.withProgress(
      `Preparing source for ${hit.session_id}...`,
      () => service.ensureLocalSource({ hit }),
    );
    if (result.fromCache) {
      deps.output.info('memory.source.usedCache', { sessionId: hit.session_id, path: result.path });
    } else {
      // fire-and-forget: 不 await，避免某些 IDE（如 Cursor）下没按钮的通知不 resolve 把流程吊死
      void deps.notify.info(`Downloaded source: ${result.path} (${result.sizeBytes} bytes)`);
      deps.output.info('memory.source.downloaded', { sessionId: hit.session_id, path: result.path, sizeBytes: result.sizeBytes });
    }
    return result.path;
  } catch (err) {
    const msg = (err as Error).message;
    if (opts.allowDegrade) {
      const pick = await deps.notify.warn(
        `Could not fetch source (${msg}). Continue with summary only?`,
        'Continue',
        'Cancel',
      );
      return pick === 'Continue' ? undefined : undefined;
    }
    await deps.notify.error(`Source download failed: ${msg}`);
    return undefined;
  }
}

/**
 * "加载到上下文"实现（无 Chat 自动操作版）：
 *
 *   1. 把 message.json 原对话渲染为 Markdown 写到 `loaded-context.md`
 *   2. 把 LoadedContext 存 workspaceState，供 `@bible-memory /load` 读取
 *   3. 在编辑器里（旁开新列）打开 `loaded-context.md`，用户可阅读原对话
 *   4. 弹通知告知用户去 Chat 里输入 `@bible-memory /load`（participant 会把对话流入历史）
 *
 * **不会触发任何 Chat 面板命令**，彻底避免误发送。
 */
export async function loadHitToContext(
  ctx: vscode.ExtensionContext,
  deps: ModuleDeps,
  service: MemoryService,
  hit: MemoryHit,
  sourceFilePath: string | undefined,
): Promise<void> {
  // 1. 写 loaded-context.md（原对话 Markdown）
  const mdPath = await service.loadHitToContextFile(hit, sourceFilePath);

  // 2. 存 workspaceState，供 @bible-memory /load 读取
  const context: LoadedContext = {
    hit,
    sourceFilePath,
    loadedContextMdPath: mdPath,
    loadedAt: new Date().toISOString(),
  };
  await ctx.workspaceState.update(LAST_LOADED_KEY, context);
  deps.output.info('memory.context.markedLoaded', {
    sessionId: hit.session_id,
    sourceFilePath: sourceFilePath ?? '(not downloaded)',
    mdPath,
  });

  // 3. 在当前编辑器列打开 loaded-context.md 供阅读
  try {
    const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(mdPath));
    await vscode.window.showTextDocument(doc, { preview: true, preserveFocus: false });
  } catch {
    // 打开失败不影响主流程
  }

  // 4. 更新状态栏（持久显示，不会自动消失，点击复制 @bible-memory /load）
  updateLoadedContextBar(hit.session_id);

  // 5. 弹一条即时通知，提示用户看状态栏（不带按钮，fire-and-forget）
  void deps.notify.info(
    sourceFilePath
      ? `Memory "${hit.session_id}" ready — click the status bar item to copy @bible-memory /load`
      : `Memory "${hit.session_id}" (summary) ready — click the status bar item to copy @bible-memory /load`,
  );
}
