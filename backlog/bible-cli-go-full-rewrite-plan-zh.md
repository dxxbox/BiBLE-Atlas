---
name: bible-cli Go全量重写实施计划
overview: 面向 VSCode/Cursor 插件调用场景，规划以 Go 对现有 `bible_cli` 做完整重写，覆盖架构设计、功能对齐、性能目标、跨平台发布与交叉编译流程。
---

# Bible-CLI Go全量重写实施计划（中文）

## 1. 决策说明

当前决策从“Rust 主 CLI 二进制化”切换为“Go 全量重写当前 `bible_cli`”。

目标是一次性形成 Go 主实现，并在功能、协议、错误码、可观测性与发布链路上达到或超过 Python 现状。

## 1.1 关联文档与优先级

本计划文件与设计文档、可执行规格文档的职责分工如下：

1. `docs/designs/client_part/01-bible-vscode-extension-design.md`：架构意图与职责边界（Why）。
2. `docs/designs/client_part/02-bible-vscode-extension-spec.md`：接口与实现细则（How）。
3. `backlog/bible-cli-go-full-rewrite-plan-zh.md`（本文）：迁移阶段、当前状态、验收口径（When/Status）。

口径冲突处理顺序：

1. `docs/manual/cli-contract-v1.md`（冻结契约）
2. `docs/designs/client_part/02-bible-vscode-extension-spec.md`（可执行规格）
3. `docs/designs/client_part/01-bible-vscode-extension-design.md`（架构说明）
4. 本文中的阶段进度标注用于说明 "当前是否完成"，不覆盖冻结契约本身。

## 2. 核心目标

1. 完整实现当前 CLI Contract 目标能力，不依赖 Python CLI 持续存在。
2. 对 VSCode/Cursor 插件保持调用协议兼容，减少插件改造。
3. 优化冷启动与 P95 响应时间。
4. 提供稳定的多平台二进制发布与交叉编译能力。
5. 形成可持续迭代的 Go 工程结构与测试体系。

## 2.1 当前实现对齐快照（2026-04-23）

已完成（与计划对齐）：

1. 输出协议已统一为 `ok/data/error`，失败默认走 `stdout` JSON。
2. 兼容开关 `BIBLE_CLI_LEGACY_STDERR=1` 已落地。
3. 错误码关键收敛已完成：`INVALID_ARGS`、`SEV_NOT_IMPLEMENTED`、`TIMEOUT`。
4. 配置加载已实现 `env > user > system > default`，并保留 `BIBLE_ATLAS_*` 回退。
5. golden 场景已补齐（success / invalid args / 404 / 5xx / timeout / cli not implemented）。
6. CI 已接入 `go vet`、可选 `staticcheck`、并增加 `windows-amd64` 构建。

未完成（后续阶段）：

1. `memory/skills` 仍为命令占位（`CLI_NOT_IMPLEMENTED`）。
2. 显式 CLI flags 优先级层（如 `--base-url`、`--timeout`）尚未接入。
3. CI 构建矩阵尚未覆盖 `linux-arm64` 与 `darwin-amd64`。
4. Extension 侧 `runCli` 分支与 `SEV_NOT_IMPLEMENTED` 分支测试未在本仓 Go 子目录内闭环。
5. 性能基线已建立（`docs/manual/go-cli-performance-baseline-2026-04-23.md`），回归门禁（Phase 3/15）尚未建立。

## 3. 范围边界

### 3.1 In Scope

1. CLI 参数解析与命令树。
2. 配置加载优先级（显式参数、环境变量、用户目录、系统目录）。
3. HTTP 客户端、超时重试、响应解包、错误映射。
4. `health/system/knowledge/memory/skills` 等当前已定义命令集。
5. 统一 JSON 输出协议、退出码、日志与 trace 字段。
6. 跨平台构建、打包、校验与发布流水线。

### 3.2 Out of Scope

1. 服务端 API 协议变更。
2. 插件 UI 流程重构。
3. 后端搜索算法和业务能力扩展。

## 4. 总体架构（Go）

