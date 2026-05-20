import * as vscode from 'vscode';
import { ModuleDeps } from '../../types';
import { MemoryService } from '../memory-service';

export function registerSaveChatCommand(deps: ModuleDeps, service: MemoryService): vscode.Disposable {
  return deps.commandRegistry.register('bible.memory.saveCurrentChat', async () => {
    try {
      const resp = await deps.notify.withProgress('Saving current chat to memory...', async (_progress, token) => {
        return service.importCurrentChat({ cancellationToken: token });
      });

      const wantCopy = deps.config.memoryCopySessionIdOnSave() && resp.session_id;
      const actions = [wantCopy ? 'Copy session_id' : null, 'Show in OutputChannel'].filter(Boolean) as string[];
      const pick = await deps.notify.info(
        resp.session_id
          ? `Memory queued. session_id=${resp.session_id}, task=${resp.task_id}`
          : `Memory import task queued: ${resp.task_id}`,
        ...actions,
      );
      if (pick === 'Copy session_id' && resp.session_id) {
        await vscode.env.clipboard.writeText(resp.session_id);
      } else if (pick === 'Show in OutputChannel') {
        deps.output.show(true);
      }
    } catch (err) {
      await deps.notify.error(`Save current chat failed: ${(err as Error).message}`);
    }
  });
}
