import type { BiblePluginConfig } from "../config/types.js";
import type { CommitSessionMemoryResult, BibleRuntime } from "../runtime/bible-runtime.js";
import type {
  AfterTurnInput,
  CompactInput,
  CompactResult,
  ContextEngineRuntimeContext,
  ConversationMessage,
  PluginLogger,
} from "../types/openclaw.js";

export interface CapturedTurn {
  turnId?: string;
  runId?: string;
  timestamp: string;
  userMessage?: string;
  assistantMessage?: string;
  toolCalls?: CapturedToolCall[];
  usage?: {
    inputTokens?: number;
    outputTokens?: number;
  };
}

export interface CapturedToolCall {
  toolName?: string;
  content?: string;
}

export interface BibleSessionState {
  sessionKey: string;
  sessionId?: string;
  startedAt: string;
  lastTurnAt?: string;
  turnCount: number;
  bufferedChars: number;
  pendingTurns: CapturedTurn[];
  lastCommitId?: string;
  lastMemoryId?: string;
  commitInFlight?: Promise<void>;
  bypassed: boolean;
  committedHashes: Set<string>;
}

export class SessionCaptureStore {
  private readonly sessions = new Map<string, BibleSessionState>();
  private readonly config: BiblePluginConfig;
  private readonly runtime: BibleRuntime;
  private readonly logger?: PluginLogger;

  constructor(options: { config: BiblePluginConfig; runtime: BibleRuntime; logger?: PluginLogger }) {
    this.config = options.config;
    this.runtime = options.runtime;
    if (options.logger !== undefined) this.logger = options.logger;
  }

  startSession(sessionKey: string, sessionId: string | undefined, bypassed: boolean): BibleSessionState {
    const existing = this.sessions.get(sessionKey);
    if (existing) return existing;
    const state: BibleSessionState = {
      sessionKey,
      startedAt: new Date().toISOString(),
      turnCount: 0,
      bufferedChars: 0,
      pendingTurns: [],
      bypassed,
      committedHashes: new Set(),
    };
    if (sessionId !== undefined) state.sessionId = sessionId;
    this.sessions.set(sessionKey, state);
    return state;
  }

  async afterTurn(input: AfterTurnInput, ctx: ContextEngineRuntimeContext, bypassed: boolean): Promise<void> {
    if (!this.config.captureEnabled || bypassed) return;
    const sessionKey = resolveSessionKey(input, ctx);
    const state = this.startSession(sessionKey, input.sessionId ?? ctx.sessionId, false);
    const captured = captureTurn(input);
    if (!captured) return;
    state.pendingTurns.push(captured);
    state.lastTurnAt = captured.timestamp;
    state.turnCount += 1;
    state.bufferedChars += turnSize(captured);
    if (shouldCommit(state, this.config) && !state.commitInFlight) {
      state.commitInFlight = this.flushState(state, "threshold")
        .then(() => undefined)
        .catch((error) => {
          this.logger?.warn?.("BiBLE threshold commit failed.", serializeError(error));
        })
        .finally(() => {
          state.commitInFlight = undefined;
        });
    }
  }

  async compact(input: CompactInput, ctx: ContextEngineRuntimeContext, bypassed: boolean): Promise<CompactResult> {
    const sessionKey = resolveSessionKey(input, ctx);
    if (bypassed || !this.config.captureEnabled) {
      return { summary: fallbackSummary(input.messages ?? []) };
    }
    const state = this.startSession(sessionKey, input.sessionId ?? ctx.sessionId, false);
    addMessagesToState(state, input.messages ?? []);
    const warnings: string[] = [];
    let commit: CommitSessionMemoryResult | undefined;
    try {
      commit = await this.flushState(state, "compact");
    } catch (error) {
      warnings.push(`BiBLE compact commit failed: ${error instanceof Error ? error.message : String(error)}`);
      this.logger?.warn?.("BiBLE compact commit failed.", serializeError(error));
    }
    const summary = commit?.summary ?? fallbackSummary(input.messages ?? [], state.pendingTurns);
    return {
      summary,
      metadata: {
        ...(commit?.memoryId !== undefined ? { bibleMemoryId: commit.memoryId } : {}),
        ...(commit?.taskId !== undefined ? { bibleTaskId: commit.taskId } : {}),
        committedTurns: commit ? state.turnCount : 0,
        ...(warnings.length > 0 ? { warnings } : {}),
      },
    };
  }

