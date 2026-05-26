import * as vscode from 'vscode';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import * as os from 'node:os';
import * as crypto from 'node:crypto';
import { CliRunner, CliInvocation } from '../../core/cli/cli-runner';
import { ExtensionConfig } from '../../core/config/extension-config';
import { OutputChannel } from '../../core/ui/output-channel';
import { TaskTracker } from '../../core/task/task-tracker';
import { ChatExportResult, exportCurrentChat, fromMessages, toCleanSource, rawJson } from '../../core/chat/chat-export';
import { ChatTurn } from '../../core/lm/budget';
import { MemoryBuilder } from './memory-builder';
import {
  ArtifactFetchResponse,
  ChatSource,
  MemoryHit,
  MemoryMeta,
  MemorySearchResult,
  SearchType,
  SubmitDownloadResponse,
  SubmitImportResponse,
} from './memory-types';
import { formatHit } from './memory-format';

/** 最近一次 import 写出的临时文件路径（debug 用）。 */
export interface LastImportFiles {
  dir: string;
  sourceFile: string;
  metaFile: string;
  /** 原始 VSCode export，本地留存供测试验证，不发给 server。 */
  rawFile?: string;
  sessionId: string;
  writtenAt: string;
}

let lastImportFiles: LastImportFiles | undefined;
export function getLastImportFiles(): LastImportFiles | undefined { return lastImportFiles; }
function setLastImportFiles(f: LastImportFiles): void { lastImportFiles = f; }

/**
 * MemoryService —— Memory 域对 CLI 的薄封装。Tool / Command / Participant 都通过它使用 CLI，
 * 不允许在外部直接拼命令字符串。
 *
 * 对外契约（CLI 参数）按 framework v4 §8.1 / collab-plan §3.1 定义；
 * 如真 CLI 命令名调整，只需要修改本文件即可。
 */
export interface MemoryService {
  search(input: { query: string; topK?: number; searchType?: SearchType; vectorModel?: string }): Promise<MemorySearchResult>;

  exportCurrentChat(): Promise<ChatExportResult>;

  buildMeta(input: {
    source: ChatSource;
    sessionId?: string;
    title?: string;
    cancellationToken?: vscode.CancellationToken;
  }): Promise<{ meta: MemoryMeta; via: 'lm' | 'rules' }>;

  submitImport(input: {
    sourceFile: string;
    metaFile: string;
    kbIndex?: string;
    vectorModel?: string;
  }): Promise<SubmitImportResponse>;

  importCurrentChat(input?: {
    kbIndex?: string;
    cancellationToken?: vscode.CancellationToken;
  }): Promise<SubmitImportResponse>;

  /** 给 LM Tool 入参路径用：LM 把 messages 作为参数传入。 */
  importFromMessages(input: {
    messages: ChatTurn[];
    title?: string;
    kbIndex?: string;
    cancellationToken?: vscode.CancellationToken;
  }): Promise<SubmitImportResponse>;

  submitDownloadFile(input: {
    storagePath: string;
    downloadName?: string;
  }): Promise<SubmitDownloadResponse>;

  fetchArtifact(input: {
    artifactId: string;
    outputPath: string;
  }): Promise<ArtifactFetchResponse>;

  /**
   * 把一个 search hit 渲染为 markdown 写到 `${ws}/.bible/memory/loaded-context.md`，
   * 返回绝对路径。供命令路径"加载到上下文"使用（用户随后在 Chat 用 #file: 引用）。
   *
   * 同名文件**覆盖式**写入：始终只保留"最近一次加载"。
   */
  loadHitToContextFile(hit: MemoryHit, sourceFilePath?: string): Promise<string>;

  /**
   * 确保 hit 对应的 source.json 已在本地落盘，返回本地路径。
   *
   * 缓存策略（first version）：
   *   - 缓存目录：`bible.memory.downloadDir`（默认 `${workspaceFolder}/.bible/memory/`）
   *   - 缓存文件名：`<sanitize(session_id ?? storage_path)>.json`
   *   - 文件存在 → 视为命中，跳过下载
   *   - 文件不存在 → 内部走完整 download + task wait + artifact fetch 流程
   *
   * 不重复下载；下载失败抛错，由调用方决定降级（如只 Load summary）。
   */
  ensureLocalSource(input: EnsureSourceInput): Promise<EnsureSourceResult>;

