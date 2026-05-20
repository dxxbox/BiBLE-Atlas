import * as vscode from 'vscode';
import { ModuleDeps } from '../../types';
import { detectCli } from '../../../core/cli/cli-detector';
import { selectPreferredModel } from '../../../core/lm/model-selector';
import { exportCurrentChat } from '../../../core/chat/chat-export';

/**
 * `Bible: Run Self-Check`：把 CLI / LM / chat export / capability 四个面挨个干跑一次，
 * 把结果以 markdown 文档形式呈现给用户。
 */
export function registerSelfCheckCommand(deps: ModuleDeps): vscode.Disposable {
  return deps.commandRegistry.register('bible.runSelfCheck', async () => {
    const lines: string[] = ['# Bible Self-Check', ''];

    // CLI
    const cliResult = await detectCli(deps.cli);
    if (cliResult.ok) {
      lines.push('## CLI');
      lines.push(`- ok: \`${cliResult.info.cli}\` @ \`${cliResult.info.version}\``);
      if (cliResult.info.server) {
        lines.push(`- server reachable: \`${cliResult.info.server.reachable}\``);
      }
    } else {
      lines.push('## CLI');
      lines.push(`- FAILED: \`${cliResult.error.code}\` ${cliResult.error.message}`);
    }
    lines.push('');

    // LM
    const model = await selectPreferredModel(deps.config.memoryLmModelPriority());
    lines.push('## LM');
    if (model) {
      lines.push(`- selected: \`${model.vendor}/${model.family}\``);
    } else {
      lines.push('- no model available; rule-based fallback will be used for memory extraction');
    }
    lines.push('');

    // Chat export
    lines.push('## Chat Export');
    try {
      const exp = await exportCurrentChat(deps.output);
      lines.push(`- strategy: \`${exp.strategy}\`, turns: ${exp.messages.length}, session_id: \`${exp.session_id}\``);
    } catch (err) {
      lines.push(`- FAILED: ${(err as Error).message}`);
    }
    lines.push('');

    // Active tools / commands
    lines.push('## Active Tools / Commands');
    lines.push(`- tools: ${deps.toolRegistry.active().map((t) => '`' + t + '`').join(', ') || '(none)'}`);
    lines.push(`- commands: ${deps.commandRegistry.active().map((t) => '`' + t + '`').join(', ') || '(none)'}`);
    lines.push('');

    // In-flight tasks
    const active = deps.tasks.listActive();
    lines.push(`## In-flight Tasks: ${active.length}`);
    for (const t of active) {
      lines.push(`- \`${t.taskId}\` (${t.taskType}, ${t.status})`);
    }

    const doc = await vscode.workspace.openTextDocument({ language: 'markdown', content: lines.join('\n') });
    await vscode.window.showTextDocument(doc, { preview: true });
  });
}