  async flushSession(
    sessionKey: string,
    reason: "before_reset" | "session_end" | "compact" | "threshold",
  ): Promise<void> {
    const state = this.sessions.get(sessionKey);
    if (!state || state.bypassed || state.pendingTurns.length === 0) return;
    if (state.commitInFlight) {
      await withBoundedWait(state.commitInFlight, 1_000);
      if (state.pendingTurns.length === 0) return;
    }
    await this.flushState(state, reason);
    if (reason === "session_end") this.sessions.delete(sessionKey);
  }

  async flushAll(reason: "session_end" | "before_reset" = "session_end"): Promise<void> {
    await Promise.allSettled(Array.from(this.sessions.keys()).map((key) => this.flushSession(key, reason)));
  }

  private async flushState(
    state: BibleSessionState,
    reason: "threshold" | "compact" | "before_reset" | "session_end",
  ): Promise<CommitSessionMemoryResult | undefined> {
    if (state.pendingTurns.length === 0) return undefined;
    const hash = hashTurns(state.pendingTurns);
    if (state.committedHashes.has(hash)) return undefined;
    const turns = [...state.pendingTurns];
    const result = await this.runtime.commitSessionMemory({
      sessionKey: state.sessionKey,
      ...(state.sessionId !== undefined ? { sessionId: state.sessionId } : {}),
      reason,
      title: `OpenClaw session ${state.sessionKey}`,
      messages: turnsToMessages(turns),
      metadata: {
        source: "openclaw",
        pluginId: "bible-oc-plugin",
        turnCount: state.turnCount,
        startedAt: state.startedAt,
        endedAt: new Date().toISOString(),
        reason,
      },
      wait: true,
    });
    state.committedHashes.add(hash);
    state.pendingTurns = state.pendingTurns.slice(turns.length);
    state.bufferedChars = state.pendingTurns.reduce((sum, turn) => sum + turnSize(turn), 0);
    if (result.taskId !== undefined) state.lastCommitId = result.taskId;
    if (result.memoryId !== undefined) state.lastMemoryId = result.memoryId;
    return result;
  }
}

export function resolveSessionKey(
  input: { sessionKey?: string; sessionId?: string },
  ctx: ContextEngineRuntimeContext,
): string {
  return input.sessionKey ?? ctx.sessionKey ?? input.sessionId ?? ctx.sessionId ?? "unknown-session";
}

function captureTurn(input: AfterTurnInput): CapturedTurn | undefined {
  const userMessage = textFromUnknown(input.userMessage ?? input.currentUserMessage);
  const assistantMessage = textFromUnknown(input.assistantMessage ?? lastAssistantMessage(input.messages ?? []));
  const toolCalls = normalizeToolCalls(input.toolCalls);
  if (!userMessage && !assistantMessage && toolCalls.length === 0) return undefined;
  return {
    ...(input.turnId !== undefined ? { turnId: input.turnId } : {}),
    ...(input.runId !== undefined ? { runId: input.runId } : {}),
    timestamp: new Date().toISOString(),
    ...(userMessage ? { userMessage: trimBounded(userMessage, 4_000) } : {}),
    ...(assistantMessage ? { assistantMessage: trimBounded(assistantMessage, 4_000) } : {}),
    ...(toolCalls.length > 0 ? { toolCalls } : {}),
    usage: normalizeUsage(input.usage),
  };
}

function normalizeUsage(raw: Record<string, unknown> | undefined): CapturedTurn["usage"] {
  if (!raw) return undefined;
  const usage: NonNullable<CapturedTurn["usage"]> = {};
  const inputTokens = raw.inputTokens ?? raw.input_tokens;
  const outputTokens = raw.outputTokens ?? raw.output_tokens;
  if (typeof inputTokens === "number") usage.inputTokens = inputTokens;
  if (typeof outputTokens === "number") usage.outputTokens = outputTokens;
  return Object.keys(usage).length > 0 ? usage : undefined;
}

