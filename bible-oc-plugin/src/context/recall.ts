import type { ResolvedBibleConfig } from "../config/types.js";
import type { BibleRuntime } from "../runtime/bible-runtime.js";
import type { AssembleInput, ContextEngineRuntimeContext, OpenClawMessage, PluginLogger } from "../types/openclaw.js";
import { actionLogger, log } from "../logging.js";
import { renderRelevantMemories } from "./injection.js";
import { filterRankAndTrim, normalizeHits, type RecallHit } from "./ranking.js";

export interface RecallPipelineResult {
  hits: RecallHit[];
  rendered: string;
  warnings: string[];
}

export async function runRecallPipeline(opts: {
  input: AssembleInput;
  ctx: ContextEngineRuntimeContext;
  config: ResolvedBibleConfig;
  runtime: BibleRuntime;
  logger?: PluginLogger;
}): Promise<RecallPipelineResult> {
  const query = buildRecallQuery(opts.input);
  const action = actionLogger(opts.logger, "recall.pipeline", { queryLength: query.length, memory: opts.config.enableMemoryRecall, skill: opts.config.enableSkillRecall, knowledge: opts.config.enableKnowledgeRecall });
  action.start();
  if (!query) {
    action.done({ skipped: "empty_query" });
    return { hits: [], rendered: "", warnings: [] };
  }
  const warnings: string[] = [];
  const tasks: Array<Promise<RecallHit[]>> = [];
  if (opts.config.enableMemoryRecall) {
    tasks.push(searchDomain("memory", () => opts.runtime.searchMemory({ query, topK: opts.config.recallTopK, minScore: opts.config.recallMinScore, searchType: "hybrid" }), warnings, opts.logger));
  }
  if (opts.config.enableSkillRecall) {
    tasks.push(searchDomain("skill", () => opts.runtime.searchSkill({ query, topK: opts.config.recallTopK, minScore: opts.config.recallMinScore, searchType: "hybrid" }), warnings, opts.logger));
  }
  if (opts.config.enableKnowledgeRecall) {
    for (const tag of opts.config.knowledgeTags) {
      tasks.push(searchDomain("knowledge", () => opts.runtime.searchKnowledge({ query, tag, topK: opts.config.recallTopK, minScore: opts.config.recallMinScore, searchType: "hybrid" }), warnings, opts.logger, tag));
    }
  }
  if (tasks.length === 0) {
    action.done({ skipped: "no_domains" });
    return { hits: [], rendered: "", warnings };
  }
  const settled = await Promise.allSettled(tasks);
  const hits = settled.flatMap((result) => result.status === "fulfilled" ? result.value : []);
  const ranked = filterRankAndTrim(hits, query, opts.config.recallMinScore, opts.config.recallTopK);
  const budget = Math.min(opts.input.contextTokenBudget ?? opts.ctx.contextTokenBudget ?? opts.config.injectionTokenBudget, opts.config.injectionTokenBudget);
  const rendered = renderRelevantMemories(ranked, budget);
  action.done({ domains: tasks.length, rawHits: hits.length, rankedHits: ranked.length, renderedChars: rendered.length, warnings: warnings.length });
  return { hits: ranked, rendered, warnings };
}

export function buildRecallQuery(input: AssembleInput): string {
  const current = textFromUnknown(input.currentUserMessage) || lastUserMessage(input.messages ?? []);
  const recent = (input.messages ?? []).slice(-6).map((message) => textFromUnknown(message.content ?? message.text)).filter(Boolean).join("\n");
  const raw = [recent, current].filter(Boolean).join("\n");
  return cleanForQuery(raw).slice(0, 2000).trim();
}

async function searchDomain(domain: "memory" | "skill" | "knowledge", fn: () => Promise<Record<string, unknown>>, warnings: string[], logger?: PluginLogger, tag?: string): Promise<RecallHit[]> {
  const action = actionLogger(logger, "recall.searchDomain", { domain, tag });
  action.start();
  try {
    const hits = normalizeHits(domain, await fn(), tag);
    action.done({ hits: hits.length });
    return hits;
  } catch (err) {
    warnings.push(`${domain} recall failed: ${err instanceof Error ? err.message : String(err)}`);
    log(logger, "warn", "recall.searchDomain warning", { domain, tag, error: err instanceof Error ? err.message : String(err) });
    action.done({ failed: true, hits: 0 });
    return [];
  }
}

function lastUserMessage(messages: OpenClawMessage[]): string {
  for (const message of [...messages].reverse()) {
    if (message.role === "user") return textFromUnknown(message.content ?? message.text);
  }
  return "";
}

export function textFromUnknown(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(textFromUnknown).filter(Boolean).join("\n");
  if (typeof value === "object" && value !== null) {
    const record = value as Record<string, unknown>;
    if (typeof record.text === "string") return record.text;
    if (typeof record.content === "string") return record.content;
  }
  return "";
}

function cleanForQuery(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, (block) => block.length > 500 ? " [code block omitted] " : block)
    .replace(/[A-Za-z0-9+/=]{120,}/g, " [encoded blob omitted] ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
