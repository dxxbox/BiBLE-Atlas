import * as vscode from 'vscode';
import { BibleTool } from '../../../core/tool/bible-tool';
import { CliInvocation } from '../../../core/cli/cli-runner';
import { MemorySearchResult, SearchType } from '../memory-types';
import { formatSearchResultForLM } from '../memory-format';

export interface MemorySearchInput {
  query: string;
  topK?: number;
  searchType?: SearchType;
}

export class MemorySearchTool extends BibleTool<MemorySearchInput, MemorySearchResult> {
  protected buildArgs(input: MemorySearchInput): CliInvocation {
    const args: string[] = ['memory', 'search', '--query', input.query, '--tag', 'memory'];
    if (input.topK !== undefined) args.push('--top-k', String(input.topK));
    if (input.searchType) args.push('--search-type', input.searchType);
    return { args };
  }

  protected format(data: MemorySearchResult, _input: MemorySearchInput): vscode.LanguageModelToolResult {
    return new vscode.LanguageModelToolResult([
      new vscode.LanguageModelTextPart(formatSearchResultForLM(data)),
    ]);
  }
}
