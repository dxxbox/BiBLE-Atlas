import * as vscode from 'vscode';

/**
 * 按优先级列表选择 LM；全部失败 fallback 到任意 copilot 模型；
 * 仍然失败返回 undefined（调用方决定是否走规则 fallback）。
 *
 * priority 元素格式：`"<vendor>/<family>"`，例 "copilot/gpt-4.1"。
 */
export async function selectPreferredModel(
  priority: string[],
): Promise<vscode.LanguageModelChat | undefined> {
  for (const slug of priority) {
    const sel = parseSlug(slug);
    if (!sel) continue;
    try {
      const models = await vscode.lm.selectChatModels(sel);
      if (models.length > 0) return models[0];
    } catch {
      /* try next */
    }
  }
  try {
    const fallback = await vscode.lm.selectChatModels({ vendor: 'copilot' });
    if (fallback.length > 0) return fallback[0];
  } catch {
    /* ignore */
  }
  return undefined;
}

function parseSlug(slug: string): vscode.LanguageModelChatSelector | undefined {
  const parts = slug.split('/').map((s) => s.trim()).filter(Boolean);
  if (parts.length === 0) return undefined;
  if (parts.length === 1) return { vendor: parts[0] };
  return { vendor: parts[0], family: parts.slice(1).join('/') };
}
