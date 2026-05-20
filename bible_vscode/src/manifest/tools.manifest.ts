/**
 * LM Tool 元数据的中心声明。
 * package.json 中的 contributes.languageModelTools 应由 scripts/gen-contributes.ts 从这里生成；
 * 当前阶段两边都手动维护，保持同步即可（见 README）。
 */

export interface ToolManifestEntry {
  name: string;
  displayName: string;
  modelDescription: string;
  toolReferenceName?: string;
  canBeReferencedInPrompt?: boolean;
  tags?: string[];
  icon?: string;
  inputSchema: object;
}

export const TOOL_MANIFEST: ToolManifestEntry[] = [
  {
    name: 'bible_health',
    displayName: 'Bible Health Check',
    modelDescription:
      'Check whether the bible CLI and its backend are reachable. Use as a smoke test when the user reports that other bible_* tools are misbehaving.',
    toolReferenceName: 'bibleHealth',
    canBeReferencedInPrompt: true,
    tags: ['bible', 'control'],
    icon: '$(pulse)',
    inputSchema: { type: 'object', properties: {} },
  },
  {
    name: 'bible_memory_search',
    displayName: 'Search Memory',
    modelDescription:
      "Semantically search the user's personal memory store (past conversations, fix records, design decisions). " +
      "Use when the user references prior discussions ('what did we conclude', 'last time we...'), or when relevant " +
      'context might exist in saved sessions. Returns ranked memory entries with title, abstract, and score.',
    toolReferenceName: 'bibleMemorySearch',
    canBeReferencedInPrompt: true,
    tags: ['bible', 'memory'],
    icon: '$(history)',
    inputSchema: {
      type: 'object',
      properties: {
        query:      { type: 'string', description: 'Natural language query' },
        topK:       { type: 'number', description: 'Max results (default 5)' },
        searchType: { type: 'string', enum: ['keyword', 'title', 'text', 'vector', 'hybrid'], description: 'Search strategy' },
      },
      required: ['query'],
    },
  },
  {
    name: 'bible_memory_import',
    displayName: 'Save to Memory',
    modelDescription:
      "Save a conversation, decision, or note to the user's memory store for future retrieval. " +
      'Pass the relevant messages from the current conversation. ' +
      'Call ONLY when the user explicitly asks to save / archive / remember. ' +
      'This is asynchronous: the tool returns a task_id immediately; progress is shown in VSCode.',
    tags: ['bible', 'memory'],
    icon: '$(save)',
    inputSchema: {
      type: 'object',
      properties: {
        title: { type: 'string' },
        messages: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              role:    { type: 'string', enum: ['user', 'assistant', 'system'] },
              content: { type: 'string' },
            },
            required: ['role', 'content'],
          },
        },
      },
      required: ['messages'],
    },
  },
  {
    name: 'bible_memory_download',
    displayName: 'Download Memory',
    modelDescription:
      'Download the original source file of a saved memory entry to the local workspace. ' +
      'Use when the user asks to export / open / read the full text of a saved memory. ' +
      'Asynchronous: returns task_id immediately.',
    tags: ['bible', 'memory'],
    icon: '$(cloud-download)',
    inputSchema: {
      type: 'object',
      properties: {
        storagePath:  { type: 'string' },
        downloadName: { type: 'string' },
        outputDir:    { type: 'string' },
      },
      required: ['storagePath'],
    },
  },
  {
    name: 'bible_task_status',
    displayName: 'Check Task Status',
    modelDescription:
      'Look up the status of an asynchronous bible task by its task_id. ' +
      'Use to follow up on a previous import/download tool call.',
    tags: ['bible', 'control'],
    icon: '$(sync)',
    inputSchema: {
      type: 'object',
      properties: { taskId: { type: 'string' } },
      required: ['taskId'],
    },
  },
];
