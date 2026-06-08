import * as vscode from 'vscode';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import * as os from 'node:os';
import * as crypto from 'node:crypto';
import { CliRunner, CliInvocation } from '../../core/cli/cli-runner';
import { ExtensionConfig } from '../../core/config/extension-config';
import { OutputChannel } from '../../core/ui/output-channel';
import { TaskTracker } from '../../core/task/task-tracker';
import { ChatExportResult, exportCurrentChat, fromMessages, parseChatExportJsonFile, toCleanSource, rawJson } from '../../core/chat/chat-export';
import { ChatTurn } from '../../core/lm/budget';
import { MemoryBuilder } from './memory-builder';
import {
  ChatSource,
  DownloadResult,
  MemoryHit,
  MemoryMeta,
  MemorySearchResult,
  SearchType,
  SubmitImportResponse,
} from './memory-types';
import { buildLoadedContextMarkdown } from './memory-format';

/** 最近一次 import 写出的临时文件路径（debug 用）。 */
export interface LastImportFiles {
  dir: string;
  /** 对话正文，对应 CLI 期望的 message.json */
  messageFile: string;
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

  /**
   * CLI: `bible memory upload <session_dir> [--kb-index K] [--vector-model V]`
   * session_dir 内须包含 `message.json`（对话正文）和 `meta.json`（结构化摘要）。
   */
  uploadMemoryDir(input: {
    dir: string;
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

  /**
   * 把 message.json 原对话（bible-chat-v1）渲染为 Markdown 写到 `${ws}/.bible/memory/loaded-context.md`，
   * 返回绝对路径。供命令路径「加载到上下文」回看；聊天草稿由调用方单独填入输入框。
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
}

export class DefaultMemoryService implements MemoryService {
  constructor(private readonly deps: MemoryServiceDeps) {}

  // ---------- search ----------

  async search(input: { query: string; topK?: number; searchType?: SearchType; vectorModel?: string }): Promise<MemorySearchResult> {
    // CLI: bible memory search <query> [--top-k N] [--search-type S]
    const args: string[] = ['memory', 'search', input.query];
    if (input.topK !== undefined) args.push('--top-k', String(input.topK));
    if (input.searchType) args.push('--search-type', input.searchType);
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

  async uploadMemoryDir(input: { dir: string; kbIndex?: string; vectorModel?: string }): Promise<SubmitImportResponse> {
    // CLI: bible memory upload <session_dir> [--kb-index K] [--vector-model V]
    const kbIndex = input.kbIndex ?? this.deps.config.memoryDefaultKbIndex();
    const args: string[] = ['memory', 'upload', input.dir, '--kb-index', kbIndex];
    const vectorModel = input.vectorModel ?? this.deps.config.memoryDefaultVectorModel();
    if (vectorModel) args.push('--vector-model', vectorModel);

    return this.deps.cli.run<SubmitImportResponse>({ args });
  }

  // ---------- import (high-level: from current chat) ----------

  async importCurrentChat(input?: { kbIndex?: string; cancellationToken?: vscode.CancellationToken }): Promise<SubmitImportResponse> {
    let exported: ChatExportResult;
    try {
      exported = await this.exportCurrentChat();
    } catch (firstErr) {
      this.deps.output.warn('memory.import.chatExportFailed', { message: (firstErr as Error).message });
      if (input?.cancellationToken?.isCancellationRequested) {
        throw new vscode.CancellationError();
      }

      const defaultUri = vscode.workspace.workspaceFolders?.[0]?.uri;
      const picked = await vscode.window.showOpenDialog({
        title: 'Select Copilot chat export JSON (e.g. from VS Code Copilot session export)',
        openLabel: 'Use this file',
        canSelectMany: false,
        canSelectFolders: false,
        filters: { JSON: ['json'] },
        defaultUri,
      });
      if (!picked?.[0]) {
        throw firstErr;
      }
      if (input?.cancellationToken?.isCancellationRequested) {
        throw new vscode.CancellationError();
      }
      exported = await parseChatExportJsonFile(picked[0].fsPath, this.deps.output);
    }
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

    const { messageFile, metaFile, rawFile, dir } = await writeImportFiles(source, meta, input.exported);
    setLastImportFiles({
      dir,
      messageFile,
      metaFile,
      rawFile,
      sessionId: meta.session_id,
      writtenAt: new Date().toISOString(),
    });

    // 打印可点击链接（VSCode OutputChannel 会自动识别 file:// URL）
    this.deps.output.info('memory.import.files', {
      sessionId: meta.session_id,
      ...(input.exported.originPath
        ? { user_picked_json: `file://${input.exported.originPath}` }
        : {}),
      generated_source_for_cli: `file://${messageFile}`,
      generated_meta_for_cli: `file://${metaFile}`,
      ...(rawFile ? { generated_raw_snapshot: `file://${rawFile}` } : {}),
    });

    return this.uploadMemoryDir({ dir, kbIndex: input.kbIndex });
    // 临时文件按 bible.debug.keepTempFiles 决定是否保留；
    // 默认保留（true），便于人工审查。GC 由 Bible: Show Last Import Files 命令的 "Clear" 动作触发。
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
      /* not cached; fall through */
    }

    // 2. cache miss → CLI 集成式下载（CLI 内部完成 task 提交+轮询+写盘）
    // CLI: bible memory download --storage-path P --output DIR --download-name FILENAME
    // CLI 最长轮询 5 分钟，插件侧同步等待，需要显式超时放宽。
    this.deps.output.info('memory.source.cacheMiss.startDownload', {
      sessionId: input.hit.session_id,
      storagePath: input.hit.storage_path,
      target: localPath,
    });

    const result = await this.deps.cli.run<DownloadResult>({
      args: [
        'memory', 'download',
        '--storage-path', input.hit.storage_path,
        '--output', dir,
        '--download-name', filename,
      ],
      timeoutMs: 6 * 60 * 1000, // CLI 最长轮询 5 min；留 1 min 缓冲
    });

    const stat = await fs.stat(result.output_path);
    this.deps.output.info('memory.source.downloaded', {
      sessionId: input.hit.session_id,
      path: result.output_path,
      sizeBytes: stat.size,
    });
    return { path: result.output_path, fromCache: false, sizeBytes: stat.size };
  }

