import { describe, expect, it, vi } from "vitest";
import { createBibleTools, CORE_TOOL_NAMES } from "../../src/tools/register.js";
import type { BibleRuntime } from "../../src/runtime/bible-runtime.js";

describe("tools", () => {
  it("registers first-delivery core tools", () => {
    const tools = createBibleTools({} as BibleRuntime);
    expect(tools.map((tool) => tool.name)).toEqual([...CORE_TOOL_NAMES]);
  });

  it("returns model-visible content and structured details", async () => {
    const tools = createBibleTools({ searchMemory: vi.fn(async () => ({ results: { memory: [{ title: "A", score: 0.8 }] } })) } as unknown as BibleRuntime);
    const result = await tools.find((tool) => tool.name === "bible_memory_search")!.execute({ query: "A" });
    expect(result.content).toContain("Found 1 BiBLE memory hits");
    expect(result.details).toHaveProperty("hits");
  });

  it("maps validation errors into tool error result", async () => {
    const tools = createBibleTools({} as BibleRuntime);
    const result = await tools.find((tool) => tool.name === "bible_memory_search")!.execute({});
    expect(result.isError).toBe(true);
    expect(result.content).toContain("query is required");
  });
});
