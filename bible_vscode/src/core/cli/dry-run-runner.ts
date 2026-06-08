import * as fs from 'node:fs';
import * as path from 'node:path';
import * as crypto from 'node:crypto';
import { CliEnvelope, CliInvocation, CliRunner } from './cli-runner';
import { BibleCliError } from './cli-error';
import { OutputChannel } from '../ui/output-channel';
import { ExtensionConfig } from '../config/extension-config';

/**
 * Debug 模式专用 CliRunner：
 *
 *   - 不调用真 bible 二进制
 *   - 把命令完整 args / 临时文件路径 / 临时文件**内容** / 假响应都打印到 OutputChannel
 *   - 命令所需的临时文件（--source-file / --meta-file / --paths-file / --input-file）保留不删
 *   - 返回类型合理的 fake envelope，让 TaskTracker / onCompleted / 通知按钮等 UX 流程能完整走通
 *
 * 设计目标：让开发者在真 CLI 没就位时也能**端到端验证插件的输入数据是否准备正确**：
 *   - LM 提取出的 meta.json 是不是该样子
 *   - source.json 是不是该样子
 *   - CLI 命令名 + flag + 顺序对不对
 */
export class DryRunCliRunner implements CliRunner {
  /** 跟踪已经发出的 task_id → 用于 task get 返回 completed */
  private readonly tasks = new Map<string, { task_type: string; result: Record<string, unknown> }>();

  constructor(private readonly opts: { output: OutputChannel; config: ExtensionConfig }) {}

  async run<T>(call: CliInvocation): Promise<T> {
    const env = await this.runRaw<T>(call);
    if (!env.ok || env.error) {
      throw BibleCliError.fromEnvelope(env.error ?? { code: 'CLI_ERROR', message: 'dry-run: synthetic error' });
    }
    if (env.data === undefined) {
      throw new BibleCliError('CLI_ERROR', 'dry-run: missing fake data');
    }
    return env.data;
  }

  async runRaw<T>(call: CliInvocation): Promise<CliEnvelope<T>> {
    this.opts.output.info('[DRY-RUN] cli.invoke', {
      cmd: `bible ${call.args.join(' ')}`,
      args: call.args,
    });

    this.dumpFileArgs(call.args);

    const env = this.fakeEnvelopeFor<T>(call.args);
    this.opts.output.info('[DRY-RUN] cli.fakeResponse', env as unknown as Record<string, unknown>);
    return env;
  }

  // ---------- 文件参数回显 ----------

  private dumpFileArgs(args: string[]): void {
    // 对于 memory upload，args[2] 是 session_dir，展示目录内的 message.json / meta.json
    if (args[0] === 'memory' && args[1] === 'upload' && args[2] && !args[2].startsWith('--')) {
      const sessionDir = args[2];
      for (const name of ['message.json', 'meta.json']) {
        this.dumpFile(`(dir)${name}`, path.join(sessionDir, name));
      }
      return;
    }
    // 其余命令：检查 --*-file 型 flag
    const flagsThatPointToFiles = ['--input-file', '--paths-file'];
    for (let i = 0; i < args.length; i++) {
      if (!flagsThatPointToFiles.includes(args[i])) continue;
      const filePath = args[i + 1];
      if (!filePath || filePath.startsWith('--')) continue;
      this.dumpFile(args[i], filePath);
    }
  }

  private dumpFile(flag: string, filePath: string): void {
    try {
      const stat = fs.statSync(filePath);
      this.opts.output.info('[DRY-RUN] cli.tempFile', {
        flag,
        path: filePath,
        size_bytes: stat.size,
        link: `file://${filePath}`,
      });

      if (!this.opts.config.debugPrintPayloads()) return;

      const cap = this.opts.config.debugPayloadMaxChars();
      const raw = fs.readFileSync(filePath, 'utf-8');
      const body = raw.length > cap ? raw.slice(0, cap) + `\n…(truncated ${raw.length - cap} chars)` : raw;
      this.opts.output.info(`[DRY-RUN] cli.tempFileContent (${flag})`, {
        path: filePath,
        body_length: raw.length,
      });
      this.opts.output.raw('----- BEGIN ' + path.basename(filePath) + ' -----');
      this.opts.output.raw(body);
      this.opts.output.raw('----- END   ' + path.basename(filePath) + ' -----');
    } catch (err) {
      this.opts.output.warn('[DRY-RUN] cli.tempFile.readFailed', {
        flag,
        path: filePath,
        error: (err as Error).message,
      });
    }
  }

  // ---------- 假响应工厂 ----------

  private fakeEnvelopeFor<T>(args: string[]): CliEnvelope<T> {
    const [cmd, sub, sub2] = args;

    if (cmd === 'health') {
      return ok({ cli: 'dry-run', version: '0.0.0-dry', server: { reachable: false, url: 'dry-run://no-cli' } });
    }

    if (cmd === 'memory') {
      if (sub === 'search') return ok(this.fakeSearch(args));
      if (sub === 'upload') return ok(this.registerUploadTask(args));
      if (sub === 'download') return ok(this.fakeIntegratedDownload(args));
    }

    if (cmd === 'task') {
      if (sub === 'get') return ok(this.fakeTaskGet(args));
      if (sub === 'cancel') return ok(this.fakeTaskCancel(args));
    }

    // 未识别命令 → 视为"CLI 未实现"，让降级路径覆盖
    return {
      ok: false,
      error: { code: 'CLI_NOT_IMPLEMENTED', message: `dry-run: no fake handler for: bible ${args.join(' ')}` },
    };
  }

