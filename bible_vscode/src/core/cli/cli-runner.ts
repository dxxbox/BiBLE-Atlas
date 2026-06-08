import { execFile, ExecFileException } from 'node:child_process';
import { BibleCliError, BibleCliErrorCode } from './cli-error';
import { OutputChannel } from '../ui/output-channel';

export interface CliInvocation {
  args: string[];
  stdinPayload?: string;
  timeoutMs?: number;
}

export interface CliEnvelope<T = unknown> {
  ok: boolean;
  data?: T;
  error?: { code: string; message: string };
}

export interface CliRunner {
  /** 解包返回 data；失败抛 BibleCliError。 */
  run<T>(call: CliInvocation): Promise<T>;
  /** 不解包，原样返回 envelope。 */
  runRaw<T>(call: CliInvocation): Promise<CliEnvelope<T>>;
}

export interface CliRunnerOptions {
  cliPath: string;
  defaultTimeoutMs: number;
  output: OutputChannel;
  /** 大入参字节阈值，超过则改走 stdin（避免命令行长度上限）。 */
  stdinThresholdBytes?: number;
  /**
   * Test mode：向每次 CLI 调用**末尾**追加 `--test` 全局标志。
   * Go CLI 在收到该标志后直接返回 mock 数据，不联系服务端，
   * 用于客户端与 CLI 联调阶段（无需运行 Server）。
   */
  testMode?: boolean;
}

const DEFAULT_STDIN_THRESHOLD = 16 * 1024;

export class ExecFileCliRunner implements CliRunner {
  constructor(private readonly opts: CliRunnerOptions) {}

  async run<T>(call: CliInvocation): Promise<T> {
    const env = await this.runRaw<T>(call);
    if (!env.ok || env.error) {
      throw BibleCliError.fromEnvelope(env.error ?? { code: 'CLI_ERROR', message: 'unknown CLI error' });
    }
    if (env.data === undefined) {
      throw new BibleCliError('CLI_ERROR', 'CLI returned ok=true but missing data');
    }
    return env.data;
  }

  async runRaw<T>(call: CliInvocation): Promise<CliEnvelope<T>> {
    const startedAt = Date.now();
    const cliPath = this.opts.cliPath;
    const timeoutMs = call.timeoutMs ?? this.opts.defaultTimeoutMs;
    // Test mode: append --test so the Go CLI skips the server and returns mock data.
    const args = this.opts.testMode ? [...call.args, '--test'] : call.args;
    this.opts.output.debug('cli.invoke', { args, timeoutMs, testMode: this.opts.testMode ?? false });

    try {
      const stdout = await this.execFilePromise(cliPath, args, call.stdinPayload, timeoutMs);
      const env = this.parseEnvelope<T>(stdout);
      const elapsedMs = Date.now() - startedAt;
      this.opts.output.debug('cli.done', { args, elapsedMs, ok: env.ok });
      return env;
    } catch (err) {
      const elapsedMs = Date.now() - startedAt;
      const mapped = this.mapExecError(err, { ...call, args });
      this.opts.output.error('cli.failed', { args, elapsedMs, code: mapped.code, message: mapped.message });
      throw mapped;
    }
  }

  private execFilePromise(
    file: string,
    args: string[],
    stdinPayload: string | undefined,
    timeoutMs: number,
  ): Promise<string> {
    return new Promise((resolve, reject) => {
      const child = execFile(
        file,
        args,
        { timeout: timeoutMs, maxBuffer: 50 * 1024 * 1024 },
        (err, stdout, stderr) => {
          if (err) {
            // execFile populates code / signal; attach stdout/stderr for envelope parsing fallback.
            (err as ExecFileException & { stdout?: string; stderr?: string }).stdout = String(stdout ?? '');
            (err as ExecFileException & { stdout?: string; stderr?: string }).stderr = String(stderr ?? '');
            reject(err);
            return;
          }
          resolve(String(stdout ?? ''));
        },
      );

      if (stdinPayload && child.stdin) {
        child.stdin.write(stdinPayload);
        child.stdin.end();
      }
    });
  }

  private parseEnvelope<T>(stdout: string): CliEnvelope<T> {
    const trimmed = stdout.trim();
    if (!trimmed) {
      throw new BibleCliError('CLI_ERROR', 'CLI returned empty stdout');
    }
    try {
      return JSON.parse(trimmed) as CliEnvelope<T>;
    } catch {
      throw new BibleCliError('CLI_ERROR', `CLI returned non-JSON output: ${trimmed.slice(0, 200)}`);
    }
  }

  private mapExecError(err: unknown, call: CliInvocation & { args: string[] }): BibleCliError {
    if (err instanceof BibleCliError) return err;

    const e = err as ExecFileException & { code?: string | number; stdout?: string; stderr?: string };
    const argsStr = call.args.join(' ');

    if (e?.code === 'ENOENT') {
      return new BibleCliError(
        'CLI_NOT_FOUND',
        `bible CLI not found at "${this.opts.cliPath}". Set "bible.cliPath" in settings.`,
        undefined,
        e,
      );
    }
    if (e?.signal === 'SIGTERM' || e?.killed) {
      return new BibleCliError('TIMEOUT', `CLI call timed out: bible ${argsStr}`, undefined, e);
    }

    // exit=3 is reserved for CLI_NOT_IMPLEMENTED in cli-contract-v1.
    const exit = typeof e?.code === 'number' ? e.code : undefined;

    // Prefer parsing envelope from stdout even on non-zero exit (CLI 协议要求失败也走 stdout JSON).
    if (e?.stdout) {
      try {
        const env = JSON.parse(e.stdout.trim()) as CliEnvelope;
        if (env?.error) {
          return BibleCliError.fromEnvelope(env.error, exit, env);
        }
      } catch {
        // fall through
      }
    }

    if (exit === 3) {
      return new BibleCliError('CLI_NOT_IMPLEMENTED', `CLI sub-command not implemented: bible ${argsStr}`, exit, e);
    }

    return new BibleCliError(
      'CLI_ERROR',
      e?.message ?? `CLI failed: bible ${argsStr}`,
      exit,
      e,
    );
  }
}

/** 把任意 unknown 错误归一化为 BibleCliError（其它层兜底用）。 */
export function toBibleCliError(err: unknown, fallbackCode: BibleCliErrorCode = 'INTERNAL'): BibleCliError {
  if (err instanceof BibleCliError) return err;
  const message = err instanceof Error ? err.message : String(err);
  return new BibleCliError(fallbackCode, message);
}