  /** 仅查 cache，不发起下载。 */
  getCachedSourcePath(hit: Pick<MemoryHit, 'session_id' | 'storage_path'>): string | undefined;
}

export interface EnsureSourceInput {
  hit: Pick<MemoryHit, 'session_id' | 'storage_path'>;
  cancellationToken?: vscode.CancellationToken;
}

export interface EnsureSourceResult {
  path: string;
  fromCache: boolean;
  sizeBytes: number;
}

export interface MemoryServiceDeps {
  cli: CliRunner;
  config: ExtensionConfig;
  output: OutputChannel;
  builder: MemoryBuilder;
  /** 用于 ensureLocalSource 内部驱动异步下载任务并复用统一的进度/取消 UI。 */
  tasks: TaskTracker;
}

export class DefaultMemoryService implements MemoryService {
  constructor(private readonly deps: MemoryServiceDeps) {}

  // ---------- search ----------

  async search(input: { query: string; topK?: number; searchType?: SearchType; vectorModel?: string }): Promise<MemorySearchResult> {
    const args: string[] = ['memory', 'search', '--query', input.query, '--tag', 'memory'];
    if (input.topK !== undefined) args.push('--top-k', String(input.topK));
    if (input.searchType) args.push('--search-type', input.searchType);
    if (input.vectorModel) args.push('--vector-model', input.vectorModel);
    return this.deps.cli.run<MemorySearchResult>({ args });
  }

  // ---------- export ----------

  async exportCurrentChat(): Promise<ChatExportResult> {
    return exportCurrentChat(this.deps.output);
  }

  // ---------- build meta ----------

  async buildMeta(input: { source: ChatSource; sessionId?: string; title?: string; cancellationToken?: vscode.CancellationToken }): Promise<{ meta: MemoryMeta; via: 'lm' | 'rules' }> {
    const { meta, via } = await this.deps.builder.build({
      source: input.source,
      sessionId: input.sessionId,
      title: input.title,
      cancellationToken: input.cancellationToken,
    });
    return { meta, via };
  }

  // ---------- import (low-level) ----------

  async submitImport(input: { sourceFile: string; metaFile: string; kbIndex?: string; vectorModel?: string }): Promise<SubmitImportResponse> {
    const args: string[] = [
      'memory', 'import',
      '--tag', 'memory',
      '--kb-index', input.kbIndex ?? this.deps.config.memoryDefaultKbIndex(),
      '--source-file', input.sourceFile,
      '--meta-file', input.metaFile,
    ];
    const vectorModel = input.vectorModel ?? this.deps.config.memoryDefaultVectorModel();
    if (vectorModel) args.push('--vector-model', vectorModel);

    return this.deps.cli.run<SubmitImportResponse>({ args });
  }

  // ---------- import (high-level: from current chat) ----------

  async importCurrentChat(input?: { kbIndex?: string; cancellationToken?: vscode.CancellationToken }): Promise<SubmitImportResponse> {
    const exported = await this.exportCurrentChat();
    return this.importFromSource({
      exported,
      kbIndex: input?.kbIndex,
      cancellationToken: input?.cancellationToken,
    });
  }

  async importFromMessages(input: { messages: ChatTurn[]; title?: string; kbIndex?: string; cancellationToken?: vscode.CancellationToken }): Promise<SubmitImportResponse> {
    const exported = fromMessages(input.messages);
    return this.importFromSource({
      exported,
      title: input.title,
      kbIndex: input.kbIndex,
      cancellationToken: input.cancellationToken,
    });
  }

