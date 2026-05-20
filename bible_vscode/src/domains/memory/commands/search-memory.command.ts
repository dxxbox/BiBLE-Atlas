import * as vscode from 'vscode';
import { ModuleDeps } from '../../types';
import { MemoryService } from '../memory-service';
import { selectOneOrTop } from '../../../core/ui/quick-pick';
import { formatHit } from '../memory-format';

export function registerSearchMemoryCommand(deps: ModuleDeps, service: MemoryService): vscode.Disposable {
  return deps.commandRegistry.register('bible.memory.search', async () => {
    const query = await vscode.window.showInputBox({
      title: 'Search Memory',
      prompt: 'Enter natural-language query',
      placeHolder: 'e.g. how did we fix the NPE in the user service?',
    });
    if (!query) return;

    const result = await deps.notify.withProgress(`Searching memory: ${query}`, async () => {
      return service.search({ query, topK: 10 });
    });

    const pick = await selectOneOrTop(result.results, {
      interactive: true,
      title: `Memory: ${result.total} results`,
      placeholder: 'Pick a memory entry to preview',
      toQuickPickItem: (hit) => ({
        label: hit.session_id,
        description: `score=${hit.score.toFixed(3)}`,
        detail: hit.abstract,
      }),
    });

    if (pick.mode === 'no-results') {
      await deps.notify.info('No memory results found.');
      return;
    }
    if (pick.mode === 'cancelled' || !pick.selected) return;

    const doc = await vscode.workspace.openTextDocument({
      language: 'markdown',
      content: formatHit(pick.selected, 1),
    });
    await vscode.window.showTextDocument(doc, { preview: true });
  });
}
