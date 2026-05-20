import * as vscode from 'vscode';
import { BibleTool } from '../../../core/tool/bible-tool';
import { CliInvocation } from '../../../core/cli/cli-runner';
import { CliInfo } from '../../../core/cli/cli-detector';

// eslint-disable-next-line @typescript-eslint/no-empty-interface
export interface HealthInput {}

export class HealthTool extends BibleTool<HealthInput, CliInfo> {
  protected buildArgs(_input: HealthInput): CliInvocation {
    return { args: ['health'] };
  }
  protected format(data: CliInfo, _input: HealthInput): vscode.LanguageModelToolResult {
    const lines = [
      `**Bible CLI health**`,
      `- cli: \`${data.cli}\``,
      `- version: \`${data.version}\``,
    ];
    if (data.server) {
      lines.push(`- server reachable: \`${data.server.reachable}\`${data.server.url ? ` (\`${data.server.url}\`)` : ''}`);
    }
    return new vscode.LanguageModelToolResult([new vscode.LanguageModelTextPart(lines.join('\n'))]);
  }
}