  private async importFromSource(input: {
    exported: ChatExportResult;
    title?: string;
    kbIndex?: string;
    cancellationToken?: vscode.CancellationToken;
  }): Promise<SubmitImportResponse> {
    const source = toCleanSource(input.exported);

    const { meta } = await this.buildMeta({
      source,
      sessionId: source.session_id,
      title: input.title,
      cancellationToken: input.cancellationToken,
    });

    const { sourceFile, metaFile, rawFile, dir } = await writeImportFiles(source, meta, input.exported);
    setLastImportFiles({
      dir,
      sourceFile,
      metaFile,
      rawFile,
      sessionId: meta.session_id,
      writtenAt: new Date().toISOString(),
    });

    // 打印可点击链接（VSCode OutputChannel 会自动识别 file:// URL）
    this.deps.output.info('memory.import.files', {
      sessionId: meta.session_id,
      source_link: `file://${sourceFile}`,
      meta_link: `file://${metaFile}`,
      ...(rawFile ? { raw_link: `file://${rawFile}` } : {}),
    });

    return this.submitImport({
      sourceFile,
      metaFile,
      kbIndex: input.kbIndex,
    });
    // 临时文件按 bible.debug.keepTempFiles 决定是否保留；
    // 默认保留（true），便于人工审查。GC 由 Bible: Show Last Import Files 命令的 "Clear" 动作触发。
  }

  // ---------- download ----------

  async submitDownloadFile(input: { storagePath: string; downloadName?: string }): Promise<SubmitDownloadResponse> {
    const args: string[] = ['memory', 'download', 'file', '--tag', 'memory', '--storage-path', input.storagePath];
    if (input.downloadName) args.push('--download-name', input.downloadName);
    return this.deps.cli.run<SubmitDownloadResponse>({ args });
  }

  async fetchArtifact(input: { artifactId: string; outputPath: string }): Promise<ArtifactFetchResponse> {
    return this.deps.cli.run<ArtifactFetchResponse>({
      args: ['memory', 'artifact', 'fetch', '--id', input.artifactId, '--out', input.outputPath],
    });
  }

  // ---------- ensureLocalSource (download + cache) ----------

  getCachedSourcePath(hit: Pick<MemoryHit, 'session_id' | 'storage_path'>): string | undefined {
    const dir = resolveDownloadDir(this.deps.config.memoryDownloadDir());
    const filePath = path.join(dir, cacheFilename(hit));
    try {
      const stat = require('node:fs').statSync(filePath);
      return stat.isFile() ? filePath : undefined;
    } catch {
      return undefined;
    }
  }

  async ensureLocalSource(input: EnsureSourceInput): Promise<EnsureSourceResult> {
    const dir = resolveDownloadDir(this.deps.config.memoryDownloadDir());
    await fs.mkdir(dir, { recursive: true });

    const filename = cacheFilename(input.hit);
    const localPath = path.join(dir, filename);

    // 1. cache hit
    try {
      const stat = await fs.stat(localPath);
      if (stat.isFile() && stat.size > 0) {
        this.deps.output.info('memory.source.cacheHit', {
          sessionId: input.hit.session_id,
          path: localPath,
          sizeBytes: stat.size,
        });
        return { path: localPath, fromCache: true, sizeBytes: stat.size };
      }
    } catch {
      /* not cached; fall through to download */
    }

    // 2. cache miss → 走异步下载任务
    this.deps.output.info('memory.source.cacheMiss.startDownload', {
      sessionId: input.hit.session_id,
      storagePath: input.hit.storage_path,
      target: localPath,
    });

    const handle = await this.deps.tasks.submit({
      taskType: 'download.memory',
      domain: 'memory',
      title: `Caching ${input.hit.session_id ?? input.hit.storage_path}`,
      submit: async () => this.submitDownloadFile({ storagePath: input.hit.storage_path }),
      showProgress: true,
    });

    const cancelSub = input.cancellationToken?.onCancellationRequested(() => {
      void this.deps.tasks.cancel(handle.taskId);
    });

    let record;
    try {
      record = await handle.promise;
    } finally {
      cancelSub?.dispose();
    }

    if (record.status !== 'completed') {
      const msg = record.error ? `${record.error.code}: ${record.error.message}` : record.status;
      throw new Error(`Download task ended (${msg})`);
    }

    const r = record.result as { artifact_id?: string } | undefined;
    if (!r?.artifact_id) {
      throw new Error('Download task completed but server returned no artifact_id');
    }

    const fetched = await this.fetchArtifact({ artifactId: r.artifact_id, outputPath: localPath });
    this.deps.output.info('memory.source.downloaded', {
      sessionId: input.hit.session_id,
      path: fetched.path,
      sizeBytes: fetched.size_bytes,
    });
    return { path: fetched.path, fromCache: false, sizeBytes: fetched.size_bytes };
  }

