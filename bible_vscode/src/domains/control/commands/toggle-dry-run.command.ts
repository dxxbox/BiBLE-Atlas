import * as vscode from 'vscode';
import { ModuleDeps } from '../../types';

export function registerToggleDryRunCommand(deps: ModuleDeps): vscode.Disposable {
  return deps.commandRegistry.register('bible.debug.toggleDryRun', async () => {
    const current = deps.config.debugDryRun();
    const next = !current;
    await deps.config.setDebugDryRun(next, vscode.ConfigurationTarget.Workspace);
    await deps.notify.info(
      `Bible dry-run mode is now ${next ? 'ON' : 'OFF'}. Reload window for the new runner to take effect.`,
      'Reload Window',
    ).then((pick) => {
      if (pick === 'Reload Window') void vscode.commands.executeCommand('workbench.action.reloadWindow');
    });
  });
}
