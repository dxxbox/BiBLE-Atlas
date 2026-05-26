export class BibleAtlasError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly statusCode?: number,
    readonly serverErrorCode?: string,
  ) {
    super(message);
    this.name = "BibleAtlasError";
  }
}

export function mapStatusToCode(statusCode: number): string {
  switch (statusCode) {
    case 400:
      return "BIBLE_INVALID_ARGS";
    case 401:
    case 403:
      return "BIBLE_AUTH_FAILED";
    case 404:
      return "BIBLE_NOT_FOUND";
    case 422:
      return "BIBLE_CONTRACT_MISMATCH";
    case 501:
      return "BIBLE_NOT_IMPLEMENTED";
    case 503:
    case 504:
      return "BIBLE_SERVICE_UNAVAILABLE";
    default:
      return statusCode >= 500 ? "BIBLE_SERVICE_UNAVAILABLE" : "BIBLE_INTERNAL";
  }
}

export function toBibleAtlasError(err: unknown): BibleAtlasError {
  if (err instanceof BibleAtlasError) return err;
  if (err instanceof Error && err.name === "AbortError") {
    return new BibleAtlasError("BIBLE_TIMEOUT", "BiBLE Atlas request timed out.");
  }
  if (err instanceof Error) return new BibleAtlasError("BIBLE_SERVICE_UNAVAILABLE", err.message);
  return new BibleAtlasError("BIBLE_INTERNAL", "Unknown BiBLE Atlas error.");
}
