import type { BibleRuntime } from "../runtime/bible-runtime.js";
import type { OpenClawTool } from "../types/openclaw.js";
import {
  errorResult,
  extractParams,
  optionalNumber,
  optionalString,
  requireString,
  summarizeHits,
  textResult,
} from "./common.js";

export function createKnowledgeTools(runtime: BibleRuntime): OpenClawTool[] {
  return [
    {
      name: "bible_knowledge_search",
      description: "Search a tagged BiBLE Atlas knowledge base.",
      parameters: {
        type: "object",
        additionalProperties: false,
        required: ["query", "tag"],
        properties: {
          query: { type: "string", minLength: 1 },
          tag: { type: "string", minLength: 1 },
          topK: { type: "integer", minimum: 1, maximum: 50 },
          searchType: { type: "string", enum: ["text", "vector", "hybrid"], default: "hybrid" },
        },
      },
      async execute(...args) {
        try {
          const params = extractParams<Record<string, unknown>>(args);
          const payload = await runtime.searchKnowledge({
            query: requireString(params, "query"),
            tag: requireString(params, "tag"),
            topK: optionalNumber(params, "topK"),
            searchType: optionalString(params, "searchType") as "text" | "vector" | "hybrid" | undefined,
          });
          return textResult(summarizeHits(payload, "knowledge"), payload);
        } catch (error) {
          return errorResult(error);
        }
      },
    },
    {
      name: "bible_knowledge_list",
      description: "List knowledge base tags and documents known to BiBLE Atlas.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {},
      },
      async execute() {
        try {
          const payload = await runtime.listKnowledge();
          return textResult("Fetched BiBLE knowledge list.", payload);
        } catch (error) {
          return errorResult(error);
        }
      },
    },
  ];
}
