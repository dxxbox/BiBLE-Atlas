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
  openclawVersion?: string;
  [key: string]: unknown;
}

export interface AssembleInput {
  sessionKey?: string;
  sessionId?: string;
  messages?: OpenClawMessage[];
  currentUserMessage?: unknown;
  availableTools?: string[];
  citationsMode?: string;
  contextTokenBudget?: number;
  [key: string]: unknown;
}

export interface AssembleResult {
  appendContext?: string;
  userMessageSuffix?: string;
  metadata?: JsonObject;
}

export interface AfterTurnInput {
  sessionKey?: string;
  sessionId?: string;
  turnId?: string;
  runId?: string;
  userMessage?: unknown;
  assistantMessage?: unknown;
  toolCalls?: unknown[];
  usage?: { inputTokens?: number; outputTokens?: number };
  messages?: OpenClawMessage[];
  [key: string]: unknown;
}

export interface ContextEngineMaintenanceResult {
  warnings?: string[];
}

export interface CompactInput {
  sessionKey?: string;
  sessionId?: string;
  messages?: OpenClawMessage[];
  reason?: string;
  [key: string]: unknown;
}

export interface CompactResult {
  summary: string;
  metadata?: JsonObject;
}

export interface ContextEngine {
  assemble(input: AssembleInput, ctx: ContextEngineRuntimeContext): Promise<AssembleResult>;
  afterTurn?(input: AfterTurnInput, ctx: ContextEngineRuntimeContext): Promise<void | ContextEngineMaintenanceResult>;
  compact?(input: CompactInput, ctx: ContextEngineRuntimeContext): Promise<CompactResult>;
}
