import type { BibleRuntime } from "../runtime/bible-runtime.js";
import type { OpenClawTool } from "../types/openclaw.js";
import { asObject, extractHits, fail, ok, optionalInteger, optionalSearchType, requireString, summarizeHits } from "./helpers.js";

export function createKnowledgeTools(runtime: BibleRuntime): OpenClawTool[] {
  return [
    {
      name: "bible_knowledge_search",
      description: "Search a tagged BiBLE Atlas knowledge base.",
      inputSchema: schema({ query: { type: "string" }, tag: { type: "string" }, topK: { type: "integer", minimum: 1, maximum: 50 }, searchType: { enum: ["text", "vector", "hybrid"] } }, ["query", "tag"]),
      async execute(input) {
        try {
          const args = asObject(input);
          const payload = await runtime.searchKnowledge({ query: requireString(args, "query"), tag: requireString(args, "tag"), topK: optionalInteger(args, "topK", 8, 1, 50), searchType: optionalSearchType(args) });
          return ok(summarizeHits("knowledge", payload), { hits: extractHits("knowledge", payload), raw: payload });
        } catch (err) { return fail(err); }
      },
    },
    {
      name: "bible_knowledge_list",
      description: "List BiBLE Atlas knowledge bases or tags.",
      inputSchema: schema({}, []),
      async execute() {
        try {
          const payload = await runtime.listKnowledge();
          return ok("Loaded BiBLE knowledge list.", { knowledge: payload });
        } catch (err) { return fail(err); }
      },
    },
  ];
}

function schema(properties: Record<string, unknown>, required: string[]): Record<string, unknown> {
  return { type: "object", additionalProperties: false, required, properties };
}
