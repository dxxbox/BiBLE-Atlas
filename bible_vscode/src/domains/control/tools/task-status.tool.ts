import * as vscode from 'vscode';
import { BibleTool } from '../../../core/tool/bible-tool';
import { CliInvocation } from '../../../core/cli/cli-runner';
import { TaskGetResponse } from '../../../core/task/task-types';

export interface TaskStatusInput {
  taskId: string;
}

export class TaskStatusTool extends BibleTool<TaskStatusInput, TaskGetResponse> {
  protected buildArgs(input: TaskStatusInput): CliInvocation {
    return { args: ['task', 'get', '--id', input.taskId] };
  }
  protected format(data: TaskGetResponse, input: TaskStatusInput): vscode.LanguageModelToolResult {
    const lines = [
      `**Task ${input.taskId}**`,
      `- type: \`${data.task_type}\``,
      `- status: \`${data.status}\``,
    ];
    if (data.error) {
      lines.push(`- error: \`${data.error.code}\` ${data.error.message}`);
    }
    if (data.result) {
      lines.push('- result:', '```json', JSON.stringify(data.result, null, 2), '```');
    }
    return new vscode.LanguageModelToolResult([new vscode.LanguageModelTextPart(lines.join('\n'))]);
  }
}
