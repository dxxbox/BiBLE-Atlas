# Search 命令层级与附带检索差异分析（2026-04-23）

## 1. 背景

根据 `docs/designs/client_part/01-bible-vscode-extension-design.md` 第 4.4 节描述：

- `search` 是最高层级命令；
- 通过 flag 可触发后端附带检索（skill，及可扩展到 memory）；
- 附带检索失败不影响主检索。

但当前实现与其他文档存在不一致，需统一口径。

## 2. 对比范围

本次对比基于以下文件：

- `docs/designs/client_part/01-bible-vscode-extension-design.md`
- `docs/designs/client_part/02-bible-vscode-extension-spec.md`
- `docs/manual/cli-contract-v1.md`
- `docs/manual/go-cli-user-guide.md`
- `backlog/bible-cli-go-full-rewrite-plan-zh.md`
- `bible_cli_go/internal/cli/run.go`
- `bible_cli_go/internal/commands/handlers.go`
- `bible_cli_go/internal/client/http/client.go`
- `bible_cli/commands/parsers/*.py`
- `bible_cli/commands/handlers.py`

## 3. 核心差异

### 3.1 命令层级差异（最高优先级）

设计文档（01/02）主叙事是顶层命令：

- `bible search --query <q> [--top-k N] [--enable-hit]`

当前 Python 与 Go 实现均为：

- `knowledge search [query]`

并且当前 Go 实现未支持 `--query`、`--top-k`、`--enable-hit` 这些目标 flag。

结论：`search 为顶层命令`目前属于目标态，不是当前态。

### 3.2 附带检索能力范围差异（skill vs memory）

`01` 的 4.4 明确写了 `--enable-hit` 自动附带 skill 结果；
但“memory 也作为附带命中”在 client 文档体系内并未被统一定义。

现状更接近：

- skill：在目标态中定义为 search 附带 hit；
- memory：在 server 文档中仍以独立链路（`/api/v1/memory/search`）描述。

结论：`search + enable-hit` 当前只应承诺 skill hit，memory 是否并入需单独决策。

### 3.3 目标态/当前态混写

`01` 中工具列表、时序流程、CLI 命令示例大量采用目标态命令；
而 `go-cli-user-guide` 与 rewrite plan 明确标识当前实现仅覆盖 `health/system/knowledge` 主路径，`memory/skills` 多为占位（`CLI_NOT_IMPLEMENTED`）。

结论：读者容易误判“4.4 已按描述可用”。

### 3.4 子命令命名不统一

存在以下并行写法：

- `skills ls`（目标态）
- `skills list`（当前实现/测试中仍使用）

此外命令示例前缀也并存（当时状态）：

- `bible`
- `bible-cli-go`
- `bs`（`run.go` help）

后续收敛方向：移除 `bs`，CLI help 与可执行示例统一使用 `bible`；`bible-cli-go` 仅作为兼容 alias。

结论：文档与实际调用示例存在学习成本和误导风险。

## 4. 影响评估

1. 插件集成风险：如果 Extension 或 agent prompt 按 `bible search --enable-hit` 调用，当前 Go CLI 将无法按预期执行。
2. 测试口径风险：验收用例难以区分“目标功能未实现”与“文档误写”。
3. 迁移风险：重写计划中的阶段成果与设计文档宣称存在错位，影响迭代判断。

## 5. 修订建议

### 5.1 建立统一口径优先级

建议沿用现有规则：

1. `docs/manual/cli-contract-v1.md`（冻结契约）
2. `docs/designs/client_part/02-bible-vscode-extension-spec.md`（可执行规格）
3. `docs/designs/client_part/01-bible-vscode-extension-design.md`（架构说明）
4. rewrite plan 仅用于阶段状态说明

### 5.2 改造 `01`（设计文档）的表达方式

将第 4.4 改为“当前态 + 目标态”双段结构：

- 当前态：`knowledge search [query]`，无 `--enable-hit` 契约能力；
- 目标态：顶层 `search` + `--enable-hit` 附带 skill；
- 明确 memory 当前为独立搜索链路，是否并入 hit 待决策。

并在 5.2 工具映射表新增 `状态` 列（Implemented/Planned）。

### 5.3 改造 `02`（可执行规格）

在命令规格前增加“实现状态矩阵”：

- Current（已实现）
- Transitional（别名/迁移窗口）
- Target（目标）

同时明确：

- `enable-hit` 当前语义只覆盖 skill；
- `memory` 为独立命令/接口（除非另有决议）。

### 5.4 改造用户与迁移文档

在 `go-cli-user-guide` 中增加“与 design/spec 差异说明”小节；
在 rewrite plan 中给出命令迁移里程碑（何时从 `knowledge search` 切到顶层 `search`）。

### 5.5 命名收敛建议

建议统一到以下最终模型：

- 顶层检索：`search`
- 技能子命令：`skills ls/search/get/upload/download`
- 迁移窗口：保留 `knowledge search` 与 `skills list` alias（明确废弃时间）

## 6. 决策建议（待确认）

需要先做一个架构决策以避免后续继续漂移：

- 方案 A（推荐短期）：`enable-hit` 仅附带 skill，memory 保持独立搜索链路；
- 方案 B（增强统一）：将 memory 也并入 `search --enable-hit`，同步改 server API、CLI schema、Extension 解析和契约文档。

建议先落地方案 A，后续再评估方案 B 的收益与改造成本。

## 7. 结论

当前最主要的问题不是“实现错误”，而是“文档状态混写”。
应先把 `01/02/guide/plan` 的当前态与目标态分层表达，确保：

- 调用方按当前能力开发不会踩坑；
- 目标态迁移路径清晰；
- 验收与发布判断有统一基线。

