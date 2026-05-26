// Ops tools are intentionally not registered in the first delivery. The CLI status
// command uses BibleRuntime health/status directly without exposing diagnostics to agents.
export const RESERVED_SYSTEM_TOOL_NAMES = ["bible_task_status", "bible_system_health", "bible_system_status"] as const;