function normalizeToolCalls(raw: unknown[] | undefined): CapturedToolCall[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter(isRecord).slice(0, 10).map((item) => ({
    ...(typeof item.toolName === "string" ? { toolName: item.toolName } : {}),
    ...(typeof item.name === "string" ? { toolName: item.name } : {}),
    content: trimBounded(textFromUnknown(item.content ?? item.result), 1_000),
  }));
}

function addMessagesToState(state: BibleSessionState, messages: ConversationMessage[]): void {
  if (state.pendingTurns.length > 0 || messages.length === 0) return;
  const captured = messages
    .slice(-8)
    .map((message) => ({
      timestamp: message.timestamp ?? message.createdAt ?? new Date().toISOString(),
      userMessage: message.role === "user" ? textFromUnknown(message.content ?? message.text) : undefined,
      assistantMessage: message.role === "assistant" ? textFromUnknown(message.content ?? message.text) : undefined,
    }))
    .filter((turn) => turn.userMessage || turn.assistantMessage);
  state.pendingTurns.push(...captured);
  state.bufferedChars = state.pendingTurns.reduce((sum, turn) => sum + turnSize(turn), 0);
}

function shouldCommit(state: BibleSessionState, config: BiblePluginConfig): boolean {
  return (
    state.pendingTurns.length >= config.captureCommitThresholdTurns ||
    state.bufferedChars >= config.captureCommitThresholdChars
  );
}

function turnsToMessages(
  turns: CapturedTurn[],
): Array<{ role: "user" | "assistant" | "tool"; content: string; timestamp?: string }> {
  const messages: Array<{ role: "user" | "assistant" | "tool"; content: string; timestamp?: string }> = [];
  for (const turn of turns) {
    if (turn.userMessage) messages.push({ role: "user", content: turn.userMessage, timestamp: turn.timestamp });
    if (turn.assistantMessage) {
      messages.push({ role: "assistant", content: turn.assistantMessage, timestamp: turn.timestamp });
    }
    for (const tool of turn.toolCalls ?? []) {
      if (tool.content) messages.push({ role: "tool", content: tool.content, timestamp: turn.timestamp });
    }
  }
  return messages;
}

function fallbackSummary(messages: ConversationMessage[], pendingTurns: CapturedTurn[] = []): string {
  const text = [
    ...messages.map((message) => textFromUnknown(message.content ?? message.text)),
    ...pendingTurns.flatMap((turn) => [turn.userMessage ?? "", turn.assistantMessage ?? ""]),
  ]
    .join("\n")
    .replace(/\s+/g, " ")
    .trim();
  return [
    "Summary:",
    `- User goals: ${trimBounded(text, 600) || "No detailed goals captured."}`,
    "- Decisions: See BiBLE Atlas memory for committed session details.",
    "- Open tasks: Continue from the latest user request.",
    "- Important files/symbols: Not extracted locally.",
    "- Tool outcomes: See current conversation context.",
  ].join("\n");
}

function lastAssistantMessage(messages: ConversationMessage[]): unknown {
  return [...messages].reverse().find((message) => message.role === "assistant")?.content;
}

function textFromUnknown(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(textFromUnknown).filter(Boolean).join("\n");
  if (isRecord(value)) {
    if (typeof value.text === "string") return value.text;
    if (typeof value.content === "string") return value.content;
  }
  return "";
}

function trimBounded(value: string, max: number): string {
  const text = value.replace(/\s+/g, " ").trim();
  return text.length > max ? `${text.slice(0, max - 1)}...` : text;
}

function turnSize(turn: CapturedTurn): number {
  return JSON.stringify(turn).length;
}

function hashTurns(turns: CapturedTurn[]): string {
  return JSON.stringify(turns.map((turn) => [turn.turnId, turn.timestamp, turn.userMessage, turn.assistantMessage]));
}

async function withBoundedWait(promise: Promise<void>, timeoutMs: number): Promise<void> {
  let timeout: NodeJS.Timeout | undefined;
  await Promise.race([
    promise,
    new Promise<void>((resolve) => {
      timeout = setTimeout(resolve, timeoutMs);
    }),
  ]);
  if (timeout) clearTimeout(timeout);
}

function serializeError(error: unknown): Record<string, unknown> {
  if (error instanceof Error) return { name: error.name, message: error.message };
  return { error };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
