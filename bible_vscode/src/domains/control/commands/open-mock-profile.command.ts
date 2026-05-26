import * as vscode from 'vscode';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import * as os from 'node:os';
import { ModuleDeps } from '../../types';

/**
 * 打开（或创建）mock-cli 的行为配置 profile。
 *
 * 此命令对真 CLI 无影响——它服务于 mock-cli/bible 的 `loadProfile()`。
 * 路径优先级：BIBLE_MOCK_PROFILE 环境变量 > ~/.bible-mock.json
 *
 * profile 改完保存后，下一次插件触发 CLI 调用就会用新值，无需 reload window。
 */
export function registerOpenMockProfileCommand(deps: ModuleDeps): vscode.Disposable {
  return deps.commandRegistry.register('bible.debug.openMockProfile', async () => {
    const profilePath = process.env.BIBLE_MOCK_PROFILE ?? path.join(os.homedir(), '.bible-mock.json');

    let exists = false;
    try {
      await fs.access(profilePath);
      exists = true;
    } catch {
      /* missing */
    }

    if (!exists) {
      const pick = await vscode.window.showInformationMessage(
        `Mock profile not found at ${profilePath}. Create a template?`,
        'Create Template',
        'Cancel',
      );
      if (pick !== 'Create Template') return;
      await fs.mkdir(path.dirname(profilePath), { recursive: true });
      await fs.writeFile(profilePath, TEMPLATE, 'utf-8');
      deps.output.info('mock.profile.created', { path: profilePath });
    }

    const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(profilePath));
    await vscode.window.showTextDocument(doc, { preview: false });
    await deps.notify.info(
      'Mock profile open. Save to apply — mock-cli re-reads it on every invocation, no reload needed.',
    );
  });
}

/**
 * 模板：JSONC 注释的形式更友好，但 mock-cli 的 JSON.parse 不接受注释。
 * 折中：给用户一个全字段示例（注释通过 _comment 字段保留）。
 */
const TEMPLATE = `{
  "_comment_global": "BIBLE_MOCK_INJECT env-var has higher priority than 'inject' here. Set to null to disable.",
  "inject": null,

  "_comment_search": "Controls 'bible memory search'. count=0 to test empty results; longAbstract for truncation UI tests.",
  "search": {
    "count": 3,
    "abstractTemplate": "Discussion about {query} (#{i})",
    "longAbstract": false,
    "longAbstractRepeat": 12,
    "errorIfQueryContains": "error",
    "scoreStart": 0.92,
    "scoreStep": 0.08,
    "sessionIdPrefix": "mock-session",
    "hitField": "abstract",
    "sessionKind": "mixed"
  },

  "_comment_task": "Controls async task progression. completeAt=N means the Nth 'task get' marks status=completed; failAt=N marks failed instead.",
  "task": {
    "completeAt": 3,
    "failAt": null
  },

  "_comment_artifact": "When fixtureFile points to a real file, 'artifact fetch --out X' copies it into X instead of writing a stub. Use this to verify how the extension handles downloaded content.",
  "artifact": {
    "fixtureFile": null,
    "contentType": "application/json"
  }
}
`;
