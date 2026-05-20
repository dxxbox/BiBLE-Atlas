import { MemoryHit, MemorySearchResult } from './memory-types';

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
