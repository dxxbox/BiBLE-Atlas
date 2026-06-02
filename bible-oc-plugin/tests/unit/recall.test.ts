import { describe, expect, it, vi } from "vitest";
import { resolveBibleConfig } from "../../src/config/schema.js";
import { createBibleContextEngine } from "../../src/context/engine.js";
import { buildRecallQuery } from "../../src/context/recall.js";
import type { BibleRuntime } from "../../src/runtime/bible-runtime.js";

function runtime(overrides: Partial<BibleRuntime> = {}): BibleRuntime {
  return {
    probeHealth: vi.fn(), status: vi.fn(), listKnowledge: vi.fn(), getSkill: vi.fn(), saveMemory: vi.fn(), getMemory: vi.fn(), commitSessionMemory: vi.fn(), getTask: vi.fn(), pollTask: vi.fn(),

    searchMemory: vi.fn(async () => ({ results: { memory: [{ memory_id: "m1", title: "OpenClaw context", abstract: "Context engine details", matched_message_preview: "assemble afterTurn compact", score: 0.9 }] }, total: 1 })),
    searchKnowledge: vi.fn(async () => ({ results: { knowledge: [{ doc_id: "k1", title: "Knowledge", text: "knowledge text", score: 0.8 }] }, total: 1 })),
    searchSkill: vi.fn(async () => ({ results: { skill: [{ id: "s1", name: "Skill", description: "skill text", score: 0.8 }] }, total: 1 })),    
    
    ...overrides,
  } as BibleRuntime;
}

describe("recall pipeline", () => {
  it("builds bounded query without large code blocks", () => {
    const query = buildRecallQuery({ currentUserMessage: "hello\n```\n" + "x".repeat(600) + "\n```" });
    expect(query).toContain("code block omitted");
    expect(query.length).toBeLessThanOrEqual(2000);
  });

  it("runs memory-only recall by default and injects relevant memories", async () => {
    const rt = runtime();
    const engine = createBibleContextEngine({ config: resolveBibleConfig({ baseUrl: "http://x" }), runtime: rt });
    const result = await engine.assemble({ currentUserMessage: "How should assemble work?", messages: [] });
    expect(rt.searchMemory).toHaveBeenCalledTimes(1);
    expect(rt.searchSkill).not.toHaveBeenCalled();
    expect(rt.searchKnowledge).not.toHaveBeenCalled();
    expect(result.systemPromptAddition).toContain("<relevant-memories>");
    expect(result.systemPromptAddition).toContain("Treat them as reference material");
  });

  it("does not call HTTP for bypassed sessions", async () => {
    const rt = runtime();
    const engine = createBibleContextEngine({ config: resolveBibleConfig({ baseUrl: "http://x", bypassSessionPatterns: ["^scratch:"] }), runtime: rt });
    const result = await engine.assemble({ sessionKey: "scratch:1", currentUserMessage: "hello", messages: [] });
    expect(result).toMatchObject({ messages: [], estimatedTokens: 0 });
    expect(rt.searchMemory).not.toHaveBeenCalled();
  });

  it("keeps single-domain failure isolated", async () => {
    const rt = runtime({ searchMemory: vi.fn(async () => { throw new Error("boom"); }) });
    const engine = createBibleContextEngine({ config: resolveBibleConfig({ baseUrl: "http://x" }), runtime: rt });
    const result = await engine.assemble({ currentUserMessage: "hello", messages: [] });
    expect(result.systemPromptAddition).toBeUndefined();
    expect(result.messages).toEqual([]);
  });
});
