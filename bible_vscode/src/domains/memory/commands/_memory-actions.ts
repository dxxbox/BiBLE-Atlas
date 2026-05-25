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
import { parseChatSource, renderChatMarkdown } from '../memory-format';
import { openChatAndAutoSend } from '../../../core/chat/chat-trigger';

export const LAST_LOADED_KEY = 'bible.memory.lastLoadedContext';

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
      'Pick **Load to @bible-memory** to download the full source and inject into chat.',
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
 * "加载到上下文"实现：
 *   1. 落一份 loaded-context.md 便于人工回看
 *   2. 把 LoadedContext 存 workspaceState，供 participant /load 读取
 *   3. 自动打开 Copilot Chat 并发送 "@bible-memory /load"
 *      → participant 把 hit 摘要 + source 全文写入 chat 历史
 */
export async function loadHitToContext(
  ctx: vscode.ExtensionContext,
  deps: ModuleDeps,
  service: MemoryService,
  hit: MemoryHit,
  sourceFilePath: string | undefined,
): Promise<void> {
  const mdPath = await service.loadHitToContextFile(hit, sourceFilePath);

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

  const opened = await openChatAndAutoSend('@bible-memory /load', deps.output);
  if (opened) {
    void deps.notify.info(
      sourceFilePath
        ? `Loaded "${hit.session_id}" + full source into @bible-memory chat.`
        : `Loaded "${hit.session_id}" (summary only) into @bible-memory chat. Download the source first to inject full content.`,
    );
  } else {
    // 这里仍然要 await：是用户必须看到的提示，且带按钮可点击
    const action = await deps.notify.warn(
      `Could not auto-open Copilot Chat in this IDE. Wrote ${mdPath}. Manually open Chat and type "@bible-memory /load".`,
      'Reveal File',
    );
    if (action === 'Reveal File') {
      await vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(mdPath));
    }
  }
}
