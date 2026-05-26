export type JsonObject = Record<string, unknown>;

export interface PluginLogger {
  debug?(message: string, meta?: JsonObject): void;
  info?(message: string, meta?: JsonObject): void;
  warn?(message: string, meta?: JsonObject): void;
  error?(message: string, meta?: JsonObject): void;
}

export interface OpenClawPluginApi {
  id?: string;
  config?: unknown;
  logger?: PluginLogger;
  registerContextEngine(id: string, factory: ContextEngineFactory): void;
  registerTool(tool: OpenClawTool, opts?: { optional?: boolean }): void;
  registerCli?(registrar: CliRegistrar, opts?: CliRegistrationOptions): void;
  on?(event: OpenClawHookName, handler: HookHandler, opts?: HookOptions): void;
  registerHook?(events: OpenClawHookName | OpenClawHookName[], handler: HookHandler, opts?: HookOptions): void;
}

export type OpenClawHookName = "session_start" | "session_end" | "before_reset" | "gateway_start" | "gateway_stop";

export interface HookOptions {
  priority?: number;
  timeoutMs?: number;
}

export type HookHandler = (event: HookEvent, ctx?: JsonObject) => Promise<void> | void;

export interface HookEvent {
  sessionKey?: string;
  sessionId?: string;
  reason?: string;
  messages?: OpenClawMessage[];
  [key: string]: unknown;
}

export interface OpenClawMessage {
  role?: string;
  content?: unknown;
  text?: string;
  timestamp?: string;
  [key: string]: unknown;
}

export interface OpenClawTool {
  name: string;
  description: string;
  inputSchema: JsonObject;
  execute(input: unknown, ctx?: JsonObject): Promise<ToolResult> | ToolResult;
}

export interface ToolResult {
  content: string;
  details?: JsonObject;
  isError?: boolean;
}

export type CliRegistrar = (ctx: { program?: unknown; commands?: unknown }) => Promise<void> | void;
export interface CliRegistrationOptions {
  descriptors?: Array<{ name: string; description?: string; hasSubcommands?: boolean }>;
}

export interface ContextEngineFactoryContext {
  openclawVersion?: string;
  [key: string]: unknown;
}

export type ContextEngineFactory = (ctx: ContextEngineFactoryContext) => ContextEngine | Promise<ContextEngine>;

export interface ContextEngineRuntimeContext {
  sessionKey?: string;
  sessionId?: string;
  contextTokenBudget?: number;
  tokenBudget?: number;
  currentTokenCount?: number;
  openclawVersion?: string;
  [key: string]: unknown;
}

export interface AssembleInput {
  sessionKey?: string;
  sessionId?: string;
  messages: OpenClawMessage[];
  currentUserMessage?: unknown;
  availableTools?: Set<string>;
  citationsMode?: string;
  contextTokenBudget?: number;
  tokenBudget?: number;
  model?: string;
  prompt?: string;
  [key: string]: unknown;
}

export interface AssembleResult {
  messages: OpenClawMessage[];
  estimatedTokens: number;
  promptAuthority?: "assembled" | "preassembly_may_overflow";
  systemPromptAddition?: string;
  contextProjection?: {
    mode: "per_turn" | "thread_bootstrap";
    epoch?: string;
    fingerprint?: string;
  };
}

export interface AfterTurnInput {
  sessionKey?: string;
  sessionId?: string;
  sessionFile?: string;
  turnId?: string;
  runId?: string;
  userMessage?: unknown;
  assistantMessage?: unknown;
  toolCalls?: unknown[];
  usage?: { inputTokens?: number; outputTokens?: number };
  messages?: OpenClawMessage[];
  prePromptMessageCount?: number;
  autoCompactionSummary?: string;
  isHeartbeat?: boolean;
  tokenBudget?: number;
  runtimeContext?: ContextEngineRuntimeContext;
  [key: string]: unknown;
}

export interface ContextEngineMaintenanceResult {
  changed: boolean;
  bytesFreed: number;
  rewrittenEntries: number;
  reason?: string;
}

export interface CompactInput {
  sessionKey?: string;
  sessionId?: string;
  sessionFile?: string;
  tokenBudget?: number;
  force?: boolean;
  currentTokenCount?: number;
  compactionTarget?: "budget" | "threshold";
  customInstructions?: string;
  runtimeContext?: ContextEngineRuntimeContext;
  abortSignal?: AbortSignal;
  [key: string]: unknown;
}

export interface CompactResult {
  ok: boolean;
  compacted: boolean;
  reason?: string;
  result?: {
    summary?: string;
    firstKeptEntryId?: string;
    tokensBefore: number;
    tokensAfter?: number;
    details?: unknown;
    sessionId?: string;
    sessionFile?: string;
  };
}

export interface ContextEngineInfo {
  id: string;
  name: string;
  version?: string;
  ownsCompaction?: boolean;
  turnMaintenanceMode?: "foreground" | "background";
}

export interface IngestResult {
  ingested: boolean;
}

export interface IngestBatchResult {
  ingestedCount: number;
}

export interface ContextEngine {
  readonly info: ContextEngineInfo;
  ingest(input: { sessionId: string; sessionKey?: string; message: OpenClawMessage; isHeartbeat?: boolean }): Promise<IngestResult>;
  ingestBatch?(input: { sessionId: string; sessionKey?: string; messages: OpenClawMessage[]; isHeartbeat?: boolean }): Promise<IngestBatchResult>;
  assemble(input: AssembleInput): Promise<AssembleResult>;
  afterTurn?(input: AfterTurnInput): Promise<void>;
  compact(input: CompactInput): Promise<CompactResult>;
}
