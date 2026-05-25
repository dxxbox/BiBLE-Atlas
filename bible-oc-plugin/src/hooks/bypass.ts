import type { BiblePluginConfig } from "../config/types.js";

export class BypassMatcher {
  private readonly patterns: RegExp[];

  constructor(config: Pick<BiblePluginConfig, "compiledBypassPatterns">) {
    this.patterns = config.compiledBypassPatterns;
  }

  matches(sessionKey: string | undefined): boolean {
    if (!sessionKey) return false;
    return this.patterns.some((pattern) => pattern.test(sessionKey));
  }
}
