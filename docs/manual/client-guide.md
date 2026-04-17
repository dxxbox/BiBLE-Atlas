# Bible CLI 使用指南（当前实现）

本文面向用户与测试人员，说明当前版本 `bible_cli` 的安装方式、可用命令与测试方法。

## 1. 当前能力范围

当前 `bible_cli` 处于框架阶段（Phase 1）：

- 已提供 CLI 入口与命令树
- 已注册命令别名：`bs`、`biblesearch`
- 已声明命令分组：`system`、`knowledge`、`memory`、`skills`
- 各具体动作尚未实现，执行时会返回统一错误码

## 2. 运行前准备

在仓库根目录执行：

```bash
uv sync --all-extras
```

## 3. 基础使用

### 3.1 查看帮助

```bash
uv run bs --help
uv run biblesearch --help
```

预期：返回 0，并显示命令树（`system/knowledge/memory/skills`）。

### 3.2 查看子命令帮助

```bash
uv run bs system --help
uv run bs knowledge --help
uv run bs memory --help
uv run bs skills --help
```

预期：返回 0，并显示对应 action：

- `system health`
- `knowledge search`
- `memory show`
- `skills list`

## 4. 当前未实现行为（测试重点）

以下命令目前会返回“未实现”错误，这是符合当前阶段预期的：

```bash
uv run bs system health
uv run bs knowledge search
uv run bs memory show
uv run bs skills list
```

预期结果：

- 退出码：`3`
- 标准错误输出包含：`Error[CLI_NOT_IMPLEMENTED]`
- 错误消息形如：`Command '<group> <action>' is not implemented yet.`

示例：

```text
Error[CLI_NOT_IMPLEMENTED]: Command 'system health' is not implemented yet.
```

## 5. 测试清单（建议）

测试人员可按以下顺序执行：

1. `uv run bs --help`，确认命令树可见
2. `uv run biblesearch --help`，确认别名可用
3. 逐条执行 4 个 action 命令，确认退出码为 `3`
4. 校验 stderr 是否包含 `CLI_NOT_IMPLEMENTED`

可用以下方式查看退出码（bash）：

```bash
uv run bs system health
echo $?
```

## 6. 常见问题

- `command not found: bs`  
  请使用 `uv run bs ...`（推荐），或确认当前环境已安装本项目脚本入口。

- `Unable to import 'bible_cli.python_cli'`（IDE 静态检查）  
  当前包入口已采用延迟导入；若仍提示，请刷新 IDE Python 解释器并重新索引。

- 命令执行失败但非退出码 `3`  
  优先检查是否在仓库根目录执行，以及依赖是否完成 `uv sync --all-extras`。
