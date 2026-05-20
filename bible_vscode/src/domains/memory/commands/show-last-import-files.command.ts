import * as vscode from 'vscode';
import * as fs from 'node:fs/promises';
import { ModuleDeps } from '../../types';
import { getLastImportFiles, cleanupDir } from '../memory-service';

export function registerShowLastImportFilesCommand(deps: ModuleDeps): vscode.Disposable {
  return deps.commandRegistry.register('bible.memory.showLastImportFiles', async () => {
    const last = getLastImportFiles();
    if (!last) {
      await deps.notify.info('No memory import has been performed in this session yet.');
      return;
    }

    const items: Array<vscode.QuickPickItem & { _action: 'open-source' | 'open-meta' | 'reveal' | 'clear' | 'log' }> = [
      { label: '$(file-code) Open source.json', detail: last.sourceFile, _action: 'open-source' },
      { label: '$(json) Open meta.json',        detail: last.metaFile,   _action: 'open-meta' },
      { label: '$(folder-opened) Reveal directory', detail: last.dir,    _action: 'reveal' },
      { label: '$(output) Show in OutputChannel', detail: `session_id=${last.sessionId}, written_at=${last.writtenAt}`, _action: 'log' },
      { label: '$(trash) Clear temp directory',  detail: `delete ${last.dir}`, _action: 'clear' },
    ];

    const pick = await vscode.window.showQuickPick(items, {
      title: 'Last Memory Import — Temp Files',
      placeHolder: `session_id=${last.sessionId}`,
    });
    if (!pick) return;

    switch (pick._action) {
      case 'open-source':
        await openIfExists(last.sourceFile);
        break;
      case 'open-meta':
        await openIfExists(last.metaFile);
        break;
      case 'reveal':
        await vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(last.dir));
        break;
      case 'log':
        deps.output.info('memory.import.lastFiles', last as unknown as Record<string, unknown>);
        deps.output.show(true);
        break;
      case 'clear':
        await cleanupDir(last.dir);
        await deps.notify.info(`Cleared ${last.dir}`);
        break;
    }
  });
}

async function openIfExists(path: string): Promise<void> {
  try {
    await fs.access(path);
    const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(path));
    await vscode.window.showTextDocument(doc, { preview: false });
  } catch {
    await vscode.window.showErrorMessage(`File not found: ${path}`);
  }
}
