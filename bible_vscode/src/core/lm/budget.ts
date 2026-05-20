export interface ChatTurn {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface BudgetOptions {
  convMaxChars: number;
  turnMaxChars: number;
}

export interface BudgetResult {
  turns: ChatTurn[];
  truncated: boolean;
  totalChars: number;
}

const TRUNC_SUFFIX = '\n…(truncated)';

/**
 * 字符预算 + 截断（见 framework v4 §14.5）：
 * 1. 每个 turn 超过 turnMaxChars 截断，加 `…(truncated)` 标记
 * 2. 累计字符超过 convMaxChars 时停止
 * 3. 优先保留首尾 turn；中间过长按时间顺序均匀采样
 */
export function applyConvBudget(turns: ChatTurn[], opts: BudgetOptions): BudgetResult {
  if (turns.length === 0) return { turns: [], truncated: false, totalChars: 0 };

  // Step 1: 每个 turn 单独截断
  const perTurn = turns.map((t) => clipTurn(t, opts.turnMaxChars));

  const totalChars = perTurn.reduce((acc, t) => acc + t.content.length, 0);
  if (totalChars <= opts.convMaxChars) {
    const someTruncated = perTurn.some((t, i) => t.content !== turns[i].content);
    return { turns: perTurn, truncated: someTruncated, totalChars };
  }

  // Step 2: 超预算，保留首尾 + 中间均匀采样
  const head = perTurn[0];
  const tail = perTurn[perTurn.length - 1];
  const reservedChars = head.content.length + tail.content.length;
  const middleBudget = Math.max(0, opts.convMaxChars - reservedChars);

  const middle = perTurn.slice(1, -1);
  const picked: ChatTurn[] = [];
  let used = 0;
  // 简单线性遍历，按顺序加直到预算用完
  for (const t of middle) {
    if (used + t.content.length > middleBudget) break;
    picked.push(t);
    used += t.content.length;
  }

  return {
    turns: [head, ...picked, tail],
    truncated: true,
    totalChars: head.content.length + used + tail.content.length,
  };
}

function clipTurn(turn: ChatTurn, max: number): ChatTurn {
  if (turn.content.length <= max) return turn;
  return { ...turn, content: turn.content.slice(0, max - TRUNC_SUFFIX.length) + TRUNC_SUFFIX };
}
