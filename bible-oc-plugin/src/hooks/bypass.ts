import type { ResolvedBibleConfig } from "../config/types.js";
import type { AssembleInput, ContextEngineRuntimeContext, HookEvent } from "../types/openclaw.js";

export function getSessionKey(input?: { sessionKey?: string; sessionId?: string }, ctx?: { sessionKey?: string; sessionId?: string }): string {
  return input?.sessionKey || ctx?.sessionKey || input?.sessionId || ctx?.sessionId || "default";
}

export function isBypassedSession(config: ResolvedBibleConfig, sessionKey: string): boolean {
  return config.compiledBypassPatterns.some((pattern) => pattern.test(sessionKey));
}

export function shouldBypassContext(config: ResolvedBibleConfig, input: AssembleInput | HookEvent, ctx?: ContextEngineRuntimeContext): boolean {
  return isBypassedSession(config, getSessionKey(input, ctx));
}
