#!/usr/bin/env node
import { access, mkdir, readFile, writeFile } from "node:fs/promises";
import { constants } from "node:fs";
import { homedir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const args = parseArgs(process.argv.slice(2));
const configPath = resolveConfigPath(args["openclaw-config"]);

await assertExists(resolve(root, "dist", "index.js"), "Run npm run build before installing.");
await assertExists(resolve(root, "openclaw.plugin.json"), "Missing openclaw.plugin.json.");

const current = await readJson(configPath);
const next = structuredClone(current);
next.plugins ??= {};
next.plugins.entries ??= {};
next.plugins.entries["bible-oc-plugin"] = {
  ...(next.plugins.entries["bible-oc-plugin"] ?? {}),
  enabled: next.plugins.entries["bible-oc-plugin"]?.enabled ?? false,
  localPath: root,
};

const diff = {
  configPath,
  pluginId: "bible-oc-plugin",
  localPath: root,
  enabled: next.plugins.entries["bible-oc-plugin"].enabled,
  contextEngineSlotChanged: false,
};

if (args.write) {
  await mkdir(dirname(configPath), { recursive: true });
  await writeFile(configPath, `${JSON.stringify(next, null, 2)}\n`, "utf8");
  console.log(JSON.stringify({ ok: true, wrote: true, diff }, null, 2));
} else {
  console.log(JSON.stringify({ ok: true, wrote: false, diff }, null, 2));
}

async function assertExists(path, hint) {
  try {
    await access(path, constants.R_OK);
  } catch {
    throw new Error(`${path} is not readable. ${hint}`);
  }
}

async function readJson(path) {
  try {
    const text = await readFile(path, "utf8");
    return JSON.parse(text);
  } catch (error) {
    if (error?.code === "ENOENT") return {};
    throw error;
  }
}

function resolveConfigPath(path) {
  if (path) {
    return path.startsWith("~") ? resolve(homedir(), path.slice(1)) : resolve(path);
  }
  return resolve(homedir(), ".openclaw", "config.json");
}

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--write") {
      parsed.write = true;
      continue;
    }
    if (arg === "--openclaw-config") {
      parsed["openclaw-config"] = argv[index + 1];
      index += 1;
    }
  }
  return parsed;
}
