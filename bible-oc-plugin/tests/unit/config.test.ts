import { describe, expect, it } from "vitest";
import { resolveBibleConfig } from "../../src/config/schema.js";

describe("config schema", () => {
  it("merges defaults and compiles bypass regex", () => {
    const config = resolveBibleConfig({ baseUrl: "http://127.0.0.1:5555/", bypassSessionPatterns: ["^scratch:"] });
    expect(config.baseUrl).toBe("http://127.0.0.1:5555");
    expect(config.enableMemoryRecall).toBe(true);
    expect(config.enableSkillRecall).toBe(false);
    expect(config.compiledBypassPatterns[0].test("scratch:1")).toBe(true);
  });

  it("requires baseUrl", () => {
    expect(() => resolveBibleConfig({})).toThrow(/baseUrl/);
  });

  it("unwraps config from full OpenClaw config", () => {
    const config = resolveBibleConfig({ plugins: { entries: { "bible-oc-plugin": { config: { baseUrl: "http://x" } } } } });
    expect(config.baseUrl).toBe("http://x");
  });

  it("reports invalid regex", () => {
    expect(() => resolveBibleConfig({ baseUrl: "http://x", bypassSessionPatterns: ["["] })).toThrow(/Invalid bypassSessionPatterns/);
  });
});
