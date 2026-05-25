import type { ResolvedBibleConfig } from "../config/types.js";
import type { BibleRuntime } from "../runtime/bible-runtime.js";
import type { HookEvent, OpenClawPluginApi, PluginLogger } from "../types/openclaw.js";
import { getSessionKey, isBypassedSession } from "./bypass.js";
import { SessionCaptureStore } from "../context/capture.js";

export function registerBibleSessionHooks(api: OpenClawPluginApi, deps: { config: ResolvedBibleConfig; runtime: BibleRuntime; logger?: PluginLogger; captureStore?: SessionCaptureStore }): SessionCaptureStore {
  const captureStore = deps.captureStore ?? new SessionCaptureStore(deps);
  const on = makeHookRegistrar(api);
  on("session_start", async (event) => {
    const sessionKey = getSessionKey(event);
    captureStore.startSession(sessionKey, event.sessionId, isBypassedSession(deps.config, sessionKey));
  }, { priority: 0, timeoutMs: 1000 });
  on("before_reset", async (event) => {
    await safeFlush(captureStore, getSessionKey(event), "before_reset", deps.logger);
  }, { priority: 50, timeoutMs: 5000 });
  on("session_end", async (event) => {
    await safeFlush(captureStore, getSessionKey(event), "session_end", deps.logger);
  }, { priority: 10, timeoutMs: 5000 });
  return captureStore;
}

function makeHookRegistrar(api: OpenClawPluginApi) {
  return (event: "session_start" | "session_end" | "before_reset", handler: (event: HookEvent) => Promise<void>, opts: { priority: number; timeoutMs: number }) => {
    const wrapped = async (payload: HookEvent) => {
      try {
        await handler(payload ?? {});
      } catch (err) {
        api.logger?.warn?.("BiBLE hook failed", { event, message: err instanceof Error ? err.message : String(err) });
      }
    };
    if (api.on) api.on(event, wrapped, opts);
    else api.registerHook?.(event, wrapped, opts);
  };
}

async function safeFlush(store: SessionCaptureStore, sessionKey: string, reason: "before_reset" | "session_end", logger?: PluginLogger): Promise<void> {
  try {
    await store.endSession(sessionKey, reason);
  } catch (err) {
    logger?.warn?.("BiBLE bounded flush failed", { sessionKey, reason, message: err instanceof Error ? err.message : String(err) });
  }
}
