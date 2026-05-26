import * as vscode from 'vscode';
import * as crypto from 'node:crypto';
import { selectPreferredModel } from '../../core/lm/model-selector';
import { applyConvBudget, ChatTurn } from '../../core/lm/budget';
import { OutputChannel } from '../../core/ui/output-channel';
import { ExtensionConfig } from '../../core/config/extension-config';
import { ChatSource, MemoryMeta } from './memory-types';

export interface BuildMetaInput {
  source: ChatSource;
  sessionId?: string;
  title?: string;
  cancellationToken?: vscode.CancellationToken;
}

export interface MemoryBuilder {
  build(input: BuildMetaInput): Promise<{ meta: MemoryMeta; via: 'lm' | 'rules'; modelInfo?: string }>;
}

export class DefaultMemoryBuilder implements MemoryBuilder {
  constructor(private readonly config: ExtensionConfig, private readonly output: OutputChannel) {}

  async build(input: BuildMetaInput): Promise<{ meta: MemoryMeta; via: 'lm' | 'rules'; modelInfo?: string }> {
    const sessionId = input.sessionId ?? input.source.session_id ?? crypto.randomUUID();

    const lmResult = await this.tryLm(sessionId, input);
    if (lmResult) return lmResult;

    const meta = buildRuleFallback(sessionId, input.source.turns, input.title);
    this.output.info('memory.builder.fallback', { sessionId, reason: 'lm_unavailable_or_failed' });
    return { meta, via: 'rules' };
  }

  private async tryLm(
    sessionId: string,
    input: BuildMetaInput,
  ): Promise<{ meta: MemoryMeta; via: 'lm'; modelInfo?: string } | undefined> {
    const model = await selectPreferredModel(this.config.memoryLmModelPriority());
    if (!model) {
      this.output.warn('memory.builder.lm.unavailable');
      return undefined;
    }

    const budget = applyConvBudget(input.source.turns, {
      convMaxChars: this.config.memoryLmConvMaxChars(),
      turnMaxChars: this.config.memoryLmTurnMaxChars(),
    });

    const messages = buildLmPrompt(sessionId, budget.turns, input.title);
    const started = Date.now();
    try {
      const resp = await model.sendRequest(
        messages,
        {},
        input.cancellationToken ?? new vscode.CancellationTokenSource().token,
      );
      let buf = '';
      for await (const chunk of resp.text) buf += chunk;
      const meta = parseMetaJson(buf, sessionId);
      if (!meta) {
        this.output.warn('memory.builder.lm.parse_failed', { elapsedMs: Date.now() - started });
        return undefined;
      }
      this.output.info('memory.builder.lm.ok', {
        model: `${model.vendor}/${model.family}`,
        elapsedMs: Date.now() - started,
        truncated: budget.truncated,
        chars: budget.totalChars,
      });
      return { meta, via: 'lm', modelInfo: `${model.vendor}/${model.family}` };
    } catch (err) {
      this.output.warn('memory.builder.lm.failed', { error: (err as Error).message });
      return undefined;
    }
  }
}

// ---------- LM Prompt ----------

const SYSTEM_PROMPT = [
  'You extract reusable work memory from a conversation.',
  'Your output MUST be a single JSON object matching the schema described in the user message; do not add prose, markdown, or code fences.',
  'Rules:',
  '1. Never claim that read-only analysis is "implemented", "fixed", or "completed". Be honest about whether code was actually changed.',
  '2. Required fields must always be present; if a value is unknown, use an empty array / empty string explicitly.',
  '3. session_kind ∈ {implementation, analysis, mixed}; code_change_status ∈ {modified, not_modified, unknown}.',
  '4. Extract concrete file paths and symbol names when possible; avoid vague phrases.',
  '5. abstract must be a single-line summary ≤ 220 characters.',
].join('\n');

function buildLmPrompt(sessionId: string, turns: ChatTurn[], title?: string): vscode.LanguageModelChatMessage[] {
  const schema = `Schema (output exactly this JSON shape):
{
  "session_id": "${sessionId}",
  "abstract": "<single line ≤ 220 chars>",
  "overview": "<multi-paragraph markdown>",
  "primary_request_intent": "<user's real goal>",
  "key_concepts": ["..."],
  "pending_tasks": ["..."],
  "session_kind": "implementation | analysis | mixed",
  "code_change_status": "modified | not_modified | unknown",
  "actual_actions": ["..."],
  "final_result": "...",
  "touched_files": ["..."],
  "touched_symbols": ["..."],
  "key_decisions": ["..."],
  "verification_evidence": ["..."],
  "risks_next_steps": ["..."]
}`;

  const transcript = turns
    .map((t) => `[${t.role}] ${t.content}`)
    .join('\n\n---\n\n');

  const user = [
    title ? `Title (hint, optional): ${title}` : null,
    schema,
    'Conversation:',
    transcript,
    'Respond with the JSON only.',
  ].filter(Boolean).join('\n\n');

  return [
    vscode.LanguageModelChatMessage.User(SYSTEM_PROMPT),
    vscode.LanguageModelChatMessage.User(user),
  ];
}

