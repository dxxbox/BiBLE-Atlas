import { describe, expect, it, vi } from "vitest";
import { resolveBibleConfig } from "../../src/config/schema.js";
import { SessionCaptureStore } from "../../src/context/capture.js";
import type { BibleRuntime } from "../../src/runtime/bible-runtime.js";

function runtime(commit = vi.fn(async () => ({ memoryId: "m1", summary: "server summary", raw: { memory_id: "m1" } }))): BibleRuntime {
  return { commitSessionMemory: commit } as unknown as BibleRuntime;
}

describe("capture store", () => {
  it("commits asynchronously when threshold is reached", async () => {
    const commit = vi.fn(async () => ({ memoryId: "m1", raw: { memory_id: "m1" } }));
    const store = new SessionCaptureStore({ config: resolveBibleConfig({ baseUrl: "http://x", captureCommitThresholdTurns: 1 }), runtime: runtime(commit) });
    store.captureTurn("s1", undefined, { userMessage: "hello", assistantMessage: "world" });
    await vi.waitFor(() => expect(commit).toHaveBeenCalledTimes(1));
  });

  it("retains buffer when commit fails and retries", async () => {
    const commit = vi.fn()
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValueOnce({ memoryId: "m1", raw: { memory_id: "m1" } });
    const store = new SessionCaptureStore({ config: resolveBibleConfig({ baseUrl: "http://x" }), runtime: runtime(commit) });
    store.captureTurn("s1", undefined, { userMessage: "hello" });
    await expect(store.flush("s1", "compact")).rejects.toThrow("down");
    await expect(store.flush("s1", "compact")).resolves.toMatchObject({ memoryId: "m1" });
    expect(commit).toHaveBeenCalledTimes(2);
  });

  it("compact fallback summary is returned when no server summary exists", () => {
    const store = new SessionCaptureStore({ config: resolveBibleConfig({ baseUrl: "http://x" }), runtime: runtime() });
    store.captureTurn("s1", undefined, { userMessage: "implement plugin" });
    expect(store.fallbackSummary("s1")).toContain("Summary:");
    expect(store.fallbackSummary("s1")).toContain("implement plugin");
  });
});
