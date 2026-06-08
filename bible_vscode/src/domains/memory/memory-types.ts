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
 * ChatSource：序列化为 `source.json` 提交给 server 的内容。
 *
 * 设计原则：**只保留可读的对话文本**，不存 raw metadata / tool call JSON / token 计数等。
 * 这使得：① source.json 体积小一个数量级；② 存下来的文件人类可直接阅读；
 *          ③ 下载回来渲染为 Markdown 时无需额外解析。
 *
 * 原始 VSCode export 写成 `source.raw.json` 保存在本地（不发给 server），仅供测试验证。
 */
export interface ChatSource {
  source_format: 'bible-chat-v1';
  session_id: string;
  exported_at: string;
  /** 纯文本对话轮次，已过滤 tool call / thinking 等运行时噪声。 */
  turns: ChatTurn[];
}

/**
 * CLI `memory upload <dir>` 的同步响应，字段来自 server ImportMemory API 透传。
 * 仅 task_id 为必填；其余字段由 server 决定是否返回。
 */
export interface SubmitImportResponse {
  task_id: string;
  status: string;
  memory_id?: string;
  kb_index?: string;
  tag?: string;
  session_id?: string;
}

/**
 * CLI `memory download` 集成式下载的同步响应。
 * CLI 内部完成 task 提交 + 轮询 + artifact 写盘，最终返回本地路径。
 */
export interface DownloadResult {
  status: 'downloaded';
  output_path: string;
}

/**
 * 持久化在 workspaceState 里的「最近加载到上下文」的描述。
 * 命令路径：把 message.json 原对话填入 **Chat 输入框草稿**（不自动发送）；`/load` 读取后把同一正文流式写入本轮回复。
 */
export interface LoadedContext {
  hit: MemoryHit;
  /** 若已下载，指向本地的 source.json；participant 会读这个文件全文塞给 LM。 */
  sourceFilePath?: string;
  /** loaded-context.md 在工作区里的绝对路径，便于 UI 引用 */
  loadedContextMdPath?: string;
  loadedAt: string;
}
