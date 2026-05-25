import type { BibleRuntime } from "../runtime/bible-runtime.js";
import type { OpenClawTool } from "../types/openclaw.js";
import {
  errorResult,
  extractParams,
  optionalBoolean,
  optionalNumber,
  optionalString,
  requireString,
  summarizeHits,
  textResult,
  trimText,
} from "./common.js";

export function createMemoryTools(runtime: BibleRuntime): OpenClawTool[] {
  return [
    {
      name: "bible_memory_search",
      description: "Search BiBLE Atlas conversation memory.",
      parameters: {
        type: "object",
        additionalProperties: false,
        required: ["query"],
        properties: {
          query: { type: "string", minLength: 1, description: "Search query." },
          topK: { type: "integer", minimum: 1, maximum: 50 },
          searchType: { type: "string", enum: ["text", "vector", "hybrid"], default: "hybrid" },
          minScore: { type: "number", minimum: 0, maximum: 1 },
        },
      },
      async execute(...args) {
        try {
          const params = extractParams<Record<string, unknown>>(args);
          const query = requireString(params, "query");
          const payload = await runtime.searchMemory({
            query,
            topK: optionalNumber(params, "topK"),
            minScore: optionalNumber(params, "minScore"),
            searchType: optionalString(params, "searchType") as "text" | "vector" | "hybrid" | undefined,
          });
          return textResult(summarizeHits(payload, "memory"), payload);
        } catch (error) {
          return errorResult(error);
        }
      },
    },
    {
      name: "bible_memory_save",
      description: "Save structured conversation content into BiBLE Atlas memory.",
      parameters: {
        type: "object",
        additionalProperties: false,
        required: ["messages"],
        properties: {
          title: { type: "string" },
          messages: {
            type: "array",
            items: {
              type: "object",
              required: ["role", "content"],
              properties: {
                role: { type: "string", enum: ["user", "assistant", "tool"] },
                content: { type: "string" },
              },
            },
          },
          kbIndex: { type: "string" },
          metadata: { type: "object" },
          wait: { type: "boolean", default: false },
        },
      },
      async execute(...args) {
        try {
          const params = extractParams<Record<string, unknown>>(args);
          const messages = normalizeMessages(params.messages);
          const payload = await runtime.saveMemory({
            title: optionalString(params, "title"),
            messages,
            kbIndex: optionalString(params, "kbIndex"),
            metadata: isRecord(params.metadata) ? params.metadata : undefined,
            wait: optionalBoolean(params, "wait") ?? false,
          });
          const title = optionalString(params, "title") ?? "untitled memory";
          return textResult(`Saved BiBLE memory: ${trimText(title, 120)}.`, payload);
        } catch (error) {
          return errorResult(error);
        }
      },
    },
    {
      name: "bible_memory_get",
      description: "Fetch or locate a BiBLE memory by id.",
      parameters: {
        type: "object",
        additionalProperties: false,
        required: ["memoryId"],
        properties: {
          memoryId: { type: "string", minLength: 1 },
        },
      },
      async execute(...args) {
        try {
          const params = extractParams<Record<string, unknown>>(args);
          const memoryId = requireString(params, "memoryId");
          const payload = await runtime.getMemory(memoryId);
          return textResult(`Fetched BiBLE memory ${memoryId}.`, payload);
        } catch (error) {
          return errorResult(error);
        }
      },
    },
  ];
}

function normalizeMessages(raw: unknown): Array<{ role: "user" | "assistant" | "tool"; content: string }> {
  if (!Array.isArray(raw) || raw.length === 0) {
    throw new Error("messages must be a non-empty array.");
  }
  return raw.map((item) => {
    if (!isRecord(item)) throw new Error("Each message must be an object.");
    const role = item.role;
    if (role !== "user" && role !== "assistant" && role !== "tool") {
      throw new Error("Message role must be user, assistant, or tool.");
    }
    if (typeof item.content !== "string" || item.content.trim() === "") {
      throw new Error("Message content must be a non-empty string.");
    }
    return { role, content: item.content };
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
