import * as vscode from 'vscode';
import { ModuleDeps } from '../../types';

export function registerShowTaskStatusCommand(deps: ModuleDeps): vscode.Disposable {
  return deps.commandRegistry.register('bible.task.showStatus', async () => {
    const active = deps.tasks.listActive();
    if (active.length === 0) {
      await deps.notify.info('No in-flight Bible tasks.');
      return;
    }
    const pick = await vscode.window.showQuickPick(
      active.map((t) => ({
        label: t.taskId,
        description: `${t.taskType} · ${t.status}`,
        detail: t.title,
        _ref: t,
      })),
      { title: 'In-flight Bible Tasks', placeHolder: 'Pick a task to inspect / cancel' },
    );
    if (!pick) return;

    const action = await vscode.window.showQuickPick(
      ['Show in OutputChannel', 'Cancel task'],
      { placeHolder: `Task ${pick.label} (${pick._ref.status})` },
    );
    if (action === 'Cancel task') {
      await deps.tasks.cancel(pick._ref.taskId);
      await deps.notify.info(`Task ${pick._ref.taskId} cancellation requested.`);
    } else if (action === 'Show in OutputChannel') {
      deps.output.show(true);
    }
  });
}