```text
VSCode/Cursor Extension
        |
        v
   bible-cli-go (single binary)
   |- cmd/bible-cli            # 入口
   |- internal/cli             # 参数解析与命令路由
   |- internal/config          # 配置解析与优先级
   |- internal/client/http     # API 调用
   |- internal/commands        # 子命令实现
   |- internal/protocol        # 输出结构/错误模型
   |- internal/telemetry       # 日志/trace
```

## 5. 代码目录规划（As-Is / To-Be）

### 5.1 当前目录（As-Is）

```text
bible_cli_go/
  go.mod
  cmd/
    bible-cli/
      main.go
  internal/
    cli/
      run.go
      run_test.go
    client/
      http/
        client.go
        client_test.go
    commands/
      handlers.go
    config/
      config.go
      config_test.go
      loader.go
      loader_test.go
      model.go
    protocol/
      error.go
      output.go
  testdata/
    golden/
```

### 5.2 目标目录（To-Be）

```text
bible_cli_go/
  go.mod
  cmd/
    bible-cli/
      main.go
  internal/
    cli/
      root.go
      flags.go
      route.go
    commands/
      health.go
      system.go
      knowledge.go
      memory.go
      skills.go
    client/
      http/
        client.go
        response.go
        retry.go
        errors.go
    config/
      loader.go
      sources.go
      model.go
    protocol/
      output.go
      exit_codes.go
      schema.go
    telemetry/
      logger.go
      trace.go
  pkg/
    version/
      version.go
  testdata/
    golden/
```

说明：
1. 命令实现放 `internal/commands`，避免外部依赖耦合。
2. 协议模型和退出码集中在 `internal/protocol`，保证一致性。
3. `testdata/golden` 存放对拍样例，供 Python/Go 行为比对。

## 6. 迁移策略（全量重写但分阶段验证）

虽然最终目标是 Go 全量替换，但实施上采用“分阶段对齐 + 一次切换默认入口”。

### Phase 0：契约冻结与基线采集（2周）

1. 冻结 CLI Contract v1：命令、参数、输出、错误码、退出码。
2. 从 Python 提取 Golden 样例（成功、失败、超时、权限等）。
3. 采集性能基线（冷启动、P50/P95、内存峰值）。

交付：
1. `docs/manual/cli-contract-v1.md`。
2. Golden 样例集与校验脚本。
3. 基线报告。

当前状态（2026-04-23）：已完成

1. 已完成：`cli-contract-v1.md` 已落地，且含验收记录。
2. 已完成：golden 样例与对拍脚本已落地（`testdata/golden`、`scripts/compare_python_go_cli.sh`）。
3. 已完成：性能基线报告已固化（`docs/manual/go-cli-performance-baseline-2026-04-23.md`）。

### Phase 1：Go 框架与基础命令（3-4周）

1. 完成 CLI 骨架、配置链路、HTTP 客户端基础层。
2. 落地 `health`、`system status/info`。
3. 建立输出协议和错误码统一处理。
4. 建立单元测试与最小集成测试。

交付：
1. 可执行的 `bible-cli-go`。
2. 基础命令与 Go Contract 回归通过。

当前状态（2026-04-23）：部分完成（Go CLI 侧已基本完成）

1. 已完成：CLI 骨架、配置链路、HTTP 客户端基础层已落地。
2. 已完成：`health`、`system status/info` 已可用。
3. 已完成：输出协议与错误码统一处理已落地（含 `BIBLE_CLI_LEGACY_STDERR=1` 兼容开关）。
4. 已完成：单元测试与最小集成形态（基于 `httptest`）已覆盖核心路径并通过。
5. 已完成：可执行入口 `cmd/bible-cli/main.go` 已具备。
6. 已完成：CI 已固定执行 Go Contract 回归并归档结果（见 `.github/workflows/_go_cli.yml` 中 `Run contract regression` 与 `Upload contract regression reports`）。

### Phase 2：核心命令全量实现（4-6周）

1. 实现 `knowledge` 命令全链路（list/search 等）。
2. 实现 `memory/skills` 与已有 Python 命令等价功能。
3. 完成参数兼容和错误语义对齐。
4. 扩展集成测试覆盖高频命令。

交付：
1. 命令覆盖 >= 90%。
2. Golden 对拍通过率 >= 99%。

