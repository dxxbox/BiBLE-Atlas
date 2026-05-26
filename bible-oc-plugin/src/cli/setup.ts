import { readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { mkdir } from "node:fs/promises";
import { resolveBibleConfig } from "../config/schema.js";
import { actionLogger } from "../logging.js";
import type { BibleRuntime } from "../runtime/bible-runtime.js";
import type { PluginLogger } from "../types/openclaw.js";

const DEFAULT_OPENCLAW_CONFIG_PATH = `${process.env.HOME ?? "."}/.openclaw/openclaw.json`;

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

export async function executeBibleSetup(opts: SetupOptions, deps: { runtimeFactory: (config: ReturnType<typeof resolveBibleConfig>) => BibleRuntime; logger?: PluginLogger }): Promise<Record<string, unknown>> {
  const action = actionLogger(deps.logger, "cli.setup", { write: opts.write === true, hasConfigPath: Boolean(opts.configPath) });
  action.start();
  try {
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
        slots: { contextEngine: config.contextEngineId },
      },
    };
    if (opts.write) {
      await writeOpenClawConfig(resolveConfigPath(opts.configPath), nextConfig);
    }
    const result = { ok: true, write: opts.write === true, health, config: nextConfig };
    action.done({ contextEngineId: config.contextEngineId, wrote: opts.write === true });
    return result;
  } catch (err) {
    action.fail(err);
    throw err;
  }
}

export function resolveConfigPath(configPath?: string): string {
  return configPath || process.env.OPENCLAW_CONFIG_PATH || process.env.OPENCLAW_CONFIG || DEFAULT_OPENCLAW_CONFIG_PATH;
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
