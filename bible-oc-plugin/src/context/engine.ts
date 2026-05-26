import type { ResolvedBibleConfig } from "../config/types.js";
import type { BibleRuntime } from "../runtime/bible-runtime.js";
import type { AssembleInput, AssembleResult, CompactInput, CompactResult, ContextEngine, OpenClawMessage, PluginLogger } from "../types/openclaw.js";
import { getSessionKey, isBypassedSession } from "../hooks/bypass.js";
import { actionLogger, log } from "../logging.js";
import { SessionCaptureStore } from "./capture.js";
import { estimateTokens } from "./injection.js";
import { runRecallPipeline } from "./recall.js";

export interface BibleContextEngineDeps {
  config: ResolvedBibleConfig;
  runtime: BibleRuntime;
  logger?: PluginLogger;
  captureStore?: SessionCaptureStore;
}

export function createBibleContextEngine(deps: BibleContextEngineDeps): ContextEngine {
  const captureStore = deps.captureStore ?? new SessionCaptureStore(deps);
  return {
    info: {
      id: deps.config.contextEngineId,
      name: "BiBLE Atlas",
      version: "0.1.0",
    },
    async ingest(): Promise<{ ingested: boolean }> {
      log(deps.logger, "info", "context.ingest no-op", { action: "context.ingest" });
      return { ingested: false };
    },
    async assemble(input: AssembleInput): Promise<AssembleResult> {
      const messages = input.messages ?? [];
      const sessionKey = getSessionKey(input);
      const action = actionLogger(deps.logger, "context.assemble", { sessionKey, messageCount: messages.length, tokenBudget: input.tokenBudget });
      action.start();
      const base = { messages, estimatedTokens: estimateMessageTokens(messages) };
      if (isBypassedSession(deps.config, sessionKey)) {
        action.done({ bypassed: true, estimatedTokens: base.estimatedTokens });
        return base;
      }
      const recallInput = { ...input, currentUserMessage: input.currentUserMessage ?? input.prompt, contextTokenBudget: input.contextTokenBudget ?? input.tokenBudget, messages };
      try {
        const result = await runRecallPipeline({ input: recallInput, ctx: { sessionKey, sessionId: input.sessionId, contextTokenBudget: input.tokenBudget }, config: deps.config, runtime: deps.runtime, logger: deps.logger });
        if (!result.rendered) {
          action.done({ hits: result.hits.length, warnings: result.warnings.length, injected: false, estimatedTokens: base.estimatedTokens });
          return base;
        }
        const assembled = { ...base, systemPromptAddition: result.rendered, estimatedTokens: base.estimatedTokens + estimateTokens(result.rendered) };
        action.done({ hits: result.hits.length, warnings: result.warnings.length, injected: true, estimatedTokens: assembled.estimatedTokens });
        return assembled;
      } catch (err) {
        action.fail(err);
        throw err;
      }
    },
    async afterTurn(input) {
      const sessionKey = getSessionKey(input);
      const messages = input.messages ?? [];
      const action = actionLogger(deps.logger, "context.afterTurn", { sessionKey, messageCount: messages.length, prePromptMessageCount: input.prePromptMessageCount });
      action.start();
      if (isBypassedSession(deps.config, sessionKey)) {
        action.done({ bypassed: true });
        return;
      }
      const turnMessages = messages.slice(input.prePromptMessageCount ?? 0);
      captureStore.captureTurn(sessionKey, input.sessionId, { ...input, messages: turnMessages });
      action.done({ turnMessageCount: turnMessages.length });
    },
    async compact(input: CompactInput): Promise<CompactResult> {
      const sessionKey = getSessionKey(input);
      const tokensBefore = input.currentTokenCount ?? 0;
      const action = actionLogger(deps.logger, "context.compact", { sessionKey, tokensBefore, force: input.force === true });
      action.start();
      if (isBypassedSession(deps.config, sessionKey)) {
        const result = { ok: true, compacted: false, reason: "bypassed", result: { summary: captureStore.fallbackSummary(sessionKey), tokensBefore } };
        action.done({ bypassed: true, compacted: false });
        return result;
      }
      const warnings: string[] = [];
      let summary = captureStore.fallbackSummary(sessionKey);
      let committedTurns = captureStore.getPendingTurnCount(sessionKey);
      let memoryId: string | undefined;
      let taskId: string | undefined;
      try {
        const commit = await captureStore.flush(sessionKey, "compact", { waitForInFlight: true });
        if (commit?.summary) summary = commit.summary;
        memoryId = commit?.memoryId;
        taskId = commit?.taskId;
      } catch (err) {
        warnings.push(err instanceof Error ? err.message : String(err));
        action.fail(err, { committedTurns });
      }
      const compacted = committedTurns > 0 || Boolean(memoryId || taskId);
      action.done({ compacted, committedTurns, warnings: warnings.length, memoryId, taskId });
      return { ok: warnings.length === 0, compacted, reason: warnings[0], result: { summary, tokensBefore, details: { bibleMemoryId: memoryId, bibleTaskId: taskId, committedTurns, warnings } } };
    },
  };
}

function estimateMessageTokens(messages: OpenClawMessage[]): number {
  return messages.reduce((sum, message) => sum + estimateTokens(textFromMessage(message)), 0);
}

function textFromMessage(message: OpenClawMessage): string {
  if (typeof message.content === "string") return message.content;
  if (typeof message.text === "string") return message.text;
  if (Array.isArray(message.content)) return message.content.map((part) => typeof part === "string" ? part : "").join("\n");
  return "";
}
