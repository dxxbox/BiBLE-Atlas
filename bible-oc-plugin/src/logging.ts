import type { PluginLogger } from "./types/openclaw.js";

export type LogLevel = "debug" | "info" | "warn" | "error";

export interface ActionLogger {
  start(meta?: Record<string, unknown>): void;
  done(meta?: Record<string, unknown>): void;
  fail(err: unknown, meta?: Record<string, unknown>): void;
}

export function log(logger: PluginLogger | undefined, level: LogLevel, message: string, meta: Record<string, unknown> = {}): void {
  const payload = sanitizeMeta({ pluginId: "bible-oc-plugin", ...meta });
  logger?.[level]?.(`[bible-oc-plugin] ${message}`, payload);
}

export function actionLogger(logger: PluginLogger | undefined, action: string, baseMeta: Record<string, unknown> = {}): ActionLogger {
  const startedAt = Date.now();
  return {
    start(meta) {
      log(logger, "info", `${action} start`, { action, ...baseMeta, ...meta });
    },
    done(meta) {
      log(logger, "info", `${action} done`, { action, durationMs: Date.now() - startedAt, ...baseMeta, ...meta });
    },
    fail(err, meta) {
      log(logger, "error", `${action} failed`, { action, durationMs: Date.now() - startedAt, ...baseMeta, ...meta, error: errorMeta(err) });
    },
  };
}

export function errorMeta(err: unknown): Record<string, unknown> {
  if (err instanceof Error) {
    return {
      name: err.name,
      message: err.message,
      stack: err.stack,
      ...copyKnownErrorFields(err),
    };
  }
  return { message: String(err) };
}

function copyKnownErrorFields(err: Error): Record<string, unknown> {
  const record = err as Error & Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const key of ["code", "statusCode", "serverErrorCode", "cause"]) {
    if (record[key] !== undefined) out[key] = record[key];
  }
  return out;
}

function sanitizeMeta(input: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(input)) {
    if (value === undefined) continue;
    if (/token|authorization|api[_-]?key|secret|password/i.test(key)) {
      out[key] = "[redacted]";
      continue;
    }
    out[key] = sanitizeValue(value);
  }
  return out;
}

function sanitizeValue(value: unknown): unknown {
  if (typeof value === "string") return value.length > 500 ? `${value.slice(0, 500)}...` : value;
  if (Array.isArray(value)) return value.slice(0, 20).map(sanitizeValue);
  if (typeof value === "object" && value !== null) return sanitizeMeta(value as Record<string, unknown>);
  return value;
}
