import * as vscode from 'vscode';

export type SelectionMode = 'single' | 'top1' | 'quick-pick' | 'no-results' | 'cancelled';

export interface SelectOneOptions<T> {
  interactive: boolean;
  toQuickPickItem: (t: T) => vscode.QuickPickItem;
  title?: string;
  placeholder?: string;
}

export interface SelectOneResult<T> {
  selected?: T;
  mode: SelectionMode;
}

/**
 * 通用 0/1/N 选择 helper（见 framework v4 §14.6）。
 * - 0 hits:           mode='no-results'
 * - 1 hit:            直接返回 mode='single'
 * - N hits, interactive=true: QuickPick；可取消 → mode='cancelled'；否则 mode='quick-pick'
 * - N hits, interactive=false: 自动取 top1，mode='top1'
 */
export async function selectOneOrTop<T>(items: T[], opts: SelectOneOptions<T>): Promise<SelectOneResult<T>> {
  if (items.length === 0) return { mode: 'no-results' };
  if (items.length === 1) return { selected: items[0], mode: 'single' };

  if (!opts.interactive) {
    return { selected: items[0], mode: 'top1' };
  }

  const picks = items.map((item) => ({ ...opts.toQuickPickItem(item), _ref: item }));
  const picked = await vscode.window.showQuickPick(picks, {
    title: opts.title,
    placeHolder: opts.placeholder,
    matchOnDescription: true,
    matchOnDetail: true,
  });

  if (!picked) return { mode: 'cancelled' };
  return { selected: (picked as { _ref: T })._ref, mode: 'quick-pick' };
}
