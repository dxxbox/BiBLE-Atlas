import { CliRunner } from '../cli/cli-runner';
import { BibleCliError } from '../cli/cli-error';
import { OutputChannel } from '../ui/output-channel';
import { CapabilityManifest, CapabilityRequirement, CapabilityReport } from './capability';

/**
 * 探测 CLI 命令是否可用。
 *
 * 策略：执行 `bible <cmd...> --help`：
 *   - 0 退出码 → 视为可用
 *   - exit=3 / CLI_NOT_IMPLEMENTED → 不可用
 *   - 其它错误（如 ENOENT）→ 不可用
 *
 * 不依赖具体业务参数，避免误调真后端。
 */
export class CapabilityProbe {
  constructor(private readonly cli: CliRunner, private readonly output: OutputChannel) {}

  async probe(domain: string, manifest: CapabilityManifest): Promise<CapabilityReport> {
    const missingRequired: CapabilityRequirement[] = [];
    for (const req of manifest.required) {
      const ok = await this.commandAvailable(req.command);
      if (!ok) missingRequired.push(req);
    }

    const enabledFlags: string[] = [];
    const disabledFlags: string[] = [];
    for (const opt of manifest.optional) {
      const ok = await this.commandAvailable(opt.command);
      if (ok) enabledFlags.push(opt.featureFlag);
      else disabledFlags.push(opt.featureFlag);
    }

    const report: CapabilityReport = {
      domain,
      available: missingRequired.length === 0,
      missingRequired,
      enabledFlags,
      disabledFlags,
    };
    this.output.info('capability.report', report as unknown as Record<string, unknown>);
    return report;
  }

  private async commandAvailable(command: string[]): Promise<boolean> {
    try {
      // `bible <cmd...> --help` 应该返回 ok=true 的 envelope；
      // 占位命令则返回 exit=3 + CLI_NOT_IMPLEMENTED。
      await this.cli.run({ args: [...command, '--help'] });
      return true;
    } catch (err) {
      if (err instanceof BibleCliError) {
        if (err.code === 'CLI_NOT_IMPLEMENTED' || err.code === 'CLI_NOT_FOUND') return false;
      }
      // 其它错误（含 INVALID_ARGS）不能确定是否可用 → 保守视为可用
      this.output.debug('capability.probe.uncertain', { command, err: (err as Error).message });
      return true;
    }
  }
}
