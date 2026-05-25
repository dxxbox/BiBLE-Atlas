export type BibleErrorCode =
  | "BIBLE_CONFIG_MISSING"
  | "BIBLE_SERVICE_UNAVAILABLE"
  | "BIBLE_AUTH_FAILED"
  | "BIBLE_INVALID_ARGS"
  | "BIBLE_CONTRACT_MISMATCH"
  | "BIBLE_TASK_TIMEOUT"
  | "BIBLE_NOT_IMPLEMENTED"
  | "BIBLE_NOT_FOUND"
  | "BIBLE_CONFLICT"
  | "BIBLE_RATE_LIMITED"
  | "BIBLE_INTERNAL";

export class BibleAtlasError extends Error {
  readonly code: BibleErrorCode;
  readonly statusCode?: number;
  readonly serverErrorCode?: string;
  readonly details?: unknown;

  constructor(
    code: BibleErrorCode,
    message: string,
    opts: { statusCode?: number; serverErrorCode?: string; details?: unknown } = {},
  ) {
    super(message);
    this.name = "BibleAtlasError";
    this.code = code;
    if (opts.statusCode !== undefined) this.statusCode = opts.statusCode;
    if (opts.serverErrorCode !== undefined) this.serverErrorCode = opts.serverErrorCode;
    if (opts.details !== undefined) this.details = opts.details;
  }
}

export function mapHttpStatusToBibleCode(statusCode: number): BibleErrorCode {
  switch (statusCode) {
    case 400:
    case 412:
    case 422:
      return statusCode === 422 ? "BIBLE_CONTRACT_MISMATCH" : "BIBLE_INVALID_ARGS";
    case 401:
    case 403:
      return "BIBLE_AUTH_FAILED";
    case 404:
      return "BIBLE_NOT_FOUND";
    case 409:
      return "BIBLE_CONFLICT";
    case 429:
      return "BIBLE_RATE_LIMITED";
    case 501:
      return "BIBLE_NOT_IMPLEMENTED";
    case 503:
    case 504:
      return "BIBLE_SERVICE_UNAVAILABLE";
    default:
      return "BIBLE_INTERNAL";
  }
}

export function normalizeServerErrorCode(code: string | undefined, statusCode: number): BibleErrorCode {
  const normalized = (code ?? "").trim().toUpperCase();
  if (statusCode === 501 || normalized === "NOT_IMPLEMENTED" || normalized === "SEV_NOT_IMPLEMENTED") {
    return "BIBLE_NOT_IMPLEMENTED";
  }
  switch (normalized) {
    case "INVALID_ARGUMENT":
    case "INVALID_ARGS":
      return "BIBLE_INVALID_ARGS";
    case "UNAUTHENTICATED":
    case "PERMISSION_DENIED":
      return "BIBLE_AUTH_FAILED";
    case "NOT_FOUND":
      return "BIBLE_NOT_FOUND";
    case "DEADLINE_EXCEEDED":
    case "TIMEOUT":
      return "BIBLE_TASK_TIMEOUT";
    case "UNAVAILABLE":
      return "BIBLE_SERVICE_UNAVAILABLE";
    default:
      return mapHttpStatusToBibleCode(statusCode);
  }
}

export function toBibleError(error: unknown, fallbackMessage = "BiBLE Atlas request failed."): BibleAtlasError {
  if (error instanceof BibleAtlasError) return error;
  if (error instanceof Error) {
    if (error.name === "AbortError" || /timeout/i.test(error.message)) {
      return new BibleAtlasError("BIBLE_SERVICE_UNAVAILABLE", "HTTP request timed out.");
    }
    return new BibleAtlasError("BIBLE_INTERNAL", error.message || fallbackMessage);
  }
  return new BibleAtlasError("BIBLE_INTERNAL", fallbackMessage);
}
