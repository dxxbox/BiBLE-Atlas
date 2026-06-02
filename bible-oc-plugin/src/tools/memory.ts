import type { BibleRuntime } from "../runtime/bible-runtime.js";
import type { OpenClawTool } from "../types/openclaw.js";
import { asObject, extractHits, fail, ok, optionalInteger, optionalSearchType, requireString, summarizeHits } from "./helpers.js";

export function createMemoryTools(runtime: BibleRuntime): OpenClawTool[] {
  return [
    {
      name: "bible_memory_search",
      description: "Search BiBLE Atlas memories for relevant conversation context.",
      inputSchema: objectSchema({ query: { type: "string" }, topK: { type: "integer", minimum: 1, maximum: 50 }, searchType: { enum: ["keyword","title", "text", "vector", "hybrid"] }, minScore: { type: "number", minimum: 0, maximum: 1 } }, ["query"]),
      async execute(input) {
        try {
          const args = asObject(input);
          const payload = await runtime.searchMemory({ query: requireString(args, "query"), topK: optionalInteger(args, "topK", 8, 1, 50), minScore: typeof args.minScore === "number" ? args.minScore : undefined, searchType: optionalSearchType(args) });
          return ok(summarizeHits("memory", payload), { hits: extractHits("memory", payload), raw: payload });
        } catch (err) { return fail(err); }
      },
    },
    {
      name: "bible_memory_save",
      description: "Save structured conversation material into BiBLE Atlas memory.",
      inputSchema: objectSchema({ 
        title: { type: "string" }, 
        abstract:     { type: "string" },
        overview:     { type: "string" },
        messages:     { type: "array"  }, 
        kbIndex:      { type: "string" },
        taskIds:      { type: "array"  },
        items:        { type: "string" },
        featureTags:  {type: "array", items: {type: "string"}}, 
        domainTags:   {type: "array", items: {type: "string"}},
        componentTags:{type: "array", items: {type: "string"}},
        metadata:     { type: "object" }, 
        wait:         { type: "boolean"} }, 
        ["messages"]),
      async execute(input) {
        try {
          const args = asObject(input);
          if (!Array.isArray(args.messages)) throw new Error("messages is required.");
          const messages = args.messages.map((message) => normalizeMessage(message));

          const payload = await runtime.saveMemory({
            title: typeof args.title === "string" ? args.title : undefined,
            abstract: typeof args.abstract === "string" ? args.abstract : undefined,
            overview: typeof args.overview === "string" ? args.overview : undefined,
            messages,
            kbIndex: typeof args.kbIndex === "string" ? args.kbIndex : undefined,
            taskIds: Array.isArray(args.taskIds) ? args.taskIds.filter((t) => typeof t === "string") as string[] : undefined,
            featureTags: Array.isArray(args.featureTags) ? args.featureTags.filter((t) => typeof t === "string") as string[] : undefined,
            domainTags: Array.isArray(args.domainTags) ? args.domainTags.filter((t) => typeof t === "string") as string[] : undefined,
            componentTags: Array.isArray(args.componentTags) ? args.componentTags.filter((t) => typeof t === "string") as string[] : undefined,
            metadata: typeof args.metadata === "object" && args.metadata !== null && !Array.isArray(args.metadata) ? args.metadata as Record<string, unknown> : undefined,
            wait: args.wait === true,
          });          
          
          return ok("Saved BiBLE memory request.", { result: payload });
        } catch (err) { return fail(err); }
      },
    },
    {
      name: "bible_memory_get",
      description: "Get a BiBLE Atlas memory by id.",
      inputSchema: objectSchema({ memoryId: { type: "string" } }, ["memoryId"]),
      async execute(input) {
        try {
          const args = asObject(input);
          const payload = await runtime.getMemory({ memoryId: requireString(args, "memoryId") });
          const title = typeof payload.title === "string" ? payload.title : requireString(args, "memoryId");
          return ok(`Loaded BiBLE memory: ${title}.`, { memory: payload });
        } catch (err) { return fail(err); }
      },
    },
  ];
}

function normalizeMessage(message: unknown): { role: "user" | "assistant" | "tool"; content: string } {
  if (typeof message !== "object" || message === null || Array.isArray(message)) throw new Error("Each message must be an object.");
  const record = message as Record<string, unknown>;
  if (record.role !== "user" && record.role !== "assistant" && record.role !== "tool") throw new Error("message.role must be user, assistant, or tool.");
  if (typeof record.content !== "string" || !record.content.trim()) throw new Error("message.content is required.");
  return { role: record.role, content: record.content };
}

function objectSchema(properties: Record<string, unknown>, required: string[]): Record<string, unknown> {
  return { type: "object", additionalProperties: false, required, properties };
}
