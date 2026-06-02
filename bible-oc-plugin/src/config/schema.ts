import type { BiblePluginConfig, ResolvedBibleConfig } from "./types.js";

export const DEFAULT_BIBLE_CONFIG: Omit<BiblePluginConfig, "baseUrl"> = {
  token: undefined,
  timeoutMs: 30000,
  contextEngineId: "bible-oc-plugin",
  defaultKbIndex: "kb_memory_main",
  sourceClient: "opencollar",
  enableMemoryRecall: true,
  enableSkillRecall: false,
  enableKnowledgeRecall: false,
  knowledgeTags: [],
  recallTopK: 8,
  recallMinScore: 0.35,
  injectionTokenBudget: 1200,
  captureEnabled: true,
  captureCommitThresholdTurns: 8,
  captureCommitThresholdChars: 16000,
  bypassSessionPatterns: [],
};

export class BibleConfigError extends Error {
  readonly code = "BIBLE_CONFIG_INVALID";
}

export function resolveBibleConfig(raw: unknown): ResolvedBibleConfig {
  const source = unwrapOpenClawConfig(raw);
  if (!isObject(source)) {
    throw new BibleConfigError("BiBLE plugin config must be an object.");
  }
  const baseUrl = readString(source.baseUrl, "baseUrl", true);
  const config: BiblePluginConfig = {
    ...DEFAULT_BIBLE_CONFIG,
    baseUrl,
    token: readString(source.token, "token", false) || undefined,
    timeoutMs: readInteger(source.timeoutMs, "timeoutMs", 1000, undefined, DEFAULT_BIBLE_CONFIG.timeoutMs),
    contextEngineId: readString(source.contextEngineId, "contextEngineId", false) || DEFAULT_BIBLE_CONFIG.contextEngineId,
    defaultKbIndex: readString(source.defaultKbIndex, "defaultKbIndex", false) || DEFAULT_BIBLE_CONFIG.defaultKbIndex,
    sourceClient: readString(source.sourceClient, "sourceClient", false) || DEFAULT_BIBLE_CONFIG.sourceClient,
    enableMemoryRecall: readBoolean(source.enableMemoryRecall, DEFAULT_BIBLE_CONFIG.enableMemoryRecall),
    enableSkillRecall: readBoolean(source.enableSkillRecall, DEFAULT_BIBLE_CONFIG.enableSkillRecall),
    enableKnowledgeRecall: readBoolean(source.enableKnowledgeRecall, DEFAULT_BIBLE_CONFIG.enableKnowledgeRecall),
    knowledgeTags: readStringArray(source.knowledgeTags, "knowledgeTags", DEFAULT_BIBLE_CONFIG.knowledgeTags),
    recallTopK: readInteger(source.recallTopK, "recallTopK", 1, 50, DEFAULT_BIBLE_CONFIG.recallTopK),
    recallMinScore: readNumber(source.recallMinScore, "recallMinScore", 0, 1, DEFAULT_BIBLE_CONFIG.recallMinScore),
    injectionTokenBudget: readInteger(source.injectionTokenBudget, "injectionTokenBudget", 128, undefined, DEFAULT_BIBLE_CONFIG.injectionTokenBudget),
    captureEnabled: readBoolean(source.captureEnabled, DEFAULT_BIBLE_CONFIG.captureEnabled),
    captureCommitThresholdTurns: readInteger(source.captureCommitThresholdTurns, "captureCommitThresholdTurns", 1, undefined, DEFAULT_BIBLE_CONFIG.captureCommitThresholdTurns),
    captureCommitThresholdChars: readInteger(source.captureCommitThresholdChars, "captureCommitThresholdChars", 1000, undefined, DEFAULT_BIBLE_CONFIG.captureCommitThresholdChars),
    bypassSessionPatterns: readStringArray(source.bypassSessionPatterns, "bypassSessionPatterns", DEFAULT_BIBLE_CONFIG.bypassSessionPatterns),
  };
  return { ...config, compiledBypassPatterns: compileBypassPatterns(config.bypassSessionPatterns) };
}

export function compileBypassPatterns(patterns: string[]): RegExp[] {
  return patterns.map((pattern) => {
    try {
      return new RegExp(pattern);
    } catch (err) {
      throw new BibleConfigError(`Invalid bypassSessionPatterns regex "${pattern}": ${(err as Error).message}`);
    }
  });
}

export function configForManifest(): Record<string, unknown> {
  return {
    baseUrl: { type: "string" },
    timeoutMs: { type: "integer", default: DEFAULT_BIBLE_CONFIG.timeoutMs },
    bypassSessionPatterns: { type: "array", default: [] },
  };
}

function unwrapOpenClawConfig(raw: unknown): unknown {
  if (isObject(raw) && isObject(raw.config)) return raw.config;
  if (isObject(raw)) {
    const entries = isObject(raw.plugins) && isObject(raw.plugins.entries) ? raw.plugins.entries : undefined;
    const pluginEntry = entries && isObject(entries["bible-oc-plugin"]) ? entries["bible-oc-plugin"] : undefined;
    if (pluginEntry && isObject(pluginEntry.config)) return pluginEntry.config;
  }
  return raw;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readString(value: unknown, field: string, required: true): string;
function readString(value: unknown, field: string, required: false): string | undefined;
function readString(value: unknown, field: string, required: boolean): string | undefined {
  if (value === undefined || value === null) {
    if (required) throw new BibleConfigError(`${field} is required.`);
    return undefined;
  }
  if (typeof value !== "string" || value.trim() === "") {
    throw new BibleConfigError(`${field} must be a non-empty string.`);
  }
  return field === "baseUrl" ? value.trim().replace(/\/+$/, "") : value.trim();
}

function readBoolean(value: unknown, fallback: boolean): boolean {
  if (value === undefined) return fallback;
  if (typeof value !== "boolean") throw new BibleConfigError("Expected boolean config value.");
  return value;
}

function readInteger(value: unknown, field: string, min: number, max: number | undefined, fallback: number): number {
  if (value === undefined) return fallback;
  if (typeof value !== "number" || !Number.isInteger(value)) throw new BibleConfigError(`${field} must be an integer.`);
  if (value < min) throw new BibleConfigError(`${field} must be >= ${min}.`);
  if (max !== undefined && value > max) throw new BibleConfigError(`${field} must be <= ${max}.`);
  return value;
}

function readNumber(value: unknown, field: string, min: number, max: number, fallback: number): number {
  if (value === undefined) return fallback;
  if (typeof value !== "number" || Number.isNaN(value)) throw new BibleConfigError(`${field} must be a number.`);
  if (value < min || value > max) throw new BibleConfigError(`${field} must be between ${min} and ${max}.`);
  return value;
}

function readStringArray(value: unknown, field: string, fallback: string[]): string[] {
  if (value === undefined) return [...fallback];
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new BibleConfigError(`${field} must be an array of strings.`);
  }
  return value.map((item) => item.trim()).filter(Boolean);
}
