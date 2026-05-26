import type { ResolvedBibleConfig } from "../config/types.js";
import type { BibleRuntime } from "../runtime/bible-runtime.js";
import type { HookEvent, OpenClawPluginApi, PluginLogger } from "../types/openclaw.js";
import { getSessionKey, isBypassedSession } from "./bypass.js";
import { SessionCaptureStore } from "../context/capture.js";
import { actionLogger } from "../logging.js";

export function registerBibleSessionHooks(api: OpenClawPluginApi, deps: { config: ResolvedBibleConfig; runtime: BibleRuntime; logger?: PluginLogger; captureStore?: SessionCaptureStore }): SessionCaptureStore {
  api.logger?.info?.("[bible-oc-plugin] hooks.register start", { pluginId: "bible-oc-plugin" });
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
  api.logger?.info?.("[bible-oc-plugin] hooks.register done", { pluginId: "bible-oc-plugin", hooks: ["session_start", "before_reset", "session_end"] });
  return captureStore;
}

function makeHookRegistrar(api: OpenClawPluginApi) {
  return (event: "session_start" | "session_end" | "before_reset", handler: (event: HookEvent) => Promise<void>, opts: { priority: number; timeoutMs: number }) => {
    const wrapped = async (payload: HookEvent) => {
      const sessionKey = getSessionKey(payload ?? {});
      const action = actionLogger(api.logger, `hook.${event}`, { event, sessionKey });
      action.start();
      try {
        await handler(payload ?? {});
        action.done();
      } catch (err) {
        api.logger?.warn?.("BiBLE hook failed", { event, message: err instanceof Error ? err.message : String(err) });
        action.fail(err);
      }
    };
    if (api.on) api.on(event, wrapped, opts);
    else api.registerHook?.(event, wrapped, opts);
  };
}

async function safeFlush(store: SessionCaptureStore, sessionKey: string, reason: "before_reset" | "session_end", logger?: PluginLogger): Promise<void> {
  const action = actionLogger(logger, "hook.safeFlush", { sessionKey, reason });
  action.start();
  try {
    await store.endSession(sessionKey, reason);
    action.done();
  } catch (err) {
    logger?.warn?.("BiBLE bounded flush failed", { sessionKey, reason, message: err instanceof Error ? err.message : String(err) });
    action.fail(err);
  }
}
