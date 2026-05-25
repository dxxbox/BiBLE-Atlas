export type RecallDomain = "memory" | "skill" | "knowledge";

export interface RecallHit {
  id: string;
  domain: RecallDomain;
  title?: string;
  summary?: string;
  contentPreview?: string;
  sourceRef?: string;
  score: number;
  tag?: string;
  updatedAt?: string;
  metadata?: Record<string, unknown>;
}

export function normalizeRecallHits(
  domain: RecallDomain,
  payload: Record<string, unknown>,
  tag?: string,
): RecallHit[] {
  return collectRawHits(payload)
    .map((raw, index) => normalizeHit(domain, raw, index, tag))
    .filter((hit): hit is RecallHit => hit !== undefined);
}

export function filterAndRankHits(
  hits: RecallHit[],
  queryText: string,
  minScore: number,
  limit: number,
): RecallHit[] {
  const deduped = dedupeHits(hits);
  const terms = extractQueryTerms(queryText);
  return deduped
    .filter((hit) => hit.score >= minScore)
    .filter((hit) => Boolean(hit.title ?? hit.summary ?? hit.contentPreview))
    .map((hit) => ({ hit, finalScore: finalScore(hit, terms) }))
    .sort((a, b) => b.finalScore - a.finalScore)
    .slice(0, limit)
    .map(({ hit }) => hit);
}

function normalizeHit(
  domain: RecallDomain,
  raw: Record<string, unknown>,
  index: number,
  tag?: string,
): RecallHit | undefined {
  const id =
    readString(raw, ["memory_id", "memoryId", "skill_id", "skillId", "doc_id", "chunk_id", "id", "name"]) ??
    `${domain}:${index}`;
  const score = normalizeScore(readNumber(raw, ["score", "similarity", "rank_score"]) ?? 0);
  const title = readString(raw, ["title", "name"]);
  const summary = readString(raw, ["abstract", "summary", "description", "overview"]);
  const contentPreview = readString(raw, [
    "matched_message_preview",
    "preview",
    "text",
    "content",
    "excerpt",
  ]);
  const sourceRef = readString(raw, ["source", "source_ref", "path", "storage_path"]);
  const updatedAt = readString(raw, ["updated_at", "updatedAt", "created_at", "timestamp"]);
  return {
    id,
    domain,
    score,
    ...(title !== undefined ? { title } : {}),
    ...(summary !== undefined ? { summary } : {}),
    ...(contentPreview !== undefined ? { contentPreview } : {}),
    ...(sourceRef !== undefined ? { sourceRef } : {}),
    ...(tag !== undefined ? { tag } : {}),
    ...(updatedAt !== undefined ? { updatedAt } : {}),
    metadata: raw,
  };
}

function dedupeHits(hits: RecallHit[]): RecallHit[] {
  const seen = new Map<string, RecallHit>();
  for (const hit of hits) {
    const keys = [
      `${hit.domain}:${hit.id}`,
      fingerprint(`${hit.title ?? ""}\n${hit.contentPreview ?? hit.summary ?? ""}`),
    ];
    const existing = keys.map((key) => seen.get(key)).find(Boolean);
    if (!existing || hit.score > existing.score) {
      for (const key of keys) seen.set(key, hit);
    }
  }
  return Array.from(new Set(seen.values()));
}

function finalScore(hit: RecallHit, terms: Set<string>): number {
  const recencyBoost = isRecent(hit.updatedAt) ? 0.1 : 0;
  const domainBoost = hit.domain === "memory" ? 0.08 : hit.domain === "skill" ? 0.04 : 0;
  const overlap = queryTermOverlap(hit, terms) * 0.1;
  const exactSymbolBoost = hasExactSymbolOverlap(hit, terms) ? 0.05 : 0;
  return hit.score * 0.55 + recencyBoost * 0.15 + domainBoost * 0.15 + overlap + exactSymbolBoost;
}

function collectRawHits(payload: Record<string, unknown>): Record<string, unknown>[] {
  for (const key of ["hits", "results", "items", "memories", "skills", "documents", "chunks"]) {
    const value = payload[key];
    if (Array.isArray(value)) return value.filter(isRecord);
  }
  const result = payload.result;
  if (Array.isArray(result)) return result.filter(isRecord);
  if (isRecord(result)) return collectRawHits(result);
  return [];
}

function readString(raw: Record<string, unknown>, keys: string[]): string | undefined {
  for (const key of keys) {
    const value = raw[key];
    if (typeof value === "string" && value.trim() !== "") return value;
  }
  return undefined;
}

function readNumber(raw: Record<string, unknown>, keys: string[]): number | undefined {
  for (const key of keys) {
    const value = raw[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return undefined;
}

function normalizeScore(score: number): number {
  if (score > 1) return Math.min(1, score / 100);
  if (score < 0) return 0;
  return score;
}

function fingerprint(value: string): string {
  return value.toLowerCase().replace(/\s+/g, " ").trim().slice(0, 240);
}

function extractQueryTerms(queryText: string): Set<string> {
  return new Set(
    queryText
      .toLowerCase()
      .split(/[^a-z0-9_./:-]+/i)
      .map((term) => term.trim())
      .filter((term) => term.length >= 3),
  );
}

function queryTermOverlap(hit: RecallHit, terms: Set<string>): number {
  if (terms.size === 0) return 0;
  const text = `${hit.title ?? ""} ${hit.summary ?? ""} ${hit.contentPreview ?? ""}`.toLowerCase();
  let matches = 0;
  for (const term of terms) {
    if (text.includes(term)) matches += 1;
  }
  return Math.min(1, matches / Math.min(terms.size, 10));
}

function hasExactSymbolOverlap(hit: RecallHit, terms: Set<string>): boolean {
  const text = `${hit.title ?? ""} ${hit.summary ?? ""} ${hit.contentPreview ?? ""}`;
  for (const term of terms) {
    if ((term.includes("/") || term.includes(".") || term.includes(":")) && text.includes(term)) {
      return true;
    }
  }
  return false;
}

function isRecent(value: string | undefined): boolean {
  if (!value) return false;
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return false;
  return Date.now() - timestamp < 30 * 24 * 60 * 60 * 1000;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
