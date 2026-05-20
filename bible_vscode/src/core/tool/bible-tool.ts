import * as vscode from 'vscode';
import { CliInvocation, CliRunner } from '../cli/cli-runner';
import { TaskRecord } from '../task/task-types';
import { TaskTracker } from '../task/task-tracker';
import { OutputChannel } from '../ui/output-channel';

export interface ToolMeta<I = unknown> {
  name: string;
  busyText: (input: I) => string;
}

export interface BibleToolDeps {
  cli: CliRunner;
  output: OutputChannel;
}

/**
 * 同步类工具基类：CLI 调用 → 格式化文本结果。
 */
export abstract class BibleTool<I, O> implements vscode.LanguageModelTool<I> {
  constructor(protected deps: BibleToolDeps, protected meta: ToolMeta<I>) {}

  /** 返回需要执行的 CLI 调用 */
  protected abstract buildArgs(input: I): CliInvocation;

  /** 把 CLI 解出的 data 翻译成 LM 友好的结果 */
  protected abstract format(data: O, input: I): vscode.LanguageModelToolResult;

  /** 写操作覆盖此方法返回确认信息；只读默认返回 undefined */
  protected confirmation(_input: I): vscode.LanguageModelToolConfirmationMessages | undefined {
    return undefined;
  }

  async invoke(opts: vscode.LanguageModelToolInvocationOptions<I>): Promise<vscode.LanguageModelToolResult> {
    const data = await this.deps.cli.run<O>(this.buildArgs(opts.input));
    return this.format(data, opts.input);
  }

  async prepareInvocation(
    opts: vscode.LanguageModelToolInvocationPrepareOptions<I>,
  ): Promise<vscode.PreparedToolInvocation> {
    return {
      invocationMessage: this.meta.busyText(opts.input),
      confirmationMessages: this.confirmation(opts.input),
    };
  }
}

export interface AsyncBibleToolDeps extends BibleToolDeps {
  tasks: TaskTracker;
}

/**
 * 异步任务类工具基类（import / download）：
 *   - 提交 CLI 任务 → TaskTracker 跟进 → 立即返回 task_id 文本
 *   - 不阻塞 LM 等任务完成
 */
export abstract class AsyncBibleTool<I> implements vscode.LanguageModelTool<I> {
  constructor(protected deps: AsyncBibleToolDeps, protected meta: ToolMeta<I>) {}

  protected abstract buildArgs(input: I): CliInvocation;
  protected abstract taskType(): string;
  protected abstract domain(): TaskRecord['domain'];
  protected abstract titleFor(input: I): string;
  protected onCompleted?(input: I, record: TaskRecord): Promise<void>;

  protected confirmation(_input: I): vscode.LanguageModelToolConfirmationMessages | undefined {
    return undefined;
  }

  async invoke(opts: vscode.LanguageModelToolInvocationOptions<I>): Promise<vscode.LanguageModelToolResult> {
    const handle = await this.deps.tasks.submit({
      taskType: this.taskType(),
      domain: this.domain(),
      title: this.titleFor(opts.input),
      submit: () => this.deps.cli.run<{ task_id: string }>(this.buildArgs(opts.input)),
      showProgress: true,
      onCompleted: this.onCompleted ? (rec) => this.onCompleted!(opts.input, rec) : undefined,
    });

    return new vscode.LanguageModelToolResult([
      new vscode.LanguageModelTextPart(
        `Task **${handle.taskId}** queued. Progress is shown in the notification area; ` +
        `you can also query later with \`bible_task_status\`.`,
      ),
    ]);
  }

  async prepareInvocation(
    opts: vscode.LanguageModelToolInvocationPrepareOptions<I>,
  ): Promise<vscode.PreparedToolInvocation> {
    return {
      invocationMessage: this.meta.busyText(opts.input),
      confirmationMessages: this.confirmation(opts.input),
    };
  }
}