### Phase 3：性能优化与稳定性治理（2-3周）

1. 连接复用、超时重试、并发请求优化。
2. 大请求响应与 JSON 序列化性能优化。
3. 增加压测和故障注入（超时、5xx、网络抖动）。

交付：
1. 冷启动与 P95 达到目标阈值。
2. 稳定性报告（错误率/超时率）。

### Phase 4：发布与切换（2周）

1. 打通多平台构建与交叉编译。
2. 插件切换默认调用到 Go 二进制。
3. Python CLI 已废止，不再作为回滚通道；仅保留历史归档证据用于审计与追溯。
4. 观察期内持续验证 Go Contract 回归与线上稳定性，归档发布证据。

交付：
1. Go 成为默认实现。
2. 回滚策略验证通过。

## 7. 命令兼容清单（必须逐项验收）

1. 命令名与子命令结构一致。
2. 参数名、默认值、可选项行为一致。
3. 成功输出 JSON 字段结构一致。
4. 错误输出前缀与错误码语义一致。
5. 退出码一致（至少保证插件依赖的退出码集合一致）。

## 8. 测试计划

### 8.1 单元测试

1. 参数解析与路由。
2. 配置优先级合并。
3. HTTP 响应解包与错误映射。
4. 超时与重试策略。

### 8.2 Contract 回归测试（关键）

1. 基于 `cli-contract-v1.md` 与 `testdata/golden` 执行 Go CLI Contract 用例（golden input/output）。
2. 比较退出码、stdout JSON、stderr（若启用兼容模式）关键信息。
3. 差异自动报告并阻断 CI。
4. Python/Go 对拍仅作为历史归档证据，不再作为持续门禁。

### 8.3 集成测试

1. 对 mock API 进行端到端测试。
2. 覆盖成功、失败、超时、异常响应格式。

### 8.4 性能回归

1. 冷启动 30 次采样。
2. 高频命令 100 次采样统计 P50/P95。
3. 同步记录 CPU/内存峰值。

## 9. CI/CD 与交叉编译

### 9.1 构建矩阵

目标矩阵（Target）：

1. `linux-amd64`
2. `linux-arm64`
3. `darwin-amd64`
4. `darwin-arm64`
5. `windows-amd64`

当前已落地（As-Is）：

1. `linux-amd64`
2. `darwin-arm64`
3. `windows-amd64`

待补齐：

1. `linux-arm64`
2. `darwin-amd64`

### 9.2 Pipeline 阶段

1. `lint`: `gofmt -w` 校验、`go vet`、`staticcheck`。
2. `test`: 单元 + 对拍 + 集成。
3. `build`: 多平台构建。
4. `release`: 打包、sha256、发布说明。

当前状态：

1. `go vet`：已接入。
2. `staticcheck`：已接入“环境可用时执行”的非阻断模式。
3. `gofmt` 校验、release 打包与 `sha256`：待补齐。

### 9.3 产物规范

1. 二进制命名统一：`bible-cli-go_<os>_<arch>`。
2. 每个产物附带 `sha256sum` 文件。
3. 发布附命令兼容变更说明。

## 10. 验收指标（建议）

1. 命令兼容通过率：>= 99%。
2. 冷启动较历史归档基线下降：>= 30%。
3. 核心命令 P95 下降：>= 20%。
4. 插件调用失败率：不高于历史归档基线。
5. 多平台构建成功率：连续 3 个版本稳定。

## 11. 风险与对策

1. 行为差异风险：以 Go Contract golden 回归为准绳，CI 强约束。
2. Windows 参数与编码差异：提早加入平台特化测试。
3. 重写周期过长：按命令域拆里程碑，阶段可独立上线。
4. 发布链路复杂：先保证 linux + macOS，再扩 windows。

## 12. 首两周启动清单

1. ~~新建 `bible_cli_go/` 工程骨架与最小 `main.go`。~~
2. ~~输出 `cli-contract-v1.md` 草案并沉淀 Golden 样例。~~
3. ~~实现 `health/system` 命令与基础 HTTP client。~~
4. ~~建立 Python/Go 对拍脚本并接入 CI（历史迁移证据，非持续门禁）。~~
5. ~~打通 `linux-amd64` 与 `darwin-arm64` 构建。~~
6. ~~补充 `windows-amd64` 构建与 `go vet`/`staticcheck` 最小门禁。~~

