import { describe, expect, it, vi } from "vitest";
import { createBibleRuntime } from "../../src/runtime/bible-runtime.js";
import { BIBLE_CORE_TOOL_NAMES, registerBibleTools } from "../../src/tools/register.js";
import type { OpenClawTool } from "../../src/types/openclaw.js";
import { resolveBibleConfig } from "../../src/config/schema.js";

describe("registerBibleTools", () => {
  it("registers the seven core tools declared in the manifest", async () => {
    const runtime = createBibleRuntime({
      config: resolveBibleConfig({ baseUrl: "http://127.0.0.1:1" }),
      client: {
        searchMemory: vi.fn().mockResolvedValue({ hits: [{ memory_id: "m1", title: "Memory", score: 0.9 }] }),
        saveMemory: vi.fn().mockResolvedValue({ task_id: "task1" }),
        getMemory: vi.fn().mockResolvedValue({ hits: [] }),
        searchKnowledge: vi.fn().mockResolvedValue({ hits: [] }),
        listKnowledge: vi.fn().mockResolvedValue({ tags: [] }),
        searchSkill: vi.fn().mockResolvedValue({ hits: [] }),
        getSkill: vi.fn().mockResolvedValue({ hits: [] }),
        health: vi.fn(),
        systemStatus: vi.fn(),
        getTask: vi.fn(),
        pollTask: vi.fn(),
      } as never,
    });
    const tools: OpenClawTool[] = [];

    registerBibleTools({ registerTool: (tool) => tools.push(tool) }, { runtime });

    expect(tools.map((tool) => tool.name)).toEqual([...BIBLE_CORE_TOOL_NAMES]);
    const search = tools.find((tool) => tool.name === "bible_memory_search");
    await expect(search?.execute({ query: "Memory" })).resolves.toMatchObject({
      details: { hits: [{ memory_id: "m1" }] },
    });
  });
});
