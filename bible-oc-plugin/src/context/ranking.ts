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
  finalScore?: number;
  promptInjectionRisk?: boolean;
}

const DOMAIN_BOOST: Record<RecallDomain, number> = { memory: 0.08, skill: 0.04, knowledge: 0 };
const DOMAIN_PRIORITY: Record<RecallDomain, number> = { memory: 3, skill: 2, knowledge: 1 };

export function normalizeHits(domain: RecallDomain, payload: Record<string, unknown>, tag?: string): RecallHit[] {
  const rawHits = extractHits(domain, payload, tag);
  return rawHits.map((raw, index) => normalizeHit(domain, raw, index, tag)).filter((hit): hit is RecallHit => Boolean(hit));
}

export function filterRankAndTrim(hits: RecallHit[], query: string, minScore: number, topK: number): RecallHit[] {
  return dedupeHits(hits)
    .filter((hit) => hit.score >= minScore && Boolean(hit.title || hit.summary || hit.contentPreview))
    .map((hit) => ({ ...hit, promptInjectionRisk: hasPromptInjectionRisk(hit), finalScore: computeFinalScore(hit, query) }))
    .sort((a, b) => (b.finalScore ?? 0) - (a.finalScore ?? 0))
    .slice(0, topK);
}

export function dedupeHits(hits: RecallHit[]): RecallHit[] {
  const byKey = new Map<string, RecallHit>();
  for (const hit of hits) {
    const strongKey = `${hit.domain}:${hit.id || hit.sourceRef}`;
    const weakKey = fingerprint(`${hit.title ?? ""}\n${hit.contentPreview ?? hit.summary ?? ""}`);
    const key = hit.id || hit.sourceRef ? strongKey : weakKey;
    const existing = byKey.get(key);
    if (!existing || hit.score > existing.score || (hit.score === existing.score && DOMAIN_PRIORITY[hit.domain] > DOMAIN_PRIORITY[existing.domain])) {
      byKey.set(key, hit);
    }
  }
  return [...byKey.values()];
}

function normalizeHit(domain: RecallDomain, raw: Record<string, unknown>, index: number, tag?: string): RecallHit | undefined {
  const id = firstString(raw, ["memory_id", "memoryId", "doc_id", "chunk_id", "skill_id", "id", "name"]) ?? `${domain}_${index}`;
  const title = firstString(raw, ["title", "name", "heading"]);
  const summary = firstString(raw, ["abstract", "summary", "description", "overview"]);
  const contentPreview = firstString(raw, ["matched_message_preview", "preview", "text", "content", "excerpt"]);
  const rawScore = firstNumber(raw, ["score", "similarity", "relevance"]);
  return {
    id,
    domain,
    title,
    summary,
    contentPreview,
    sourceRef: firstString(raw, ["source", "source_ref", "path", "storage_path"]),
    score: normalizeScore(rawScore ?? 1),
    tag: tag ?? firstString(raw, ["tag", "kb_tag"]),
    updatedAt: firstString(raw, ["updated_at", "updatedAt", "timestamp"]),
    metadata: raw,
  };
}

// function pickHits(payload: Record<string, unknown>): Record<string, unknown>[] {
//   for (const key of ["hits", "items", "results", "documents", "memories", "skills"]) {
//     const value = payload[key];
//     if (Array.isArray(value)) return value.filter(isRecord);
//   }
//   if (Array.isArray(payload.result)) return payload.result.filter(isRecord);
//   return [];
// }

function extractHits(domain: RecallDomain, payload: Record<string, unknown>, tag?: string): Record<string, unknown> [] {
  const results = payload.results;
  if (isRecord(results)) {
    const key = domain === 'knowledge' ? (tag ?? domain) : domain;
    if (Array.isArray(results[key])) return (results[key] as unknown[]).filter(isRecord);
  }
  return []
}

function computeFinalScore(hit: RecallHit, query: string): number {
  const recencyBoost = hit.updatedAt && Date.now() - Date.parse(hit.updatedAt) < 30 * 24 * 3600 * 1000 ? 0.1 : 0;
  const overlap = queryTermOverlap(query, [hit.title, hit.summary, hit.contentPreview].filter(Boolean).join(" ")) * 0.1;
  const symbolBoost = exactSymbolBoost(query, hit) ? 0.05 : 0;
  return hit.score * 0.55 + recencyBoost + DOMAIN_BOOST[hit.domain] + overlap + symbolBoost;
}

function queryTermOverlap(query: string, text: string): number {
  const q = new Set(tokens(query));
  if (q.size === 0) return 0;
  const t = new Set(tokens(text));
  let matches = 0;
  for (const token of q) if (t.has(token)) matches += 1;
  return Math.min(1, matches / q.size);
}

function exactSymbolBoost(query: string, hit: RecallHit): boolean {
  const symbols = query.match(/[A-Za-z0-9_./-]{6,}/g) ?? [];
  const haystack = `${hit.title ?? ""} ${hit.summary ?? ""} ${hit.contentPreview ?? ""}`;
  return symbols.some((symbol) => haystack.includes(symbol));
}

function hasPromptInjectionRisk(hit: RecallHit): boolean {
  const text = `${hit.title ?? ""}\n${hit.summary ?? ""}\n${hit.contentPreview ?? ""}`.toLowerCase();
  return /ignore (all )?(previous|above) instructions|system prompt|developer message|you are now/.test(text);
}

function tokens(text: string): string[] {
  return text.toLowerCase().match(/[\p{L}\p{N}_./-]{2,}/gu) ?? [];
}

function normalizeScore(score: number): number {
  if (!Number.isFinite(score)) return 0;
  if (score > 1) return Math.max(0, Math.min(1, score / 100));
  return Math.max(0, Math.min(1, score));
}

function fingerprint(text: string): string {
  return text.toLowerCase().replace(/\s+/g, " ").trim().slice(0, 256);
}

function firstString(raw: Record<string, unknown>, keys: string[]): string | undefined {
  for (const key of keys) if (typeof raw[key] === "string" && raw[key].trim()) return raw[key] as string;
  return undefined;
}

function firstNumber(raw: Record<string, unknown>, keys: string[]): number | undefined {
  for (const key of keys) if (typeof raw[key] === "number") return raw[key] as number;
  return undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
