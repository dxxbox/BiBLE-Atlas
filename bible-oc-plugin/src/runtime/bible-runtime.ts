import type { BiblePluginConfig } from "../config/types.js";
import { BibleAtlasClient, type MemorySaveRequest, type PollOptions } from "../http/client.js";
import { BibleAtlasError, toBibleError } from "../http/errors.js";
import type { PluginLogger } from "../types/openclaw.js";

export interface BibleRuntimeOptions {
  config: BiblePluginConfig;
  logger?: PluginLogger;
  client?: BibleAtlasClient;
}

export interface RuntimeSearchRequest {
  query: string;
  topK?: number;
  minScore?: number;
  searchType?: "text" | "vector" | "hybrid";
  tag?: string;
}

export interface CommitSessionMemoryRequest {
  sessionKey: string;
  sessionId?: string;
  reason: "threshold" | "compact" | "before_reset" | "session_end" | "manual";
  title: string;
  messages: Array<{ role: "user" | "assistant" | "tool"; content: string; timestamp?: string }>;
  metadata: {
    source: "openclaw";
    pluginId: "bible-oc-plugin";
    openclawVersion?: string;
    turnCount: number;
    startedAt?: string;
    endedAt?: string;
    [key: string]: unknown;
  };
  wait?: boolean;
}

export interface CommitSessionMemoryResult {
  memoryId?: string;
  taskId?: string;
  summary?: string;
  raw: Record<string, unknown>;
}

export class BibleRuntime {
  readonly config: BiblePluginConfig;
  readonly client: BibleAtlasClient;
  private readonly logger?: PluginLogger;

  constructor(options: BibleRuntimeOptions) {
    this.config = options.config;
    this.client = options.client ?? new BibleAtlasClient(options.config);
    if (options.logger !== undefined) this.logger = options.logger;
  }

  async probeHealth(): Promise<{ ok: boolean; payload?: Record<string, unknown>; error?: string; code?: string }> {
    try {
      const payload = await this.client.health();
      return { ok: true, payload };
    } catch (error) {
      const bibleError = toBibleError(error);
      return { ok: false, error: bibleError.message, code: bibleError.code };
    }
  }

  async status(): Promise<Record<string, unknown>> {
    const health = await this.probeHealth();
    let system: Record<string, unknown> | undefined;
    if (health.ok) {
      try {
        system = await this.client.systemStatus();
      } catch (error) {
        this.logger?.warn?.("BiBLE Atlas system status failed.", serializeError(error));
      }
    }
    return {
      baseUrl: this.config.baseUrl,
      health,
      system,
      recall: {
        memory: this.config.enableMemoryRecall,
        skill: this.config.enableSkillRecall,
        knowledge: this.config.enableKnowledgeRecall,
        topK: this.config.recallTopK,
        minScore: this.config.recallMinScore,
      },
      capture: {
        enabled: this.config.captureEnabled,
        thresholdTurns: this.config.captureCommitThresholdTurns,
        thresholdChars: this.config.captureCommitThresholdChars,
      },
    };
  }

  searchMemory(req: RuntimeSearchRequest): Promise<Record<string, unknown>> {
    return this.client.searchMemory({
      query: req.query,
      topK: req.topK ?? this.config.recallTopK,
      threshold: req.minScore,
      searchType: req.searchType ?? "hybrid",
    });
  }

  searchKnowledge(req: RuntimeSearchRequest & { tag: string }): Promise<Record<string, unknown>> {
    return this.client.searchKnowledge({
      query: req.query,
      tag: req.tag,
      topK: req.topK ?? this.config.recallTopK,
      searchType: req.searchType ?? "hybrid",
    });
  }

  listKnowledge(): Promise<Record<string, unknown>> {
    return this.client.listKnowledge();
  }

  searchSkill(req: RuntimeSearchRequest): Promise<Record<string, unknown>> {
    return this.client.searchSkill({
      query: req.query,
      topK: req.topK ?? this.config.recallTopK,
      threshold: req.minScore,
      searchType: req.searchType ?? "hybrid",
    });
  }

  getMemory(memoryId: string): Promise<Record<string, unknown>> {
    return this.client.getMemory({ memoryId });
  }

  getSkill(skillId: string): Promise<Record<string, unknown>> {
    return this.client.getSkill({ skillId });
  }

  async saveMemory(req: MemorySaveRequest): Promise<Record<string, unknown>> {
    try {
      return await this.client.saveMemory(req);
    } catch (error) {
      throw normalizeCommitError(error);
    }
  }

  async commitSessionMemory(req: CommitSessionMemoryRequest): Promise<CommitSessionMemoryResult> {
    const raw = await this.saveMemory({
      title: req.title,
      messages: req.messages,
      metadata: req.metadata,
      wait: req.wait ?? true,
    });
    return {
      raw,
      memoryId: readString(raw, ["memory_id", "memoryId", "id"]),
      taskId: readString(raw, ["task_id", "taskId"]),
      summary: readString(raw, ["summary", "abstract", "overview"]),
    };
  }

  getTask(taskId: string): Promise<Record<string, unknown>> {
    return this.client.getTask(taskId);
  }

  pollTask(taskId: string, opts: PollOptions): Promise<Record<string, unknown>> {
    return this.client.pollTask(taskId, opts);
  }
}

export function createBibleRuntime(options: BibleRuntimeOptions): BibleRuntime {
  return new BibleRuntime(options);
}

function normalizeCommitError(error: unknown): BibleAtlasError {
  const bibleError = toBibleError(error);
  if (bibleError.statusCode === 422) {
    return new BibleAtlasError("BIBLE_CONTRACT_MISMATCH", bibleError.message, {
      statusCode: bibleError.statusCode,
      serverErrorCode: bibleError.serverErrorCode,
      details: bibleError.details,
    });
  }
  return bibleError;
}

function readString(payload: Record<string, unknown>, keys: string[]): string | undefined {
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "string" && value.trim() !== "") return value;
  }
  return undefined;
}

function serializeError(error: unknown): Record<string, unknown> {
  if (error instanceof Error) {
    return { name: error.name, message: error.message };
  }
  return { error };
}
