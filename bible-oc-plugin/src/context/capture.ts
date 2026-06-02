import type { ResolvedBibleConfig } from "../config/types.js";
import type { BibleRuntime, CommitSessionMemoryResponse } from "../runtime/bible-runtime.js";
import type { AfterTurnInput, CompactInput, OpenClawMessage, PluginLogger } from "../types/openclaw.js";
import { actionLogger, log } from "../logging.js";
import { textFromUnknown } from "./recall.js";

export interface CapturedTurn {
  turnId?: string;
  runId?: string;
  timestamp: string;
  userMessage?: string;
  assistantMessage?: string;
  toolCalls?: Array<{ name?: string; content?: string }>;
  usage?: { inputTokens?: number; outputTokens?: number };
}

interface BibleSessionState {
  sessionKey: string;
  sessionId?: string;
  startedAt: string;
  turnCount: number;
  bufferedChars: number;
  pendingTurns: CapturedTurn[];
  lastCompactionSummary?: string;
  commitInFlight?: Promise<CommitSessionMemoryResponse>;
  lastCommitHash?: string;
  bypassed: boolean;
}

export class SessionCaptureStore {
  private readonly sessions = new Map<string, BibleSessionState>();
  constructor(private readonly opts: { config: ResolvedBibleConfig; runtime: BibleRuntime; logger?: PluginLogger }) {}

  startSession(sessionKey: string, sessionId: string | undefined, bypassed: boolean): void {
    log(this.opts.logger, "info", "capture.startSession start", { action: "capture.startSession", sessionKey, sessionId, bypassed });
    if (!this.sessions.has(sessionKey)) {
      this.sessions.set(sessionKey, { sessionKey, sessionId, startedAt: new Date().toISOString(), turnCount: 0, bufferedChars: 0, pendingTurns: [], bypassed });
    }
    log(this.opts.logger, "info", "capture.startSession done", { action: "capture.startSession", sessionKey, existing: this.sessions.has(sessionKey) });
  }

  getPendingTurnCount(sessionKey: string): number {
    return this.sessions.get(sessionKey)?.pendingTurns.length ?? 0;
  }

  captureTurn(sessionKey: string, sessionId: string | undefined, input: AfterTurnInput): void {
    const action = actionLogger(this.opts.logger, "capture.captureTurn", { sessionKey, sessionId });
    action.start();
    if (!this.opts.config.captureEnabled) {
      action.done({ skipped: "capture_disabled" });
      return;
    }
    const state = this.ensureState(sessionKey, sessionId, false);
    if (state.bypassed) {
      action.done({ skipped: "bypassed" });
      return;
    }
    const turn = normalizeTurn(input);
    if (!turn.userMessage && !turn.assistantMessage && (!turn.toolCalls || turn.toolCalls.length === 0)) {
      action.done({ skipped: "empty_turn" });
      return;
    }
    state.pendingTurns.push(turn);
    state.turnCount += 1;
    state.bufferedChars += JSON.stringify(turn).length;

    if (typeof input.autoCompactionSummary == "string" && input.autoCompactionSummary.trim()) {
      state.lastCompactionSummary = input.autoCompactionSummary.trim()
    }

    this.enforceHardCap(state);
    if (state.pendingTurns.length >= this.opts.config.captureCommitThresholdTurns || state.bufferedChars >= this.opts.config.captureCommitThresholdChars) {
      log(this.opts.logger, "info", "capture.threshold reached", { sessionKey, pendingTurns: state.pendingTurns.length, bufferedChars: state.bufferedChars });
      void this.flush(sessionKey, "threshold", { waitForInFlight: false }).catch((err) => this.opts.logger?.warn?.("BiBLE threshold commit failed", { sessionKey, message: (err as Error).message }));
    }
    action.done({ pendingTurns: state.pendingTurns.length, bufferedChars: state.bufferedChars });
  }

  async flush(sessionKey: string, reason: "threshold" | "compact" | "before_reset" | "session_end" | "manual", opts: { waitForInFlight?: boolean; messages?: OpenClawMessage[] } = {}): Promise<CommitSessionMemoryResponse | undefined> {
    const action = actionLogger(this.opts.logger, "capture.flush", { sessionKey, reason, waitForInFlight: opts.waitForInFlight });
    action.start();
    const state = this.sessions.get(sessionKey);
    if (!state || state.bypassed) {
      action.done({ skipped: !state ? "missing_state" : "bypassed" });
      return undefined;
    }
    if (state.commitInFlight) {
      if (opts.waitForInFlight ?? true) {
        action.done({ joinedInFlight: true });
        return state.commitInFlight;
      }
      action.done({ skipped: "commit_in_flight" });
      return undefined;
    }
    const turns = [...state.pendingTurns, ...messagesToTurns(opts.messages ?? [])];
    if (turns.length === 0) {
      action.done({ skipped: "empty_buffer" });
      return undefined;
    }
    const hash = commitHash(turns);
    if (state.lastCommitHash === hash) {
      action.done({ skipped: "duplicate_hash" });
      return undefined;
    }
    const committedPendingCount = state.pendingTurns.length;

    const abstract = (state.lastCompactionSummary ?? deriveAbstract(turns)).slice(0,500);
    const overview = deriveOverview(turns).slice(0,2000)

    const promise = this.opts.runtime.commitSessionMemory({
      sessionKey,
      sessionId: state.sessionId,
      reason,
      title: makeTitle(sessionKey, turns),
      abstract,
      overview,
      messages: turns.flatMap(turnToMessages),
      metadata: { source: "openclaw", pluginId: "bible-oc-plugin", turnCount: turns.length, startedAt: state.startedAt },
    });
    state.commitInFlight = promise;
    try {
      const result = await promise;
      state.pendingTurns.splice(0, committedPendingCount);
      state.bufferedChars = state.pendingTurns.reduce((sum, turn) => sum + JSON.stringify(turn).length, 0);
      state.lastCommitHash = hash;
      action.done({ memoryId: result.memoryId, taskId: result.taskId, committedTurns: committedPendingCount, remainingTurns: state.pendingTurns.length });
      return result;
    } catch (err) {
      action.fail(err, { turnCount: turns.length });
      throw err;
    } finally {
      state.commitInFlight = undefined;
    }
  }

