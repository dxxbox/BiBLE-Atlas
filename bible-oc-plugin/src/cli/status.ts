import { readFile } from "node:fs/promises";
import type { ResolvedBibleConfig } from "../config/types.js";
import type { BibleRuntime } from "../runtime/bible-runtime.js";
import { actionLogger, log } from "../logging.js";
import { CORE_TOOL_NAMES } from "../tools/register.js";
import type { PluginLogger } from "../types/openclaw.js";

export interface StatusOptions {
  json?: boolean;
  configPath?: string;
  registeredTools?: string[];
}

export async function executeBibleStatus(opts: StatusOptions, deps: { config?: ResolvedBibleConfig; runtime?: BibleRuntime; openclawConfig?: unknown; logger?: PluginLogger }): Promise<Record<string, unknown>> {
  const action = actionLogger(deps.logger, "cli.status", { json: opts.json === true, hasConfigPath: Boolean(opts.configPath) });
  action.start();
  const openclawConfig = opts.configPath ? await readConfig(opts.configPath) : readRecord(deps.openclawConfig) ?? {};
  const pluginEntry = (((openclawConfig.plugins as Record<string, unknown> | undefined)?.entries as Record<string, unknown> | undefined)?.["bible-oc-plugin"] ?? {}) as Record<string, unknown>;
  const slot = ((openclawConfig.plugins as Record<string, unknown> | undefined)?.slots as Record<string, unknown> | undefined)?.contextEngine;
  let health: Record<string, unknown> | undefined;
  let healthError: string | undefined;
  if (deps.runtime) {
    try {
      health = await deps.runtime.probeHealth();
    } catch (err) {
      healthError = err instanceof Error ? err.message : String(err);
      log(deps.logger, "warn", "cli.status health check failed", { error: healthError });
    }
  } else {
    healthError = "not configured";
  }
  const registered = opts.registeredTools ?? [...CORE_TOOL_NAMES];
  const status = {
    installed: true,
    enabled: pluginEntry.enabled === true,
    contextEngineSlot: slot ?? null,
    baseUrl: deps.config?.baseUrl ?? null,
    health: healthError ? { ok: false, error: healthError } : { ok: true, details: health },
    recall: { memory: deps.config?.enableMemoryRecall ?? false, skill: deps.config?.enableSkillRecall ?? false, knowledge: deps.config?.enableKnowledgeRecall ?? false, knowledgeTags: deps.config?.knowledgeTags ?? [] },
    capture: { enabled: deps.config?.captureEnabled ?? false, thresholdTurns: deps.config?.captureCommitThresholdTurns ?? null, thresholdChars: deps.config?.captureCommitThresholdChars ?? null },
    bypassSessionPatterns: deps.config?.bypassSessionPatterns ?? [],
    tools: { registered: registered.length, declared: CORE_TOOL_NAMES.length, names: registered, contractAligned: sameSet(registered, [...CORE_TOOL_NAMES]) },
  };
  action.done({ enabled: status.enabled, contextEngineSlot: status.contextEngineSlot, healthOk: (status.health as Record<string, unknown>).ok });
  return status;
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
function readRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}
function yesNo(value: unknown): string { return value ? "yes" : "no"; }
function enabled(value: unknown): string { return value ? "enabled" : "disabled"; }
