import type { BiblePluginConfig } from "../config/types.js";
import { ENDPOINTS } from "./endpoints.js";
import {
  BibleAtlasError,
  mapHttpStatusToBibleCode,
  normalizeServerErrorCode,
  toBibleError,
} from "./errors.js";

export interface MemorySearchRequest {
  query: string;
  topK?: number;
  threshold?: number;
  searchType?: "text" | "vector" | "hybrid";
  vectorModel?: string;
}

export interface SkillSearchRequest {
  query: string;
  topK?: number;
  threshold?: number;
  searchType?: "text" | "vector" | "hybrid";
}

export interface KnowledgeSearchRequest {
  query: string;
  tag: string;
  topK?: number;
  searchType?: "text" | "vector" | "hybrid";
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
  skillId: string;
}

export interface TaskStatusResponse {
  status?: string;
  task_id?: string;
  taskId?: string;
  result?: unknown;
  error?: unknown;
  [key: string]: unknown;
}

export interface PollOptions {
  intervalMs?: number;
  timeoutMs?: number;
}

export interface MultipartFile {
  filename: string;
  contentType: string;
  content: string;
}

export class BibleAtlasClient {
  private readonly baseUrl: string;
  private readonly token?: string;
  private readonly timeoutMs: number;

  constructor(config: Pick<BiblePluginConfig, "baseUrl" | "token" | "timeoutMs">) {
    this.baseUrl = config.baseUrl.replace(/\/+$/, "");
    if (config.token !== undefined) this.token = config.token;
    this.timeoutMs = config.timeoutMs;
  }

  health(): Promise<Record<string, unknown>> {
    return this.getPlain(ENDPOINTS.health);
  }

  async systemStatus(): Promise<Record<string, unknown>> {
    try {
      return await this.getEnvelope(ENDPOINTS.systemStatus);
    } catch (error) {
      const bibleError = toBibleError(error);
      if (bibleError.code !== "BIBLE_NOT_FOUND") throw bibleError;
      return this.health();
    }
  }

  searchMemory(req: MemorySearchRequest): Promise<Record<string, unknown>> {
    const body: Record<string, unknown> = {
      query: req.query,
      top_k: req.topK ?? 8,
      tag: "memory",
    };
    if (req.threshold !== undefined) body.threshold = req.threshold;
    if (req.searchType !== undefined) body.search_type = req.searchType;
    if (req.vectorModel !== undefined) body.vector_model = req.vectorModel;
    return this.postEnvelope(ENDPOINTS.memorySearch, body);
  }

  searchSkill(req: SkillSearchRequest): Promise<Record<string, unknown>> {
    const body: Record<string, unknown> = {
      query: req.query,
      top_k: req.topK ?? 8,
      tag: "skill",
    };
    if (req.threshold !== undefined) body.threshold = req.threshold;
    if (req.searchType !== undefined) body.search_type = req.searchType;
    return this.postEnvelope(ENDPOINTS.skillSearch, body);
  }

  searchKnowledge(req: KnowledgeSearchRequest): Promise<Record<string, unknown>> {
    const body: Record<string, unknown> = {
      query: req.query,
      tag: req.tag,
      top_k: req.topK ?? 8,
    };
    if (req.searchType !== undefined) body.search_type = req.searchType;
    return this.postEnvelope(ENDPOINTS.knowledgeSearch, body);
  }

  async listKnowledge(): Promise<Record<string, unknown>> {
    try {
      return await this.getEnvelope(ENDPOINTS.knowledgeList);
    } catch (error) {
      const bibleError = toBibleError(error);
      if (bibleError.code !== "BIBLE_NOT_FOUND") throw bibleError;
      return this.getEnvelope(ENDPOINTS.knowledgeListFallback);
    }
  }

  async saveMemory(req: MemorySaveRequest): Promise<Record<string, unknown>> {
    const metadata = {
      ...(req.metadata ?? {}),
      source: "openclaw",
      pluginId: "bible-oc-plugin",
      title: req.title,
    };
    const files: MultipartFile[] = [
      {
        filename: "message.json",
        contentType: "application/json",
        content: JSON.stringify({ messages: req.messages }, null, 2),
      },
      {
        filename: "meta.json",
        contentType: "application/json",
        content: JSON.stringify(metadata, null, 2),
      },
    ];
    const result = await this.postMultipartImport(ENDPOINTS.memoryImport, files, {
      tag: "memory",
      kb_index: req.kbIndex,
    });
    if (!req.wait) return result;
    const taskId = extractTaskId(result);
    if (!taskId) return result;
    const task = await this.pollTask(taskId, {});
    return { ...result, task };
  }

  getMemory(req: MemoryGetRequest): Promise<Record<string, unknown>> {
    return this.searchMemory({ query: req.memoryId, topK: 1, searchType: "text" });
  }

