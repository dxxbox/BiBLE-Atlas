import * as vscode from 'vscode';
import { CliRunner } from '../core/cli/cli-runner';
import { CapabilityManifest } from '../core/registry/capability';
import { CommandRegistry } from '../core/registry/command-registry';
import { ToolRegistry } from '../core/registry/tool-registry';
import { TaskTracker } from '../core/task/task-tracker';
import { Notifications } from '../core/ui/notifications';
import { OutputChannel } from '../core/ui/output-channel';
import { ExtensionConfig } from '../core/config/extension-config';

export interface ModuleDeps {
  cli: CliRunner;
  tasks: TaskTracker;
  toolRegistry: ToolRegistry;
  commandRegistry: CommandRegistry;
  notify: Notifications;
  output: OutputChannel;
  config: ExtensionConfig;
}

export interface DomainModule {
  readonly id: 'memory' | 'skill' | 'knowledge_base' | 'control';
  capabilities(): CapabilityManifest;
  register(ctx: vscode.ExtensionContext, deps: ModuleDeps): vscode.Disposable[];
}
