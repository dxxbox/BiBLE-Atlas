import * as vscode from 'vscode';
import * as path from 'node:path';
import { ModuleDeps } from '../../types';
import { MemoryService } from '../memory-service';

export function registerDownloadMemoryCommand(deps: ModuleDeps, service: MemoryService): vscode.Disposable {
  return deps.commandRegistry.register('bible.memory.downloadFile', async () => {
    const storagePath = await vscode.window.showInputBox({
      title: 'Download Memory File',
      prompt: 'Enter the storage_path returned by a previous search',
    });
    if (!storagePath) return;

    const outputDir = resolveOutputDir(deps.config.memoryDownloadDir());

    try {
      const handle = await deps.tasks.submit({
        taskType: 'download.memory',
        domain: 'memory',
        title: `Downloading ${storagePath}`,
        submit: async () => service.submitDownloadFile({ storagePath }),
        showProgress: true,
        onCompleted: async (record) => {
          const result = record.result as { artifact_id?: string; artifact_name?: string } | undefined;
          if (!result?.artifact_id) {
            await deps.notify.warn('Download task completed but no artifact_id returned.');
            return;
          }
          const fileName = result.artifact_name ?? `memory-${record.taskId}.json`;
          const outputPath = path.join(outputDir, fileName);
          const fetched = await service.fetchArtifact({ artifactId: result.artifact_id, outputPath });
          const pick = await deps.notify.info(
            `Memory file downloaded: ${fetched.path} (${fetched.size_bytes} bytes)`,
            'Reveal in Explorer',
          );
          if (pick === 'Reveal in Explorer') {
            await vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(fetched.path));
          }
        },
      });
      deps.output.info('memory.download.queued', { taskId: handle.taskId, storagePath });
    } catch (err) {
      await deps.notify.error(`Download failed: ${(err as Error).message}`);
    }
  });
}

function resolveOutputDir(template: string): string {
  const ws = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  return template.replace('${workspaceFolder}', ws ?? process.cwd());
}
