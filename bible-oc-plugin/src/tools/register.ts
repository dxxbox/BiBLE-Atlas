import type { ResolvedBibleConfig } from "../config/types.js";
import type { BibleRuntime } from "../runtime/bible-runtime.js";
import type { OpenClawPluginApi } from "../types/openclaw.js";
import { createKnowledgeTools } from "./knowledge.js";
import { createMemoryTools } from "./memory.js";
import { createSkillTools } from "./skill.js";

export const CORE_TOOL_NAMES = [
  "bible_memory_search",
  "bible_memory_save",
  "bible_memory_get",
  "bible_knowledge_search",
  "bible_knowledge_list",
  "bible_skill_search",
  "bible_skill_get",
] as const;

export function createBibleTools(runtime: BibleRuntime) {
  return [...createMemoryTools(runtime), ...createKnowledgeTools(runtime), ...createSkillTools(runtime)];
}

export function registerBibleTools(api: OpenClawPluginApi, deps: { config: ResolvedBibleConfig; runtime: BibleRuntime }): void {
  for (const tool of createBibleTools(deps.runtime)) api.registerTool(tool);
}
