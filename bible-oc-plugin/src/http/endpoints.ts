export const ENDPOINTS = {
  health: "/health",
  systemStatus: "/api/v1/system/status",
  memorySearch: "/api/search/memory",
  skillSearch: "/api/search/skill",
  knowledgeSearch: "/api/search/knowledge-base",
  knowledgeList: "/api/control/docs/list",
  knowledgeListFallback: "/api/v1/knowledge/list",
  memoryImport: "/api/import/memory",
  memoryGet: "/api/memory/get",
  skillGet: "/api/skill/get",
  task: (taskId: string) => `/api/control/admin/tasks/${encodeURIComponent(taskId)}`,
} as const;
