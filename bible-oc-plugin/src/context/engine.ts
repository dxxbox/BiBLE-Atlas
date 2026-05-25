import type { BiblePluginConfig } from "../config/types.js";
import { BypassMatcher } from "../hooks/bypass.js";
import type { BibleRuntime } from "../runtime/bible-runtime.js";
import type {
  AssembleInput,
  AssembleResult,
  CompactInput,
  CompactResult,
  ContextEngine,
  ContextEngineRuntimeContext,
  PluginLogger,
} from "../types/openclaw.js";
import { SessionCaptureStore, resolveSessionKey } from "./capture.js";
import { renderRelevantMemories, resolveInjectionBudget } from "./injection.js";
import { buildRecallQuery, RecallPipeline } from "./recall.js";

export interface BibleContextEngineDeps {
  config: BiblePluginConfig;
  runtime: BibleRuntime;
  logger?: PluginLogger;
  captureStore?: SessionCaptureStore;
}

export function createBibleContextEngine(deps: BibleContextEngineDeps): () => ContextEngine {
  return () => {
    const bypassMatcher = new BypassMatcher(deps.config);
    const recall = new RecallPipeline({
      config: deps.config,
      runtime: deps.runtime,
      logger: deps.logger,
    });
    const captureStore =
      deps.captureStore ??
      new SessionCaptureStore({
        config: deps.config,
        runtime: deps.runtime,
        logger: deps.logger,
      });

    return {
      async assemble(input: AssembleInput, ctx: ContextEngineRuntimeContext): Promise<AssembleResult> {
        const sessionKey = resolveSessionKey(input, ctx);
        if (bypassMatcher.matches(sessionKey)) return {};
        const query = buildRecallQuery(input, deps.config);
        if (!query.text) return {};
        const hits = await recall.search(query);
        const rendered = renderRelevantMemories(
          hits,
          resolveInjectionBudget(input, ctx, deps.config),
        );
        if (!rendered) return {};
        return {
          appendContext: rendered,
          metadata: {
            source: "bible-oc-plugin",
            hitCount: hits.length,
          },
        };
      },
      async afterTurn(input, ctx) {
        const sessionKey = resolveSessionKey(input, ctx);
        await captureStore.afterTurn(input, ctx, bypassMatcher.matches(sessionKey));
      },
      async compact(input: CompactInput, ctx: ContextEngineRuntimeContext): Promise<CompactResult> {
        const sessionKey = resolveSessionKey(input, ctx);
        return captureStore.compact(input, ctx, bypassMatcher.matches(sessionKey));
      },
    };
  };
}
