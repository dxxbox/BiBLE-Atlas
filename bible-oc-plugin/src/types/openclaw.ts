export interface PluginLogger {
  debug?(message: string, meta?: Record<string, unknown>): void;
  info?(message: string, meta?: Record<string, unknown>): void;
  warn?(message: string, meta?: Record<string, unknown>): void;
  error?(message: string, meta?: Record<string, unknown>): void;
}

export type OpenClawHookName =
  | "session_start"
  | "session_end"
  | "before_reset"
  | "gateway_start"
  | "gateway_stop";

export interface HookOptions {
  priority?: number;
  timeoutMs?: number;
}

export type HookHandler = (event: HookEvent) => void | HookDecision | Promise<void | HookDecision>;

export interface HookEvent {
  sessionKey?: string;
  sessionId?: string;
  reason?: string;
  context?: {
    pluginConfig?: unknown;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface HookDecision {
  warnings?: string[];
  [key: string]: unknown;
}

export interface OpenClawPluginApi {
  id?: string;
  config?: unknown;
  logger?: PluginLogger;
  registrationMode?: "full" | "discovery" | "setup-only" | "setup-runtime" | "cli-metadata" | string;
  registerContextEngine(id: string, factory: ContextEngineFactory): void;
  registerTool(tool: OpenClawTool, opts?: { optional?: boolean }): void;
  registerCli?(registrar: CliRegistrar, opts?: CliRegistrationOptions): void;
  on?(event: OpenClawHookName, handler: HookHandler, opts?: HookOptions): void;
  registerHook?(
    events: OpenClawHookName | OpenClawHookName[],
    handler: HookHandler,
    opts?: HookOptions,
  ): void;
}

export interface ContextEngineFactoryContext {
  logger?: PluginLogger;
  config?: unknown;
  contextTokenBudget?: number;
  [key: string]: unknown;
}

export type ContextEngineFactory = (
  ctx: ContextEngineFactoryContext,
) => ContextEngine | Promise<ContextEngine>;

export interface ContextEngine {
  assemble(input: AssembleInput, ctx: ContextEngineRuntimeContext): Promise<AssembleResult>;
  afterTurn?(
    input: AfterTurnInput,
    ctx: ContextEngineRuntimeContext,
  ): Promise<void | ContextEngineMaintenanceResult>;
  compact?(input: CompactInput, ctx: ContextEngineRuntimeContext): Promise<CompactResult>;
}

export interface ContextEngineRuntimeContext {
  sessionKey?: string;
  sessionId?: string;
  contextTokenBudget?: number;
  openclawVersion?: string;
  [key: string]: unknown;
}

export interface ConversationMessage {
  id?: string;
  turnId?: string;
  role?: "user" | "assistant" | "tool" | "system" | string;
  content?: unknown;
  text?: string;
  toolName?: string;
  createdAt?: string;
  timestamp?: string;
  [key: string]: unknown;
}

export interface AssembleInput {
  sessionKey?: string;
  sessionId?: string;
  messages?: ConversationMessage[];
  currentUserMessage?: unknown;
  availableTools?: string[];
  citationsMode?: string;
  contextTokenBudget?: number;
  [key: string]: unknown;
}

export interface AssembleResult {
  appendContext?: string;
  context?: string;
  messages?: ConversationMessage[];
  metadata?: Record<string, unknown>;
  warnings?: string[];
  [key: string]: unknown;
}

export interface AfterTurnInput {
  sessionKey?: string;
  sessionId?: string;
  messages?: ConversationMessage[];
  currentUserMessage?: unknown;
  userMessage?: unknown;
  assistantMessage?: unknown;
  toolCalls?: unknown[];
  usage?: Record<string, unknown>;
  turnId?: string;
  runId?: string;
  [key: string]: unknown;
}

export interface ContextEngineMaintenanceResult {
  warnings?: string[];
  [key: string]: unknown;
}

export interface CompactInput {
  sessionKey?: string;
  sessionId?: string;
  messages?: ConversationMessage[];
  reason?: string;
  [key: string]: unknown;
}

export interface CompactResult {
  summary: string;
  metadata?: {
    bibleMemoryId?: string;
    bibleTaskId?: string;
    committedTurns?: number;
    warnings?: string[];
    [key: string]: unknown;
  };
}

export interface OpenClawTool {
  name: string;
  description: string;
  parameters: JsonSchema;
  execute: (...args: unknown[]) => Promise<OpenClawToolResult> | OpenClawToolResult;
}

export interface OpenClawToolResult {
  content: Array<{ type: "text"; text: string }> | string;
  details?: unknown;
  isError?: boolean;
}

export interface JsonSchema {
  type?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  additionalProperties?: boolean;
  items?: JsonSchema;
  enum?: unknown[];
  minimum?: number;
  maximum?: number;
  minLength?: number;
  description?: string;
  default?: unknown;
  [key: string]: unknown;
}

export type CliRegistrar = (ctx: CliRegistrarContext) => void | Promise<void>;

export interface CliRegistrarContext {
  program: CommandLike;
  [key: string]: unknown;
}

export interface CliRegistrationOptions {
  descriptors?: Array<{
    name: string;
    description: string;
    hasSubcommands?: boolean;
  }>;
  [key: string]: unknown;
}

export interface CommandLike {
  command?(name: string): CommandLike;
  description?(description: string): CommandLike;
  option?(flags: string, description?: string, parserOrDefault?: unknown, defaultValue?: unknown): CommandLike;
  requiredOption?(flags: string, description?: string, parserOrDefault?: unknown, defaultValue?: unknown): CommandLike;
  action?(handler: (...args: unknown[]) => unknown): CommandLike;
  [key: string]: unknown;
}
