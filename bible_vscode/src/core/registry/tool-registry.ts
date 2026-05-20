import * as vscode from 'vscode';
import { OutputChannel } from '../ui/output-channel';

export interface ToolRegistry {
  register(name: string, tool: vscode.LanguageModelTool<unknown>): vscode.Disposable;
  /** capability 探测确认未实现时调用：从 VSCode 注销 + 标记为不可用 */
  disable(name: string, reason: string): void;
  isActive(name: string): boolean;
  active(): string[];
}

interface Entry {
  disposable: vscode.Disposable;
  active: boolean;
  reason?: string;
}

export class DefaultToolRegistry implements ToolRegistry {
  private readonly entries = new Map<string, Entry>();

  constructor(private readonly output: OutputChannel, private readonly disabledByConfig: () => string[]) {}

  register(name: string, tool: vscode.LanguageModelTool<unknown>): vscode.Disposable {
    if (this.disabledByConfig().includes(name)) {
      this.output.info('tool.disabledByConfig', { name });
      return { dispose() { /* no-op */ } };
    }
    const disposable = vscode.lm.registerTool(name, tool);
    this.entries.set(name, { disposable, active: true });
    this.output.info('tool.registered', { name });

    // 包装 disposable，确保 dispose 时同步状态
    return {
      dispose: () => {
        const entry = this.entries.get(name);
        if (entry && entry.active) {
          entry.disposable.dispose();
          entry.active = false;
        }
      },
    };
  }

  disable(name: string, reason: string): void {
    const entry = this.entries.get(name);
    if (!entry || !entry.active) return;
    entry.disposable.dispose();
    entry.active = false;
    entry.reason = reason;
    this.output.warn('tool.disabled', { name, reason });
  }

  isActive(name: string): boolean {
    return this.entries.get(name)?.active === true;
  }

  active(): string[] {
    return [...this.entries.entries()].filter(([, v]) => v.active).map(([k]) => k);
  }
}
