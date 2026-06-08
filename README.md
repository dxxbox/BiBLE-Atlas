# BiBLE Atlas

BiBLE Atlas 是一个 **Agent-native 上下文管理数据库**，支持语义检索与渐进式内容加载。它帮助 AI Agent 高效地建立领域知识体系、维护会话记忆，并在与通用 LLM 协作时提供精准的上下文支撑。

**文档导航：** [环境准备](#环境准备) · [构建与发布](#构建与发布) · [代码质量 & Lint](#代码质量--lint) · [配置说明](#配置说明) · [提交规范](#提交规范) · [AI 协作指南](#ai-协作指南)

## 核心特性

- **多域知识管理** — 支持结构化知识库（Knowledge Base）、可复用技能包（Skill）和会话记忆（Memory）三大知识域
- **混合检索引擎** — 关键词匹配 + 向量语义检索 + Rerank 重排序，支持多种向量模型（BGE / E5 / MiniLM 等）
- **渐进式内容加载** — Rapid 模式（快速）与 Thinking 模式（深度推理）两种检索策略
- **灵活的存储后端** — 数据库支持 OpenSearch / Elasticsearch / PostgreSQL；文件系统支持 Local / MinIO / S3
- **异步任务处理** — 基于 Celery + Redis 的异步导入与批量处理
- **Skill 生态** — 标准化 `.skill` 包格式，支持导入、索引、搜索与调用
- **多客户端** — 提供 Go CLI、VSCode 扩展和 OpenClaw 插件三种客户端接入方式

## 架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                          客户端层                                     │
│   ┌──────────────┐  ┌──────────────────┐  ┌──────────────────────┐ │
│   │   Go CLI     │  │ VSCode Extension │  │  OpenClaw Plugin     │ │
│   └──────┬───────┘  └────────┬─────────┘  └──────────┬───────────┘ │
└──────────┼───────────────────┼────────────────────────┼─────────────┘
           │                   │                        │
           ▼                   ▼                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    BiBLE Atlas Server (FastAPI)                      │
│                                                                     │
│   ┌─────────┐  ┌─────────┐  ┌──────────┐  ┌──────────────────┐   │
│   │ Search  │  │ Import  │  │Knowledge │  │     System       │   │
│   │  API    │  │  API    │  │   API    │  │      API         │   │
│   └────┬────┘  └────┬────┘  └────┬─────┘  └────────┬─────────┘   │
│        │             │            │                  │             │
│   ┌────┴─────────────┴────────────┴──────────────────┴─────────┐  │
│   │                      Features Layer                          │  │
│   │  ┌──────────┐  ┌──────────────┐  ┌──────────────────────┐   │  │
│   │  │ Search   │  │ Import       │  │ Async Task (Celery)  │   │  │
│   │  │ Engine   │  │ Pipeline     │  │                      │   │  │
│   │  └────┬─────┘  └──────┬───────┘  └──────────┬───────────┘   │  │
│   └───────┼───────────────┼──────────────────────┼───────────────┘  │
│           │              │                    │                    │
│   ┌───────┴──────────────┴────────────────────┴────────────────┐  │
│   │                  Infrastructure Layer                        │  │
│   │  ┌───────────┐  ┌─────────────┐  ┌───────────────────┐    │  │
│   │  │ Database  │  │ File System │  │  Vector Engine     │    │  │
│   │  │ (OS/ES/PG)│  │(Local/MinIO)│  │ (sentence-trans.)  │    │  │
│   │  └───────────┘  └─────────────┘  └───────────────────┘    │  │
│   └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
           │                   │                    │
           ▼                   ▼                    ▼
    ┌─────────────┐    ┌─────────────┐     ┌─────────────┐
    │ OpenSearch  │    │    Redis    │     │  HuggingFace │
    │  Cluster   │    │   (Broker)  │     │    Models    │
    └─────────────┘    └─────────────┘     └─────────────┘
```

## 目录结构

```
bibleV/
├── bible/                    # Python 服务端（核心）
│   ├── api/                  #   REST API 层（FastAPI 路由）
│   │   ├── search/           #     检索 API（memory / knowledge 等）
│   │   ├── import/           #     导入 API（memory 等）
│   │   ├── knowledge.py      #     知识库路由聚合
│   │   ├── system.py         #     系统/健康检查等
│   │   └── deps.py           #     依赖注入
│   ├── features/             #   业务逻辑层
│   │   ├── search/           #     检索引擎（关键词 + 向量 + 混合）
│   │   ├── import/           #     导入流水线
│   │   └── async_task/       #     Celery 异步任务
│   ├── infrastructure/       #   基础设施层
│   │   ├── database/         #     数据库抽象（OpenSearch/ES/PG）
│   │   ├── file_system/      #     文件系统抽象（Local/MinIO/S3）
│   │   └── vector/           #     向量模型管理与编码
│   ├── config/               #   配置加载与管理
│   ├── common/               #   公共工具（日志、版本、契约等）
│   └── main.py              #   应用入口
├── bible_cli_go/             # Go CLI 客户端
│   ├── cmd/bible-cli/        #   CLI 入口
│   ├── internal/             #   内部模块（命令/HTTP/格式化等）
│   └── build.sh             #   编译脚本
├── bible_vscode/             # VSCode 扩展
│   └── src/                  #   TypeScript 源码
├── bible-oc-plugin/          # OpenClaw 插件
│   ├── src/                  #   TypeScript 源码
│   └── tests/                #   测试
├── scripts/                  # 部署与运维脚本
│   ├── opensearch_deploy/    #   OpenSearch Docker 部署方案
│   ├── redis_celery_deploy/  #   Redis + Celery 部署方案
│   └── build_bible_cli_multi_platform.sh
├── tests/                    # Python 服务端测试
├── docs/                     # 设计文档
│   ├── designs/              #   架构与详细设计
│   └── manual/               #   用户手册
├── bible-atlas.yaml          # 服务端动态配置（热更新）
├── bible-atlas.conf          # 旧版配置（参考）
├── pyproject.toml            # Python 项目配置 & 工具链配置
└── build_all.sh              # 一键编译所有模块（说明见下文「构建与发布」）
```

## 环境准备

### 必需工具

| 工具 | 最低版本 | 用途 |
|------|---------|------|
| Python | 3.10+ | 服务端运行 |
| [uv](https://docs.astral.sh/uv/) | latest | Python 包管理 & 虚拟环境 |
| Go | 1.20+ | CLI 编译 |
| Node.js | 20+ | VSCode 扩展 & OpenClaw 插件 |
| npm | 9+ | JS 依赖管理 |
| Docker | 20+ | OpenSearch / Redis 部署 |

### 基础设施

| 服务 | 用途 | 部署指南 |
|------|------|---------|
| OpenSearch | 全文检索 + 向量索引 | `scripts/opensearch_deploy/` |
| Redis | Celery 消息队列 | `scripts/redis_celery_deploy/` |

### 快速开始

```bash
# 1. 克隆仓库并进入项目目录
cd bibleV

# 2. 安装 Python 依赖（含所有可选依赖）
uv sync --all-extras

# 3. 激活虚拟环境
source .venv/bin/activate

# 4. 部署 OpenSearch（参考 scripts/opensearch_deploy/README.md）
cd scripts/opensearch_deploy
./quickstart.sh          # 交互式向导

# 5. 部署 Redis + Celery（参考 scripts/redis_celery_deploy/README.md）
cd ../redis_celery_deploy
./quickstart.sh

# 6. 修改配置文件
cd ../..
# 编辑 bible-atlas.yaml，设置 OpenSearch / Redis 连接信息

# 7. 启动服务
uv run python -m bible.main
# 服务默认监听 http://127.0.0.1:5555

# 8.（按需）异步导入 / 后台任务依赖 Celery Worker
#    见 scripts/redis_celery_deploy/README.md 中 worker 启动说明
```

### 可选依赖

根据部署需求按需安装：

```bash
uv sync --extra vector   # 向量检索（sentence-transformers）
uv sync --extra minio    # MinIO 文件后端
uv sync --extra s3       # AWS S3 文件后端
uv sync --extra test     # 测试框架
uv sync --extra dev      # 开发工具（mypy, ruff）
uv sync --all-extras     # 全部安装
```

## 构建与发布

> 本节整合了原独立文档中的构建与发布说明，作为仓库内**唯一权威的构建/产物说明**。

### 模块与产物总览

| 模块 | 目录 | 技术栈 | 产物 |
|------|------|--------|------|
| 服务器端 | `bible/` | Python 3.10+ / FastAPI | `.tar.gz` + `.whl` |
| Go CLI | `bible_cli_go/` | Go 1.20+ | `bible` 二进制 |
| VSCode 扩展 | `bible_vscode/` | TypeScript / esbuild | `bible-vscode.vsix` |
| OpenClaw 插件 | `bible-oc-plugin/` | TypeScript / tsc | `release/bible-oc-plugin/`（由 `dist/` 复制并附带清单文件） |

### 构建环境要求（打 release 最低集）

| 工具 | 最低版本 | 用途 |
|------|---------|------|
| Python | 3.10+ | 服务器端 |
| [uv](https://docs.astral.sh/uv/) | latest | Python 包管理 & 构建 |
| Go | 1.20+ | CLI 编译 |
| Node.js | 20+ | VSCode 扩展 & OC 插件 |
| npm | 9+ | JS 依赖管理 |

完整运行与部署（含 Docker、OpenSearch、Redis）见上文「环境准备」。

### 一键编译

项目根目录执行 `build_all.sh`，将所有模块产物输出到 **`release/`**（该目录在 `.gitignore` 中，**不会提交**）。

```bash
./build_all.sh              # 完整流程：同步依赖、lint、构建、测试
./build_all.sh --skip-test  # 跳过各模块测试，其余仍执行
```

**脚本行为摘要（与当前 `build_all.sh` 一致）：**

0. **环境**：`uv sync --extra test --extra dev`（满足 CI/构建所需；若你本地开发需要向量、MinIO、S3 等，请先执行 `uv sync --all-extras` 再跑脚本，或按需安装可选 extra）。
1. **Python**：`ruff check bible/` → `mypy bible/` → `uv build --out-dir release/` →（可选）`pytest tests/ -x -q`。
2. **Go CLI**：`go vet` → `go build -o release/bible` →（可选）`go test`。
3. **VSCode**：`npm install` → `tsc --noEmit` → `npm run package` + `vsce package` 生成 `.vsix`。
4. **OpenClaw 插件**：`npm install` → `npm run typecheck` → `npm run build` → 复制 `dist/` 等到 `release/bible-oc-plugin/` →（可选）`npm run test`（vitest）。

**构建输出：**

- 每步完整日志在 **`release/logs/`**（便于 CI 或本地排错）。
- 成功跑完后会生成 **`release/BUILD_INFO.md`**（产物说明、安装示例、Git 与工具版本等）。

若某步失败，控制台会标出失败模块；请结合 **`release/logs/`** 下对应 `.log` 修复后重跑。

### 产物目录结构

```
release/
├── bible                         # Go CLI 二进制（当前平台）
├── bible-vscode.vsix             # VSCode 扩展安装包
├── bible-oc-plugin/              # OpenClaw 插件发布目录
│   ├── package.json
│   ├── openclaw.plugin.json      # 若存在则一并复制
│   └── *.js / *.d.ts             # 由 dist/ 复制
├── bible_atlas-<ver>.tar.gz      # Python sdist
├── bible_atlas-<ver>-py3-*.whl   # Python wheel
├── BUILD_INFO.md                 # 由 build_all.sh 自动生成
└── logs/                         # 各步骤构建日志
```

### 各模块单独编译

<details>
<summary><strong>Python 服务端</strong></summary>

```bash
uv sync --all-extras
uv run ruff check bible/
uv run mypy bible/
uv run pytest tests/ -x -q
uv build                    # 或: uv build --out-dir release/ 与一键脚本一致
```
</details>

<details>
<summary><strong>Go CLI</strong></summary>

```bash
cd bible_cli_go
./build.sh                # 一键编译（含 vet + test）

# 或手动
go vet ./...
go build -o target/bible ./cmd/bible-cli/
go test ./... -race -count=1
```

多平台交叉编译（在**仓库根目录**执行）：

```bash
# pwd 应为 bibleV 仓库根目录（若当前在 bible_cli_go/，先执行 cd ..）
./scripts/build_bible_cli_multi_platform.sh
```
</details>

<details>
<summary><strong>VSCode 扩展</strong></summary>

```bash
cd bible_vscode
npm install
npm run compile         # 开发编译
npm run package         # 生产编译
npm run vsix            # 打包 .vsix
```
</details>

<details>
<summary><strong>OpenClaw 插件</strong></summary>

```bash
cd bible-oc-plugin
npm install
npm run typecheck
npm run build
npm run test
```
</details>

## 代码质量 & Lint

项目通过 GitHub Actions 自动执行 lint 检查。推送代码前请在本地执行以下检查：

### Python（Ruff + mypy）

```bash
# 格式化
uv run ruff format path/to/changed_file.py

# 代码检查（含自动修复）
uv run ruff check --fix path/to/changed_file.py

# 类型检查
uv run mypy path/to/changed_file.py
```

**Ruff 规则配置**（见 `pyproject.toml`）：
- 行宽限制：100 字符
- 启用规则集：`E`(pycodestyle) / `W`(warnings) / `F`(pyflakes) / `I`(isort) / `C`(comprehensions) / `B`(bugbear)
- `target-version`: Python 3.9+

### Go

```bash
cd bible_cli_go
go vet ./...
go test ./... -race -count=1
```

### TypeScript（VSCode 扩展 & OC 插件）

```bash
# VSCode 扩展
cd bible_vscode && npx tsc --noEmit

# OpenClaw 插件
cd bible-oc-plugin && npm run typecheck
```

### CI 工作流

GitHub Actions 在 `push` 和 `pull_request` 时自动执行：

| 工作流 | 内容 |
|--------|------|
| `_lint.yml` | 对变更的 `.py` 文件执行 `ruff format --check`、`ruff check`、`mypy`（单文件 mypy 可能漏掉跨文件类型问题，本地建议仍对 `bible/` 全量跑一次） |
| `_test_lite.yml` | pytest（Python 3.10/3.11/3.12） |
| `_go_cli.yml` | Go vet + build + test |

## 配置说明

服务端配置文件为 `bible-atlas.yaml`，支持热更新（修改后无需重启）。主要配置节：

| 配置节 | 说明 |
|--------|------|
| `log` | 日志级别与输出目标 |
| `storage` | 工作空间数据目录 |
| `file_system` | 文件存储后端（local / minio / s3） |
| `database` | 数据库后端（opensearch / elasticsearch / postgres） |
| `celery` | 异步任务队列 broker 与 backend |
| `import_memory` | 导入任务配置（超时、保留策略等） |
| `import_skill` | Skill 导入任务配置（解析器目录、工作目录、超时、保留策略等） |
| `import_skill_upload` | Skill 上传限制（允许 `.skill` 及附件扩展名、大小和数量限制） |
| `search` | v4 检索 API 默认值与限制（`top_k`、允许的检索类型等） |
| `vector` | 向量模型列表与预加载设置 |
| `rerank` | 重排序模型配置 |
| `copilot_config` | AI 增强检索（可选） |

详细字段说明请参阅 `bible-atlas.yaml` 内的注释。

## 提交规范

### 提交前检查清单

1. **运行一键编译**（推荐与 CI 一致）：
   ```bash
   ./build_all.sh
   ```
2. **确认结果**：控制台应出现「所有模块编译 & 测试通过」；若有失败项，先查看 **`release/logs/`** 中对应日志并修复后重跑。
3. **Python 变更**（除全量 `ruff check bible/` 外，可按文件快速整理）：
   ```bash
   uv run ruff format path/to/changed_file.py
   uv run ruff check --fix path/to/changed_file.py
   uv run mypy path/to/changed_file.py
   ```
4. **核对产物（可选）**：`ls -lh release/`，并打开 **`release/BUILD_INFO.md`** 确认产物说明无误。
5. **提交**：勿将 `release/` 或其中的密钥、本地路径提交进仓库（该目录已被 `.gitignore` 忽略）。

### 分支策略

- `main` — 稳定分支，CI 全部通过方可合入
- `feature/**` — 功能开发分支

### Commit Message

遵循清晰、简洁的提交信息风格。每次提交应当：
- 标题行简短描述变更（不超过 72 字符）
- 正文（可选）解释 **为什么** 做这个变更
- 将不相关的变更拆分为独立的 commit

## AI 协作指南

本项目积极使用 AI 辅助开发。以下约定确保 AI Agent 高效且安全地参与协作：

### 架构原则

- **分层架构**：API → Features → Infrastructure，严禁跨层直接调用
- **依赖方向**：上层依赖下层，下层禁止引用上层模块
- **配置驱动**：所有可调参数通过 `bible-atlas.yaml` 管理，禁止硬编码

### AI 编码约束

1. **不修改基础设施层接口** — `infrastructure/` 下的公共接口变更需人工审批
2. **不自行添加新依赖** — 新增 Python/Go/Node 依赖前需人工确认
3. **不修改 CI 配置** — `.github/workflows/` 变更需人工审批
4. **不生成文档文件** — 除非明确要求，不主动创建 `.md` 文件
5. **不提交敏感信息** — 禁止提交 `.env`、API Key、密码等
6. **测试覆盖** — 新增功能必须附带对应的测试用例

### 代码风格

| 语言 | 风格要求 |
|------|---------|
| Python | Ruff 规则 + mypy 类型检查，行宽 100 |
| Go | `go vet` + `go test -race` |
| TypeScript | 严格模式 `tsc --noEmit` |

### 目录约定

- 新功能模块放在 `bible/features/` 下
- 新的存储/中间件适配放在 `bible/infrastructure/` 下
- API 路由放在 `bible/api/` 下
- 测试文件命名 `test_<module>.py`，放在 `tests/` 目录

### 维护注意事项

- Python CLI 已废弃（`bible_cli_DEPRECATED/`），仅保留归档用途，**不再维护**
- Go CLI 为唯一有效的 CLI 实现，所有 CLI 功能开发在 `bible_cli_go/` 进行
- 设计文档在 `docs/designs/` 下按版本和模块组织

## 相关文档

| 文档 | 说明 |
|------|------|
| [RELEASE.md](RELEASE.md) | 已合并至本 README「构建与发布」；保留文件仅作旧链接重定向 |
| [bible_cli_go/README.md](bible_cli_go/README.md) | Go CLI 完整文档 |
| [bible_vscode/README.md](bible_vscode/README.md) | VSCode 扩展文档 |
| [scripts/opensearch_deploy/README.md](scripts/opensearch_deploy/README.md) | OpenSearch 部署方案 |
| [scripts/redis_celery_deploy/README.md](scripts/redis_celery_deploy/README.md) | Redis + Celery 部署方案 |
| [docs/](docs/) | 架构设计与用户手册 |

## License

见 [LICENSE](LICENSE) 文件。
