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
    expect(api.registerContextEngine).toHaveBeenCalledWith("bible-oc-plugin", expect.any(Function));
    expect(api.registerTool).toHaveBeenCalledTimes(7);
    expect(api.on).toHaveBeenCalledTimes(3);
    expect(api.registerCli).toHaveBeenCalledWith(expect.any(Function), expect.objectContaining({ descriptors: [expect.objectContaining({ name: "bible" })] }));
    const factory = api.registerContextEngine.mock.calls[0][1];
    const engine = factory({});
    expect(engine.info).toMatchObject({ id: "bible-oc-plugin", name: "BiBLE Atlas" });
    expect(await engine.ingest({ sessionId: "s1", message: { role: "user", content: "x" } })).toEqual({ ingested: false });
    expect(await engine.assemble({ sessionKey: "scratch", currentUserMessage: "x", messages: [] })).toBeDefined();
  });

  it("registers CLI without runtime features before setup", () => {
    const api = {
      config: {},
      registerContextEngine: vi.fn(),
      registerTool: vi.fn(),
      registerCli: vi.fn(),
      on: vi.fn(),
      logger: { warn: vi.fn() },
    };
    plugin.register(api as any);
    expect(api.registerCli).toHaveBeenCalledWith(expect.any(Function), expect.objectContaining({ descriptors: [expect.objectContaining({ name: "bible" })] }));
    expect(api.registerContextEngine).not.toHaveBeenCalled();
    expect(api.registerTool).not.toHaveBeenCalled();
    expect(api.logger.warn).toHaveBeenCalled();
  });
});
