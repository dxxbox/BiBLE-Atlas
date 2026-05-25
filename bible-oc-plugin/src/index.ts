import { resolveBibleConfig } from "./config/schema.js";
import { SessionCaptureStore } from "./context/capture.js";
import { createBibleContextEngine } from "./context/engine.js";
import { registerBibleCli } from "./cli/register.js";
import { registerBibleSessionHooks } from "./hooks/lifecycle.js";
import { createBibleRuntime } from "./runtime/bible-runtime.js";
import { registerBibleTools } from "./tools/register.js";
import type { OpenClawPluginApi } from "./types/openclaw.js";

export default {
  id: "bible-oc-plugin",
  name: "BiBLE Atlas OpenClaw Plugin",
  description: "OpenClaw context-engine, lifecycle, tools, and CLI integration for BiBLE Atlas.",
  kind: "context-engine",
  register(api: OpenClawPluginApi) {
    const config = resolveBibleConfig(api.config);
    const runtime = createBibleRuntime({ config, logger: api.logger });
    const captureStore = new SessionCaptureStore({ config, runtime, logger: api.logger });
    const engineFactory = createBibleContextEngine({
      config,
      runtime,
      logger: api.logger,
      captureStore,
    });

    api.registerContextEngine(config.contextEngineId, engineFactory);
    registerBibleSessionHooks(api, { config, captureStore, logger: api.logger });
    registerBibleTools(api, { runtime, logger: api.logger });
    registerBibleCli(api, { runtime });
  },
};
