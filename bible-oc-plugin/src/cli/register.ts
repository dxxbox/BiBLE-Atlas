import { createBibleRuntime } from "../runtime/bible-runtime.js";
import type { ResolvedBibleConfig } from "../config/types.js";
import type { BibleRuntime } from "../runtime/bible-runtime.js";
import type { OpenClawPluginApi } from "../types/openclaw.js";
import { actionLogger, log } from "../logging.js";
import { executeBibleSetup } from "./setup.js";
import { executeBibleStatus, formatStatusText } from "./status.js";

export interface BibleCliDeps {
  config?: ResolvedBibleConfig;
  runtime?: BibleRuntime;
  openclawConfig?: unknown;
}

export function registerBibleCli(api: OpenClawPluginApi, deps: BibleCliDeps = {}): void {
  log(api.logger, "info", "cli.register start", { configured: Boolean(deps.config) });
  api.registerCli?.(
    ({ program }) => {
      const action = actionLogger(api.logger, "cli.registerCommands");
      action.start();
      const root = getCommandBuilder(program);
      if (!root) {
        action.done({ skipped: "missing_program" });
        return;
      }
      const bible = root.command("bible").description("Configure and inspect BiBLE Atlas integration");
      bible.command("status").option("--json").action(async (options: { json?: boolean; configPath?: string }) => {
        const status = await executeBibleStatus(options, { ...deps, logger: api.logger });
        writeOutput(options.json ? JSON.stringify(status, null, 2) : formatStatusText(status));
      });
      bible.command("setup").requiredOption("--base-url <url>").option("--write").option("--config-path <path>").action(async (options: { baseUrl: string; write?: boolean; configPath?: string }) => {
        const result = await executeBibleSetup({ baseUrl: options.baseUrl, write: options.write, configPath: options.configPath }, { logger: api.logger, runtimeFactory: (config) => createBibleRuntime({ config, logger: api.logger }) });
        writeOutput(JSON.stringify(result, null, 2));
      });
      action.done({ commands: ["bible status", "bible setup"] });
    },
    { descriptors: [{ name: "bible", description: "Configure and inspect BiBLE Atlas integration", hasSubcommands: true }] },
  );
  log(api.logger, "info", "cli.register done", { descriptors: ["bible"] });
}

function getCommandBuilder(program: unknown): any {
  if (program && typeof program === "object" && "command" in program) return program;
  return undefined;
}

function writeOutput(text: string): void {
  process.stdout.write(text.endsWith("\n") ? text : text + "\n");
}
