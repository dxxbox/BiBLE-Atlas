export interface BiblePluginConfig {
  baseUrl: string;
  token?: string;
  timeoutMs: number;
  contextEngineId: string;
  defaultKbIndex: string;
  sourceClient: string;
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
}

export interface ResolvedBibleConfig extends BiblePluginConfig {
  compiledBypassPatterns: RegExp[];
}
