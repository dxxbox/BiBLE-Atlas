/**
 * Bible: Search Memory
 *
 * UX 目标（来自 user feedback）：
 *   - 一条命令的生命周期内可反复"看候选 → 预览 → 不满意回去 → 看下一条 → 满意了再 Load"
 *   - 不要"看一次就退出，下次只能重新触发命令"
 *
 * 实现：单实例 createQuickPick，根据 state 切换 items：
 *   state = 'hits'    → 显示候选 list（带 cached / viewed 标记）
 *   state = 'actions' → 显示当前 hit 的动作菜单（2 个动作 + Back to list）
 *
 *   预览完动作返回 actions 菜单（用户可直接选 Load）；
 *   Back to list 返回 hits（用户可挑下一条）；
 *   Esc / hide 退出整个命令；
 *   Load 完成后自动结束命令。
 */
import * as vscode from 'vscode';
import { ModuleDeps } from '../../types';
import { MemoryService } from '../memory-service';
import { MemoryHit, MemorySearchResult } from '../memory-types';
import {
  ensureSourceWithProgress,
  loadHitToContext,
  previewHitSummary,
} from './_memory-actions';

interface HitItem extends vscode.QuickPickItem {
  _kind: 'hit';
  hit: MemoryHit;
}
interface ActionItem extends vscode.QuickPickItem {
  _kind: 'action';
  action: 'preview' | 'load' | 'back';
}
type Item = HitItem | ActionItem;

export function registerSearchMemoryCommand(
  ctx: vscode.ExtensionContext,
  deps: ModuleDeps,
  service: MemoryService,
): vscode.Disposable {
  return deps.commandRegistry.register('bible.memory.search', async () => {
    const query = await vscode.window.showInputBox({
      title: 'Search Memory',
      prompt: 'Enter natural-language query',
      placeHolder: 'e.g. how did we fix the NPE in the user service?',
    });
    if (!query) return;

    const result = await deps.notify.withProgress(`Searching memory: ${query}`, async () =>
      service.search({ query, topK: 10 }),
    );

    if (result.results.length === 0) {
      await deps.notify.info('No memory results found.');
      return;
    }

    await runInteractivePicker(ctx, deps, service, result);
  });
}

async function runInteractivePicker(
  ctx: vscode.ExtensionContext,
  deps: ModuleDeps,
  service: MemoryService,
  result: MemorySearchResult,
): Promise<void> {
  return new Promise<void>((resolve) => {
    const qp = vscode.window.createQuickPick<Item>();
    qp.ignoreFocusOut = true; // 用户预览文件时 QuickPick 不消失
    qp.matchOnDescription = true;
    qp.matchOnDetail = true;
    qp.canSelectMany = false;

    const viewed = new Set<string>();
    let currentHit: MemoryHit | undefined;
    let resolved = false;

    const finish = () => {
      if (resolved) return;
      resolved = true;
      qp.dispose();
      resolve();
    };

    const showHits = () => {
      currentHit = undefined;
      qp.title = `Memory: ${result.total} results — pick to preview / load`;
      qp.placeholder = 'Pick a memory entry (Esc to cancel)';
      qp.items = result.results.map((hit) => buildHitItem(service, viewed, hit));
    };

    const showActions = (hit: MemoryHit) => {
      currentHit = hit;
      const cached = service.getCachedSourcePath(hit) !== undefined;
      qp.title = `Memory: ${hit.session_id} ${cached ? '· cached' : ''}`;
      qp.placeholder = 'Pick an action (Esc to cancel)';
      const items: ActionItem[] = [
        {
          _kind: 'action',
          action: 'back',
          label: '$(arrow-left) Back to list',
          description: 'Browse other candidates',
        },
        {
          _kind: 'action',
          action: 'preview',
          label: '$(eye) Preview summary',
          description: 'Show abstract / snippet / source path (no download)',
        },
        {
          _kind: 'action',
          action: 'load',
          label: '$(rocket) Load to @bible-memory',
          description: cached
            ? 'Open conversation in editor, then type @bible-memory /load in Chat'
            : 'Download message.json, open in editor, then type @bible-memory /load in Chat',
        },
      ];
      qp.items = items;
      // 默认聚焦 Preview，让"先看摘要 → 满意了再 Load"成为最顺路径
      qp.activeItems = [items[1]];
    };

    qp.onDidAccept(async () => {
      const picked = qp.selectedItems[0];
      if (!picked) return;

      if (picked._kind === 'hit') {
        showActions(picked.hit);
        return;
      }

      if (!currentHit) return;

      if (picked.action === 'back') {
        showHits();
        return;
      }

      if (picked.action === 'preview') {
        // Preview 只渲染 hit 已有字段，不触发下载 → 不会卡
        try {
          await previewHitSummary(service, currentHit);
          viewed.add(currentHit.session_id);
        } catch (err) {
          await deps.notify.error(`Preview failed: ${(err as Error).message}`);
        }
        // 留在动作菜单：用户预览完可直接选 Load，或选 Back 比较其他候选
        showActions(currentHit);
        return;
      }

      if (picked.action === 'load') {
        const targetHit = currentHit;
        qp.busy = true;
        let sourcePath: string | undefined;
        try {
          sourcePath = await ensureSourceWithProgress(deps, service, targetHit, {
            allowDegrade: true,
          });
        } catch (err) {
          await deps.notify.error(`Load failed: ${(err as Error).message}`);
          qp.busy = false;
          showActions(targetHit);
          return;
        }
        qp.busy = false;
        // 先 hide QuickPick 再 trigger chat —— 避免 chat panel 抢焦点时 QuickPick 残留
        qp.hide();
        finish();
        await loadHitToContext(ctx, deps, service, targetHit, sourcePath);
        return;
      }
    });

    qp.onDidHide(() => finish());

    showHits();
    qp.show();
  });
}

function buildHitItem(service: MemoryService, viewed: Set<string>, hit: MemoryHit): HitItem {
  const cached = service.getCachedSourcePath(hit) !== undefined;
  const seen = viewed.has(hit.session_id);
  const marks: string[] = [];
  if (cached) marks.push('cached');
  if (seen) marks.push('viewed');
  const tag = marks.length ? ` · ${marks.join(', ')}` : '';
  return {
    _kind: 'hit',
    hit,
    label: hit.session_id,
    description: `score=${hit.score.toFixed(3)}${tag}`,
    detail: hit.abstract,
  };
}
