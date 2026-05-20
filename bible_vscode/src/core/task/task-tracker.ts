import * as vscode from 'vscode';
import { CliRunner } from '../cli/cli-runner';
import { BibleCliError } from '../cli/cli-error';
import { Notifications } from '../ui/notifications';
import { OutputChannel } from '../ui/output-channel';
import { ExtensionConfig } from '../config/extension-config';
import { TaskStore } from './task-store';
import { TaskGetResponse, TaskRecord, TaskStatus } from './task-types';

export interface TaskHandle<R = unknown> {
  taskId: string;
  onUpdate(listener: (record: TaskRecord<R>) => void): vscode.Disposable;
  /** 终态 resolve；用户取消 reject(BibleCliError CANCELLED) */
  promise: Promise<TaskRecord<R>>;
}

export interface SubmitOptions<R = unknown> {
  taskType: string;
  domain: TaskRecord['domain'];
  title: string;
  submit: () => Promise<{ task_id: string }>;
  showProgress?: boolean;
  onCompleted?: (record: TaskRecord<R>) => Promise<void>;
}

export interface TaskTracker {
  submit<R = unknown>(opts: SubmitOptions<R>): Promise<TaskHandle<R>>;
  watch<R = unknown>(taskId: string, taskType?: string, domain?: TaskRecord['domain']): TaskHandle<R>;
  cancel(taskId: string): Promise<void>;
  listActive(): TaskRecord[];
}

interface InternalDeps {
  cli: CliRunner;
  notify: Notifications;
  output: OutputChannel;
  config: ExtensionConfig;
  store: TaskStore;
}

const TERMINAL: TaskStatus[] = ['completed', 'failed', 'cancelled'];

export class DefaultTaskTracker implements TaskTracker {
  private readonly emitters = new Map<string, vscode.EventEmitter<TaskRecord>>();

  constructor(private readonly deps: InternalDeps) {}

  async submit<R = unknown>(opts: SubmitOptions<R>): Promise<TaskHandle<R>> {
    this.deps.output.info('task.submit', { taskType: opts.taskType, title: opts.title });

    const { task_id } = await opts.submit();
    const now = Date.now();
    const initial: TaskRecord<R> = {
      taskId: task_id,
      taskType: opts.taskType,
      domain: opts.domain,
      status: 'queued',
      submittedAt: now,
      updatedAt: now,
      title: opts.title,
    };
    await this.deps.store.upsert(initial);
    this.emit(initial);

    const promise = this.runWatch<R>(initial, opts);
    return {
      taskId: task_id,
      onUpdate: (l) => this.onUpdate(task_id, l as (r: TaskRecord) => void),
      promise,
    };
  }

  watch<R = unknown>(taskId: string, taskType = 'unknown', domain: TaskRecord['domain'] = 'memory'): TaskHandle<R> {
    const existing = this.deps.store.list().find((r) => r.taskId === taskId) as TaskRecord<R> | undefined;
    const record: TaskRecord<R> = existing ?? {
      taskId,
      taskType,
      domain,
      status: 'queued',
      submittedAt: Date.now(),
      updatedAt: Date.now(),
    };
    const promise = this.runWatch<R>(record, { taskType, domain, title: record.title ?? `Task ${taskId}`, submit: async () => ({ task_id: taskId }) });
    return {
      taskId,
      onUpdate: (l) => this.onUpdate(taskId, l as (r: TaskRecord) => void),
      promise,
    };
  }

  async cancel(taskId: string): Promise<void> {
    try {
      await this.deps.cli.run({ args: ['task', 'cancel', '--id', taskId] });
    } catch (err) {
      // 即便 CLI 报错（例如服务端已结束），本地仍标记取消
      this.deps.output.warn('task.cancel.cli_error', { taskId, err: (err as Error).message });
    }
    const existing = this.deps.store.list().find((r) => r.taskId === taskId);
    if (existing) {
      const updated: TaskRecord = { ...existing, status: 'cancelled', updatedAt: Date.now() };
      await this.deps.store.upsert(updated);
      this.emit(updated);
    }
  }

  listActive(): TaskRecord[] {
    return this.deps.store.list().filter((r) => !TERMINAL.includes(r.status));
  }

  // ---------- 内部 ----------

