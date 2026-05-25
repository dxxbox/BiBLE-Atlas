export interface BiblePluginConfig {
  baseUrl: string;
  token?: string;
  timeoutMs: number;
  contextEngineId: string;
  enableMemoryRecall: boolean;
  enableSkillRecall: boolean;
  enableKnowledgeRecall: boolean;
  knowledgeTags: string[];
  recallTopK: number;
  recallMinScore: number;
  injectionTokenBudget: number;
  captureEnabled: boolean;
  captureCommitThresholdTurns: number;
  captureCommitThresholdChars: number;
  bypassSessionPatterns: string[];
  compiledBypassPatterns: RegExp[];
}

export interface BiblePluginConfigInput {
  baseUrl?: unknown;
  token?: unknown;
  timeoutMs?: unknown;
  contextEngineId?: unknown;
  enableMemoryRecall?: unknown;
  enableSkillRecall?: unknown;
  enableKnowledgeRecall?: unknown;
  knowledgeTags?: unknown;
  recallTopK?: unknown;
  recallMinScore?: unknown;
  injectionTokenBudget?: unknown;
  captureEnabled?: unknown;
  captureCommitThresholdTurns?: unknown;
  captureCommitThresholdChars?: unknown;
  bypassSessionPatterns?: unknown;
}

export interface ConfigValidationIssue {
  path: string;
  message: string;
}

export class BibleConfigError extends Error {
  readonly code = "BIBLE_CONFIG_INVALID";
  readonly issues: ConfigValidationIssue[];

  constructor(message: string, issues: ConfigValidationIssue[]) {
    super(message);
    this.name = "BibleConfigError";
    this.issues = issues;
  }
}
