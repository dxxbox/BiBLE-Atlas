import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { CORE_TOOL_NAMES } from "../../src/tools/register.js";

const manifest = JSON.parse(readFileSync(new URL("../../openclaw.plugin.json", import.meta.url), "utf8"));
const pkg = JSON.parse(readFileSync(new URL("../../package.json", import.meta.url), "utf8"));

describe("plugin contracts", () => {
  it("keeps manifest tool contract aligned with runtime registry", () => {
    expect(manifest.contracts.tools).toEqual([...CORE_TOOL_NAMES]);
    expect(Object.keys(manifest.toolMetadata).sort()).toEqual([...CORE_TOOL_NAMES].sort());
  });

  it("declares context engine metadata and config schema", () => {
    expect(manifest.kind).toBe("context-engine");
    expect(manifest.activation).toHaveProperty("onStartup");
    expect(manifest.configSchema.required).not.toContain("baseUrl");
    expect(manifest.configSchema.properties).toHaveProperty("bypassSessionPatterns");
    expect(manifest.configSchema.properties).toHaveProperty("enableMemoryRecall");
  });

  it("pins OpenClaw compatibility baseline", () => {
    expect(pkg.engines.openclaw).toBe(">=2026.5.18");
    expect(pkg.openclaw.compat.pluginApi).toBe(">=2026.5.18");
    expect(pkg.openclaw.compat.minGatewayVersion).toBe("2026.5.18");
    expect(pkg.openclaw.runtimeExtensions).toContain("./dist/index.js");
  });
});