## 13. 输出协议改造计划（对齐 `02` 规格）

### 13.1 目标协议（Target State）

1. 所有命令统一输出到 `stdout` 单行 JSON：
  - 成功：`{"ok":true,"data":...}`
  - 失败：`{"ok":false,"error":{"code":"...","message":"..."}}`
2. 退出码保持现有语义：`0` 成功、`1` 通用失败、`3` 已声明未实现。
3. `stderr` 默认不再承载业务错误正文，仅保留极端进程级故障信息（如 panic/崩溃场景）。

### 13.2 增量改造步骤（Implementation Plan）

1. ~~`internal/protocol` 新增统一响应模型：`Response{OK,Data,Error}` 与 JSON 输出函数。~~
2. ~~将当前 `CLIError` 适配为结构化 `error.code/error.message`，保留已有 `ExitCode`，并按错误码契约做兼容映射。~~
3. ~~`cli.Run` 统一从单出口写 `stdout` JSON，不再默认走 `PrintCLIError(stderr, ...)`。~~
4. ~~为迁移窗口保留可选兼容开关（建议）：`BIBLE_CLI_LEGACY_STDERR=1`。~~
  - 开启时：同时输出历史 `Error[CODE]: message` 到 `stderr`，便于旧调用方平滑过渡。
  - 关闭时：仅输出 `ok/error` JSON（默认新行为）。
5. ~~更新 `go-cli-user-guide.md` 的输出章节，明确默认行为与兼容开关。~~
6. 同步更新 VSCode Extension `runCli` 解析逻辑，移除对“非零退出码但 stdout 可能为空”的历史分支依赖。
7. 在 VSCode Extension/调用方错误处理分支中显式接收并处理 `SEV_NOT_IMPLEMENTED`。

当前状态：

1. Go CLI 侧 1-5 已完成。
2. Extension/调用方侧 6-7 待在对应仓或目录推进。

### 13.3 验收清单（Acceptance）

1. `health/system/knowledge` 成功路径返回 `ok=true` 的单行 JSON。
2. 参数错误、HTTP 错误、未实现命令均返回 `ok=false` 的单行 JSON。
3. 退出码与错误类别匹配：未实现命令必须保持 `exit=3`。
4. golden 用例覆盖：成功、参数错误、404、5xx、超时、未实现命令。

当前状态（Go CLI 侧）：已满足。

### 13.4 错误码契约决议（已冻结）

1. 参数错误统一对外使用 `INVALID_ARGS`。
2. 服务端错误码保留细分，不引入单一 `SERVER_ERROR` 聚合码。
3. 超时码采用兼容映射：
  - 对外 Contract 主码使用 `TIMEOUT`。
  - 内部与兼容层保留 `DEADLINE_EXCEEDED`。
4. HTTP 501 错误码统一为 `SEV_NOT_IMPLEMENTED`，不再使用 `NOT_IMPLEMENTED`。
5. `SEV_NOT_IMPLEMENTED`（HTTP 501）与 `CLI_NOT_IMPLEMENTED`（命令占位未实现，退出码 `3`）必须长期并存并显式区分。

### 13.5 错误码映射规范（实施约束）

1. `INVALID_ARGUMENT` -> `INVALID_ARGS`（输出层兼容映射）。
2. `TIMEOUT` <-> `DEADLINE_EXCEEDED`（双向兼容映射）。
3. HTTP 501 -> `SEV_NOT_IMPLEMENTED`（强制映射）。
4. 禁止将 `CLI_NOT_IMPLEMENTED` 映射到 HTTP 语义层错误码。

### 13.6 错误码验收补充（测试）

1. 参数错误 golden 断言必须为 `INVALID_ARGS`。
2. HTTP 501 golden 断言必须为 `SEV_NOT_IMPLEMENTED`。
3. 未实现命令 golden 断言必须为 `CLI_NOT_IMPLEMENTED` 且 `exit=3`。
4. 超时场景 golden 需覆盖 `TIMEOUT` 与 `DEADLINE_EXCEEDED` 兼容行为。
5. Extension/调用方测试需覆盖 `SEV_NOT_IMPLEMENTED` 分支（如显示“服务端接口未实现/稍后重试”的可读提示）。