  private fakeSearch(args: string[]): Record<string, unknown> {
    // CLI: memory search <query> [--top-k N] — query 是 positional (args[2])
    const query = args[2] ?? '(empty)';
    return {
      results: [
        mkHit('dry-session-aaa', 0.93, `Dry-run match for "${query}"`),
        mkHit('dry-session-bbb', 0.78, `Older dry-run note about "${query}"`),
      ],
      total: 2,
      kb_index: 'memory_main',
      tag: 'memory',
    };
  }

  private registerUploadTask(args: string[]): Record<string, unknown> {
    // CLI: memory upload <session_dir> [--kb-index K] — session_dir 是 positional (args[2])
    const flags = parseFlags(args);
    const sessionDir = args[2] ?? '';
    const kbIndex = (flags['--kb-index'] as string) ?? 'memory_main';
    const taskId = `dry-imp-${crypto.randomUUID().slice(0, 8)}`;
    const metaPath = sessionDir ? path.join(sessionDir, 'meta.json') : undefined;
    const sessionId = readSessionIdFromMeta(metaPath) ?? `dry-session-${crypto.randomUUID().slice(0, 8)}`;

    this.tasks.set(taskId, {
      task_type: 'import.memory',
      result: { session_id: sessionId, kb_index: kbIndex, chunks_count: 5 },
    });

    return { task_id: taskId, status: 'queued', kb_index: kbIndex, session_id: sessionId };
  }

  private fakeIntegratedDownload(args: string[]): Record<string, unknown> {
    // CLI: memory download --storage-path P --output DIR --download-name FILENAME
    // CLI 内部完成轮询+写盘，直接返回 {status: "downloaded", output_path}
    const flags = parseFlags(args);
    const outputDir = flags['--output'] as string | undefined;
    const downloadName = flags['--download-name'] as string | undefined;
    const storagePath = flags['--storage-path'] as string | undefined;

    if (!outputDir || !downloadName) {
      return {
        ok: false,
        error: { code: 'INVALID_ARGS', message: 'dry-run: --output and --download-name are required' },
      };
    }

    const outputPath = path.join(outputDir, downloadName);
    const content = JSON.stringify({
      source_format: 'bible-chat-v1',
      session_id: 'dry-download-session',
      exported_at: new Date().toISOString(),
      turns: [
        { role: 'user', content: `[dry-run] Downloaded source for ${storagePath ?? 'unknown'}` },
        { role: 'assistant', content: '[dry-run] This is a synthetic source file created by DryRunCliRunner.' },
      ],
    }, null, 2);

    try {
      fs.mkdirSync(outputDir, { recursive: true });
      fs.writeFileSync(outputPath, content);
      this.opts.output.info('[DRY-RUN] cli.download.wrote', { path: outputPath, size_bytes: content.length });
    } catch (err) {
      this.opts.output.warn('[DRY-RUN] cli.download.writeFailed', { path: outputPath, error: (err as Error).message });
    }

    return { status: 'downloaded', output_path: outputPath };
  }

  private fakeTaskGet(args: string[]): Record<string, unknown> {
    // CLI: task get <task_id> — task_id 是 positional (args[2])
    const id = args[2];
    if (!id) {
      return { task_id: '', task_type: 'unknown', status: 'failed', error: { code: 'INVALID_ARGS', message: 'task_id required' } };
    }
    const known = this.tasks.get(id);
    return {
      task_id: id,
      task_type: known?.task_type ?? 'unknown',
      status: 'completed',
      result: known?.result ?? { dry_run: true },
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
  }

  private fakeTaskCancel(args: string[]): Record<string, unknown> {
    // CLI: task cancel <task_id> — task_id 是 positional (args[2])
    return { task_id: args[2] ?? '', status: 'cancelled' };
  }
}

// ---------- helpers ----------

function ok<T>(data: unknown): CliEnvelope<T> {
  return { ok: true, data: data as T };
}

function parseFlags(args: string[]): Record<string, string | boolean> {
  const out: Record<string, string | boolean> = {};
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (!a.startsWith('--')) continue;
    const next = args[i + 1];
    if (!next || next.startsWith('--')) {
      out[a] = true;
    } else {
      out[a] = next;
      i++;
    }
  }
  return out;
}

function mkHit(sessionId: string, score: number, abstract: string): Record<string, unknown> {
  return {
    session_id: sessionId,
    storage_path: `dry-run/memory/${sessionId}.json`,
    abstract,
    score,
    hit_field: 'abstract',
    snippet: abstract,
    meta: { session_kind: 'mixed' },
  };
}

function readSessionIdFromMeta(filePath?: string): string | undefined {
  if (!filePath) return undefined;
  try {
    const raw = fs.readFileSync(filePath, 'utf-8');
    const obj = JSON.parse(raw) as { session_id?: string };
    return typeof obj.session_id === 'string' ? obj.session_id : undefined;
  } catch {
    return undefined;
  }
}
