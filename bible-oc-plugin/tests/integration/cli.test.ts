import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resolveBibleConfig } from "../../src/config/schema.js";
import { executeBibleSetup } from "../../src/cli/setup.js";
import { executeBibleStatus, formatStatusText } from "../../src/cli/status.js";
import type { BibleRuntime } from "../../src/runtime/bible-runtime.js";

let temp: string | undefined;
afterEach(async () => { if (temp) await rm(temp, { recursive: true, force: true }); temp = undefined; });

describe("CLI setup/status", () => {
  it("setup --write health-checks before writing plugin config and slot", async () => {
    temp = await mkdtemp(join(tmpdir(), "bible-oc-"));
    const configPath = join(temp, "config.json");
    await executeBibleSetup({ baseUrl: "http://x", write: true, configPath }, { runtimeFactory: () => ({ probeHealth: vi.fn(async () => ({ status: "ok" })) } as unknown as BibleRuntime) });
    const written = JSON.parse(await readFile(configPath, "utf8"));
    expect(written.plugins.entries["bible-oc-plugin"].enabled).toBe(true);
    expect(written.plugins.slots.contextEngine).toBe("bible-oc-plugin");
  });

  it("setup does not write when health fails", async () => {
    temp = await mkdtemp(join(tmpdir(), "bible-oc-"));
    const configPath = join(temp, "config.json");
    await expect(executeBibleSetup({ baseUrl: "http://x", write: true, configPath }, { runtimeFactory: () => ({ probeHealth: vi.fn(async () => { throw new Error("down"); }) } as unknown as BibleRuntime) })).rejects.toThrow("down");
    await expect(readFile(configPath, "utf8")).rejects.toThrow();
  });

  it("status has stable JSON shape and text output", async () => {
    const status = await executeBibleStatus({}, { config: resolveBibleConfig({ baseUrl: "http://x" }), runtime: { probeHealth: vi.fn(async () => ({ status: "ok" })) } as unknown as BibleRuntime });
    expect(status.tools).toMatchObject({ registered: 7, declared: 7, contractAligned: true });
    expect(formatStatusText(status)).toContain("BiBLE Atlas plugin");
  });

  it("status reads enabled state from host config snapshot", async () => {
    const openclawConfig = { plugins: { entries: { "bible-oc-plugin": { enabled: true } }, slots: { contextEngine: "bible-oc-plugin" } } };
    const status = await executeBibleStatus({}, { config: resolveBibleConfig({ baseUrl: "http://x" }), runtime: { probeHealth: vi.fn(async () => ({ status: "ok" })) } as unknown as BibleRuntime, openclawConfig });
    expect(status.enabled).toBe(true);
    expect(status.contextEngineSlot).toBe("bible-oc-plugin");
  });

  it("status is available before plugin setup", async () => {
    const status = await executeBibleStatus({}, {});
    expect(status.baseUrl).toBeNull();
    expect(status.health).toMatchObject({ ok: false, error: "not configured" });
  });
});
