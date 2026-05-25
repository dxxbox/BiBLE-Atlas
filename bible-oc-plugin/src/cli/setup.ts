import { readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { mkdir } from "node:fs/promises";
import { resolveBibleConfig } from "../config/schema.js";
import type { BibleRuntime } from "../runtime/bible-runtime.js";

export interface SetupOptions {
  baseUrl: string;
  token?: string;
  timeoutMs?: number;
  enableMemoryRecall?: boolean;
  enableSkillRecall?: boolean;
  enableKnowledgeRecall?: boolean;
  knowledgeTags?: string[];
  bypassSessionPatterns?: string[];
  write?: boolean;
  configPath?: string;
}

export async function executeBibleSetup(opts: SetupOptions, deps: { runtimeFactory: (config: ReturnType<typeof resolveBibleConfig>) => BibleRuntime }): Promise<Record<string, unknown>> {
  const config = resolveBibleConfig({
    baseUrl: opts.baseUrl,
    token: opts.token,
    timeoutMs: opts.timeoutMs,
    enableMemoryRecall: opts.enableMemoryRecall,
    enableSkillRecall: opts.enableSkillRecall,
    enableKnowledgeRecall: opts.enableKnowledgeRecall,
    knowledgeTags: opts.knowledgeTags,
    bypassSessionPatterns: opts.bypassSessionPatterns,
  });
  const runtime = deps.runtimeFactory(config);
  const health = await runtime.probeHealth();
  const nextConfig = {
    plugins: {
      entries: {
        "bible-oc-plugin": { enabled: true, config: publicConfig(config) },
      },
      slots: { contextEngine: "bible-oc-plugin" },
    },
  };
  if (opts.write) {
    if (!opts.configPath) throw new Error("configPath is required when write is true.");
    await writeOpenClawConfig(opts.configPath, nextConfig);
  }
  return { ok: true, write: opts.write === true, health, config: nextConfig };
}

async function writeOpenClawConfig(path: string, patch: Record<string, unknown>): Promise<void> {
  let existing: Record<string, unknown> = {};
  try {
    existing = JSON.parse(await readFile(path, "utf8")) as Record<string, unknown>;
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code !== "ENOENT") throw err;
  }
  const merged = deepMerge(existing, patch);
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, JSON.stringify(merged, null, 2) + "\n", "utf8");
}

function publicConfig(config: ReturnType<typeof resolveBibleConfig>): Record<string, unknown> {
  const { compiledBypassPatterns, ...rest } = config;
  return rest;
}

function deepMerge(target: Record<string, unknown>, patch: Record<string, unknown>): Record<string, unknown> {
  const out = { ...target };
  for (const [key, value] of Object.entries(patch)) {
    out[key] = isRecord(value) && isRecord(out[key]) ? deepMerge(out[key] as Record<string, unknown>, value) : value;
  }
  return out;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
