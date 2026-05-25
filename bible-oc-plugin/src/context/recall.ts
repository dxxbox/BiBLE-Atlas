import type { BiblePluginConfig } from "../config/types.js";
import { toBibleError } from "../http/errors.js";
import type { BibleRuntime } from "../runtime/bible-runtime.js";
import type { AssembleInput, ConversationMessage, PluginLogger } from "../types/openclaw.js";
import { filterAndRankHits, normalizeRecallHits, type RecallHit } from "./ranking.js";

export interface RecallQuery {
  text: string;
}

export interface RecallPipelineOptions {
  config: BiblePluginConfig;
  runtime: BibleRuntime;
  logger?: PluginLogger;
}

export class RecallPipeline {
  private readonly config: BiblePluginConfig;
  private readonly runtime: BibleRuntime;
  private readonly logger?: PluginLogger;

  constructor(options: RecallPipelineOptions) {
    this.config = options.config;
    this.runtime = options.runtime;
    if (options.logger !== undefined) this.logger = options.logger;
  }

  async search(query: RecallQuery): Promise<RecallHit[]> {
    const tasks: Array<Promise<RecallHit[]>> = [];
    if (this.config.enableMemoryRecall) {
      tasks.push(this.searchDomain("memory", () => this.runtime.searchMemory({ query: query.text })));
    }
    if (this.config.enableSkillRecall) {
      tasks.push(this.searchDomain("skill", () => this.runtime.searchSkill({ query: query.text })));
    }
    if (this.config.enableKnowledgeRecall) {
      for (const tag of this.config.knowledgeTags) {
        tasks.push(
          this.searchDomain("knowledge", () => this.runtime.searchKnowledge({ query: query.text, tag }), tag),
        );
      }
    }
    if (tasks.length === 0) return [];
    const settled = await Promise.allSettled(tasks);
    const hits = settled.flatMap((result) => (result.status === "fulfilled" ? result.value : []));
    for (const result of settled) {
      if (result.status === "rejected") {
        this.logger?.warn?.("BiBLE recall domain failed.", serializeError(result.reason));
      }
    }
    return filterAndRankHits(hits, query.text, this.config.recallMinScore, this.config.recallTopK);
  }

  private async searchDomain(
    domain: "memory" | "skill" | "knowledge",
    run: () => Promise<Record<string, unknown>>,
    tag?: string,
  ): Promise<RecallHit[]> {
    try {
      const payload = await withTimeout(run(), Math.min(this.config.timeoutMs, 5_000));
      return normalizeRecallHits(domain, payload, tag);
    } catch (error) {
      throw toBibleError(error);
    }
  }
}

export function buildRecallQuery(input: AssembleInput, config: BiblePluginConfig): RecallQuery {
  const parts: string[] = [];
  const current = textFromUnknown(input.currentUserMessage);
  if (current) parts.push(current);
  const recent = (input.messages ?? [])
    .slice(-6)
    .map((message) => messageToText(message))
    .filter(Boolean);
  parts.push(...recent);
  const text = stripNoisyBlocks(parts.join("\n\n")).slice(0, Math.max(500, config.injectionTokenBudget * 2));
  return { text: text.trim().slice(0, 2_000) };
}

function messageToText(message: ConversationMessage): string {
  const role = typeof message.role === "string" ? `${message.role}: ` : "";
  return role + textFromUnknown(message.content ?? message.text);
}

function textFromUnknown(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    return value.map(textFromUnknown).filter(Boolean).join("\n");
  }
  if (isRecord(value)) {
    if (typeof value.text === "string") return value.text;
    if (typeof value.content === "string") return value.content;
  }
  return "";
}

function stripNoisyBlocks(value: string): string {
  return value
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/[A-Za-z0-9+/]{120,}={0,2}/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
  let timeout: NodeJS.Timeout | undefined;
  const timeoutPromise = new Promise<never>((_, reject) => {
    timeout = setTimeout(() => reject(new Error("Recall domain request timed out.")), timeoutMs);
  });
  return Promise.race([promise, timeoutPromise]).finally(() => {
    if (timeout) clearTimeout(timeout);
  });
}

function serializeError(error: unknown): Record<string, unknown> {
  if (error instanceof Error) return { name: error.name, message: error.message };
  return { error };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