  getSkill(req: SkillGetRequest): Promise<Record<string, unknown>> {
    return this.searchSkill({ query: req.skillId, topK: 1, searchType: "text" });
  }

  getTask(taskId: string): Promise<TaskStatusResponse> {
    return this.getPlain(ENDPOINTS.taskStatus(taskId));
  }

  async pollTask(taskId: string, opts: PollOptions): Promise<TaskStatusResponse> {
    const intervalMs = opts.intervalMs ?? 1_000;
    const timeoutMs = opts.timeoutMs ?? 30_000;
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const payload = await this.getTask(taskId);
      const status = typeof payload.status === "string" ? payload.status : undefined;
      if (status === "completed" || status === "failed" || status === "cancelled") {
        return payload;
      }
      if (Date.now() >= deadline) {
        throw new BibleAtlasError(
          "BIBLE_TASK_TIMEOUT",
          `Task ${taskId} did not complete within ${timeoutMs}ms.`,
        );
      }
      await sleep(intervalMs);
    }
  }

  private async getEnvelope(path: string): Promise<Record<string, unknown>> {
    const payload = await this.requestJson(path, { method: "GET" });
    return unwrapEnvelope(payload);
  }

  private async getPlain(path: string): Promise<Record<string, unknown>> {
    return this.requestJson(path, { method: "GET" });
  }

  private async postEnvelope(
    path: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const payload = await this.requestJson(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return unwrapEnvelope(payload);
  }

  private async postMultipartImport(
    path: string,
    files: MultipartFile[],
    fields: Record<string, string | undefined>,
  ): Promise<Record<string, unknown>> {
    const form = new FormData();
    for (const file of files) {
      form.append("files", new Blob([file.content], { type: file.contentType }), file.filename);
    }
    for (const [key, value] of Object.entries(fields)) {
      if (value !== undefined && value !== "") form.append(key, value);
    }
    return this.requestJson(path, { method: "POST", body: form });
  }

  private async requestJson(path: string, init: RequestInit): Promise<Record<string, unknown>> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const headers = new Headers(init.headers);
      if (this.token) headers.set("Authorization", `Bearer ${this.token}`);
      const response = await fetch(this.baseUrl + path, {
        ...init,
        headers,
        signal: controller.signal,
      });
      const payload = await readJsonObject(response);
      if (!response.ok) {
        throw errorFromPayload(response.status, payload);
      }
      return payload;
    } catch (error) {
      throw toBibleError(error);
    } finally {
      clearTimeout(timeout);
    }
  }
}

export function unwrapEnvelope(payload: Record<string, unknown>): Record<string, unknown> {
  const status = typeof payload.status === "string" ? payload.status : undefined;
  if (status === "ok") {
    const result = payload.result;
    if (isRecord(result)) return result;
    if (result !== undefined) return { result };
    return payload;
  }
  if (status === "error") {
    throw errorFromPayload(500, payload);
  }
  throw new BibleAtlasError("BIBLE_INTERNAL", "Malformed response envelope.", { details: payload });
}

async function readJsonObject(response: Response): Promise<Record<string, unknown>> {
  const text = await response.text();
  if (text.trim() === "") return {};
  try {
    const parsed = JSON.parse(text) as unknown;
    return isRecord(parsed) ? parsed : { result: parsed };
  } catch {
    throw new BibleAtlasError("BIBLE_INTERNAL", "Invalid JSON response.", {
      statusCode: response.status,
    });
  }
}

function errorFromPayload(statusCode: number, payload: Record<string, unknown>): BibleAtlasError {
  if (payload.status === "error" && isRecord(payload.error)) {
    const code = typeof payload.error.code === "string" ? payload.error.code : undefined;
    const message =
      typeof payload.error.message === "string" ? payload.error.message : "Unknown server error.";
    return new BibleAtlasError(normalizeServerErrorCode(code, statusCode), message, {
      statusCode,
      serverErrorCode: code,
      details: payload.error,
    });
  }
  const detail = typeof payload.detail === "string" ? payload.detail : `HTTP request failed with ${statusCode}.`;
  return new BibleAtlasError(mapHttpStatusToBibleCode(statusCode), detail, {
    statusCode,
    details: payload,
  });
}

function extractTaskId(payload: Record<string, unknown>): string | undefined {
  for (const key of ["task_id", "taskId", "id"]) {
    const value = payload[key];
    if (typeof value === "string" && value.trim() !== "") return value;
  }
  if (isRecord(payload.task)) {
    const value = payload.task.task_id ?? payload.task.taskId ?? payload.task.id;
    if (typeof value === "string" && value.trim() !== "") return value;
  }
  return undefined;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
