#!/usr/bin/env node
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const root = process.cwd();
const manifest = JSON.parse(await readFile(resolve(root, "openclaw.plugin.json"), "utf8"));
const pkg = JSON.parse(await readFile(resolve(root, "package.json"), "utf8"));
const registerSource = await readFile(resolve(root, "src", "tools", "register.ts"), "utf8");

const declared = manifest.contracts?.tools ?? [];
const match = registerSource.match(/BIBLE_CORE_TOOL_NAMES\s*=\s*\[([\s\S]*?)\]\s+as const/);
if (!match) fail("Could not find BIBLE_CORE_TOOL_NAMES.");
const registered = Array.from(match[1].matchAll(/"([^"]+)"/g)).map((item) => item[1]);

assertEqualSets(declared, registered, "manifest contracts.tools must match BIBLE_CORE_TOOL_NAMES");
if (manifest.kind !== "context-engine") fail("openclaw.plugin.json kind must be context-engine.");
if (pkg.engines?.openclaw !== ">=2026.5.18") fail("package engines.openclaw must be >=2026.5.18.");
if (pkg.openclaw?.compat?.pluginApi !== ">=2026.5.18") {
  fail("package openclaw.compat.pluginApi must be >=2026.5.18.");
}
if (pkg.openclaw?.build?.openclawVersion !== "2026.5.18") {
  fail("package openclaw.build.openclawVersion must be 2026.5.18.");
}
for (const toolName of declared) {
  if (!manifest.toolMetadata?.[toolName]) fail(`Missing toolMetadata for ${toolName}.`);
}
console.log(JSON.stringify({ ok: true, tools: declared.length }, null, 2));

function assertEqualSets(left, right, message) {
  const leftSorted = [...left].sort();
  const rightSorted = [...right].sort();
  if (JSON.stringify(leftSorted) !== JSON.stringify(rightSorted)) {
    fail(`${message}. left=${JSON.stringify(leftSorted)} right=${JSON.stringify(rightSorted)}`);
  }
}

function fail(message) {
  console.error(message);
  process.exit(1);
}
