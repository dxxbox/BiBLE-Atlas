import * as vscode from 'vscode';
import { DomainModule, ModuleDeps } from '../types';
import { CapabilityManifest } from '../../core/registry/capability';
import { HealthTool } from './tools/health.tool';
import { TaskStatusTool } from './tools/task-status.tool';
import { registerSelfCheckCommand } from './commands/self-check.command';
import { registerShowTaskStatusCommand } from './commands/task-status.command';
import { registerToggleDryRunCommand } from './commands/toggle-dry-run.command';
import { registerOpenMockProfileCommand } from './commands/open-mock-profile.command';

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

    // Commands (面板可见的用户命令)
    disposables.push(registerSelfCheckCommand(deps));
    disposables.push(registerShowTaskStatusCommand(deps));
    // Hidden debug commands (代码注册但 package.json 不暴露到命令面板；
    // 需要时通过 keybinding 或 vscode.commands.executeCommand('bible.debug.*') 调用)
    disposables.push(registerToggleDryRunCommand(deps));
    disposables.push(registerOpenMockProfileCommand(deps));

    return disposables;
  }
}
