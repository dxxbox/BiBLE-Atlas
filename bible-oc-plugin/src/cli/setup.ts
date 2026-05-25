import { readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, resolve } from "node:path";
import { mkdir } from "node:fs/promises";
import { resolveBibleConfig } from "../config/schema.js";
import type { BiblePluginConfig } from "../config/types.js";
import type { BibleRuntime } from "../runtime/bible-runtime.js";

export interface SetupOptions {
  baseUrl?: string;
  token?: string;
  tokenEnv?: string;
  timeoutMs?: number | string;
  knowledgeTag?: string | string[];
  bypassSession?: string | string[];
  enableMemoryRecall?: boolean;
  enableSkillRecall?: boolean;
  enableKnowledgeRecall?: boolean;
  write?: boolean;
  config?: string;
}

export async function runBibleSetup(
  runtime: BibleRuntime,
  options: SetupOptions,
): Promise<Record<string, unknown>> {
  const config = resolveSetupConfig(runtime.config, options);
  const probe = await runtime.probeHealth();
  if (!probe.ok) {
    throw new Error(`BiBLE Atlas health check failed: ${probe.code ?? "UNKNOWN"} ${probe.error ?? ""}`.trim());
  }

  const configPath = resolveConfigPath(options.config);
  const current = await readJsonFile(configPath);
  const next = patchOpenClawConfig(current, config);
  const diff = {
    configPath,
    pluginEnabled: true,
    contextEngine: "bible-oc-plugin",
    baseUrl: config.baseUrl,
  };
  if (options.write) {
    await mkdir(dirname(configPath), { recursive: true });
    await writeFile(configPath, `${JSON.stringify(next, null, 2)}\n`, "utf8");
  }
  return {
    ok: true,
    wrote: Boolean(options.write),
    diff,
    health: probe.payload,
  };
}

export function resolveSetupConfig(base: BiblePluginConfig, options: SetupOptions): BiblePluginConfig {
  const tokenFromEnv =
    options.tokenEnv && process.env[options.tokenEnv] ? process.env[options.tokenEnv] : undefined;
  return resolveBibleConfig({
    ...base,
    baseUrl: options.baseUrl ?? base.baseUrl,
    token: options.token ?? tokenFromEnv ?? base.token,
    timeoutMs: options.timeoutMs !== undefined ? Number(options.timeoutMs) : base.timeoutMs,
    enableMemoryRecall: options.enableMemoryRecall ?? base.enableMemoryRecall,
    enableSkillRecall: options.enableSkillRecall ?? base.enableSkillRecall,
    enableKnowledgeRecall: options.enableKnowledgeRecall ?? base.enableKnowledgeRecall,
    knowledgeTags: normalizeArray(options.knowledgeTag) ?? base.knowledgeTags,
    bypassSessionPatterns: normalizeArray(options.bypassSession) ?? base.bypassSessionPatterns,
  });
}

export function patchOpenClawConfig(raw: Record<string, unknown>, config: BiblePluginConfig): Record<string, unknown> {
  const next = structuredClone(raw);
  const plugins = ensureRecord(next, "plugins");
  const entries = ensureRecord(plugins, "entries");
  entries["bible-oc-plugin"] = {
    enabled: true,
    config: {
      baseUrl: config.baseUrl,
      ...(config.token !== undefined ? { token: config.token } : {}),
      timeoutMs: config.timeoutMs,
      contextEngineId: config.contextEngineId,
      enableMemoryRecall: config.enableMemoryRecall,
      enableSkillRecall: config.enableSkillRecall,
      enableKnowledgeRecall: config.enableKnowledgeRecall,
      knowledgeTags: config.knowledgeTags,
      recallTopK: config.recallTopK,
      recallMinScore: config.recallMinScore,
      injectionTokenBudget: config.injectionTokenBudget,
      captureEnabled: config.captureEnabled,
      captureCommitThresholdTurns: config.captureCommitThresholdTurns,
      captureCommitThresholdChars: config.captureCommitThresholdChars,
      bypassSessionPatterns: config.bypassSessionPatterns,
    },
  };
  const slots = ensureRecord(plugins, "slots");
  slots.contextEngine = "bible-oc-plugin";
  return next;
}

export function resolveConfigPath(path?: string): string {
  if (path && path.trim() !== "") {
    return path.startsWith("~") ? resolve(homedir(), path.slice(1)) : resolve(path);
  }
  return resolve(homedir(), ".openclaw", "config.json");
}

async function readJsonFile(path: string): Promise<Record<string, unknown>> {
  try {
    const text = await readFile(path, "utf8");
    const parsed = JSON.parse(text) as unknown;
    return isRecord(parsed) ? parsed : {};
  } catch (error) {
    if (isNodeError(error) && error.code === "ENOENT") return {};
    throw error;
  }
}

function ensureRecord(parent: Record<string, unknown>, key: string): Record<string, unknown> {
  const existing = parent[key];
  if (isRecord(existing)) return existing;
  const created: Record<string, unknown> = {};
  parent[key] = created;
  return created;
}

function normalizeArray(value: string | string[] | undefined): string[] | undefined {
  if (value === undefined) return undefined;
  return Array.isArray(value) ? value : [value];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNodeError(error: unknown): error is NodeJS.ErrnoException {
  return error instanceof Error && "code" in error;
}
