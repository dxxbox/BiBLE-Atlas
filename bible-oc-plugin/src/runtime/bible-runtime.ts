import type { ResolvedBibleConfig } from "../config/types.js";
import { BibleAtlasClient, type MemorySaveRequest, type SearchRequest } from "../http/client.js";
import { BibleAtlasError, toBibleAtlasError } from "../http/errors.js";
import { actionLogger, errorMeta, log } from "../logging.js";
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
  abstract?: string;
  overview?: string;
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

  const client = opts.client ?? new BibleAtlasClient({ baseUrl: opts.config.baseUrl, token: opts.config.token, timeoutMs: 
    opts.config.timeoutMs, defaultKbIndex: opts.config.defaultKbIndex, sourceClient: opts.config.sourceClient, logger:opts.logger });

  log(opts.logger, "info", "runtime created", { baseUrl: opts.config.baseUrl, timeoutMs: opts.config.timeoutMs });

  return {
    probeHealth: () => runRuntimeAction(opts.logger, "runtime.probeHealth", {}, () => client.health()),
    status: () => runRuntimeAction(opts.logger, "runtime.status", {}, () => client.systemStatus()),
    searchMemory: (req) => runRuntimeAction(opts.logger, "runtime.searchMemory", searchMeta(req), () => client.searchMemory(req)),
    searchKnowledge: (req) => runRuntimeAction(opts.logger, "runtime.searchKnowledge", { ...searchMeta(req), tag: req.tag }, () => client.searchKnowledge(req)),
    listKnowledge: () => runRuntimeAction(opts.logger, "runtime.listKnowledge", {}, () => client.listKnowledge()),
    searchSkill: (req) => runRuntimeAction(opts.logger, "runtime.searchSkill", searchMeta(req), () => client.searchSkill(req)),
    getSkill: (req) => runRuntimeAction(opts.logger, "runtime.getSkill", { skillId: req.skillId, name: req.name }, () => client.getSkill(req)),
    saveMemory: (req) => runRuntimeAction(opts.logger, "runtime.saveMemory", { messageCount: req.messages.length, wait: req.wait === true, hasKbIndex: Boolean(req.kbIndex) }, () => client.saveMemory(req)),
    getMemory: (req) => runRuntimeAction(opts.logger, "runtime.getMemory", { memoryId: req.memoryId }, () => client.getMemory(req)),
    getTask: (taskId) => runRuntimeAction(opts.logger, "runtime.getTask", { taskId }, () => client.getTask(taskId)),
    pollTask: (taskId, pollOpts) => runRuntimeAction(opts.logger, "runtime.pollTask", { taskId, intervalMs: pollOpts?.intervalMs, timeoutMs: pollOpts?.timeoutMs }, () => client.pollTask(taskId, pollOpts)),
    async commitSessionMemory(req) {
      const action = actionLogger(opts.logger, "runtime.commitSessionMemory", { reason: req.reason, sessionKey: req.sessionKey, messageCount: req.messages.length });
      action.start();
      try {
        const raw = await client.saveMemory({
          title: req.title,
          abstract: req.abstract,
          overview: req.overview,
          messages: req.messages,
          metadata: { ...req.metadata, sessionKey: req.sessionKey, sessionId: req.sessionId, reason: req.reason },
          wait: req.reason === "compact" || req.reason === "before_reset" || req.reason === "session_end",
        });
        const result = {
          memoryId: firstString(raw, ["memory_id", "memoryId", "id"]),
          taskId: firstString(raw, ["task_id", "taskId"]),
          summary: firstString(raw, ["summary", "abstract", "overview"]),
          raw,
        };
        action.done({ memoryId: result.memoryId, taskId: result.taskId });
        return result;
      } catch (err) {
        const mapped = toBibleAtlasError(err);
        opts.logger?.warn?.("BiBLE session commit failed", { code: mapped.code, reason: req.reason, sessionKey: req.sessionKey, error: errorMeta(mapped) });
        action.fail(mapped);
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

async function runRuntimeAction<T>(logger: PluginLogger | undefined, name: string, meta: Record<string, unknown>, fn: () => Promise<T>): Promise<T> {
  const action = actionLogger(logger, name, meta);
  action.start();
  try {
    const result = await fn();
    action.done(resultMeta(result));
    return result;
  } catch (err) {
    action.fail(toBibleAtlasError(err));
    throw err;
  }
}

function searchMeta(req: SearchRequest): Record<string, unknown> {
  return { queryLength: req.query.length, topK: req.topK, minScore: req.minScore, searchType: req.searchType };
}

function resultMeta(result: unknown): Record<string, unknown> {
  if (typeof result !== "object" || result === null || Array.isArray(result)) return {};
  const record = result as Record<string, unknown>;
  const hits = Array.isArray(record.hits) ? record.hits.length : Array.isArray(record.results) ? record.results.length : undefined;
  return { hits, status: record.status, taskId: record.task_id ?? record.taskId };
}
