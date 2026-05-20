import { CliRunner } from './cli-runner';
import { BibleCliError } from './cli-error';

export interface CliInfo {
  cli: string;
  version: string;
  server?: { reachable: boolean; url?: string };
}

/**
 * 探测 CLI 可用性 / 版本。失败时返回 undefined（不抛），调用方决定是否提示。
 */
export async function detectCli(runner: CliRunner): Promise<{ ok: true; info: CliInfo } | { ok: false; error: BibleCliError }> {
  try {
    const info = await runner.run<CliInfo>({ args: ['health'] });
    return { ok: true, info };
  } catch (err) {
    return { ok: false, error: err as BibleCliError };
  }
}
