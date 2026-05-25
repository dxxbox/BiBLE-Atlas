import type { BibleRuntime } from "../runtime/bible-runtime.js";
import { BIBLE_CORE_TOOL_NAMES } from "../tools/register.js";

export interface StatusOptions {
  json?: boolean;
}

export async function runBibleStatus(
  runtime: BibleRuntime,
  options: StatusOptions = {},
): Promise<Record<string, unknown> | string> {
  const status = await runtime.status();
  const payload = {
    installed: true,
    enabled: true,
    contextEngineSlot: "bible-oc-plugin",
    baseUrl: runtime.config.baseUrl,
    health: status.health,
    memoryRecall: runtime.config.enableMemoryRecall,
    skillRecall: runtime.config.enableSkillRecall,
    knowledgeRecall: runtime.config.enableKnowledgeRecall,
    capture: runtime.config.captureEnabled,
    tools: {
      registered: BIBLE_CORE_TOOL_NAMES.length,
      declared: BIBLE_CORE_TOOL_NAMES.length,
      names: [...BIBLE_CORE_TOOL_NAMES],
    },
  };
  if (options.json) return payload;
  return [
    "BiBLE Atlas plugin",
    `  installed: ${payload.installed ? "yes" : "no"}`,
    `  enabled: ${payload.enabled ? "yes" : "no"}`,
    `  contextEngine slot: ${payload.contextEngineSlot}`,
    `  baseUrl: ${payload.baseUrl}`,
    `  health: ${isHealthy(payload.health) ? "ok" : "error"}`,
    `  memory recall: ${payload.memoryRecall ? "enabled" : "disabled"}`,
    `  skill recall: ${payload.skillRecall ? "enabled" : "disabled"}`,
    `  knowledge recall: ${payload.knowledgeRecall ? "enabled" : "disabled"}`,
    `  capture: ${payload.capture ? "enabled" : "disabled"}`,
    `  tools: ${payload.tools.registered} registered / ${payload.tools.declared} declared`,
  ].join("\n");
}

function isHealthy(value: unknown): boolean {
  return typeof value === "object" && value !== null && "ok" in value && value.ok === true;
}
