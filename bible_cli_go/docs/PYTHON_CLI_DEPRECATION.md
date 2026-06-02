# Python CLI 废弃与 Go CLI 迁移记录

本文记录 `bible_cli`（Python CLI）废弃为 `bible_cli_DEPRECATED` 的完整操作过程、影响范围及后续说明。

**操作日期：** 2026-05-26

---

## 1. 背景

`bibleV` 目录下原有两个 CLI 实现并存：

| 目录 | 语言 | 状态 |
|---|---|---|
| `bible_cli/` | Python | **已废弃** → 重命名为 `bible_cli_DEPRECATED/` |
| `bible_cli_go/` | Go | **当前唯一有效实现** |

根据 `backlog/bible-cli-go-full-rewrite-plan-zh.md` Phase 4 决策：

> Python CLI 已废止，不再作为回滚通道；仅保留历史归档证据用于审计与追溯。

Go CLI 已完成契约冻结、命令全量实现、golden 对拍及 CI 接入，正式成为唯一维护入口。

---

## 2. 本次操作清单

### 2.1 目录重命名

```
bibleV/bible_cli/  →  bibleV/bible_cli_DEPRECATED/
```

目录内容（Python 源码）**原样保留**，作为历史审计证据，不再运行或维护。

### 2.2 设计文档更新

**`backlog/bible-cli-go-full-rewrite-plan-zh.md`**

- overview 及正文中 `` `bible_cli` ``（Python 包）→ `` `bible_cli_DEPRECATED` ``，并加注"现已废弃，由 `bible_cli_go` 取代"

**`docs/designs/server_part/v3/10_Import_Search流程_skill_详细设计.md`**

该 v3 设计文档中引用了 Python CLI 的实现文件路径，已统一更新为 Go 实现路径：

| 原引用 | 更新后 |
|---|---|
| `` `bible-cli/commands/skills.py` ``（表格） | `` `bible_cli_go/internal/commands/skills.go` `` |
| Mermaid 图 participant `bible-cli/commands/skills.py<br/>SkillCommands`（×2） | `bible_cli_go/internal/commands/skills.go<br/>SkillCommands` |

> 注：v3 文档中 `bible-cli ls-skills`、`bible-cli search-skills`、`bible-cli download-skill` 等 **CLI 命令调用语法保持不变**——`bible-cli` 是二进制名称，Go 版本 (`bible_cli_go/cmd/bible-cli`) 维持相同的命令接口。

### 2.3 Python 测试文件删除

以下 3 个测试文件专门测试已废弃的 Python CLI，其 import 路径在重命名后已断链，所有覆盖场景在 Go 测试体系中均已有对应覆盖（部分行为已升级），故直接删除：

| 删除文件 | 主要测试内容 | Go 中的对应覆盖 |
|---|---|---|
| `tests/test_bible_cli_config.py` | 配置默认值、`BIBLE_CLI_*` 环境变量覆盖 | `config_test.go`、`loader_test.go` |
| `tests/test_bible_cli_phase1.py` | 命令树结构、health/system/knowledge 命令调用、`CLI_NOT_IMPLEMENTED` 退出码 | `run_test.go`（`TestRunHelpWithoutArgs`、`TestRunHealthSuccess`、`TestRunSkillsUnknownActionNotImplemented` 等） |
| `tests/test_bible_cli_error_mapping.py` | 错误码映射、HTTP 响应 unwrap、health/info fallback、501 处理 | `client_test.go`（`TestErrorEnvelopeMapsToCLIError`、`TestErrorEnvelopeFor501ForcesSEVNotImplemented`、`TestStatusFallbackToHealthEndpoint` 等） |

**行为升级说明（Python → Go 的有意变更）：**

- 501 响应错误码：`NOT_IMPLEMENTED` → `SEV_NOT_IMPLEMENTED`（见 CLI 契约 `docs/manual/cli-contract-v1.md`）
- 业务错误输出位置：Python 版默认写 `stderr` → Go 版默认写 `stdout` JSON（`BIBLE_CLI_LEGACY_STDERR=1` 可开启兼容模式）
- `CLI_NOT_IMPLEMENTED` 退出码 `3` 语义保持不变

### 2.4 `pyproject.toml` 更新

```toml
# bible_cli (Python CLI) 已废弃，入口点已移除。
# Go CLI 实现位于 bible_cli_go/，使用 `go build ./cmd/bible-cli` 构建。
# [project.scripts]
# bs = "bible_cli_DEPRECATED.python_cli:main"
# biblesearch = "bible_cli_DEPRECATED.python_cli:main"
```

`tool.setuptools.packages.find.include` 由 `bible_cli*` 改为 `bible_cli_DEPRECATED*`。

### 2.5 `scripts/compare_python_go_cli.sh` 归档

该脚本原用于 Python/Go 对拍（Phase 0 迁移证据）。Python 侧已废弃，脚本已更新为：
- 注释掉 `PY_CMD`
- 执行时输出归档提示并立即退出
- 如需 Go CLI 契约回归，改用 `cd bible_cli_go && go test ./...`

---

## 3. 当前有效的测试入口

```bash
cd /var/fpwork/w77wang/BiBLE/rrmBIBLE/bibleV/bible_cli_go

# 单元测试 + 集成测试
go test ./...

# 静态检查
go vet ./...

# Contract golden 对拍（testdata/golden/）
go test ./internal/cli/... -run TestRunGoldenScenarios -v
```

---

## 4. 未处理项（bible-atlas 目录）

`/var/fpwork/w77wang/BiBLE/rrmBIBLE/bible-atlas/` 是兄弟项目目录，结构与 `bibleV` 相同，同样包含 `bible_cli/`（Python）和 `bible_cli_go/`（Go），尚未做同步处理。

涉及文件：

| 类别 | 文件 | 建议操作 |
|---|---|---|
| Python CLI 源码 | `bible-atlas/bible_cli/`（18 处内部 import） | 按需重命名为 `bible_cli_DEPRECATED/` |
| 设计文档 | `bible-atlas/backlog/bible-cli-go-full-rewrite-plan-zh.md` | 同步 `bibleV` 已做的修改 |
| Python 测试 | `bible-atlas/tests/test_bible_cli_*.py`（3 个文件） | 按需删除（Go 测试已覆盖） |
| 包配置 | `bible-atlas/pyproject.toml` | 同步注释掉 Python 入口点 |
| 生成文件 | `bible-atlas/bible_atlas.egg-info/entry_points.txt` | 重新生成或手动更新 |
| 对拍脚本 | `bible-atlas/scripts/compare_python_go_cli.sh` | 同步归档处理 |

---

## 5. 相关文档

- CLI 契约（冻结）：`docs/manual/cli-contract-v1.md`
- Go CLI 用户手册：`docs/manual/go-cli-user-guide.md`
- 性能基线：`docs/manual/go-cli-performance-baseline.md`
- 迁移计划全文：`backlog/bible-cli-go-full-rewrite-plan-zh.md`
- 现状与路线图：`bible_cli_go/docs/STATUS_AND_ROADMAP.md`
