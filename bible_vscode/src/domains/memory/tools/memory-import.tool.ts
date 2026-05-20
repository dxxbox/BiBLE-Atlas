import * as vscode from 'vscode';
import { MemoryService } from '../memory-service';
import { TaskTracker } from '../../../core/task/task-tracker';
import { Notifications } from '../../../core/ui/notifications';
import { OutputChannel } from '../../../core/ui/output-channel';
import { ExtensionConfig } from '../../../core/config/extension-config';
import { ChatTurn } from '../../../core/lm/budget';

export interface MemoryImportInput {
  title?: string;
  messages: ChatTurn[];
}

export interface MemoryImportDeps {
  service: MemoryService;
  tasks: TaskTracker;
  notify: Notifications;
  output: OutputChannel;
  config: ExtensionConfig;
}

/**
 * `bible_memory_import` —— 异步写入工具。
 * 与 `AsyncBibleTool` 基类不同的是：本工具的"提交"不是单次 cli.run，
 * 而是 service.importFromMessages（含 LM 构建 + 双文件写盘 + cli.run import），
 * 所以单独实现，不继承 AsyncBibleTool。
 */
export class MemoryImportTool implements vscode.LanguageModelTool<MemoryImportInput> {
  constructor(private readonly deps: MemoryImportDeps) {}

  async prepareInvocation(
    opts: vscode.LanguageModelToolInvocationPrepareOptions<MemoryImportInput>,
  ): Promise<vscode.PreparedToolInvocation> {
    const count = opts.input.messages?.length ?? 0;
    const title = opts.input.title ?? '(auto-generated title)';
    return {
      invocationMessage: `Preparing memory entry from ${count} messages...`,
      confirmationMessages: {
        title: 'Save to Bible Memory?',
        message: new vscode.MarkdownString(
          `Save **${count} messages** as a memory entry?\n\n` +
          `- title: ${title}\n` +
          `- kb_index: \`${this.deps.config.memoryDefaultKbIndex()}\`\n\n` +
          `The original chat will be stored as an artifact, and a structured summary will be indexed for retrieval.`,
        ),
      },
    };
  }

  async invoke(opts: vscode.LanguageModelToolInvocationOptions<MemoryImportInput>): Promise<vscode.LanguageModelToolResult> {
    const input = opts.input;
    if (!Array.isArray(input.messages) || input.messages.length === 0) {
      return new vscode.LanguageModelToolResult([
        new vscode.LanguageModelTextPart('No messages provided. bible_memory_import requires a non-empty `messages` array.'),
      ]);
    }

    const handle = await this.deps.tasks.submit({
      taskType: 'import.memory',
      domain: 'memory',
      title: `Saving memory: ${input.title ?? input.messages[0]?.content?.slice(0, 40) ?? '(no title)'}`,
      submit: async () => {
        const resp = await this.deps.service.importFromMessages({
          messages: input.messages,
          title: input.title,
        });
        return { task_id: resp.task_id };
      },
      showProgress: true,
      onCompleted: async (record) => {
        const sessionId = (record.result as { session_id?: string } | undefined)?.session_id;
        await this.notifyCompleted(sessionId, record.taskId);
      },
    });

    return new vscode.LanguageModelToolResult([
      new vscode.LanguageModelTextPart(
        `Memory import queued. task_id: \`${handle.taskId}\`. ` +
        `Progress is shown in VSCode notifications; you can follow up with bible_task_status.`,
      ),
    ]);
  }

  private async notifyCompleted(sessionId: string | undefined, taskId: string): Promise<void> {
    const wantCopy = this.deps.config.memoryCopySessionIdOnSave() && sessionId;
    const actions = [wantCopy ? 'Copy session_id' : null, 'Show in OutputChannel'].filter(Boolean) as string[];

    const pick = await this.deps.notify.info(
      sessionId ? `Memory saved. session_id=${sessionId}` : `Memory import completed. task_id=${taskId}`,
      ...actions,
    );
    if (pick === 'Copy session_id' && sessionId) {
      await vscode.env.clipboard.writeText(sessionId);
    } else if (pick === 'Show in OutputChannel') {
      this.deps.output.show(true);
    }
  }
}
