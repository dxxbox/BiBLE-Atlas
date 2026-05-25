export const ENDPOINTS = {
  health: "/health",
  systemStatus: "/api/v1/system/status",
  memorySearch: "/api/search/memory",
  memoryImport: "/api/import/memory",
  skillSearch: "/api/search/skill",
  skillImport: "/api/import/skill",
  knowledgeSearch: "/api/search/knowledge-base",
  knowledgeList: "/api/control/docs/list",
  knowledgeListFallback: "/api/v1/knowledge/list",
  taskStatus: (taskId: string) => `/api/control/admin/tasks/${encodeURIComponent(taskId)}`,
} as const;
