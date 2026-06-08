import * as vscode from 'vscode';
import { MemoryService } from '../memory-service';
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
  notify: Notifications;
  output: OutputChannel;
  config: ExtensionConfig;
}

/**
 * LM Tool: bible_memory_download
 *
 * 让 LM Agent 能按需下载并缓存 memory source 文件。
 * 复用 ensureLocalSource 的缓存+集成下载逻辑；不再单独维护 3 步 TaskTracker 流。
 */
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
          `Download \`${opts.input.storagePath}\` to local cache?`,
        ),
      },
    };
  }

  async invoke(opts: vscode.LanguageModelToolInvocationOptions<MemoryDownloadInput>): Promise<vscode.LanguageModelToolResult> {
    const input = opts.input;

    // ensureLocalSource 使用 session_id ?? storage_path 作为缓存键；
    // LM Tool 只知道 storage_path，所以 session_id 留空，CLI 会按 storage_path 下载。
    const result = await this.deps.service.ensureLocalSource({
      hit: { session_id: '', storage_path: input.storagePath },
    });

    const label = result.fromCache ? 'cached' : 'downloaded';
    const pick = await this.deps.notify.info(
      `Memory file ${label}: ${result.path} (${result.sizeBytes} bytes)`,
      'Reveal in Explorer',
    );
    if (pick === 'Reveal in Explorer') {
      await vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(result.path));
    }

    return new vscode.LanguageModelToolResult([
      new vscode.LanguageModelTextPart(
        `Memory source ${label}. Local path: \`${result.path}\` (${result.sizeBytes} bytes).`,
      ),
    ]);
  }
}
