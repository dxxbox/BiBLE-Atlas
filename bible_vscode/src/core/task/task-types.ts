export type TaskStatus =
  | 'queued' | 'running' | 'retrying'
  | 'completed' | 'failed' | 'cancelled';

export interface TaskRecord<R = unknown> {
  taskId: string;
  /** 例：'import.memory' / 'download.memory' / 'download.memory.batch' */
  taskType: string;
  domain: 'memory' | 'skill' | 'knowledge_base';
  status: TaskStatus;
  result?: R;
  error?: { code: string; message: string };
  submittedAt: number;
  updatedAt: number;
  /** UI 文案，用于状态栏/任务面板。 */
  title?: string;
}

export interface DownloadArtifact {
  artifact_id: string;
  artifact_name: string;
  content_type: string;
  size_bytes: number;
  expires_at: string;
}

/** server 端任务返回的 result，常见字段（不同 task_type 取不同子集）。 */
export interface TaskResultData {
  session_id?: string;
  artifact_id?: string;
  artifact_name?: string;
  size_bytes?: number;
  content_type?: string;
  expires_at?: string;
  chunks_count?: number;
  // 透传未知字段
  [k: string]: unknown;
}

/** `bible task get` 返回结构 */
export interface TaskGetResponse {
  task_id: string;
  task_type: string;
  status: TaskStatus;
  result?: TaskResultData;
  error?: { code: string; message: string };
  created_at?: string;
  updated_at?: string;
}