  // ---------- load to context ----------

  async loadHitToContextFile(hit: MemoryHit, sourceFilePath?: string): Promise<string> {
    const dir = resolveContextDir(this.deps.config.memoryDownloadDir());
    await fs.mkdir(dir, { recursive: true });
    const outPath = path.join(dir, 'loaded-context.md');

    const lines: string[] = [
      `<!-- Loaded by Bible Atlas at ${new Date().toISOString()} -->`,
      '',
      formatHit(hit, 1),
    ];
    if (sourceFilePath) {
      lines.push('', `> Full source file: \`${sourceFilePath}\``);
    }
    await fs.writeFile(outPath, lines.join('\n') + '\n', 'utf-8');

    this.deps.output.info('memory.context.loaded', { path: outPath, sessionId: hit.session_id });
    return outPath;
  }
}

function resolveContextDir(template: string): string {
  return resolveDownloadDir(template);
}

function resolveDownloadDir(template: string): string {
  const ws = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  return template.replace('${workspaceFolder}', ws ?? os.tmpdir());
}

/** 算 hit 的本地缓存文件名：优先 session_id，回退 storage_path。 */
function cacheFilename(hit: Pick<MemoryHit, 'session_id' | 'storage_path'>): string {
  const base = hit.session_id?.trim() || hit.storage_path;
  return sanitizeFilename(base) + '.json';
}

function sanitizeFilename(s: string): string {
  return s.replace(/[^a-zA-Z0-9._-]/g, '_').slice(0, 200);
}

// ---------- 临时文件辅助 ----------

/**
 * 写出三个临时文件：
 *   source.json     — 精简对话（bible-chat-v1），发给 server
 *   meta.json       — LM 提炼的结构化摘要，发给 server
 *   source.raw.json — 原始 VSCode export JSON，**仅本地留存**，不发给 CLI
 */
export async function writeImportFiles(
  source: ChatSource,
  meta: MemoryMeta,
  exported?: ChatExportResult,
): Promise<{ sourceFile: string; metaFile: string; rawFile: string | undefined; dir: string }> {
  const dir = path.join(os.tmpdir(), 'bible-vscode', crypto.randomUUID());
  await fs.mkdir(dir, { recursive: true });

  const sourceFile = path.join(dir, 'source.json');
  const metaFile = path.join(dir, 'meta.json');
  await fs.writeFile(sourceFile, JSON.stringify(source, null, 2), 'utf-8');
  await fs.writeFile(metaFile, JSON.stringify(meta, null, 2), 'utf-8');

  let rawFile: string | undefined;
  if (exported) {
    rawFile = path.join(dir, 'source.raw.json');
    await fs.writeFile(rawFile, rawJson(exported), 'utf-8');
  }

  return { sourceFile, metaFile, rawFile, dir };
}

export async function cleanupDir(dir: string): Promise<void> {
  try {
    await fs.rm(dir, { recursive: true, force: true });
  } catch {
    /* ignore */
  }
}

/** 用于构造 invocation 的 helper，可在 Tool 中复用拼参逻辑（保持与 service.submit* 一致）。 */
export function buildImportInvocation(sourceFile: string, metaFile: string, kbIndex: string, vectorModel?: string): CliInvocation {
  const args = ['memory', 'import', '--tag', 'memory', '--kb-index', kbIndex, '--source-file', sourceFile, '--meta-file', metaFile];
  if (vectorModel) args.push('--vector-model', vectorModel);
  return { args };
}
