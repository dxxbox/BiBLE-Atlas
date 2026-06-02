import type { BibleRuntime } from "../runtime/bible-runtime.js";
import type { OpenClawTool } from "../types/openclaw.js";
import { asObject,extractHits, fail, ok, optionalInteger, optionalSearchType, requireString, summarizeHits } from "./helpers.js";

export function createSkillTools(runtime: BibleRuntime): OpenClawTool[] {
  return [
    {
      name: "bible_skill_search",
      description: "Search BiBLE Atlas skills.",
      inputSchema: schema({ query: { type: "string" }, topK: { type: "integer", minimum: 1, maximum: 50 }, searchType: { enum: ["text", "vector", "hybrid"] } }, ["query"]),
      async execute(input) {
        try {
          const args = asObject(input);
          const payload = await runtime.searchSkill({ query: requireString(args, "query"), topK: optionalInteger(args, "topK", 8, 1, 50), searchType: optionalSearchType(args) });
          return ok(summarizeHits("skill", payload), { hits: extractHits("skill", payload), raw: payload });
        } catch (err) { return fail(err); }
      },
    },
    {
      name: "bible_skill_get",
      description: "Get a BiBLE Atlas skill by id or name.",
      inputSchema: schema({ skillId: { type: "string" }, name: { type: "string" } }, []),
      async execute(input) {
        try {
          const args = asObject(input);
          const skillId = typeof args.skillId === "string" ? args.skillId : undefined;
          const name = typeof args.name === "string" ? args.name : undefined;
          if (!skillId && !name) throw new Error("skillId or name is required.");
          const payload = await runtime.getSkill({ skillId, name });
          return ok(`Loaded BiBLE skill: ${String(payload.name ?? skillId ?? name)}.`, { skill: payload });
        } catch (err) { return fail(err); }
      },
    },
  ];
}

function schema(properties: Record<string, unknown>, required: string[]): Record<string, unknown> {
  return { type: "object", additionalProperties: false, required, properties };
}
