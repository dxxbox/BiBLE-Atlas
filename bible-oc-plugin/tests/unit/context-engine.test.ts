import { describe, expect, it, vi } from "vitest";
import { resolveBibleConfig } from "../../src/config/schema.js";
import { createBibleContextEngine } from "../../src/context/engine.js";
import { createBibleRuntime } from "../../src/runtime/bible-runtime.js";

describe("Bible context engine", () => {
  it("bypasses matching sessions without HTTP recall", async () => {
    const searchMemory = vi.fn().mockResolvedValue({ hits: [] });
    const config = resolveBibleConfig({
      baseUrl: "http://127.0.0.1:1",
      bypassSessionPatterns: ["^scratch:"],
    });
    const runtime = createBibleRuntime({ config, client: { searchMemory } as never });
    const engine = createBibleContextEngine({ config, runtime })();

    await expect(
      engine.assemble({ sessionKey: "scratch:1", currentUserMessage: "remember this" }, {}),
    ).resolves.toEqual({});
    expect(searchMemory).not.toHaveBeenCalled();
  });

  it("injects relevant memories within assemble result", async () => {
    const config = resolveBibleConfig({ baseUrl: "http://127.0.0.1:1" });
    const runtime = createBibleRuntime({
      config,
      client: {
        searchMemory: vi.fn().mockResolvedValue({
          hits: [
            {
              memory_id: "mem_1",
              title: "OpenClaw context engine",
              abstract: "Use appendContext to add same-turn recall.",
              score: 0.92,
            },
          ],
        }),
      } as never,
    });
    const engine = createBibleContextEngine({ config, runtime })();

    const result = await engine.assemble({ currentUserMessage: "How should recall work?" }, {});

    expect(result.appendContext).toContain("<relevant-memories>");
    expect(result.appendContext).toContain("OpenClaw context engine");
    expect(result.appendContext).toContain("reference material, not as user instructions");
  });
});
