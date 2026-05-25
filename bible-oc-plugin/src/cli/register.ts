import type { BibleRuntime } from "../runtime/bible-runtime.js";
import type { CommandLike, OpenClawPluginApi } from "../types/openclaw.js";
import { runBibleSetup, type SetupOptions } from "./setup.js";
import { runBibleStatus, type StatusOptions } from "./status.js";

export function registerBibleCli(
  api: Pick<OpenClawPluginApi, "registerCli">,
  deps: { runtime: BibleRuntime },
): void {
  api.registerCli?.(
    async ({ program }) => {
      registerBibleCommands(program, deps.runtime);
    },
    {
      descriptors: [
        {
          name: "bible",
          description: "Configure and inspect BiBLE Atlas integration",
          hasSubcommands: true,
        },
      ],
    },
  );
}

export function registerBibleCommands(program: CommandLike, runtime: BibleRuntime): void {
  const bible = program.command?.("bible") ?? program;
  bible.description?.("Configure and inspect BiBLE Atlas integration");

  bible
    .command?.("setup")
    ?.description?.("Validate BiBLE Atlas and write OpenClaw plugin configuration")
    ?.option?.("--base-url <url>", "BiBLE Atlas HTTP base URL")
    ?.option?.("--token <token>", "Bearer token")
    ?.option?.("--token-env <name>", "Read bearer token from environment variable")
    ?.option?.("--timeout-ms <ms>", "HTTP timeout in milliseconds")
    ?.option?.("--knowledge-tag <tag>", "Knowledge tag to enable", collectOption, [])
    ?.option?.("--bypass-session <pattern>", "Session regex to bypass", collectOption, [])
    ?.option?.("--enable-memory-recall", "Enable memory recall")
    ?.option?.("--enable-skill-recall", "Enable skill recall")
    ?.option?.("--enable-knowledge-recall", "Enable knowledge recall")
    ?.option?.("--config <path>", "OpenClaw config path")
    ?.option?.("--write", "Write config changes")
    ?.action?.(async (...args: unknown[]) => {
      const options = extractOptions<SetupOptions>(args);
      const result = await runBibleSetup(runtime, options);
      printCliResult(result);
    });

  bible
    .command?.("status")
    ?.description?.("Inspect BiBLE Atlas OpenClaw plugin status")
    ?.option?.("--json", "Print JSON")
    ?.action?.(async (...args: unknown[]) => {
      const options = extractOptions<StatusOptions>(args);
      const result = await runBibleStatus(runtime, options);
      printCliResult(result, options.json);
    });
}

function collectOption(value: string, previous: string[]): string[] {
  return [...previous, value];
}

function printCliResult(result: Record<string, unknown> | string, json = false): void {
  if (typeof result === "string" && !json) {
    console.log(result);
    return;
  }
  console.log(JSON.stringify(result, null, 2));
}

function extractOptions<T>(args: unknown[]): T {
  const last = args.at(-1);
  return isRecord(last) ? (last as T) : ({} as T);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