  // ---------- load to context ----------

  async loadHitToContextFile(hit: MemoryHit, sourceFilePath?: string): Promise<string> {
    const dir = resolveContextDir(this.deps.config.memoryDownloadDir());
    await fs.mkdir(dir, { recursive: true });
    const outPath = path.join(dir, 'loaded-context.md');

    const body = await buildLoadedContextMarkdown(hit, sourceFilePath);
    const content = `<!-- Loaded by Bible Atlas at ${new Date().toISOString()} -->\n\n${body}`;
    await fs.writeFile(outPath, content, 'utf-8');

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
 *   message.json    — 精简对话（bible-chat-v1），CLI `memory upload` 要求的文件名
 *   meta.json       — LM 提炼的结构化摘要，发给 server
 *   source.raw.json — 原始 VSCode export JSON，**仅本地留存**，不发给 CLI
 */
export async function writeImportFiles(
  source: ChatSource,
  meta: MemoryMeta,
  exported?: ChatExportResult,
): Promise<{ messageFile: string; metaFile: string; rawFile: string | undefined; dir: string }> {
  const dir = path.join(os.tmpdir(), 'bible-vscode', crypto.randomUUID());
  await fs.mkdir(dir, { recursive: true });

  const messageFile = path.join(dir, 'message.json');
  const metaFile = path.join(dir, 'meta.json');
  await fs.writeFile(messageFile, JSON.stringify(source, null, 2), 'utf-8');
  await fs.writeFile(metaFile, JSON.stringify(meta, null, 2), 'utf-8');

  let rawFile: string | undefined;
  if (exported) {
    rawFile = path.join(dir, 'source.raw.json');
    await fs.writeFile(rawFile, rawJson(exported), 'utf-8');
  }

  return { messageFile, metaFile, rawFile, dir };
}

export async function cleanupDir(dir: string): Promise<void> {
  try {
    await fs.rm(dir, { recursive: true, force: true });
  } catch {
    /* ignore */
  }
}

/** 用于构造 invocation 的 helper，可在 Tool 中复用拼参逻辑（保持与 service.uploadMemoryDir 一致）。 */
export function buildUploadInvocation(sessionDir: string, kbIndex: string, vectorModel?: string): CliInvocation {
  const args = ['memory', 'upload', sessionDir, '--kb-index', kbIndex];
  if (vectorModel) args.push('--vector-model', vectorModel);
  return { args };
}
