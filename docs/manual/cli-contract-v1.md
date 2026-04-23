# Bible CLI Contract v1

本文档固化 `bible_cli_go` 当前冻结契约（v1），用于 CLI、插件与测试的共同基线。

## 1. 输出协议

所有业务命令遵循单行 JSON 输出契约：

- 成功：`stdout` 输出 `{"ok":true,"data":...}`
- 失败：`stdout` 输出 `{"ok":false,"error":{"code":"...","message":"..."}}`
- 默认不将业务错误正文写入 `stderr`

兼容开关：

- 当 `BIBLE_CLI_LEGACY_STDERR=1` 时，在保留 `stdout` JSON 的同时，额外输出历史文本到 `stderr`：`Error[<CODE>]: <message>`

## 2. 退出码

- `0`：成功
- `1`：通用错误（参数错误、网络/接口错误、内部错误等）
- `3`：命令路径已声明但未实现（`CLI_NOT_IMPLEMENTED`）

## 3. 错误码契约

### 3.1 CLI 参数与本地错误

- 参数错误统一为 `INVALID_ARGS`
- 未实现命令保留 `CLI_NOT_IMPLEMENTED`（并保持 `exit=3`）
- 子命令短写与长写需兼容（示例：`ls` 等价 `list`）

### 3.2 HTTP 映射关键规则

- `400 -> INVALID_ARGS`
- `501 -> SEV_NOT_IMPLEMENTED`
- 超时对外主码统一为 `TIMEOUT`
- `DEADLINE_EXCEEDED` 与 `TIMEOUT` 做兼容归一（输出层以 `TIMEOUT` 为主）

### 3.3 `search --enable-hit` 契约

- 顶层检索命令：`search --query <q> [--top-k N] [--enable-hit] [--hit-types skill,memory]`
- 当设置 `--enable-hit` 且未显式指定 `--hit-types` 时，默认附带 `skill,memory`
- 附带检索遵循降级策略：`skill` 或 `memory` 任一分支失败，不影响主检索成功返回
- 发生降级时，在 `data.hit_warnings` 返回失败分支信息（调用方据此提示，不应将主请求判为失败）

## 4. 配置来源优先级

生效优先级（高 -> 低）：

1. 环境变量：`BIBLE_CLI_*`（其中 `BIBLE_CLI_BASE_URL` 优先于 `BIBLE_ATLAS_BASE_URL`）
2. 用户配置：`~/.bible/config.json`
3. 系统配置：`/etc/bible/config.json`
4. 内置默认值

## 5. 验收门槛（v1）

1. 所有命令输出均为单行 JSON（成功/失败都走 `stdout`）。
2. 参数错误码为 `INVALID_ARGS`。
3. HTTP 501 映射为 `SEV_NOT_IMPLEMENTED`。
4. 占位命令保持 `CLI_NOT_IMPLEMENTED` 且退出码 `3`。
5. 配置可从 env/user/system 三层解析并有优先级。
6. `go test ./...` 全通过，golden 用例被执行。
7. `search --enable-hit` 默认附带 `skill,memory`，且附带分支失败时主检索仍成功并返回 `hit_warnings`。

## 6. 验收记录（2026-04-23）

结论：已通过。

- 门槛 1（单行 JSON / stdout）：
	- `internal/cli`：`TestRunGoldenScenarios` 全子场景通过（`success`、`invalid_args`、`404`、`5xx`、`timeout`、`cli_not_implemented`）。
- 门槛 2（`INVALID_ARGS`）：
	- `internal/cli`：`TestRunUnknownCommand` 通过。
	- `internal/client/http`：`TestErrorEnvelopeMapsToCLIError` 通过。
- 门槛 3（`501 -> SEV_NOT_IMPLEMENTED`）：
	- `internal/client/http`：`TestErrorEnvelopeFor501ForcesSEVNotImplemented` 通过。
- 门槛 4（`CLI_NOT_IMPLEMENTED` + `exit=3`）：
	- `internal/cli`：`TestRunSkillsListNotImplemented` 与 `TestRunGoldenScenarios/cli_not_implemented` 通过。
- 门槛 5（配置优先级）：
	- `internal/config`：`TestLoadResolvedConfigPrioritySystemUserEnv` 等优先级测试通过。
- 门槛 6（全量测试 + golden）：
	- `go test ./...` 通过。
	- `testdata/golden` 已包含新增用例：`success`、`invalid-args`、`not-found-404`、`server-5xx`、`timeout`、`cli-not-implemented`。
- 门槛 7（search hit 默认值与降级）：
	- `internal/client/http`：`TestSearchIncludesSkillAndMemoryHitsWhenEnabled` 与 `TestSearchHitFailureDoesNotBreakMainKnowledgeResult` 通过。
	- `internal/cli`：`TestRunSearchEnableHitReturnsKnowledgeAndMemoryWhenSkillFails` 通过。

## 7. 关联文档

- `docs/manual/go-cli-user-guide.md`
- `backlog/bible-cli-go-rewrite-alignment-checklist-zh.md`
- `backlog/bible-cli-go-full-rewrite-plan-zh.md`
