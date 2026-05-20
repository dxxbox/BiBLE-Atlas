import * as vscode from 'vscode';

export interface Notifications {
  info(message: string, ...actions: string[]): Promise<string | undefined>;
  warn(message: string, ...actions: string[]): Promise<string | undefined>;
  error(message: string, ...actions: string[]): Promise<string | undefined>;
  withProgress<T>(title: string, fn: ProgressFn<T>): Promise<T>;
}

export type ProgressFn<T> = (
  progress: vscode.Progress<{ message?: string; increment?: number }>,
  token: vscode.CancellationToken,
) => Promise<T>;

export class VsCodeNotifications implements Notifications {
  info(message: string, ...actions: string[]) {
    return Promise.resolve(vscode.window.showInformationMessage(message, ...actions)).then((v) => v ?? undefined);
  }
  warn(message: string, ...actions: string[]) {
    return Promise.resolve(vscode.window.showWarningMessage(message, ...actions)).then((v) => v ?? undefined);
  }
  error(message: string, ...actions: string[]) {
    return Promise.resolve(vscode.window.showErrorMessage(message, ...actions)).then((v) => v ?? undefined);
  }
  withProgress<T>(title: string, fn: ProgressFn<T>): Promise<T> {
    return Promise.resolve(
      vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title, cancellable: true },
        fn,
      ),
    );
  }
}
