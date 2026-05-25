import { describe, expect, it, vi } from "vitest";
import plugin from "../../src/index.js";

describe("OpenClaw registration smoke", () => {
  it("registers context engine, hooks, tools, and CLI", async () => {
    const api = {
      config: { baseUrl: "http://x" },
      registerContextEngine: vi.fn(),
      registerTool: vi.fn(),
      registerCli: vi.fn(),
      on: vi.fn(),
      logger: { warn: vi.fn() },
    };
    plugin.register(api as any);
    expect(api.registerContextEngine).toHaveBeenCalledWith("bible-atlas", expect.any(Function));
    expect(api.registerTool).toHaveBeenCalledTimes(7);
    expect(api.on).toHaveBeenCalledTimes(3);
    expect(api.registerCli).toHaveBeenCalledWith(expect.any(Function), expect.objectContaining({ descriptors: [expect.objectContaining({ name: "bible" })] }));
    const factory = api.registerContextEngine.mock.calls[0][1];
    const engine = factory({});
    expect(await engine.assemble({ sessionKey: "scratch", currentUserMessage: "x" }, {})).toBeDefined();
  });
});
