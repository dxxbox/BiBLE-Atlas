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

export function createSkillTools(runtime: BibleRuntime): OpenClawTool[] {
  return [
    {
      name: "bible_skill_search",
      description: "Search BiBLE Atlas skills.",
      parameters: {
        type: "object",
        additionalProperties: false,
        required: ["query"],
        properties: {
          query: { type: "string", minLength: 1 },
          topK: { type: "integer", minimum: 1, maximum: 50 },
          searchType: { type: "string", enum: ["text", "vector", "hybrid"], default: "hybrid" },
        },
      },
      async execute(...args) {
        try {
          const params = extractParams<Record<string, unknown>>(args);
          const payload = await runtime.searchSkill({
            query: requireString(params, "query"),
            topK: optionalNumber(params, "topK"),
            searchType: optionalString(params, "searchType") as "text" | "vector" | "hybrid" | undefined,
          });
          return textResult(summarizeHits(payload, "skill"), payload);
        } catch (error) {
          return errorResult(error);
        }
      },
    },
    {
      name: "bible_skill_get",
      description: "Fetch or locate a BiBLE Atlas skill by id or name.",
      parameters: {
        type: "object",
        additionalProperties: false,
        required: ["skillId"],
        properties: {
          skillId: { type: "string", minLength: 1 },
        },
      },
      async execute(...args) {
        try {
          const params = extractParams<Record<string, unknown>>(args);
          const skillId = requireString(params, "skillId");
          const payload = await runtime.getSkill(skillId);
          return textResult(`Fetched BiBLE skill ${skillId}.`, payload);
        } catch (error) {
          return errorResult(error);
        }
      },
    },
  ];
}
