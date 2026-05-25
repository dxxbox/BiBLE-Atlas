import { describe, expect, it, vi } from "vitest";
import { resolveBibleConfig } from "../../src/config/schema.js";
import { SessionCaptureStore } from "../../src/context/capture.js";

describe("SessionCaptureStore", () => {
  it("buffers turns below threshold and commits when threshold is reached", async () => {
    const config = resolveBibleConfig({
      baseUrl: "http://127.0.0.1:1",
      captureCommitThresholdTurns: 2,
    });
    const commitSessionMemory = vi.fn().mockResolvedValue({ raw: {}, memoryId: "mem_1" });
    const store = new SessionCaptureStore({
      config,
      runtime: { commitSessionMemory } as never,
    });

    await store.afterTurn({ sessionKey: "s1", userMessage: "u1", assistantMessage: "a1" }, {}, false);
    expect(commitSessionMemory).not.toHaveBeenCalled();

    await store.afterTurn({ sessionKey: "s1", userMessage: "u2", assistantMessage: "a2" }, {}, false);
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(commitSessionMemory).toHaveBeenCalledTimes(1);
    expect(commitSessionMemory.mock.calls[0]?.[0]).toMatchObject({
      sessionKey: "s1",
      reason: "threshold",
    });
  });

  it("compact returns fallback summary if commit fails", async () => {
    const config = resolveBibleConfig({ baseUrl: "http://127.0.0.1:1" });
    const store = new SessionCaptureStore({
      config,
      runtime: { commitSessionMemory: vi.fn().mockRejectedValue(new Error("down")) } as never,
    });

    const result = await store.compact(
      { sessionKey: "s2", messages: [{ role: "user", content: "Build the plugin" }] },
      {},
      false,
    );

    expect(result.summary).toContain("Summary:");
    expect(result.metadata?.warnings?.[0]).toContain("BiBLE compact commit failed");
  });
});
