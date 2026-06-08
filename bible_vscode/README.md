# Bible VSCode Extension

VSCode 插件，通过 `bible` CLI 与 Bible Atlas server 协作，提供 **memory / skill / knowledge_base** 三域能力的端到端闭环。
当前阶段聚焦 **MEMORY 域**（save / search / download），框架可无侵入扩展到其它域。

> 设计与协作文档：
> - 框架设计：`../docs/designs/client_part/03-vscode-extension-framework-v4.md`
> - 域 spec（W0 必产）：`../docs/designs/client_part/04-vscode-extension-memory-spec-v4.md`
> - 2 人协作计划：`../backlog/memory-closure-collab-plan-zh.md`
> - CLI 契约：`../docs/manual/cli-contract-v1.md`

## 目录结构

```
bible_vscode/
├── package.json                # contributes（commands / tools / participant / config）
├── tsconfig.json
├── esbuild.js                  # 打包入口
├── mock-cli/                   # 对外依赖隔离层（不依赖真 CLI 即可开发）
│   └── bible                   # Node 实现的 mock 二进制
└── src/
    ├── extension.ts            # 激活入口
    ├── core/                   # 业务无关基础设施（Role 1 负责）
    │   ├── cli/                # CliRunner / BibleCliError / cli-detector
    │   ├── task/               # TaskTracker / task-store
    │   ├── registry/           # Tool / Command 注册中心 + CapabilityProbe
    │   ├── tool/               # BibleTool / AsyncBibleTool 抽象基类
    │   ├── lm/                 # 模型选择 + 字符预算
    │   ├── chat/               # Copilot Chat 双策略导出
    │   ├── ui/                 # notifications / quick-pick / output-channel
    │   └── config/             # bible.* 配置访问
    ├── domains/                # 业务域
    │   ├── control/            # bible_health / bible_task_status / Self-Check
    │   └── memory/             # Memory 域（Role 2 负责，本期重点）
    └── manifest/               # 工具与命令元数据
```

## 开发

```bash
cd bible_vscode
npm install
npm run compile           # tsc 检查 + esbuild 打包（开发用，含 source map）
npm run watch             # 开发模式
```

按 F5 在 Extension Development Host 中调试。

## 打包并安装为 .vsix（推荐：本地真实环境验证）

如果不习惯 Extension Development Host（F5），可以直接打成 `.vsix` 装到你日常用的 VSCode / Cursor 里：

```bash
cd bible_vscode
npm install                # 仅首次
npm run vsix               # 产物：bible-vscode.vsix
```

`vsix` 脚本干两件事：

1. `tsc --noEmit + esbuild --production` 出干净的 `dist/extension.js`
2. `npx @vscode/vsce package` 打成 `bible-vscode.vsix`（约 22 KB，仅含 `dist/` + `package.json` + `README.md`，不带 `node_modules` / `src/` / `mock-cli/`）

安装到 IDE（任选一种）：

**方式 A · UI 安装（最直观）**

1. 打开 VSCode / Cursor
2. 左侧 Extensions 面板 → 右上角 `…` → **Install from VSIX...**
3. 选 `bible_vscode/bible-vscode.vsix`
4. 重新加载窗口

**方式 B · 命令行安装**

```bash
# VSCode
code --install-extension bible_vscode/bible-vscode.vsix --force

# Cursor
cursor --install-extension bible_vscode/bible-vscode.vsix --force
```

`--force` 在覆盖同名旧版本时必须加。

### 验证已安装

- `Ctrl/Cmd + Shift + P` → 输入 **Bible** → 应能看到全部 Bible 命令
- View → Output → 通道下拉选 **Bible** → 应能看到 `INFO  extension.activated {...}`

### 迭代节奏

代码改动后：

```bash
npm run vsix
code --install-extension bible-vscode.vsix --force
# 然后 Ctrl/Cmd + Shift + P → Developer: Reload Window
```

`Developer: Reload Window` 比退出整个 IDE 快很多。

### 卸载

Extensions 面板里搜 **Bible Atlas** → 齿轮 → Uninstall；或：

```bash
code --uninstall-extension bible-atlas.bible-vscode
```

## Mock CLI 开发模式

为了与真 CLI 实现进度解耦，本目录自带 `mock-cli/bible` 脚本，实现了 `bible health / memory * / task *` 的假返回，行为见 `mock-cli/README.md`。

启用方式：

1. `chmod +x mock-cli/bible`
2. 在 VSCode 设置中：`"bible.cliPath": "<abs>/bible_vscode/mock-cli/bible"`
3. 重启扩展宿主

错误注入（验降级路径）：

```bash
export BIBLE_MOCK_INJECT=index_conflict   # 或 slow / task_failed / artifact_expired / not_implemented
```

## Debug Dry-Run 模式（CLI 还没就位时的本地自验）

当真 CLI **完全没有**、甚至连 mock 都不想跑（比如只想检查"我构造的临时文件对不对"）时，启用 dry-run：

```jsonc
// settings.json
{
  "bible.debug.dryRun": true,
  "bible.debug.printPayloads": true,   // 把 source.json / meta.json 全文打印到 OutputChannel
  "bible.debug.payloadMaxChars": 8000, // 每个文件最多回显 N 字符
  "bible.debug.keepTempFiles": true    // 临时文件不清理，方便你 VSCode 打开看
}
```

