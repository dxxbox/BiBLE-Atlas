import { BibleAtlasError, toBibleError } from "../http/errors.js";
import type { OpenClawToolResult } from "../types/openclaw.js";

export function extractParams<T extends Record<string, unknown>>(args: unknown[]): T {
  const candidate = args.length >= 2 ? args[1] : args[0];
  if (isRecord(candidate)) return candidate as T;
  return {} as T;
}

export function textResult(content: string, details?: unknown): OpenClawToolResult {
  const result: OpenClawToolResult = {
    content: [{ type: "text", text: content }],
  };
  if (details !== undefined) result.details = details;
  return result;
}

export function errorResult(error: unknown): OpenClawToolResult {
  const bibleError = toBibleError(error);
  return {
    content: [
      {
        type: "text",
        text: `${bibleError.code}: ${bibleError.message}`,
      },
    ],
    details: {
      code: bibleError.code,
      message: bibleError.message,
      statusCode: bibleError.statusCode,
      serverErrorCode: bibleError.serverErrorCode,
      details: bibleError.details,
    },
    isError: true,
  };
}

export function requireString(params: Record<string, unknown>, key: string): string {
  const value = params[key];
  if (typeof value !== "string" || value.trim() === "") {
    throw new BibleAtlasError("BIBLE_INVALID_ARGS", `${key} is required.`);
  }
  return value;
}

export function optionalNumber(params: Record<string, unknown>, key: string): number | undefined {
  const value = params[key];
  if (value === undefined || value === null) return undefined;
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new BibleAtlasError("BIBLE_INVALID_ARGS", `${key} must be a number.`);
  }
  return value;
}

export function optionalBoolean(params: Record<string, unknown>, key: string): boolean | undefined {
  const value = params[key];
  if (value === undefined || value === null) return undefined;
  if (typeof value !== "boolean") {
    throw new BibleAtlasError("BIBLE_INVALID_ARGS", `${key} must be a boolean.`);
  }
  return value;
}

export function optionalString(params: Record<string, unknown>, key: string): string | undefined {
  const value = params[key];
  if (value === undefined || value === null || value === "") return undefined;
  if (typeof value !== "string") {
    throw new BibleAtlasError("BIBLE_INVALID_ARGS", `${key} must be a string.`);
  }
  return value;
}

export function trimText(value: unknown, max = 500): string {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length > max ? `${text.slice(0, max - 1)}...` : text;
}

export function summarizeHits(payload: Record<string, unknown>, noun: string): string {
  const hits = collectHits(payload);
  if (hits.length === 0) return `Found 0 BiBLE ${noun} hits.`;
  const top = hits[0];
  if (!top) return `Found 0 BiBLE ${noun} hits.`;
  const title = pickTitle(top) ?? "untitled";
  const score = pickScore(top);
  return `Found ${hits.length} BiBLE ${noun} hits. Top hit: ${title}${score !== undefined ? ` (score ${score.toFixed(2)})` : ""}.`;
}

export function collectHits(payload: Record<string, unknown>): Record<string, unknown>[] {
  for (const key of ["hits", "results", "items", "memories", "skills", "documents"]) {
    const value = payload[key];
    if (Array.isArray(value)) return value.filter(isRecord);
  }
  if (Array.isArray(payload.result)) return payload.result.filter(isRecord);
  return [];
}

export function pickTitle(hit: Record<string, unknown>): string | undefined {
  for (const key of ["title", "name", "memory_id", "memoryId", "id", "doc_id", "chunk_id"]) {
    const value = hit[key];
    if (typeof value === "string" && value.trim() !== "") return trimText(value, 120);
  }
  return undefined;
}

function pickScore(hit: Record<string, unknown>): number | undefined {
  const value = hit.score ?? hit.similarity;
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
