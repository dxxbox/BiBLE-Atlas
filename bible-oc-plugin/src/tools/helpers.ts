import { errorDetails } from "../runtime/bible-runtime.js";
import type { ToolResult } from "../types/openclaw.js";

export function requireString(input: Record<string, unknown>, key: string): string {
  const value = input[key];
  if (typeof value !== "string" || value.trim() === "") throw new Error(`${key} is required.`);
  return value.trim();
}

export function optionalInteger(input: Record<string, unknown>, key: string, fallback: number, min: number, max: number): number {
  const value = input[key];
  if (value === undefined) return fallback;
  if (!Number.isInteger(value) || (value as number) < min || (value as number) > max) throw new Error(`${key} must be an integer between ${min} and ${max}.`);
  return value as number;
}

export function optionalSearchType(input: Record<string, unknown>): "keyword" | "title" | "text" | "vector" | "hybrid" {
  const value = input.searchType;
  if (value === undefined) return "hybrid";
  if (value !== "title" && value !== "keyword" && value !== "text" && value !== "vector" && value !== "hybrid") throw new Error("searchType must be keyword, title, text, vector, or hybrid.");
  return value;
}

export function asObject(input: unknown): Record<string, unknown> {
  if (typeof input !== "object" || input === null || Array.isArray(input)) throw new Error("Tool input must be an object.");
  return input as Record<string, unknown>;
}

export function ok(content: string, details: Record<string, unknown>): ToolResult {
  return { content, details: trimDetails(details) };
}

export function fail(err: unknown): ToolResult {
  const details = errorDetails(err);
  return { isError: true, content: `${details.code}: ${details.message}`, details };
}

export function summarizeHits(domain: string, payload: Record<string, unknown>): string {
  const hits = extractHits(domain, payload);
  if (hits.length === 0) return `Found 0 BiBLE ${domain} hits.`;
  const top = hits[0];
  const title = typeof top.title === "string" ? top.title : typeof top.name === "string" ? top.name : typeof top.memory_id === "string" ? top.memory_id : "untitled";
  const score = typeof top.score === "number" ? ` (score ${top.score.toFixed(2)})` : "";
  return `Found ${hits.length} BiBLE ${domain} hits. Top hit: ${title}${score}.`;
}

export function pickHits(payload: Record<string, unknown>): Record<string, unknown>[] {
  for (const key of ["hits", "items", "results", "documents", "memories", "skills"]) {
    const value = payload[key];
    if (Array.isArray(value)) return value.filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null && !Array.isArray(item));
  }
  return [];
}

export function extractHits(domain: string, payload: Record<string, unknown>): Record<string, unknown>[] {
  const results = payload.results;
  if (typeof results === "object" && results !== null && !Array.isArray(results)) {
    const nested = results as Record<string, unknown>;
    if (Array.isArray(nested[domain])) return (nested[domain] as unknown[]).filter((v): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v))
  }
  return [];
}

function trimDetails(details: Record<string, unknown>): Record<string, unknown> {
  const json = JSON.stringify(details);
  if (json.length <= 20000) return details;
  return { truncated: true, preview: json.slice(0, 20000) };
}
