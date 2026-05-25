import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { BIBLE_CORE_TOOL_NAMES } from "../../src/tools/register.js";

describe("plugin contracts", () => {
  it("keeps manifest tool contracts aligned with runtime registry", async () => {
    const manifest = JSON.parse(
      await readFile(resolve(process.cwd(), "openclaw.plugin.json"), "utf8"),
    ) as {
      kind?: string;
      contracts?: { tools?: string[] };
      toolMetadata?: Record<string, unknown>;
    };

    expect(manifest.kind).toBe("context-engine");
    expect(manifest.contracts?.tools?.sort()).toEqual([...BIBLE_CORE_TOOL_NAMES].sort());
    for (const toolName of BIBLE_CORE_TOOL_NAMES) {
      expect(manifest.toolMetadata?.[toolName]).toBeTruthy();
    }
  });
});
