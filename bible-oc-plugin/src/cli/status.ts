import { readFile } from "node:fs/promises";
import type { ResolvedBibleConfig } from "../config/types.js";
import type { BibleRuntime } from "../runtime/bible-runtime.js";
import { CORE_TOOL_NAMES } from "../tools/register.js";

export interface StatusOptions {
  json?: boolean;
  configPath?: string;
  registeredTools?: string[];
}

export async function executeBibleStatus(opts: StatusOptions, deps: { config: ResolvedBibleConfig; runtime: BibleRuntime }): Promise<Record<string, unknown>> {
  const openclawConfig = opts.configPath ? await readConfig(opts.configPath) : {};
  const pluginEntry = (((openclawConfig.plugins as Record<string, unknown> | undefined)?.entries as Record<string, unknown> | undefined)?.["bible-oc-plugin"] ?? {}) as Record<string, unknown>;
  const slot = ((openclawConfig.plugins as Record<string, unknown> | undefined)?.slots as Record<string, unknown> | undefined)?.contextEngine;
  let health: Record<string, unknown> | undefined;
  let healthError: string | undefined;
  try {
    health = await deps.runtime.probeHealth();
  } catch (err) {
    healthError = err instanceof Error ? err.message : String(err);
  }
  const registered = opts.registeredTools ?? [...CORE_TOOL_NAMES];
  return {
    installed: true,
    enabled: pluginEntry.enabled === true,
    contextEngineSlot: slot ?? null,
    baseUrl: deps.config.baseUrl,
    health: healthError ? { ok: false, error: healthError } : { ok: true, details: health },
    recall: { memory: deps.config.enableMemoryRecall, skill: deps.config.enableSkillRecall, knowledge: deps.config.enableKnowledgeRecall, knowledgeTags: deps.config.knowledgeTags },
    capture: { enabled: deps.config.captureEnabled, thresholdTurns: deps.config.captureCommitThresholdTurns, thresholdChars: deps.config.captureCommitThresholdChars },
    bypassSessionPatterns: deps.config.bypassSessionPatterns,
    tools: { registered: registered.length, declared: CORE_TOOL_NAMES.length, names: registered, contractAligned: sameSet(registered, [...CORE_TOOL_NAMES]) },
  };
}

export function formatStatusText(status: Record<string, unknown>): string {
  const health = status.health as Record<string, unknown>;
  const recall = status.recall as Record<string, unknown>;
  const capture = status.capture as Record<string, unknown>;
  const tools = status.tools as Record<string, unknown>;
  return [
    "BiBLE Atlas plugin",
    `  installed: ${yesNo(status.installed)}`,
    `  enabled: ${yesNo(status.enabled)}`,
    `  contextEngine slot: ${String(status.contextEngineSlot ?? "none")}`,
    `  baseUrl: ${String(status.baseUrl)}`,
    `  health: ${health.ok ? "ok" : "failed"}`,
    `  memory recall: ${enabled(recall.memory)}`,
    `  skill recall: ${enabled(recall.skill)}`,
    `  knowledge recall: ${enabled(recall.knowledge)}`,
    `  capture: ${enabled(capture.enabled)}`,
    `  tools: ${String(tools.registered)} registered / ${String(tools.declared)} declared`,
  ].join("\n");
}

async function readConfig(path: string): Promise<Record<string, unknown>> {
  try {
    return JSON.parse(await readFile(path, "utf8")) as Record<string, unknown>;
  } catch {
    return {};
  }
}

function sameSet(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((item) => b.includes(item));
}
function yesNo(value: unknown): string { return value ? "yes" : "no"; }
function enabled(value: unknown): string { return value ? "enabled" : "disabled"; }
