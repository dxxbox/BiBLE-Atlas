import * as vscode from 'vscode';
import { CliRunner, ExecFileCliRunner } from './core/cli/cli-runner';
import { DryRunCliRunner } from './core/cli/dry-run-runner';
import { VsCodeOutputChannel } from './core/ui/output-channel';
import { VsCodeNotifications } from './core/ui/notifications';
import { VsCodeExtensionConfig } from './core/config/extension-config';
import { DefaultToolRegistry } from './core/registry/tool-registry';
import { DefaultCommandRegistry } from './core/registry/command-registry';
import { CapabilityProbe } from './core/registry/capability-probe';
import { GlobalStateTaskStore } from './core/task/task-store';
import { DefaultTaskTracker } from './core/task/task-tracker';
import { DomainModule, ModuleDeps } from './domains/types';
import { ControlModule } from './domains/control/control-module';
import { MemoryModule } from './domains/memory/memory-module';

export async function activate(ctx: vscode.ExtensionContext): Promise<void> {
  const output = new VsCodeOutputChannel('Bible');
  ctx.subscriptions.push({ dispose: () => output.dispose() });

  const config = new VsCodeExtensionConfig();
  const notify = new VsCodeNotifications();

  const dryRun = config.debugDryRun();
  const testMode = config.cliTestMode();
  const cli: CliRunner = dryRun
    ? new DryRunCliRunner({ output, config })
    : new ExecFileCliRunner({
        cliPath: config.cliPath(),
        defaultTimeoutMs: config.cliTimeoutMs(),
        testMode,
        output,
      });

  if (dryRun) {
    output.warn('extension.dryRun.enabled', {
      hint: 'CLI calls will NOT be executed; payloads will be dumped to this channel. Disable with `bible.debug.dryRun=false`.',
    });
    output.show(true);
  }
  if (testMode && !dryRun) {
    output.warn('extension.testMode.enabled', {
      hint: 'All CLI calls will include --test flag. The Go CLI returns mock data without contacting the server. Disable with `bible.cli.testMode=false`.',
    });
    output.show(true);
  }

  const toolRegistry = new DefaultToolRegistry(output, () => config.toolsDisabled());
  const commandRegistry = new DefaultCommandRegistry(output);

  const taskStore = new GlobalStateTaskStore(ctx.globalState);
  await taskStore.gc();

  const tasks = new DefaultTaskTracker({ cli, notify, output, config, store: taskStore });

  const deps: ModuleDeps = { cli, tasks, toolRegistry, commandRegistry, notify, output, config };

  const modules: DomainModule[] = [
    new ControlModule(),
    new MemoryModule(),
    // 未来：new SkillModule(), new KnowledgeBaseModule(), ...
  ];

  for (const m of modules) {
    const disposables = m.register(ctx, deps);
    ctx.subscriptions.push(...disposables);
    output.info('module.registered', { id: m.id, count: disposables.length });
  }

  // CapabilityProbe（dry-run 模式下跳过，避免触发 CLI 实际探测；DryRunCliRunner 对 unknown 命令会返回 CLI_NOT_IMPLEMENTED）
  if (!dryRun) {
    const probe = new CapabilityProbe(cli, output);
    void runCapabilityProbe(probe, deps, modules);
  } else {
    output.info('capability.probe.skipped', { reason: 'dry-run' });
  }

  // 配置变更监听：CLI / dryRun 相关项改了提示重启
  ctx.subscriptions.push(
    config.onDidChange((e) => {
      if (
        e.affectsConfiguration('bible.cliPath') ||
        e.affectsConfiguration('bible.cli.timeoutMs') ||
        e.affectsConfiguration('bible.cli.testMode') ||
        e.affectsConfiguration('bible.debug.dryRun')
      ) {
        void notify.info('Bible CLI / debug settings changed; reload window for changes to take effect.', 'Reload Window').then((pick) => {
          if (pick === 'Reload Window') void vscode.commands.executeCommand('workbench.action.reloadWindow');
        });
      }
    }),
  );

  output.info('extension.activated', {
    cliPath: dryRun ? '(dry-run, no CLI)' : config.cliPath(),
    dryRun,
    testMode: testMode && !dryRun,
    tools: toolRegistry.active(),
    commands: commandRegistry.active(),
  });
}

export function deactivate(): void {
  // resources released via ctx.subscriptions
}

async function runCapabilityProbe(probe: CapabilityProbe, deps: ModuleDeps, modules: DomainModule[]): Promise<void> {
  for (const m of modules) {
    try {
      const report = await probe.probe(m.id, m.capabilities());
      if (!report.available) {
        deps.output.warn('capability.required.missing', {
          domain: m.id,
          missing: report.missingRequired.map((r) => r.command.join(' ')),
        });
      }
      // 这里仅做日志；future: 根据 report.enabledFlags 决定是否注销具体工具
    } catch (err) {
      deps.output.error('capability.probe.failed', { domain: m.id, err: (err as Error).message });
    }
  }
}
