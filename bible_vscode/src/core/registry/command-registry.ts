import * as vscode from 'vscode';
import { OutputChannel } from '../ui/output-channel';

export interface CommandRegistry {
  register(id: string, handler: (...args: unknown[]) => unknown): vscode.Disposable;
  disable(id: string, reason: string): void;
  isActive(id: string): boolean;
  active(): string[];
}

interface Entry {
  disposable: vscode.Disposable;
  active: boolean;
  reason?: string;
}

export class DefaultCommandRegistry implements CommandRegistry {
  private readonly entries = new Map<string, Entry>();

  constructor(private readonly output: OutputChannel) {}

  register(id: string, handler: (...args: unknown[]) => unknown): vscode.Disposable {
    const disposable = vscode.commands.registerCommand(id, handler);
    this.entries.set(id, { disposable, active: true });
    this.output.info('command.registered', { id });

    return {
      dispose: () => {
        const entry = this.entries.get(id);
        if (entry && entry.active) {
          entry.disposable.dispose();
          entry.active = false;
        }
      },
    };
  }

  disable(id: string, reason: string): void {
    const entry = this.entries.get(id);
    if (!entry || !entry.active) return;
    entry.disposable.dispose();
    entry.active = false;
    entry.reason = reason;
    this.output.warn('command.disabled', { id, reason });
  }

  isActive(id: string): boolean {
    return this.entries.get(id)?.active === true;
  }

  active(): string[] {
    return [...this.entries.entries()].filter(([, v]) => v.active).map(([k]) => k);
  }
}
