import { BibleConfigError, type BiblePluginConfig, type BiblePluginConfigInput } from "./types.js";

const DEFAULTS = {
  timeoutMs: 30_000,
  contextEngineId: "bible-atlas",
  enableMemoryRecall: true,
  enableSkillRecall: false,
  enableKnowledgeRecall: false,
  recallTopK: 8,
  recallMinScore: 0.35,
  injectionTokenBudget: 1_200,
  captureEnabled: true,
  captureCommitThresholdTurns: 8,
  captureCommitThresholdChars: 16_000,
} as const;

export function resolveBibleConfig(raw: unknown): BiblePluginConfig {
  const input = isRecord(raw) ? (raw as BiblePluginConfigInput) : {};
  const issues: Array<{ path: string; message: string }> = [];

  const envBaseUrl = process.env.BIBLE_ATLAS_BASE_URL ?? process.env.BIBLE_CLI_BASE_URL;
  const baseUrl = readString(input.baseUrl, "baseUrl", issues) ?? envBaseUrl;
  if (!baseUrl || baseUrl.trim() === "") {
    issues.push({ path: "baseUrl", message: "baseUrl is required." });
  }

  const token = readOptionalString(input.token, "token", issues);
  const timeoutMs = readInteger(input.timeoutMs, "timeoutMs", DEFAULTS.timeoutMs, issues, {
    min: 1_000,
  });
  const contextEngineId =
    readString(input.contextEngineId, "contextEngineId", issues) ?? DEFAULTS.contextEngineId;
  const enableMemoryRecall = readBoolean(
    input.enableMemoryRecall,
    "enableMemoryRecall",
    DEFAULTS.enableMemoryRecall,
    issues,
  );
  const enableSkillRecall = readBoolean(
    input.enableSkillRecall,
    "enableSkillRecall",
    DEFAULTS.enableSkillRecall,
    issues,
  );
  const enableKnowledgeRecall = readBoolean(
    input.enableKnowledgeRecall,
    "enableKnowledgeRecall",
    DEFAULTS.enableKnowledgeRecall,
    issues,
  );
  const knowledgeTags = readStringArray(input.knowledgeTags, "knowledgeTags", issues);
  const recallTopK = readInteger(input.recallTopK, "recallTopK", DEFAULTS.recallTopK, issues, {
    min: 1,
    max: 50,
  });
  const recallMinScore = readNumber(
    input.recallMinScore,
    "recallMinScore",
    DEFAULTS.recallMinScore,
    issues,
    { min: 0, max: 1 },
  );
  const injectionTokenBudget = readInteger(
    input.injectionTokenBudget,
    "injectionTokenBudget",
    DEFAULTS.injectionTokenBudget,
    issues,
    { min: 128 },
  );
  const captureEnabled = readBoolean(
    input.captureEnabled,
    "captureEnabled",
    DEFAULTS.captureEnabled,
    issues,
  );
  const captureCommitThresholdTurns = readInteger(
    input.captureCommitThresholdTurns,
    "captureCommitThresholdTurns",
    DEFAULTS.captureCommitThresholdTurns,
    issues,
    { min: 1 },
  );
  const captureCommitThresholdChars = readInteger(
    input.captureCommitThresholdChars,
    "captureCommitThresholdChars",
    DEFAULTS.captureCommitThresholdChars,
    issues,
    { min: 1_000 },
  );
  const bypassSessionPatterns = readStringArray(
    input.bypassSessionPatterns,
    "bypassSessionPatterns",
    issues,
  );
  const compiledBypassPatterns = compileRegexes(bypassSessionPatterns, issues);

  if (issues.length > 0) {
    throw new BibleConfigError("Invalid bible-oc-plugin configuration.", issues);
  }

  const config: BiblePluginConfig = {
    baseUrl: normalizeBaseUrl(baseUrl ?? ""),
    timeoutMs,
    contextEngineId,
    enableMemoryRecall,
    enableSkillRecall,
    enableKnowledgeRecall,
    knowledgeTags,
    recallTopK,
    recallMinScore,
    injectionTokenBudget,
    captureEnabled,
    captureCommitThresholdTurns,
    captureCommitThresholdChars,
    bypassSessionPatterns,
    compiledBypassPatterns,
  };
  if (token !== undefined) {
    config.token = token;
  }
  return config;
}

export function normalizeBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

function readString(
  raw: unknown,
  path: string,
  issues: Array<{ path: string; message: string }>,
): string | undefined {
  if (raw === undefined || raw === null) return undefined;
  if (typeof raw !== "string") {
    issues.push({ path, message: "Expected a string." });
    return undefined;
  }
  return raw;
}

function readOptionalString(
  raw: unknown,
  path: string,
  issues: Array<{ path: string; message: string }>,
): string | undefined {
  const value = readString(raw, path, issues);
  if (value === undefined || value.trim() === "") return undefined;
  return value;
}

function readBoolean(
  raw: unknown,
  path: string,
  fallback: boolean,
  issues: Array<{ path: string; message: string }>,
): boolean {
  if (raw === undefined || raw === null) return fallback;
  if (typeof raw !== "boolean") {
    issues.push({ path, message: "Expected a boolean." });
    return fallback;
  }
  return raw;
}

function readInteger(
  raw: unknown,
  path: string,
  fallback: number,
  issues: Array<{ path: string; message: string }>,
  opts: { min?: number; max?: number },
): number {
  if (raw === undefined || raw === null) return fallback;
  if (typeof raw !== "number" || !Number.isInteger(raw)) {
    issues.push({ path, message: "Expected an integer." });
    return fallback;
  }
  if (opts.min !== undefined && raw < opts.min) {
    issues.push({ path, message: `Expected a value >= ${opts.min}.` });
  }
  if (opts.max !== undefined && raw > opts.max) {
    issues.push({ path, message: `Expected a value <= ${opts.max}.` });
  }
  return raw;
}

function readNumber(
  raw: unknown,
  path: string,
  fallback: number,
  issues: Array<{ path: string; message: string }>,
  opts: { min?: number; max?: number },
): number {
  if (raw === undefined || raw === null) return fallback;
  if (typeof raw !== "number" || !Number.isFinite(raw)) {
    issues.push({ path, message: "Expected a finite number." });
    return fallback;
  }
  if (opts.min !== undefined && raw < opts.min) {
    issues.push({ path, message: `Expected a value >= ${opts.min}.` });
  }
  if (opts.max !== undefined && raw > opts.max) {
    issues.push({ path, message: `Expected a value <= ${opts.max}.` });
  }
  return raw;
}

function readStringArray(
  raw: unknown,
  path: string,
  issues: Array<{ path: string; message: string }>,
): string[] {
  if (raw === undefined || raw === null) return [];
  if (!Array.isArray(raw)) {
    issues.push({ path, message: "Expected an array of strings." });
    return [];
  }
  const values: string[] = [];
  raw.forEach((item, index) => {
    if (typeof item !== "string") {
      issues.push({ path: `${path}[${index}]`, message: "Expected a string." });
      return;
    }
    if (item.trim() !== "") {
      values.push(item);
    }
  });
  return values;
}

function compileRegexes(
  patterns: string[],
  issues: Array<{ path: string; message: string }>,
): RegExp[] {
  return patterns.flatMap((pattern, index) => {
    try {
      return [new RegExp(pattern)];
    } catch (error) {
      issues.push({
        path: `bypassSessionPatterns[${index}]`,
        message: error instanceof Error ? error.message : "Invalid regular expression.",
      });
      return [];
    }
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
