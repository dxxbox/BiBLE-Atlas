import type { BiblePluginConfig } from "../config/types.js";
import type { SessionCaptureStore } from "../context/capture.js";
import { BypassMatcher } from "./bypass.js";
import type { HookEvent, OpenClawHookName, OpenClawPluginApi, PluginLogger } from "../types/openclaw.js";

export function registerBibleSessionHooks(
  api: Pick<OpenClawPluginApi, "on" | "registerHook">,
  deps: { config: BiblePluginConfig; captureStore: SessionCaptureStore; logger?: PluginLogger },
): void {
  const bypassMatcher = new BypassMatcher(deps.config);
  const register = (
    event: OpenClawHookName,
    handler: (event: HookEvent) => Promise<void> | void,
    opts: { priority: number; timeoutMs: number },
  ) => {
    const safeHandler = async (hookEvent: HookEvent) => {
      try {
        await handler(hookEvent);
      } catch (error) {
        deps.logger?.warn?.("BiBLE lifecycle hook failed.", {
          hook: event,
          ...(error instanceof Error ? { name: error.name, message: error.message } : { error }),
        });
      }
    };
    if (api.on) {
      api.on(event, safeHandler, opts);
    } else {
      api.registerHook?.(event, safeHandler, opts);
    }
  };

  register(
    "session_start",
    (event) => {
      const sessionKey = getSessionKey(event);
      deps.captureStore.startSession(sessionKey, getSessionId(event), bypassMatcher.matches(sessionKey));
    },
    { priority: 0, timeoutMs: 1_000 },
  );

  register(
    "before_reset",
    async (event) => {
      await deps.captureStore.flushSession(getSessionKey(event), "before_reset");
    },
    { priority: 50, timeoutMs: 5_000 },
  );

  register(
    "session_end",
    async (event) => {
      await deps.captureStore.flushSession(getSessionKey(event), "session_end");
    },
    { priority: 10, timeoutMs: 5_000 },
  );

  register(
    "gateway_stop",
    async () => {
      await deps.captureStore.flushAll("session_end");
    },
    { priority: 10, timeoutMs: 8_000 },
  );
}

function getSessionKey(event: HookEvent): string {
  return (
    event.sessionKey ??
    (typeof event.sessionId === "string" ? event.sessionId : undefined) ??
    (typeof event.id === "string" ? event.id : undefined) ??
    "unknown-session"
  );
}

function getSessionId(event: HookEvent): string | undefined {
  return typeof event.sessionId === "string" ? event.sessionId : undefined;
}
