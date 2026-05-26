import { ENDPOINTS } from "./endpoints.js";
import { BibleAtlasError, mapStatusToCode, toBibleAtlasError } from "./errors.js";

export interface BibleAtlasClientOptions {
  baseUrl: string;
  token?: string;
  timeoutMs: number;
  fetchImpl?: typeof fetch;
}

export interface SearchRequest {
  query: string;
  topK?: number;
  minScore?: number;
  searchType?: "text" | "vector" | "hybrid";
  tag?: string;
}

export interface MemorySaveRequest {
  title?: string;
  messages: Array<{ role: "user" | "assistant" | "tool"; content: string; timestamp?: string }>;
  kbIndex?: string;
  metadata?: Record<string, unknown>;
  wait?: boolean;
}

export interface MemoryGetRequest {
  memoryId: string;
}

export interface SkillGetRequest {
  skillId?: string;
  name?: string;
}

export class BibleAtlasClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(private readonly opts: BibleAtlasClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/+$/, "");
    this.fetchImpl = opts.fetchImpl ?? fetch;
  }

  health(): Promise<Record<string, unknown>> {
    return this.getPlain(ENDPOINTS.health);
  }

  async systemStatus(): Promise<Record<string, unknown>> {
    try {
      return await this.getEnvelope(ENDPOINTS.systemStatus);
    } catch (err) {
      const mapped = toBibleAtlasError(err);
      if (mapped.statusCode !== 404 && mapped.code !== "BIBLE_NOT_FOUND") throw mapped;
      return this.getPlain(ENDPOINTS.health);
    }
  }

  searchMemory(req: SearchRequest): Promise<Record<string, unknown>> {
    return this.postEnvelope(ENDPOINTS.memorySearch, searchBody(req, "memory"));
  }

  searchSkill(req: SearchRequest): Promise<Record<string, unknown>> {
    return this.postEnvelope(ENDPOINTS.skillSearch, searchBody(req, "skill"));
  }

  searchKnowledge(req: SearchRequest & { tag: string }): Promise<Record<string, unknown>> {
    return this.postEnvelope(ENDPOINTS.knowledgeSearch, searchBody(req, req.tag));
  }

  async listKnowledge(): Promise<Record<string, unknown>> {
    try {
      return await this.getEnvelope(ENDPOINTS.knowledgeList);
    } catch (err) {
      const mapped = toBibleAtlasError(err);
      if (mapped.statusCode !== 404 && mapped.code !== "BIBLE_NOT_FOUND") throw mapped;
      return this.getEnvelope(ENDPOINTS.knowledgeListFallback);
    }
  }

  saveMemory(req: MemorySaveRequest): Promise<Record<string, unknown>> {
    return this.postEnvelope(ENDPOINTS.memoryImport, {
      title: req.title,
      messages: req.messages,
      kb_index: req.kbIndex,
      metadata: req.metadata,
      wait: req.wait ?? false,
      tag: "memory",
    });
  }

  getMemory(req: MemoryGetRequest): Promise<Record<string, unknown>> {
    return this.postEnvelope(ENDPOINTS.memoryGet, { memory_id: req.memoryId });
  }

  getSkill(req: SkillGetRequest): Promise<Record<string, unknown>> {
    return this.postEnvelope(ENDPOINTS.skillGet, { skill_id: req.skillId, name: req.name });
  }

  getTask(taskId: string): Promise<Record<string, unknown>> {
    return this.getPlain(ENDPOINTS.task(taskId));
  }

  async pollTask(taskId: string, opts: { intervalMs?: number; timeoutMs?: number } = {}): Promise<Record<string, unknown>> {
    const intervalMs = opts.intervalMs ?? 500;
    const deadline = Date.now() + (opts.timeoutMs ?? this.opts.timeoutMs);
    while (true) {
      const payload = await this.getTask(taskId);
      const status = String(payload.status ?? payload.state ?? "");
      if (["completed", "failed", "cancelled"].includes(status)) return payload;
      if (Date.now() >= deadline) throw new BibleAtlasError("BIBLE_TASK_TIMEOUT", `Task ${taskId} did not complete in time.`);
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
  }

  private getPlain(path: string): Promise<Record<string, unknown>> {
    return this.request(path, { method: "GET" }, false);
  }

  private getEnvelope(path: string): Promise<Record<string, unknown>> {
    return this.request(path, { method: "GET" }, true);
  }

  private postEnvelope(path: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.request(path, { method: "POST", body: JSON.stringify(pruneUndefined(body)) }, true);
  }

  private async request(path: string, init: RequestInit, envelope: boolean): Promise<Record<string, unknown>> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.opts.timeoutMs);
    try {
      const headers = new Headers(init.headers);
      if (init.body) headers.set("Content-Type", "application/json");
      if (this.opts.token) headers.set("Authorization", `Bearer ${this.opts.token}`);
      const response = await this.fetchImpl(this.baseUrl + path, { ...init, headers, signal: controller.signal });
      const payload = await readJsonObject(response);
      if (!response.ok) throw errorFromPayload(response.status, payload);
      return envelope ? unwrapEnvelope(payload, response.status) : payload;
    } catch (err) {
      throw toBibleAtlasError(err);
    } finally {
      clearTimeout(timeout);
    }
  }
}

function searchBody(req: SearchRequest, tag: string): Record<string, unknown> {
  return pruneUndefined({
    query: req.query,
    top_k: req.topK,
    threshold: req.minScore,
    search_type: req.searchType ?? "hybrid",
    tag,
  });
}

async function readJsonObject(response: Response): Promise<Record<string, unknown>> {
  const text = await response.text();
  if (!text.trim()) return {};
  const parsed = JSON.parse(text) as unknown;
  return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed) ? parsed as Record<string, unknown> : { result: parsed };
}

function unwrapEnvelope(payload: Record<string, unknown>, statusCode: number): Record<string, unknown> {
  if (payload.status === "ok") {
    const result = payload.result;
    if (result === undefined) return payload;
    return typeof result === "object" && result !== null && !Array.isArray(result) ? result as Record<string, unknown> : { result };
  }
  if (payload.status === "error") throw errorFromPayload(statusCode, payload);
  return payload;
}

function errorFromPayload(statusCode: number, payload: Record<string, unknown>): BibleAtlasError {
  const error = typeof payload.error === "object" && payload.error !== null ? payload.error as Record<string, unknown> : payload;
  const serverCode = typeof error.code === "string" ? error.code : undefined;
  const message = typeof error.message === "string" ? error.message : typeof payload.detail === "string" ? payload.detail : `HTTP request failed with ${statusCode}.`;
  return new BibleAtlasError(mapStatusToCode(statusCode), message, statusCode, serverCode);
}

function pruneUndefined(input: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(input).filter(([, value]) => value !== undefined));
}
