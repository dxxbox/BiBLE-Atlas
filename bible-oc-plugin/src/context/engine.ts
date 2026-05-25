import type { ResolvedBibleConfig } from "../config/types.js";
import type { BibleRuntime } from "../runtime/bible-runtime.js";
import type { AssembleInput, AssembleResult, CompactInput, CompactResult, ContextEngine, ContextEngineRuntimeContext, PluginLogger } from "../types/openclaw.js";
import { getSessionKey, isBypassedSession } from "../hooks/bypass.js";
import { SessionCaptureStore } from "./capture.js";
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
    async assemble(input: AssembleInput, ctx: ContextEngineRuntimeContext): Promise<AssembleResult> {
      const sessionKey = getSessionKey(input, ctx);
      if (isBypassedSession(deps.config, sessionKey)) return {};
      const result = await runRecallPipeline({ input, ctx, config: deps.config, runtime: deps.runtime, logger: deps.logger });
      if (!result.rendered) return result.warnings.length ? { metadata: { warnings: result.warnings } } : {};
      return { appendContext: result.rendered, userMessageSuffix: `\n\n${result.rendered}`, metadata: { hits: result.hits.length, warnings: result.warnings } };
    },
    async afterTurn(input, ctx) {
      const sessionKey = getSessionKey(input, ctx);
      if (isBypassedSession(deps.config, sessionKey)) return;
      captureStore.captureTurn(sessionKey, input.sessionId ?? ctx.sessionId, input);
    },
    async compact(input: CompactInput, ctx: ContextEngineRuntimeContext): Promise<CompactResult> {
      const sessionKey = getSessionKey(input, ctx);
      if (isBypassedSession(deps.config, sessionKey)) return { summary: captureStore.fallbackSummary(sessionKey, input.messages), metadata: { bypassed: true } };
      const warnings: string[] = [];
      let summary = captureStore.fallbackSummary(sessionKey, input.messages);
      let committedTurns = captureStore.getPendingTurnCount(sessionKey);
      let memoryId: string | undefined;
      let taskId: string | undefined;
      try {
        const commit = await captureStore.flush(sessionKey, "compact", { waitForInFlight: true, messages: input.messages });
        if (commit?.summary) summary = commit.summary;
        memoryId = commit?.memoryId;
        taskId = commit?.taskId;
      } catch (err) {
        warnings.push(err instanceof Error ? err.message : String(err));
      }
      return { summary, metadata: { bibleMemoryId: memoryId, bibleTaskId: taskId, committedTurns, warnings } };
    },
  };
}