## 14. 配置来源策略收敛（对齐 `02` 与当前计划）

### 14.1 差异说明

1. `02` 当前写法偏“配置文件中心”（`~/.bible/config.json`）。
2. 本重写计划是“多来源优先级模型”（显式参数/环境变量/用户目录/系统目录）。
3. 当前已实现 `env > user > system > default` 合并；显式 CLI flags 层仍待接入。

### 14.2 最终优先级（建议冻结为 Contract）

1. 显式 CLI 参数（如 `--base-url`、`--timeout`、`--trust-env`）。
2. 环境变量：`BIBLE_CLI_*` 优先，`BIBLE_ATLAS_*` 作为回退兼容。
3. 用户配置：`~/.bible/config.json`。
4. 系统配置：`/etc/bible/config.json`（Windows 对应系统级路径）。
5. 内置默认值（仅兜底）。

### 14.3 增量落地步骤

1. ~~先引入 `internal/config/loader.go`，统一聚合四层来源。~~
2. ~~定义 `ConfigSource` 与 merge 规则，输出最终 `ResolvedConfig`。~~
3. ~~在 `go-cli-user-guide.md` 补齐优先级矩阵与冲突示例。~~
4. 增加配置测试：
  - 同键多来源冲突
  - 非法值回退
  - 缺失配置的错误提示

当前状态：

1. 1-3 已完成。
2. 配置测试中“同键冲突/非法值回退”已覆盖；“缺失配置错误提示”可按产品决策选择继续保持默认值兜底或改为显式报错。

## 15. 性能回归与发布级指标校验闭环（Go-Only）

> Python CLI 将在正式开发前废止，性能与回归基线统一以 Go CLI Contract 为准。

### 15.1 指标层级

1. 启动性能：`cold_start_ms`（进程启动到首字节输出）。
2. 命令延迟：`latency_ms`（P50/P95/P99，按命令维度）。
3. 资源开销：`peak_rss_mb`、`cpu_user_ms`。
4. 稳定性：`error_rate`、`timeout_rate`、`retry_success_rate`。
5. 发布质量：跨平台构建成功率、签名/校验通过率、安装与 smoke 成功率。

### 15.2 回归场景矩阵

1. 快路径：`health`、`system status`。
2. 常规路径：`knowledge list/search`（空查询、短查询、长查询）。
3. 异常路径：4xx、5xx、超时、畸形 JSON。
4. 占位命令路径：`CLI_NOT_IMPLEMENTED`（退出码与错误 JSON）。
5. 跨平台路径：Linux/macOS/Windows 同一用例集。

### 15.3 校验机制

1. `perf-baseline.json`：保存当前稳定版本的基线指标。
2. `perf-regression-check`：PR 中自动对比基线，超阈值失败。
3. 阈值建议：
  - `cold_start_ms` 回退 > 15% 阻断。
  - 核心命令 `P95` 回退 > 20% 阻断。
  - `error_rate` 超过基线 + 0.5% 阻断。
4. 发布前必须执行：
  - 全量 contract tests
  - 性能回归套件
  - 多平台 smoke（下载、执行、`--help`、核心命令）

### 15.4 CI/CD 闭环

1. PR 阶段：`lint -> unit -> integration -> contract -> perf-smoke`。
2. Release Candidate：`build-matrix -> full-perf -> artifact-sign -> smoke-install`。
3. 正式发布：附带 `metrics-summary.md`、`compatibility-report.md`、`sha256`。
4. 发布后观察：72 小时内跟踪失败率、超时率、平均延迟，超阈值触发回滚预案。

---

## 附录 A：建议 EPIC 拆分

1. `EPIC-GO-1` CLI 契约冻结与 Golden 基线。
2. `EPIC-GO-2` Go 工程骨架与基础命令。
3. `EPIC-GO-3` 命令域全量迁移与兼容收敛。
4. `EPIC-GO-4` 性能优化与稳定性治理。
5. `EPIC-GO-5` 跨平台发布、切换与 Python 退役。
