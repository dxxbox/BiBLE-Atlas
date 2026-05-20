import * as vscode from 'vscode';
import { TaskRecord } from './task-types';

const STORE_KEY = 'bible.tasks.v1';
const RETENTION_MS = 24 * 60 * 60 * 1000;

/** 任务持久化到 globalState（跨工作区）。终态保留 24h 用于排障。 */
export interface TaskStore {
  list(): TaskRecord[];
  upsert(record: TaskRecord): Promise<void>;
  remove(taskId: string): Promise<void>;
  gc(): Promise<void>;
}

export class GlobalStateTaskStore implements TaskStore {
  constructor(private readonly state: vscode.Memento) {}

  list(): TaskRecord[] {
    return this.state.get<TaskRecord[]>(STORE_KEY, []);
  }

  async upsert(record: TaskRecord): Promise<void> {
    const all = this.list().filter((r) => r.taskId !== record.taskId);
    all.push(record);
    await this.state.update(STORE_KEY, all);
  }

  async remove(taskId: string): Promise<void> {
    const all = this.list().filter((r) => r.taskId !== taskId);
    await this.state.update(STORE_KEY, all);
  }

  async gc(): Promise<void> {
    const now = Date.now();
    const all = this.list().filter((r) => {
      const terminal = r.status === 'completed' || r.status === 'failed' || r.status === 'cancelled';
      if (!terminal) return true;
      return now - r.updatedAt < RETENTION_MS;
    });
    await this.state.update(STORE_KEY, all);
  }
}
