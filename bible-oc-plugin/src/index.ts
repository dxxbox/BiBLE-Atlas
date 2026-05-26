import { registerBibleCli } from "./cli/register.js";
import { resolveBibleConfig } from "./config/schema.js";
import { createBibleContextEngine } from "./context/engine.js";
import { SessionCaptureStore } from "./context/capture.js";
import { registerBibleSessionHooks } from "./hooks/lifecycle.js";
import { createBibleRuntime } from "./runtime/bible-runtime.js";
import { registerBibleTools } from "./tools/register.js";
import { actionLogger, log } from "./logging.js";
import type { ResolvedBibleConfig } from "./config/types.js";
import type { OpenClawPluginApi } from "./types/openclaw.js";

export default {
  id: "bible-oc-plugin",
  name: "BiBLE Atlas OpenClaw Plugin",
  description: "OpenClaw context-engine, lifecycle, tools, and CLI integration for BiBLE Atlas.",
  register(api: OpenClawPluginApi) {
    const registration = actionLogger(api.logger, "plugin.register");
    registration.start();
    let config: ResolvedBibleConfig;
    try {
      config = resolveBibleConfig(api.config);
    } catch (err) {
      registerBibleCli(api);
      api.logger?.warn?.("BiBLE Atlas plugin is not configured; runtime features are disabled until setup completes.", { error: err instanceof Error ? err.message : String(err) });
      log(api.logger, "warn", "plugin.register unconfigured", { action: "plugin.register", error: err instanceof Error ? err.message : String(err) });
      return;
    }
    const runtime = createBibleRuntime({ config, logger: api.logger });
    log(api.logger, "info", "plugin.register runtime created", { baseUrl: config.baseUrl, contextEngineId: config.contextEngineId, captureEnabled: config.captureEnabled });
    registerBibleCli(api, { config, runtime, openclawConfig: api.config });
    if (!api.registerContextEngine) throw new Error("OpenClaw host does not provide registerContextEngine.");
    const captureStore = new SessionCaptureStore({ config, runtime, logger: api.logger });
    api.registerContextEngine(config.contextEngineId, () => createBibleContextEngine({ config, runtime, logger: api.logger, captureStore }));
    registerBibleSessionHooks(api, { config, runtime, logger: api.logger, captureStore });
    registerBibleTools(api, { config, runtime });
    registration.done({ contextEngineId: config.contextEngineId, tools: 7 });
  },
};

export { resolveBibleConfig } from "./config/schema.js";
export { createBibleContextEngine } from "./context/engine.js";
export { createBibleRuntime } from "./runtime/bible-runtime.js";
export { CORE_TOOL_NAMES, createBibleTools } from "./tools/register.js";
