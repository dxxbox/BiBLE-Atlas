import * as vscode from 'vscode';

/**
 * 类型安全的 bible.* 配置访问 + 变更监听。
 * 任何配置项加入 package.json 的 contributes.configuration 时，需要在这里同步加方法。
 */
export interface ExtensionConfig {
  cliPath(): string;
  cliTimeoutMs(): number;
  cliTestMode(): boolean;

  taskPollIntervalMs(): number;
  taskMaxWaitMs(): number;
  taskPersistOnReload(): boolean;

  memoryDefaultKbIndex(): string;
  memoryDefaultVectorModel(): string;
  memoryDownloadDir(): string;
  memoryLmModelPriority(): string[];
  memoryLmConvMaxChars(): number;
  memoryLmTurnMaxChars(): number;
  memoryCopySessionIdOnSave(): boolean;
  memorySourceFormat(): string;

  toolsDisabled(): string[];

  debugDryRun(): boolean;
  debugPrintPayloads(): boolean;
  debugPayloadMaxChars(): number;
  debugKeepTempFiles(): boolean;

  setDebugDryRun(value: boolean, target?: vscode.ConfigurationTarget): Thenable<void>;

  onDidChange(listener: (e: vscode.ConfigurationChangeEvent) => void): vscode.Disposable;
}

const ROOT = 'bible';

function get<T>(key: string, defaultValue: T): T {
  const cfg = vscode.workspace.getConfiguration(ROOT);
  return cfg.get<T>(key, defaultValue);
}

export class VsCodeExtensionConfig implements ExtensionConfig {
  cliPath(): string { return get<string>('cliPath', 'bible'); }
  cliTimeoutMs(): number { return get<number>('cli.timeoutMs', 30000); }
  cliTestMode(): boolean { return get<boolean>('cli.testMode', false); }

  taskPollIntervalMs(): number { return get<number>('task.pollIntervalMs', 2000); }
  taskMaxWaitMs(): number { return get<number>('task.maxWaitMs', 600000); }
  taskPersistOnReload(): boolean { return get<boolean>('task.persistOnReload', true); }

  memoryDefaultKbIndex(): string { return get<string>('memory.defaultKbIndex', 'memory_main'); }
  memoryDefaultVectorModel(): string { return get<string>('memory.defaultVectorModel', ''); }
  memoryDownloadDir(): string { return get<string>('memory.downloadDir', '${workspaceFolder}/.bible/memory'); }
  memoryLmModelPriority(): string[] {
    return get<string[]>('memory.lmModelPriority', [
      'copilot/gpt-4.1', 'copilot/gpt-4o', 'copilot/claude-sonnet-4-5',
      'copilot/claude-sonnet-4', 'copilot/gemini-2.5-pro',
    ]);
  }
  memoryLmConvMaxChars(): number { return get<number>('memory.lmConvMaxChars', 80000); }
  memoryLmTurnMaxChars(): number { return get<number>('memory.lmTurnMaxChars', 3000); }
  memoryCopySessionIdOnSave(): boolean { return get<boolean>('memory.copySessionIdOnSave', true); }
  memorySourceFormat(): string { return get<string>('memory.sourceFormat', 'chat-export-json'); }

  toolsDisabled(): string[] { return get<string[]>('tools.disabled', []); }

  debugDryRun(): boolean { return get<boolean>('debug.dryRun', false); }
  debugPrintPayloads(): boolean { return get<boolean>('debug.printPayloads', true); }
  debugPayloadMaxChars(): number { return get<number>('debug.payloadMaxChars', 8000); }
  debugKeepTempFiles(): boolean { return get<boolean>('debug.keepTempFiles', true); }

  setDebugDryRun(value: boolean, target: vscode.ConfigurationTarget = vscode.ConfigurationTarget.Global): Thenable<void> {
    return vscode.workspace.getConfiguration(ROOT).update('debug.dryRun', value, target);
  }

  onDidChange(listener: (e: vscode.ConfigurationChangeEvent) => void): vscode.Disposable {
    return vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration(ROOT)) listener(e);
    });
  }
}
