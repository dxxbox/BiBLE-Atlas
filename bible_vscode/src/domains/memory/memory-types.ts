import { ChatTurn } from '../../core/lm/budget';

export type SearchType = 'keyword' | 'title' | 'text' | 'vector' | 'hybrid';

/** server 端 search 返回的单条命中。字段由 04-spec 最终冻结。 */
export interface MemoryHit {
  session_id: string;
  storage_path: string;
  abstract: string;
  score: number;
  /** 可选：命中的具体字段名（"abstract" / "overview" / ...） */
  hit_field?: string;
  /** 可选：命中片段，server 端可能截断/高亮 */
  snippet?: string;
  /** 透传未知元数据 */
  meta?: Record<string, unknown>;
}

export interface MemorySearchResult {
  results: MemoryHit[];
  total: number;
  kb_index: string;
  tag: string;
}

/**
 * SessionMemory / MemoryMeta：序列化为 `meta.json` 的内容；
 * 与 `source` 文件配对提交给 CLI 的 `bible memory import`。
 * 字段对应 framework v4 §6.4 表格。
 */
export interface MemoryMeta {
  session_id: string;
  abstract: string;
  overview: string;

  primary_request_intent: string;
  key_concepts: string[];
  pending_tasks: string[];

  session_kind?: 'implementation' | 'analysis' | 'mixed';
  code_change_status?: 'modified' | 'not_modified' | 'unknown';
  actual_actions?: string[];
  final_result?: string;
  touched_files?: string[];
  touched_symbols?: string[];
  key_decisions?: string[];
  verification_evidence?: string[];
  risks_next_steps?: string[];
}

/**
 * ChatSource：序列化为 `source` 文件的内容（chat-export-json 格式）。
 * 与 `meta.json` 配对提交，server 端落 artifact。
 */
export interface ChatSource {
  session_id: string;
  exported_at: string;
  messages: ChatTurn[];
  raw: Record<string, unknown>;
}

/** 提交 import 后的同步响应。 */
export interface SubmitImportResponse {
  task_id: string;
  status: 'queued';
  kb_index: string;
  tag: string;
  session_id: string;
}

/** 单文件 / 批量 download 任务的同步响应。 */
export interface SubmitDownloadResponse {
  task_id: string;
  status: 'queued';
}

/** artifact fetch 同步流响应。 */
export interface ArtifactFetchResponse {
  path: string;
  size_bytes: number;
  content_type: string;
}
