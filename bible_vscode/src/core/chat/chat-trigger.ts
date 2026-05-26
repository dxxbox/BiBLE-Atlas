import * as vscode from 'vscode';
import { OutputChannel } from '../ui/output-channel';

/**
 * 尝试打开 Chat 视图并以给定 prompt 自动发送一次请求。
 *
 * 不同 IDE / 不同 Copilot 版本的命令名不一致，按可能性从高到低逐个尝试：
 *   1. VSCode `workbench.action.chat.open` —— 接受 { query, isPartialQuery }
 *      isPartialQuery=false 时按官方语义会"提交"该 query
 *   2. VSCode 简版 `workbench.action.chat.open` —— 只传 query 字符串
 *   3. `workbench.action.chat.openInSidebar` —— 老版本兜底
 *   4. Cursor `composer.startComposerPrompt` / `aichat.newchataction` —— Cursor 兼容
 *   5. 仅 focus chat 视图 —— 最差兜底
 *
 * 任一变体成功（不抛错）即返回 true；用户随后看到 chat 自动打开并触发 participant。
 */
export async function openChatAndAutoSend(prompt: string, output: OutputChannel): Promise<boolean> {
  const variants: Array<{ name: string; run: () => Thenable<unknown> }> = [
    {
      name: 'workbench.action.chat.open (object args)',
      run: () => vscode.commands.executeCommand('workbench.action.chat.open', { query: prompt, isPartialQuery: false }),
    },
    {
      name: 'workbench.action.chat.open (string query)',
      run: () => vscode.commands.executeCommand('workbench.action.chat.open', prompt),
    },
    {
      name: 'workbench.action.chat.openInSidebar',
      run: () => vscode.commands.executeCommand('workbench.action.chat.openInSidebar', { query: prompt }),
    },
    {
      name: 'composer.startComposerPrompt (cursor)',
      run: () => vscode.commands.executeCommand('composer.startComposerPrompt', { prompt }),
    },
    {
      name: 'aichat.newchataction (cursor)',
      run: () => vscode.commands.executeCommand('aichat.newchataction', { prompt }),
    },
    {
      name: 'workbench.panel.chat.view.copilot.focus (focus only)',
      run: () => vscode.commands.executeCommand('workbench.panel.chat.view.copilot.focus'),
    },
  ];

  for (const v of variants) {
    try {
      await v.run();
      output.info('chat.trigger.success', { variant: v.name });
      return true;
    } catch (err) {
      output.debug('chat.trigger.variant.failed', { variant: v.name, error: (err as Error).message });
    }
  }
  output.warn('chat.trigger.allFailed', { prompt });
  return false;
}
