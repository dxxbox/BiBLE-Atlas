#!/usr/bin/env node
import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const args = parseArgs(process.argv.slice(2));
const pluginRoot = resolve(new URL("..", import.meta.url).pathname);
const manifestPath = resolve(pluginRoot, "openclaw.plugin.json");
const runtimePath = resolve(pluginRoot, "dist/index.js");
if (!existsSync(manifestPath)) fail("openclaw.plugin.json is missing.");
if (!existsSync(runtimePath)) fail("dist/index.js is missing. Run npm run build first.");
const configPath = args["openclaw-config"] || process.env.OPENCLAW_CONFIG_PATH || process.env.OPENCLAW_CONFIG || `${process.env.HOME}/.openclaw/openclaw.json`;
let config = {};
try { config = JSON.parse(await readFile(configPath, "utf8")); } catch (err) { if (err.code !== "ENOENT") throw err; }
const next = merge(config, { plugins: { entries: { "bible-oc-plugin": { path: pluginRoot, manifest: manifestPath, enabled: false } } } });
const before = JSON.stringify(config, null, 2);
const after = JSON.stringify(next, null, 2);
console.log("BiBLE Atlas OpenClaw plugin local install");
console.log(`config: ${configPath}`);
console.log(`plugin: ${pluginRoot}`);
console.log("diff preview:");
console.log(after === before ? "  no changes" : after);
if (args.write) {
  await mkdir(dirname(configPath), { recursive: true });
  await writeFile(configPath, after + "\n", "utf8");
  console.log("written: yes");
} else {
  console.log("written: no (pass --write to apply)");
}

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--write") out.write = true;
    else if (arg === "--openclaw-config") out["openclaw-config"] = argv[++i];
  }
  return out;
}
function merge(target, patch) {
  const out = { ...target };
  for (const [key, value] of Object.entries(patch)) out[key] = isObject(value) && isObject(out[key]) ? merge(out[key], value) : value;
  return out;
}
function isObject(value) { return typeof value === "object" && value !== null && !Array.isArray(value); }
function fail(message) { console.error(message); process.exit(1); }
