import * as vscode from 'vscode';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';
import * as crypto from 'node:crypto';
import { OutputChannel } from '../ui/output-channel';
import { ChatTurn } from '../lm/budget';
import { ChatSource } from '../../domains/memory/memory-types';

/**
 * Copilot Chat 导出结果（内部中间态）。
 *
 * `raw` 是 VSCode 给的原始 JSON，**只在 chat-export.ts 内部**用于解析 session_id / turns，
 * 不会直接序列化到 source.json——调用方用 `toCleanSource()` 拿精简版，
 * 或用 `rawJson()` 拿原始字符串写 source.raw.json（本地留存测试用）。
 */
export interface ChatExportResult {
  session_id: string;
  exported_at: string;
  messages: ChatTurn[];
  /** 原始 VSCode JSON，仅供内部使用和本地调试留存，不传给 server。 */
  raw: Record<string, unknown>;
  strategy: 'exportSession' | 'workbench' | 'manualFile';
  /** 仅 `manualFile`：用户在文件选择器里选中的原始 JSON 路径（与下方生成的 source.json 不同属正常）。 */
  originPath?: string;
}

/**
 * 把导出结果转成精简的 `ChatSource`：只含 session_id / exported_at / turns，
 * 不含任何 VSCode 原始 metadata。这是提交给 server 的 source.json 内容。
 */
export function toCleanSource(result: ChatExportResult): ChatSource {
  return {
    source_format: 'bible-chat-v1',
    session_id: result.session_id,
    exported_at: result.exported_at,
    turns: result.messages,
  };
}

/** 把原始 raw 序列化为可写入文件的 JSON 字符串，供 source.raw.json 本地留存。 */
export function rawJson(result: ChatExportResult): string {
  return JSON.stringify(result.raw, null, 2);
}

/** Cursor（及同类宿主）不注册 Copilot Chat 导出命令，直接走「不可用」错误以便上层弹出选文件。 */
function isCursorLikeHost(): boolean {
  return (vscode.env.appName ?? '').toLowerCase().includes('cursor');
}

function chatExportCommandsUnavailableError(): Error {
  return new Error(
    'Save current chat needs VS Code Copilot Chat export APIs (chat.exportSession or workbench.action.chat.export). Cursor and some VS Code builds do not register these commands — you will be asked to pick a chat export .json file (e.g. exported from VS Code), or use VS Code with Copilot Chat for one-click save.',
  );
}

/**
 * 双策略导出当前 Copilot Chat：
 * 1. `chat.exportSession`（直接返数据，部分 VSCode 版本不存在）
 * 2. `workbench.action.chat.export` 写临时文件 → 读 → 清理（fallback）
 *
 * **Cursor** 等环境通常两种命令都不存在（内置聊天非 Copilot Chat），此时会抛出明确说明。
 *
 * 见 framework v4 §14.3。
 */
export async function exportCurrentChat(output: OutputChannel): Promise<ChatExportResult> {
  if (isCursorLikeHost()) {
    throw chatExportCommandsUnavailableError();
  }

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
    // 常见：未装 Copilot Chat 或命令名变更 — 静默进入策略 2，避免误导性 DEBUG
  }

  // Strategy 2
  const tmpDir = path.join(os.tmpdir(), 'bible-vscode');
  await fs.promises.mkdir(tmpDir, { recursive: true });
  const tmpFile = path.join(tmpDir, `chat-export-${Date.now()}-${crypto.randomBytes(4).toString('hex')}.json`);

  try {
    try {
      await vscode.commands.executeCommand('workbench.action.chat.export', vscode.Uri.file(tmpFile));
    } catch (err2) {
      const msg2 = (err2 as Error).message ?? String(err2);
      if (/not found|command/i.test(msg2)) {
        throw chatExportCommandsUnavailableError();
      }
      throw err2;
    }
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

/**
 * 从用户选择的 JSON 文件解析 Copilot Chat 导出（与 workbench 导出格式相同：`requests` 数组等）。
 * 用于自动导出不可用（如 Cursor）时由 `importCurrentChat` 触发文件选择后的路径。
 */
export async function parseChatExportJsonFile(filePath: string, output: OutputChannel): Promise<ChatExportResult> {
  let text: string;
  try {
    text = await fs.promises.readFile(filePath, 'utf-8');
  } catch (e) {
    throw new Error(`Cannot read file: ${(e as Error).message}`);
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (e) {
    throw new Error(`Invalid JSON: ${(e as Error).message}`);
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Chat export JSON must be a single object (e.g. VS Code Copilot chat export).');
  }
  const raw = parsed as Record<string, unknown>;
  const result = buildResult(raw, 'manualFile');
  output.info('chat.export.strategy', { strategy: 'manualFile', path: filePath, turns: result.messages.length });
  return { ...result, originPath: filePath };
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
