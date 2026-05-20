import * as vscode from 'vscode';
import * as path from 'node:path';
import { MemoryService } from '../memory-service';
import { TaskTracker } from '../../../core/task/task-tracker';
import { Notifications } from '../../../core/ui/notifications';
import { OutputChannel } from '../../../core/ui/output-channel';
import { ExtensionConfig } from '../../../core/config/extension-config';

export interface MemoryDownloadInput {
  storagePath: string;
  downloadName?: string;
  outputDir?: string;
}

export interface MemoryDownloadDeps {
  service: MemoryService;
  tasks: TaskTracker;
  notify: Notifications;
  output: OutputChannel;
  config: ExtensionConfig;
}

export class MemoryDownloadTool implements vscode.LanguageModelTool<MemoryDownloadInput> {
  constructor(private readonly deps: MemoryDownloadDeps) {}

  async prepareInvocation(
    opts: vscode.LanguageModelToolInvocationPrepareOptions<MemoryDownloadInput>,
  ): Promise<vscode.PreparedToolInvocation> {
    return {
      invocationMessage: `Downloading memory: ${opts.input.storagePath}`,
      confirmationMessages: {
        title: 'Download memory file?',
        message: new vscode.MarkdownString(
          `Download \`${opts.input.storagePath}\` to ${opts.input.outputDir ?? this.deps.config.memoryDownloadDir()}?`,
        ),
      },
    };
  }

  async invoke(opts: vscode.LanguageModelToolInvocationOptions<MemoryDownloadInput>): Promise<vscode.LanguageModelToolResult> {
    const input = opts.input;
    const outputDir = resolveOutputDir(input.outputDir ?? this.deps.config.memoryDownloadDir());

    const handle = await this.deps.tasks.submit({
      taskType: 'download.memory',
      domain: 'memory',
      title: `Downloading memory: ${input.storagePath}`,
      submit: async () => {
        const resp = await this.deps.service.submitDownloadFile({
          storagePath: input.storagePath,
          downloadName: input.downloadName,
        });
        return { task_id: resp.task_id };
      },
      showProgress: true,
      onCompleted: async (record) => {
        const result = record.result as { artifact_id?: string; artifact_name?: string } | undefined;
        if (!result?.artifact_id) {
          await this.deps.notify.warn('Download task completed but no artifact_id returned.');
          return;
        }
        const fileName = input.downloadName ?? result.artifact_name ?? `memory-${record.taskId}`;
        const outputPath = path.join(outputDir, fileName);
        const fetched = await this.deps.service.fetchArtifact({ artifactId: result.artifact_id, outputPath });
        const pick = await this.deps.notify.info(
          `Memory file downloaded: ${fetched.path} (${fetched.size_bytes} bytes)`,
          'Reveal in Explorer',
        );
        if (pick === 'Reveal in Explorer') {
          await vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(fetched.path));
        }
      },
    });

    return new vscode.LanguageModelToolResult([
      new vscode.LanguageModelTextPart(`Memory download queued. task_id: \`${handle.taskId}\`.`),
    ]);
  }
}

function resolveOutputDir(template: string): string {
  const ws = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  return template.replace('${workspaceFolder}', ws ?? process.cwd());
}
