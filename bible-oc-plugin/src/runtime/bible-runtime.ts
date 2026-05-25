import type { ResolvedBibleConfig } from "../config/types.js";
import { BibleAtlasClient, type MemorySaveRequest, type SearchRequest } from "../http/client.js";
import { BibleAtlasError, toBibleAtlasError } from "../http/errors.js";
import type { PluginLogger } from "../types/openclaw.js";

export interface BibleRuntime {
  probeHealth(): Promise<Record<string, unknown>>;
  status(): Promise<Record<string, unknown>>;
  searchMemory(req: SearchRequest): Promise<Record<string, unknown>>;
  searchKnowledge(req: SearchRequest & { tag: string }): Promise<Record<string, unknown>>;
  listKnowledge(): Promise<Record<string, unknown>>;
  searchSkill(req: SearchRequest): Promise<Record<string, unknown>>;
  getSkill(req: { skillId?: string; name?: string }): Promise<Record<string, unknown>>;
  saveMemory(req: MemorySaveRequest): Promise<Record<string, unknown>>;
  getMemory(req: { memoryId: string }): Promise<Record<string, unknown>>;
  commitSessionMemory(req: CommitSessionMemoryRequest): Promise<CommitSessionMemoryResponse>;
  getTask(taskId: string): Promise<Record<string, unknown>>;
  pollTask(taskId: string, opts?: { intervalMs?: number; timeoutMs?: number }): Promise<Record<string, unknown>>;
}

export interface CommitSessionMemoryRequest {
  sessionKey: string;
  sessionId?: string;
  reason: "threshold" | "compact" | "before_reset" | "session_end" | "manual";
  title: string;
  messages: Array<{ role: "user" | "assistant" | "tool"; content: string; timestamp?: string }>;
  metadata: Record<string, unknown>;
}

export interface CommitSessionMemoryResponse {
  memoryId?: string;
  taskId?: string;
  summary?: string;
  raw: Record<string, unknown>;
}

export function createBibleRuntime(opts: { config: ResolvedBibleConfig; logger?: PluginLogger; client?: BibleAtlasClient }): BibleRuntime {
  const client = opts.client ?? new BibleAtlasClient({ baseUrl: opts.config.baseUrl, token: opts.config.token, timeoutMs: opts.config.timeoutMs });
  return {
    probeHealth: () => client.health(),
    status: () => client.systemStatus(),
    searchMemory: (req) => client.searchMemory(req),
    searchKnowledge: (req) => client.searchKnowledge(req),
    listKnowledge: () => client.listKnowledge(),
    searchSkill: (req) => client.searchSkill(req),
    getSkill: (req) => client.getSkill(req),
    saveMemory: (req) => client.saveMemory(req),
    getMemory: (req) => client.getMemory(req),
    getTask: (taskId) => client.getTask(taskId),
    pollTask: (taskId, pollOpts) => client.pollTask(taskId, pollOpts),
    async commitSessionMemory(req) {
      try {
        const raw = await client.saveMemory({
          title: req.title,
          messages: req.messages,
          metadata: { ...req.metadata, sessionKey: req.sessionKey, sessionId: req.sessionId, reason: req.reason },
          wait: req.reason === "compact" || req.reason === "before_reset" || req.reason === "session_end",
        });
        return {
          memoryId: firstString(raw, ["memory_id", "memoryId", "id"]),
          taskId: firstString(raw, ["task_id", "taskId"]),
          summary: firstString(raw, ["summary", "abstract", "overview"]),
          raw,
        };
      } catch (err) {
        const mapped = toBibleAtlasError(err);
        opts.logger?.warn?.("BiBLE session commit failed", { code: mapped.code, reason: req.reason, sessionKey: req.sessionKey });
        throw mapped;
      }
    },
  };
}

export function errorDetails(err: unknown): Record<string, unknown> {
  const mapped = err instanceof BibleAtlasError ? err : toBibleAtlasError(err);
  return { code: mapped.code, message: mapped.message, statusCode: mapped.statusCode, serverErrorCode: mapped.serverErrorCode };
}

function firstString(raw: Record<string, unknown>, keys: string[]): string | undefined {
  for (const key of keys) if (typeof raw[key] === "string") return raw[key] as string;
  return undefined;
}