  async endSession(sessionKey: string, reason: "session_end" | "before_reset" = "session_end"): Promise<void> {
    const action = actionLogger(this.opts.logger, "capture.endSession", { sessionKey, reason });
    action.start();
    try {
      await this.flush(sessionKey, reason, { waitForInFlight: true });
      if (reason === "session_end") this.sessions.delete(sessionKey);
      action.done();
    } catch (err) {
      this.opts.logger?.warn?.("BiBLE lifecycle flush failed", { sessionKey, reason, message: (err as Error).message });
      action.fail(err);
    }
  }

  fallbackSummary(sessionKey: string, messages: OpenClawMessage[] = []): string {
    const state = this.sessions.get(sessionKey);
    const snippets = [...(state?.pendingTurns ?? []).flatMap((turn) => [turn.userMessage, turn.assistantMessage]), ...messages.map((m) => textFromUnknown(m.content ?? m.text))].filter(Boolean).slice(-8);
    return ["Summary:", "- User goals: " + (snippets[0] ?? "No explicit goal captured."), "- Decisions: See recent conversation context.", "- Open tasks: Continue from the latest user request.", "- Important files/symbols: Not extracted by local fallback.", "- Tool outcomes: Not extracted by local fallback."].join("\n");
  }

  private ensureState(sessionKey: string, sessionId: string | undefined, bypassed: boolean): BibleSessionState {
    let state = this.sessions.get(sessionKey);
    if (!state) {
      state = { sessionKey, sessionId, startedAt: new Date().toISOString(), turnCount: 0, bufferedChars: 0, pendingTurns: [], bypassed };
      this.sessions.set(sessionKey, state);
    }
    return state;
  }

  private enforceHardCap(state: BibleSessionState): void {
    const hardCap = this.opts.config.captureCommitThresholdChars * 4;
    while (state.bufferedChars > hardCap && state.pendingTurns.length > 1) {
      const dropped = state.pendingTurns.shift();
      state.bufferedChars -= dropped ? JSON.stringify(dropped).length : 0;
    }
  }
}

export function normalizeTurn(input: AfterTurnInput): CapturedTurn {
  return {
    turnId: input.turnId,
    runId: input.runId,
    timestamp: new Date().toISOString(),
    userMessage: textFromUnknown(input.userMessage) || lastMessageText(input.messages, "user"),
    assistantMessage: textFromUnknown(input.assistantMessage) || lastMessageText(input.messages, "assistant"),
    toolCalls: Array.isArray(input.toolCalls) ? input.toolCalls.slice(0, 10).map(normalizeToolCall) : undefined,
    usage: input.usage,
  };
}

function messagesToTurns(messages: OpenClawMessage[]): CapturedTurn[] {
  return messages.map((message) => ({ timestamp: message.timestamp ?? new Date().toISOString(), [message.role === "assistant" ? "assistantMessage" : "userMessage"]: textFromUnknown(message.content ?? message.text) }));
}

function turnToMessages(turn: CapturedTurn): Array<{ role: "user" | "assistant" | "tool"; content: string; timestamp?: string }> {
  const messages: Array<{ role: "user" | "assistant" | "tool"; content: string; timestamp?: string }> = [];
  if (turn.userMessage) messages.push({ role: "user", content: turn.userMessage, timestamp: turn.timestamp });
  if (turn.assistantMessage) messages.push({ role: "assistant", content: turn.assistantMessage, timestamp: turn.timestamp });
  for (const call of turn.toolCalls ?? []) if (call.content) messages.push({ role: "tool", content: call.content.slice(0, 2000), timestamp: turn.timestamp });
  return messages;
}

function normalizeToolCall(value: unknown): { name?: string; content?: string } {
  if (typeof value !== "object" || value === null) return { content: String(value).slice(0, 1000) };
  const record = value as Record<string, unknown>;
  return { name: typeof record.name === "string" ? record.name : undefined, content: textFromUnknown(record.content ?? record.result).slice(0, 1000) };
}

function lastMessageText(messages: OpenClawMessage[] | undefined, role: string): string | undefined {
  for (const message of [...(messages ?? [])].reverse()) if (message.role === role) return textFromUnknown(message.content ?? message.text);
  return undefined;
}

function makeTitle(sessionKey: string, turns: CapturedTurn[]): string {
  const first = turns.find((turn) => turn.userMessage)?.userMessage?.slice(0, 80);
  return first || `OpenClaw session ${sessionKey}`;
}

function deriveAbstract(turns: CapturedTurn[]):string {
  return turns.find((t) => t.userMessage)?.userMessage ?? "";
}

function deriveOverview(turns: CapturedTurn[]): string {
  return turns.flatMap((t) => {
    const parts: string[] = [];
    if (t.userMessage) parts.push(`user: ${t.userMessage}`);
    if (t.assistantMessage) parts.push(`assistant: ${t.assistantMessage}`);
    return parts;
  }
  ).join("\n");
}

function commitHash(turns: CapturedTurn[]): string {
  return JSON.stringify(turns.map((turn) => [turn.turnId, turn.timestamp, turn.userMessage, turn.assistantMessage]));
}
