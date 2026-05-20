import * as vscode from 'vscode';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';
import * as crypto from 'node:crypto';
import { OutputChannel } from '../ui/output-channel';
import { ChatTurn } from '../lm/budget';

/**
 * Copilot Chat 导出结果。`raw` 字段是 VSCode 给的原始 JSON（无损保留），
 * `messages` 是解析后的纯文本 turn 序列，`session_id` 优先取 raw.id / raw.sessionId / raw.requests[0].requestId。
 */
export interface ChatExportResult {
  session_id: string;
  exported_at: string;
  messages: ChatTurn[];
  raw: Record<string, unknown>;
  /** 走的哪条策略 */
  strategy: 'exportSession' | 'workbench';
}

/**
 * 双策略导出当前 Copilot Chat：
 * 1. `chat.exportSession`（直接返数据，部分 VSCode 版本不存在）
 * 2. `workbench.action.chat.export` 写临时文件 → 读 → 清理（fallback）
 *
 * 见 framework v4 §14.3。
 */
export async function exportCurrentChat(output: OutputChannel): Promise<ChatExportResult> {
  // Strategy 1
  try {
    const result = await vscode.commands.executeCommand<unknown>('chat.exportSession');
    if (result) {
      const raw = (typeof result === 'string' ? JSON.parse(result) : result) as Record<string, unknown>;
      output.info('chat.export.strategy', { strategy: 'exportSession' });
      return buildResult(raw, 'exportSession');
    }
  } catch (err) {
    const msg = (err as Error).message ?? String(err);
    if (!/not found|command/i.test(msg)) {
      throw new Error(`chat.exportSession failed: ${msg}`);
    }
    output.debug('chat.export.strategy1.unavailable', { reason: msg });
  }

  // Strategy 2
  const tmpDir = path.join(os.tmpdir(), 'bible-vscode');
  await fs.promises.mkdir(tmpDir, { recursive: true });
  const tmpFile = path.join(tmpDir, `chat-export-${Date.now()}-${crypto.randomBytes(4).toString('hex')}.json`);

  try {
    await vscode.commands.executeCommand('workbench.action.chat.export', vscode.Uri.file(tmpFile));
    await delay(200);
    if (!fs.existsSync(tmpFile)) {
      throw new Error('Chat export did not produce a file. Make sure a Copilot Chat session is open.');
    }
    const raw = JSON.parse(await fs.promises.readFile(tmpFile, 'utf-8')) as Record<string, unknown>;
    output.info('chat.export.strategy', { strategy: 'workbench' });
    return buildResult(raw, 'workbench');
  } finally {
    try {
      await fs.promises.unlink(tmpFile);
    } catch {
      /* ignore */
    }
  }
}

/** 把任意 messages[] / chat raw 转成 ChatExportResult 的通用方法（供 LM Tool 入参路径复用）。 */
export function fromMessages(messages: ChatTurn[], opts?: { sessionId?: string }): ChatExportResult {
  return {
    session_id: opts?.sessionId ?? crypto.randomUUID(),
    exported_at: new Date().toISOString(),
    messages,
    raw: { messages },
    strategy: 'exportSession',
  };
}

// ---------- 内部 ----------

function buildResult(raw: Record<string, unknown>, strategy: ChatExportResult['strategy']): ChatExportResult {
  const session_id = pickSessionId(raw);
  const messages = extractTurns(raw);
  return {
    session_id,
    exported_at: new Date().toISOString(),
    messages,
    raw,
    strategy,
  };
}

function pickSessionId(raw: Record<string, unknown>): string {
  return (
    typeOrUndefined<string>(raw['sessionId']) ??
    typeOrUndefined<string>(raw['id']) ??
    firstRequestId(raw) ??
    crypto.randomUUID()
  );
}

function firstRequestId(raw: Record<string, unknown>): string | undefined {
  const reqs = raw['requests'];
  if (!Array.isArray(reqs) || reqs.length === 0) return undefined;
  const first = reqs[0] as Record<string, unknown>;
  return typeOrUndefined<string>(first['requestId']);
}

function typeOrUndefined<T>(v: unknown): T | undefined {
  return v === undefined || v === null ? undefined : (v as T);
}

/**
 * 解析 chat export 的 requests 数组为 ChatTurn[]：
 * - user turn:      取 requests[].message.text
 * - assistant turn: 取 requests[].response[]，跳过含 kind 字段（thinking/toolInvocationSerialized/prepareToolInvocation 等运行时片段）
 *                   仅保留 typeof value === 'string' 的项；多 value 用 \n 拼接
 */
function extractTurns(raw: Record<string, unknown>): ChatTurn[] {
  const reqs = raw['requests'];
  if (!Array.isArray(reqs)) {
    // 如果是 fromMessages 已经放好的，直接取
    if (Array.isArray(raw['messages'])) {
      return (raw['messages'] as ChatTurn[]).filter(
        (m) => m && typeof m.role === 'string' && typeof m.content === 'string',
      );
    }
    return [];
  }

  const turns: ChatTurn[] = [];
  for (const r of reqs) {
    const req = r as Record<string, unknown>;
    const userText = ((req['message'] as Record<string, unknown> | undefined)?.['text'] as string | undefined) ?? '';
    if (userText) turns.push({ role: 'user', content: userText });

    const resp = req['response'];
    if (Array.isArray(resp)) {
      const parts: string[] = [];
      for (const p of resp) {
        const item = p as Record<string, unknown>;
        if (item['kind']) continue;
        const v = item['value'];
        if (typeof v === 'string' && v.trim()) parts.push(v);
      }
      if (parts.length > 0) turns.push({ role: 'assistant', content: parts.join('\n') });
    }
  }
  return turns;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
