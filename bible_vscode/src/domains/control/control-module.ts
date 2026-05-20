import * as vscode from 'vscode';
import { DomainModule, ModuleDeps } from '../types';
import { CapabilityManifest } from '../../core/registry/capability';
import { HealthTool } from './tools/health.tool';
import { TaskStatusTool } from './tools/task-status.tool';
import { registerSelfCheckCommand } from './commands/self-check.command';
import { registerShowTaskStatusCommand } from './commands/task-status.command';
import { registerToggleDryRunCommand } from './commands/toggle-dry-run.command';

export class ControlModule implements DomainModule {
  readonly id = 'control' as const;

  capabilities(): CapabilityManifest {
    return {
      required: [{ command: ['health'] }],
      optional: [{ command: ['task', 'get'], featureFlag: 'control.task' }],
    };
  }

  register(_ctx: vscode.ExtensionContext, deps: ModuleDeps): vscode.Disposable[] {
    const disposables: vscode.Disposable[] = [];

    // Tools
    disposables.push(
      deps.toolRegistry.register('bible_health', new HealthTool({ cli: deps.cli, output: deps.output }, {
        name: 'bible_health',
        busyText: () => 'Checking bible CLI...',
      })),
    );
    disposables.push(
      deps.toolRegistry.register('bible_task_status', new TaskStatusTool({ cli: deps.cli, output: deps.output }, {
        name: 'bible_task_status',
        busyText: (i) => `Looking up task ${i.taskId}...`,
      })),
    );

    // Commands
    disposables.push(registerSelfCheckCommand(deps));
    disposables.push(registerShowTaskStatusCommand(deps));
    disposables.push(registerToggleDryRunCommand(deps));

    return disposables;
  }
}
