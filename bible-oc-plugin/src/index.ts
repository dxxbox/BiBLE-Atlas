import { registerBibleCli } from "./cli/register.js";
import { resolveBibleConfig } from "./config/schema.js";
import { createBibleContextEngine } from "./context/engine.js";
import { SessionCaptureStore } from "./context/capture.js";
import { registerBibleSessionHooks } from "./hooks/lifecycle.js";
import { createBibleRuntime } from "./runtime/bible-runtime.js";
import { registerBibleTools } from "./tools/register.js";
import type { OpenClawPluginApi } from "./types/openclaw.js";

export default {
  id: "bible-oc-plugin",
  name: "BiBLE Atlas OpenClaw Plugin",
  description: "OpenClaw context-engine, lifecycle, tools, and CLI integration for BiBLE Atlas.",
  register(api: OpenClawPluginApi) {
    if (!api.registerContextEngine) throw new Error("OpenClaw host does not provide registerContextEngine.");
    const config = resolveBibleConfig(api.config);
    const runtime = createBibleRuntime({ config, logger: api.logger });
    const captureStore = new SessionCaptureStore({ config, runtime, logger: api.logger });
    api.registerContextEngine(config.contextEngineId, () => createBibleContextEngine({ config, runtime, logger: api.logger, captureStore }));
    registerBibleSessionHooks(api, { config, runtime, logger: api.logger, captureStore });
    registerBibleTools(api, { config, runtime });
    registerBibleCli(api, { config, runtime });
  },
};

export { resolveBibleConfig } from "./config/schema.js";
export { createBibleContextEngine } from "./context/engine.js";
export { createBibleRuntime } from "./runtime/bible-runtime.js";
export { CORE_TOOL_NAMES, createBibleTools } from "./tools/register.js";
