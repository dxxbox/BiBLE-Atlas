import type { BibleRuntime } from "../runtime/bible-runtime.js";
import type { OpenClawPluginApi, PluginLogger } from "../types/openclaw.js";
import { createKnowledgeTools } from "./knowledge.js";
import { createMemoryTools } from "./memory.js";
import { createSkillTools } from "./skill.js";

export const BIBLE_CORE_TOOL_NAMES = [
  "bible_memory_search",
  "bible_memory_save",
  "bible_memory_get",
  "bible_knowledge_search",
  "bible_knowledge_list",
  "bible_skill_search",
  "bible_skill_get",
] as const;

export function registerBibleTools(
  api: Pick<OpenClawPluginApi, "registerTool">,
  deps: { runtime: BibleRuntime; logger?: PluginLogger },
): void {
  const tools = [
    ...createMemoryTools(deps.runtime),
    ...createKnowledgeTools(deps.runtime),
    ...createSkillTools(deps.runtime),
  ];
  for (const tool of tools) {
    api.registerTool(tool);
    deps.logger?.debug?.("Registered BiBLE Atlas tool.", { tool: tool.name });
  }
}