或通过隐藏的 debug 命令一键切换（默认不在命令面板，绑 keybinding 后调用 `bible.debug.toggleDryRun`）。

启用后：

- 所有 `bible ...` 命令**不会真去 exec**，只在 `Bible` OutputChannel 打印：
  - `[DRY-RUN] cli.invoke` —— 完整命令 + args 数组
  - `[DRY-RUN] cli.tempFile` —— `--source-file` / `--meta-file` / `--paths-file` / `--input-file` 指向的临时文件路径（`file://...` 可点击）+ 字节数
  - `[DRY-RUN] cli.tempFileContent` —— 紧跟一段 `----- BEGIN source.json -----` ... `----- END source.json -----`，回显原始内容（按 `payloadMaxChars` 截断）
  - `[DRY-RUN] cli.fakeResponse` —— 返回给上层的假 envelope
- import / download 类异步任务直接走 `queued → completed`，让 TaskTracker、notification、`onCompleted` 钩子等 UX 流程能完整走通，无需轮询等待。

### 命令面板可见的用户命令

| Command                              | 用途                                                                                                |
| ------------------------------------ | --------------------------------------------------------------------------------------------------- |
| `Bible: Run Self-Check`              | 探测 CLI 是否可用 + 能力集                                                                          |
| `Bible: Search Memory`               | 交互式 QuickPick：候选列表 ↔ 动作菜单（Preview summary / Load to @bible-memory：把 **message.json 原对话**填入 Copilot **输入框草稿**，不自动发送） |
| `Bible: Save Current Chat as Memory` | 导出当前 Copilot Chat，LM 提炼 meta，CLI 提交                                                       |
| `Bible: Show Task Status`            | 查看本插件已提交的异步任务（含 dry-run 下的虚拟任务）                                                |

> Memory 体系里**没有面向用户的"下载"命令**。下载已被 `MemoryService.ensureLocalSource` 隐式化——`Bible: Search Memory` 里选 Load 时自动按需下载 `message.json` 并复用缓存；随后打开 Chat 并把**原对话**填入输入框，由你自行编辑后点发送。

### 隐藏的 debug 命令（不在命令面板）

为了减少普通用户面板上的干扰，下列 debug 命令**只在代码层 register、不在 `package.json` 的 `commands` 数组里暴露**。需要的话用 keybinding 或 `vscode.commands.executeCommand(...)` 调用：

| Command id                          | 作用                                                                                         |
| ----------------------------------- | -------------------------------------------------------------------------------------------- |
| `bible.debug.toggleDryRun`          | 切换 `bible.debug.dryRun`，提示重启窗口                                                      |
| `bible.debug.openMockProfile`       | 打开 / 初始化 `~/.bible-mock.json`，调整 mock-cli 的 search/task/artifact 行为              |
| `bible.memory.showLastImportFiles`  | 列出最近一次 Save 写出的 `message.json` / `meta.json` / `source.raw.json` 并提供动作   |

需要打开任一项最简单的方式：`Ctrl/Cmd+Shift+P` → "Preferences: Open Keyboard Shortcuts (JSON)" → 加一条 `{ "key": "...", "command": "bible.debug.toggleDryRun" }`。

### 验证流程示例（你最关心的"上传"路径）

1. 在 settings.json 中设 `"bible.debug.dryRun": true`，重启窗口
2. 在 Copilot Chat 中和模型聊几句
3. 命令面板 → **Bible: Save Current Chat as Memory**
4. 打开 OutputChannel `Bible`：
   - 找到 `memory.import.files` 行 → `user_picked_json`（若从文件选择器导入）为你选的原始 JSON；`generated_source_for_cli` / `generated_meta_for_cli` 为插件生成、交给 `bible memory import` 的临时文件（点击可打开）
   - 再往下看 `[DRY-RUN] cli.invoke` 确认 `args` 是不是你预期的（`memory import --tag memory --kb-index memory_main --source-file /tmp/... --meta-file /tmp/... --vector-model ...`）
   - 紧跟的 `----- BEGIN source.json -----` 段就是真要发给 server 的源数据；`----- BEGIN meta.json -----` 段就是 LM 提取的结构化元数据

### dry-run vs mock CLI 该选哪个？

| 场景                                                 | 推荐               |
| ---------------------------------------------------- | ------------------ |
| 验证"插件构造的临时文件 / CLI args 对不对"         | **dry-run**        |
| 验证 CLI 错误码降级（INDEX_CONFLICT / 网络失败...） | mock CLI + INJECT |
| 验证异步任务 polling / 取消 / 状态流转              | mock CLI（slow）  |
| 真正联调                                             | 真 Go CLI          |

## 当前实现状态

- core/* 基础设施：已搭骨架（接口签名 + 最小实现），可编译可激活。
- `domains/control`：`bible_health` Tool / `Bible: Run Self-Check` Command 可用。
- `domains/memory`：模块骨架就绪；service / builder / tools / commands / participant 已挂载，但部分流程为占位（带 `TODO(spec)` 标注），待 04-spec 冻结后补齐。
- 真 CLI：仅 `bible health` 已就绪；其它命令默认走 mock。
