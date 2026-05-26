import type { ResolvedBibleConfig } from "../config/types.js";
import type { BibleRuntime } from "../runtime/bible-runtime.js";
import { actionLogger, log } from "../logging.js";
import type { OpenClawPluginApi, OpenClawTool, PluginLogger } from "../types/openclaw.js";
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
  log(api.logger, "info", "tools.register start", { toolCount: CORE_TOOL_NAMES.length });
  for (const tool of createBibleTools(deps.runtime)) {
    api.registerTool(wrapToolWithLogging(tool, api.logger));
    log(api.logger, "info", `tools.register tool ${tool.name}`, { tool: tool.name });
  }
  log(api.logger, "info", "tools.register done", { toolCount: CORE_TOOL_NAMES.length });
}

function wrapToolWithLogging(tool: OpenClawTool, logger?: PluginLogger): OpenClawTool {
  return {
    ...tool,
    async execute(input, ctx) {
      const action = actionLogger(logger, "tool.execute", { tool: tool.name, inputKeys: inputKeys(input) });
      action.start();
      try {
        const result = await tool.execute(input, ctx);
        if (result.isError) {
          log(logger, "warn", "tool.execute returned error", { tool: tool.name, details: result.details });
        }
        action.done({ isError: result.isError === true });
        return result;
      } catch (err) {
        action.fail(err);
        throw err;
      }
    },
  };
}

function inputKeys(input: unknown): string[] {
  return typeof input === "object" && input !== null && !Array.isArray(input) ? Object.keys(input as Record<string, unknown>) : [];
}