function parseMetaJson(raw: string, sessionId: string): MemoryMeta | undefined {
  const stripped = stripCodeFences(raw).trim();
  if (!stripped) return undefined;
  try {
    const obj = JSON.parse(stripped) as Partial<MemoryMeta>;
    if (typeof obj.abstract !== 'string' || typeof obj.overview !== 'string') return undefined;
    return {
      session_id: obj.session_id ?? sessionId,
      abstract: obj.abstract,
      overview: obj.overview,
      primary_request_intent: obj.primary_request_intent ?? '',
      key_concepts: obj.key_concepts ?? [],
      pending_tasks: obj.pending_tasks ?? [],
      session_kind: obj.session_kind,
      code_change_status: obj.code_change_status,
      actual_actions: obj.actual_actions,
      final_result: obj.final_result,
      touched_files: obj.touched_files,
      touched_symbols: obj.touched_symbols,
      key_decisions: obj.key_decisions,
      verification_evidence: obj.verification_evidence,
      risks_next_steps: obj.risks_next_steps,
    };
  } catch {
    return undefined;
  }
}

function stripCodeFences(s: string): string {
  return s.replace(/^```(?:json)?\s*([\s\S]*?)\s*```$/i, '$1');
}

// ---------- 规则 fallback ----------

export function buildRuleFallback(sessionId: string, turns: ChatTurn[], title?: string): MemoryMeta {
  const firstUser = turns.find((t) => t.role === 'user')?.content ?? title ?? '(no user message)';
  const lastAssistant = [...turns].reverse().find((t) => t.role === 'assistant')?.content ?? '';

  const abstract = title ?? firstSentence(firstUser, 220);
  const overview = [
    '## User goal',
    firstUser.slice(0, 1500),
    '',
    '## Final assistant response',
    lastAssistant.slice(0, 1500),
  ].join('\n');

  const text = turns.map((t) => t.content).join(' ').toLowerCase();
  const sessionKind = pickSessionKind(text);
  const codeChangeStatus = pickCodeChangeStatus(text);

  return {
    session_id: sessionId,
    abstract,
    overview,
    primary_request_intent: firstSentence(firstUser, 200),
    key_concepts: extractKeyConcepts(turns, 8),
    pending_tasks: [],
    session_kind: sessionKind,
    code_change_status: codeChangeStatus,
    actual_actions: [],
    final_result: firstSentence(lastAssistant, 200),
  };
}

function firstSentence(s: string, max: number): string {
  const t = s.trim();
  if (!t) return '';
  const match = t.match(/^[^。.!?！？]{1,400}[。.!?！？]/);
  const sent = (match ? match[0] : t).slice(0, max);
  return sent.replace(/\s+/g, ' ').trim();
}

const STOPWORDS = new Set([
  'the', 'a', 'an', 'and', 'or', 'is', 'are', 'was', 'were', 'of', 'in', 'on', 'to', 'for',
  'with', 'this', 'that', 'it', 'be', 'as', 'at', 'by', 'we', 'you', 'i', 'me', 'my',
  '我', '我们', '的', '是', '了', '在', '和', '与', '一个', '这个', '那个', '可以', '需要',
]);

function extractKeyConcepts(turns: ChatTurn[], topN: number): string[] {
  const freq = new Map<string, number>();
  for (const t of turns) {
    const words = t.content
      .toLowerCase()
      .split(/[^\w\u4e00-\u9fff]+/)
      .filter((w) => w.length >= 3 && !STOPWORDS.has(w));
    for (const w of words) freq.set(w, (freq.get(w) ?? 0) + 1);
  }
  return [...freq.entries()].sort((a, b) => b[1] - a[1]).slice(0, topN).map(([w]) => w);
}

function pickSessionKind(text: string): 'implementation' | 'analysis' | 'mixed' {
  const hasImpl = /已修改|已实现|已写入|implemented|modified|wrote|edited/.test(text);
  const hasAnalysis = /分析|解释|说明|理解|analyze|explain|describe/.test(text);
  if (hasImpl && hasAnalysis) return 'mixed';
  if (hasImpl) return 'implementation';
  if (hasAnalysis) return 'analysis';
  return 'analysis';
}

function pickCodeChangeStatus(text: string): 'modified' | 'not_modified' | 'unknown' {
  if (/已修改|已写入|已提交|modified|edited|committed|saved file/.test(text)) return 'modified';
  if (/只读|未修改|没有修改|read.only|no changes/.test(text)) return 'not_modified';
  return 'unknown';
}
