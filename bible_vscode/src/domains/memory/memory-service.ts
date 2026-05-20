import * as vscode from 'vscode';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import * as os from 'node:os';
import * as crypto from 'node:crypto';
import { CliRunner, CliInvocation } from '../../core/cli/cli-runner';
import { ExtensionConfig } from '../../core/config/extension-config';
import { OutputChannel } from '../../core/ui/output-channel';
import { ChatExportResult, exportCurrentChat, fromMessages } from '../../core/chat/chat-export';
import { ChatTurn } from '../../core/lm/budget';
import { MemoryBuilder } from './memory-builder';
import {
  ArtifactFetchResponse,
  ChatSource,
  MemoryMeta,
  MemorySearchResult,
  SearchType,
  SubmitDownloadResponse,
  SubmitImportResponse,
} from './memory-types';

/** 最近一次 import 写出的临时文件路径（debug 用）。 */
export interface LastImportFiles {
  dir: string;
  sourceFile: string;
  metaFile: string;
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
    const source = await this.exportCurrentChat();
    return this.importFromSource({
      source: { session_id: source.session_id, exported_at: source.exported_at, messages: source.messages, raw: source.raw },
      kbIndex: input?.kbIndex,
      cancellationToken: input?.cancellationToken,
    });
  }

  async importFromMessages(input: { messages: ChatTurn[]; title?: string; kbIndex?: string; cancellationToken?: vscode.CancellationToken }): Promise<SubmitImportResponse> {
    const exp = fromMessages(input.messages);
    return this.importFromSource({
      source: { session_id: exp.session_id, exported_at: exp.exported_at, messages: exp.messages, raw: exp.raw },
      title: input.title,
      kbIndex: input.kbIndex,
      cancellationToken: input.cancellationToken,
    });
  }

  private async importFromSource(input: {
    source: ChatSource;
    title?: string;
    kbIndex?: string;
    cancellationToken?: vscode.CancellationToken;
  }): Promise<SubmitImportResponse> {
    const { meta } = await this.buildMeta({
      source: input.source,
      sessionId: input.source.session_id,
      title: input.title,
      cancellationToken: input.cancellationToken,
    });

    const { sourceFile, metaFile, dir } = await writeImportFiles(input.source, meta);
    setLastImportFiles({
      dir,
      sourceFile,
      metaFile,
      sessionId: meta.session_id,
      writtenAt: new Date().toISOString(),
    });

    // 打印可点击链接（VSCode OutputChannel 会自动识别 file:// URL）
    this.deps.output.info('memory.import.files', {
      sessionId: meta.session_id,
      sourceFile,
      metaFile,
      source_link: `file://${sourceFile}`,
      meta_link: `file://${metaFile}`,
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
}

// ---------- 临时文件辅助 ----------

export async function writeImportFiles(source: ChatSource, meta: MemoryMeta): Promise<{ sourceFile: string; metaFile: string; dir: string }> {
  const dir = path.join(os.tmpdir(), 'bible-vscode', crypto.randomUUID());
  await fs.mkdir(dir, { recursive: true });
  const sourceFile = path.join(dir, 'source.json');
  const metaFile = path.join(dir, 'meta.json');
  await fs.writeFile(sourceFile, JSON.stringify(source, null, 2), 'utf-8');
  await fs.writeFile(metaFile, JSON.stringify(meta, null, 2), 'utf-8');
  return { sourceFile, metaFile, dir };
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