  private onUpdate(taskId: string, listener: (record: TaskRecord) => void): vscode.Disposable {
    let emitter = this.emitters.get(taskId);
    if (!emitter) {
      emitter = new vscode.EventEmitter<TaskRecord>();
      this.emitters.set(taskId, emitter);
    }
    return emitter.event(listener);
  }

  private emit(record: TaskRecord): void {
    this.emitters.get(record.taskId)?.fire(record);
    if (TERMINAL.includes(record.status)) {
      // 终态后清理 emitter
      setTimeout(() => {
        this.emitters.get(record.taskId)?.dispose();
        this.emitters.delete(record.taskId);
      }, 5000);
    }
  }

  private async runWatch<R>(initial: TaskRecord<R>, opts: { title: string; showProgress?: boolean; onCompleted?: (r: TaskRecord<R>) => Promise<void>; taskType: string; domain: TaskRecord['domain']; submit?: unknown; }): Promise<TaskRecord<R>> {
    const showProgress = (opts as SubmitOptions<R>).showProgress ?? true;
    const work = (token?: vscode.CancellationToken) => this.pollUntilTerminal<R>(initial, token);

    if (!showProgress) {
      const rec = await work();
      if (rec.status === 'completed' && opts.onCompleted) {
        await this.safeOnCompleted(rec, opts.onCompleted);
      }
      return rec;
    }

    return this.deps.notify.withProgress(opts.title, async (progress, token) => {
      progress.report({ message: 'queued' });

      const unsub = this.onUpdate(initial.taskId, (rec) => {
        progress.report({ message: rec.status });
      });
      token.onCancellationRequested(() => {
        void this.cancel(initial.taskId);
      });

      try {
        const rec = await work(token);
        if (rec.status === 'completed' && opts.onCompleted) {
          await this.safeOnCompleted(rec, opts.onCompleted);
        }
        return rec;
      } finally {
        unsub.dispose();
      }
    });
  }

  private async safeOnCompleted<R>(rec: TaskRecord<R>, cb: (r: TaskRecord<R>) => Promise<void>): Promise<void> {
    try {
      await cb(rec);
    } catch (err) {
      this.deps.output.error('task.onCompleted.failed', { taskId: rec.taskId, err: (err as Error).message });
    }
  }

  private async pollUntilTerminal<R>(initial: TaskRecord<R>, token?: vscode.CancellationToken): Promise<TaskRecord<R>> {
    const pollMs = this.deps.config.taskPollIntervalMs();
    const maxMs = this.deps.config.taskMaxWaitMs();
    const startedAt = Date.now();
    let backoffMs = pollMs;
    let consecutiveUnavailable = 0;
    let current = initial;

    while (!TERMINAL.includes(current.status)) {
      if (token?.isCancellationRequested) {
        return { ...current, status: 'cancelled', updatedAt: Date.now() };
      }
      if (Date.now() - startedAt > maxMs) {
        this.deps.output.warn('task.poll.maxWaitExceeded', { taskId: current.taskId });
        // 不算失败，调用方可以稍后再 watch
        return current;
      }

      await delay(backoffMs);

      try {
        const resp = await this.deps.cli.run<TaskGetResponse>({
          args: ['task', 'get', '--id', current.taskId],
        });
        consecutiveUnavailable = 0;
        backoffMs = pollMs;

        current = {
          ...current,
          status: resp.status,
          result: (resp.result as R | undefined) ?? current.result,
          error: resp.error,
          updatedAt: Date.now(),
        };
        await this.deps.store.upsert(current);
        this.emit(current);
      } catch (err) {
        if (err instanceof BibleCliError && err.code === 'UNAVAILABLE') {
          consecutiveUnavailable += 1;
          if (consecutiveUnavailable >= 3) backoffMs = Math.min(5000, backoffMs * 2);
          this.deps.output.warn('task.poll.unavailable', { taskId: current.taskId, consecutiveUnavailable });
          continue;
        }
        // 其它错误：标记失败，跳出循环
        const failed: TaskRecord<R> = {
          ...current,
          status: 'failed',
          error: { code: (err as BibleCliError).code ?? 'CLI_ERROR', message: (err as Error).message },
          updatedAt: Date.now(),
        };
        await this.deps.store.upsert(failed);
        this.emit(failed);
        return failed;
      }
    }
    return current;
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
