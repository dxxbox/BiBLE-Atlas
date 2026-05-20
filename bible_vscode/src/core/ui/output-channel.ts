import * as vscode from 'vscode';

/**
 * 统一日志通道。所有 CLI 调用、LM 调用、Task 状态变化都必须写到这里
 * （见 framework v4 §14.9）。日志格式：`<timestamp> <level> <event> <json-payload>`。
 */
export interface OutputChannel {
  debug(event: string, payload?: Record<string, unknown>): void;
  info(event: string, payload?: Record<string, unknown>): void;
  warn(event: string, payload?: Record<string, unknown>): void;
  error(event: string, payload?: Record<string, unknown>): void;
  /** 写入原始文本（不带时间戳/级别前缀）；用于回显临时文件内容、长 dump 等。 */
  raw(text: string): void;
  show(preserveFocus?: boolean): void;
  dispose(): void;
}

const SENSITIVE_KEYS = new Set(['authToken', 'token', 'password', 'apiKey']);

function redact(value: unknown): unknown {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = SENSITIVE_KEYS.has(k) ? '***' : v;
    }
    return out;
  }
  return value;
}

export class VsCodeOutputChannel implements OutputChannel {
  private readonly channel: vscode.OutputChannel;

  constructor(name = 'Bible') {
    this.channel = vscode.window.createOutputChannel(name);
  }

  private write(level: string, event: string, payload?: Record<string, unknown>): void {
    const ts = new Date().toISOString();
    const body = payload === undefined ? '' : ' ' + JSON.stringify(redact(payload));
    this.channel.appendLine(`${ts} ${level.padEnd(5)} ${event}${body}`);
  }

  debug(event: string, payload?: Record<string, unknown>): void { this.write('DEBUG', event, payload); }
  info(event: string, payload?: Record<string, unknown>): void  { this.write('INFO',  event, payload); }
  warn(event: string, payload?: Record<string, unknown>): void  { this.write('WARN',  event, payload); }
  error(event: string, payload?: Record<string, unknown>): void { this.write('ERROR', event, payload); }

  raw(text: string): void {
    for (const line of text.split('\n')) this.channel.appendLine(line);
  }

  show(preserveFocus = true): void { this.channel.show(preserveFocus); }
  dispose(): void { this.channel.dispose(); }
}
