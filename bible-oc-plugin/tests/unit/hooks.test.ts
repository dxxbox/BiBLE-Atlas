import { describe, expect, it, vi } from "vitest";
import { resolveBibleConfig } from "../../src/config/schema.js";
import { registerBibleSessionHooks } from "../../src/hooks/lifecycle.js";
import type { OpenClawPluginApi } from "../../src/types/openclaw.js";

describe("hooks", () => {
  it("registers lifecycle hooks with bounded priority and timeout", () => {
    const on = vi.fn();
    registerBibleSessionHooks({ on, registerContextEngine: vi.fn(), registerTool: vi.fn() } as unknown as OpenClawPluginApi, { config: resolveBibleConfig({ baseUrl: "http://x" }), runtime: { commitSessionMemory: vi.fn() } as any });
    expect(on).toHaveBeenCalledWith("session_start", expect.any(Function), { priority: 0, timeoutMs: 1000 });
    expect(on).toHaveBeenCalledWith("before_reset", expect.any(Function), { priority: 50, timeoutMs: 5000 });
    expect(on).toHaveBeenCalledWith("session_end", expect.any(Function), { priority: 10, timeoutMs: 5000 });
  });

  it("isolates hook flush errors", async () => {
    const on = vi.fn();
    const warn = vi.fn();
    registerBibleSessionHooks({ on, logger: { warn }, registerContextEngine: vi.fn(), registerTool: vi.fn() } as unknown as OpenClawPluginApi, { config: resolveBibleConfig({ baseUrl: "http://x" }), runtime: { commitSessionMemory: vi.fn(async () => { throw new Error("down"); }) } as any });
    const start = on.mock.calls.find((call) => call[0] === "session_start")![1];
    const end = on.mock.calls.find((call) => call[0] === "session_end")![1];
    await start({ sessionKey: "s1" });
    await end({ sessionKey: "s1" });
    expect(warn).not.toHaveBeenCalled();
  });
});
