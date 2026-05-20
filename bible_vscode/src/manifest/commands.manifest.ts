/**
 * VSCode Command 元数据的中心声明。同上：当前手动与 package.json 同步。
 */

export interface CommandManifestEntry {
  command: string;
  title: string;
  category?: string;
}

export const COMMAND_MANIFEST: CommandManifestEntry[] = [
  { command: 'bible.runSelfCheck',           title: 'Run Self-Check',            category: 'Bible' },
  { command: 'bible.memory.search',          title: 'Search Memory',             category: 'Bible' },
  { command: 'bible.memory.saveCurrentChat', title: 'Save Current Chat as Memory', category: 'Bible' },
  { command: 'bible.memory.downloadFile',    title: 'Download Memory File',      category: 'Bible' },
  { command: 'bible.task.showStatus',        title: 'Show Task Status',          category: 'Bible' },
];
