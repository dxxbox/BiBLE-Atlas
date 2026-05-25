import { describe, expect, it } from "vitest";
import { BibleConfigError } from "../../src/config/types.js";
import { resolveBibleConfig } from "../../src/config/schema.js";

describe("resolveBibleConfig", () => {
  it("applies defaults and compiles bypass patterns", () => {
    const config = resolveBibleConfig({
      baseUrl: "http://127.0.0.1:5555/",
      bypassSessionPatterns: ["^scratch:"],
    });

    expect(config.baseUrl).toBe("http://127.0.0.1:5555");
    expect(config.enableMemoryRecall).toBe(true);
    expect(config.enableKnowledgeRecall).toBe(false);
    expect(config.recallTopK).toBe(8);
    expect(config.compiledBypassPatterns[0]?.test("scratch:1")).toBe(true);
  });

  it("rejects missing baseUrl and invalid regex", () => {
    expect(() =>
      resolveBibleConfig({
        bypassSessionPatterns: ["["],
      }),
    ).toThrow(BibleConfigError);
  });
});
