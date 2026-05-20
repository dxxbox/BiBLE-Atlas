/**
 * 错误码归一表（见 docs/designs/client_part/03-vscode-extension-framework-v4.md §5.1 / §9）。
 * 任何新的 server v4 业务错误码必须在 PR 时同步加入此处与 §9 表格。
 */
export type BibleCliErrorCode =
  // 进程层
  | 'CLI_NOT_FOUND'
  | 'CLI_NOT_IMPLEMENTED'
  | 'TIMEOUT'
  | 'UNAVAILABLE'
  | 'INTERNAL'
  | 'UNKNOWN'
  | 'CLI_ERROR'
  // 通用业务
  | 'INVALID_ARGS'
  | 'NOT_FOUND'
  | 'CONFLICT'
  | 'FAILED_PRECONDITION'
  | 'UNAUTHENTICATED'
  | 'PERMISSION_DENIED'
  | 'RESOURCE_EXHAUSTED'
  | 'SEV_NOT_IMPLEMENTED'
  // v4 业务码透传
  | 'INDEX_BINDING_CONFLICT'
  | 'INDEX_NOT_BOUND'
  | 'VECTOR_MODEL_CONFLICT'
  | 'PARSER_SCRIPT_RISK'
  | 'PARSER_SCRIPT_TIMEOUT'
  | 'PARSER_SCRIPT_RUNTIME_ERROR'
  | 'PARSE_RESULT_SCHEMA_INVALID'
  | 'FILE_REGISTRY_NOT_FOUND'
  | 'FILE_NOT_FOUND'
  | 'DOWNLOAD_LIMIT_EXCEEDED'
  | 'ZIP_BUILD_FAILED'
  | 'DOWNLOAD_ARTIFACT_NOT_FOUND'
  | 'DOWNLOAD_ARTIFACT_EXPIRED'
  // 客户端发起
  | 'CANCELLED';

export class BibleCliError extends Error {
  constructor(
    public readonly code: BibleCliErrorCode,
    message: string,
    public readonly exitCode?: number,
    public readonly raw?: unknown,
  ) {
    super(`[${code}] ${message}`);
    this.name = 'BibleCliError';
  }

  /** Convert envelope error → BibleCliError; preserves unknown codes as CLI_ERROR. */
  static fromEnvelope(error: { code?: string; message?: string }, exitCode?: number, raw?: unknown): BibleCliError {
    const code = (error.code ?? 'CLI_ERROR') as BibleCliErrorCode;
    return new BibleCliError(code, error.message ?? 'CLI error', exitCode, raw);
  }
}
