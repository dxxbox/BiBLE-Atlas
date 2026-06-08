import * as fs from 'node:fs/promises';
import { ChatSource, MemoryHit, MemorySearchResult } from './memory-types';

/** 加载到聊天草稿 / loaded-context.md 的正文长度上限（字符）。 */
export const DEFAULT_LOAD_CONTEXT_MAX_CHARS = 60_000;

/**
 * 把 search 结果格式化为 LM 注入文本（也用于命令面板展示）。
 * 待 04-spec 细化布局；当前 minimum-viable 实现：列表 + 关键字段。
 */
export function formatSearchResultForLM(result: MemorySearchResult): string {
  if (result.results.length === 0) {
    return `_No memory found for the current query (tag=${result.tag}, kb_index=${result.kb_index})._`;
  }

  const header = `**Found ${result.total} memory entries** (showing ${result.results.length}, tag=${result.tag}, kb_index=${result.kb_index}):`;
  const body = result.results.map((h, idx) => formatHit(h, idx + 1)).join('\n\n');
  return `${header}\n\n${body}`;
}

export function formatHit(hit: MemoryHit, index: number): string {
  const lines: string[] = [];
  lines.push(`### ${index}. \`${hit.session_id}\` (score=${hit.score.toFixed(3)})`);
  lines.push(`- abstract: ${hit.abstract}`);
  if (hit.snippet) lines.push(`- snippet: ${truncate(hit.snippet, 400)}`);
  if (hit.hit_field) lines.push(`- hit_field: \`${hit.hit_field}\``);
  if (hit.storage_path) lines.push(`- storage_path: \`${hit.storage_path}\``);
  return lines.join('\n');
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return s.slice(0, max - 1) + '…';
}

/**
 * 把 source.json（bible-chat-v1）渲染为可读的 Markdown 对话。
 *
 * 渲染规则：
 *   - 每轮之间用分隔线隔开
 *   - user 用 `**You**`，assistant 用 `**Assistant**`
 *   - 正文原样输出（不转义），保留代码块等 Markdown 格式
 *   - 文件头部附上 session_id + 导出时间，方便回溯
 */
export function renderChatMarkdown(source: ChatSource): string {
  const lines: string[] = [
    `<!-- Bible Atlas · session: ${source.session_id} · exported: ${source.exported_at} -->`,
    '',
  ];

  for (let i = 0; i < source.turns.length; i++) {
    const turn = source.turns[i];
    const speaker = turn.role === 'user' ? '**You**' : '**Assistant**';
    lines.push(`${speaker}`, '', turn.content.trimEnd());
    if (i < source.turns.length - 1) {
      lines.push('', '---', '');
    }
  }

  return lines.join('\n') + '\n';
}

/**
 * 尝试把下载到本地的 source.json 文件内容解析为 ChatSource。
 * 若格式不符（老版本 / 非 bible-chat-v1）返回 undefined。
 */
export function parseChatSource(json: string): ChatSource | undefined {
  try {
    const obj = JSON.parse(json) as Partial<ChatSource>;
    if (obj.source_format === 'bible-chat-v1' && Array.isArray(obj.turns)) {
      return obj as ChatSource;
    }
  } catch {
    /* ignore */
  }
  return undefined;
}

/**
 * 从本地的 message.json（bible-chat-v1）构建「加载到上下文」用的 Markdown：
 * 原对话渲染，不含检索摘要 abstract。
 *
 * - 无路径或读失败：简短说明（不嵌入 summary）
 * - 非 bible-chat-v1：以 ```json 原文展示
 */
export async function buildLoadedContextMarkdown(
  hit: MemoryHit,
  messageJsonPath: string | undefined,
  maxChars: number = DEFAULT_LOAD_CONTEXT_MAX_CHARS,
): Promise<string> {
  const header = [
    `<!-- Bible Atlas · memory · session: ${hit.session_id} · storage_path: ${hit.storage_path} -->`,
    '',
    `## Memory: \`${hit.session_id}\``,
    '',
  ].join('\n');

  if (!messageJsonPath) {
    return (
      `${header}` +
      '_No message.json on disk yet — use **Load** only after the source file has been downloaded for this entry._\n'
    );
  }

  let raw: string;
  try {
    raw = await fs.readFile(messageJsonPath, 'utf-8');
  } catch {
    return `${header}_Could not read message.json at \`${messageJsonPath}\`._\n`;
  }

  const source = parseChatSource(raw);
  let body: string;
  if (source) {
    body = renderChatMarkdown(source);
  } else {
    body = ['_message.json is not bible-chat-v1; raw file:_', '', '```json', raw, '```'].join('\n');
  }

  let text = header + body;
  if (text.length > maxChars) {
    text =
      text.slice(0, maxChars) +
      `\n\n_…truncated to ${maxChars} characters (full text is in \`${messageJsonPath}\`)._\n`;
  }
  return text;
}
