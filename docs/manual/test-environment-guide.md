# BiBLE Atlas — Test Environment Setup & Cleanup Guide

面向系统测试工程师，覆盖 BiBLE Atlas 四大组件的测试环境搭建（从零开始）和测试完成后的清理操作。

---

## 目录

0. [懒人模式：一键脚本（推荐）](#0-懒人模式一键脚本推荐)
1. [组件概览](#1-组件概览)
2. [快速路径：Test Mode（无依赖，推荐首选）](#2-快速路径test-mode无依赖推荐首选)
3. [完整后端模式（生产级基础设施）](#3-完整后端模式生产级基础设施)
   - [3.1 部署 OpenSearch](#31-部署-opensearch)
   - [3.2 部署 Redis + Celery Worker](#32-部署-redis--celery-worker)
   - [3.3 部署 Bible Server](#33-部署-bible-server)
4. [Bible CLI Go（命令行）](#4-bible-cli-go命令行)
5. [Bible Hermes Plugin（Hermes 插件）](#5-bible-hermes-pluginhermes-插件)
6. [Bible OC Plugin（OpenClaw 插件）](#6-bible-oc-pluginopenclaw-插件)
7. [全组件联合测试](#7-全组件联合测试)
8. [环境清理](#8-环境清理)
9. [部署脚本速查](#9-部署脚本速查)
10. [故障排查速查表](#10-故障排查速查表)

---

## 0. 懒人模式：一键脚本（推荐）

`scripts/env-prepare.sh` 是本指南的终极武器——一条命令完成全部搭建或清理。

```bash
# 一键搭建（Test Mode + Go CLI + Hermes + OC 插件）
./scripts/env-prepare.sh setup

# 一键清理
./scripts/env-prepare.sh teardown --force

# 查看全貌
./scripts/env-prepare.sh status
```

**按需选择组件：**

```bash
./scripts/env-prepare.sh setup --full                    # 完整后端（含 Docker）
./scripts/env-prepare.sh setup cli                       # 只搭 Go CLI
./scripts/env-prepare.sh setup --full opensearch redis   # 只搭基础设施
./scripts/env-prepare.sh teardown hermes oc              # 只清理插件
./scripts/env-prepare.sh status --json                   # JSON 输出
```

**命令速查：**

| 命令 | 作用 |
|---|---|
| `setup` | 从零搭建测试环境 |
| `setup --full` | 完整后端（含 OpenSearch/Redis Docker 容器） |
| `setup <c1> <c2>` | 只搭建指定组件 |
| `teardown` | 清理测试环境（停止进程、删除本地构建产物，默认保留用户级配置/插件） |
| `teardown --full` | 完整清理（额外删除 Docker 容器和数据） |
| `status` | 查看所有组件状态（含 Server URL 和 /health） |

`teardown` 默认只停止服务并清理本地构建产物，不删除用户级配置、用户级插件安装或项目 `workspace/` 数据。需要彻底清理时显式增加：

```bash
./scripts/env-prepare.sh teardown --force --purge-workspace --purge-config --uninstall-plugins
```

完整后端模式下，如果是交互式终端且未使用 `--force`，脚本会询问：

- Docker Hub 镜像前缀/镜像站（可留空使用默认 Docker Hub）
- OpenSearch CPU 核数（默认会参考 Docker 可用 CPU）
- OpenSearch 内存 GB（2 核默认 6GB，其他默认 12GB）

非交互或自动化运行时，使用环境变量预先指定：

```bash
BIBLE_DOCKER_REGISTRY_PREFIX=docker.m.daocloud.io/ \
BIBLE_OPENSEARCH_CPU_CORES=2 \
BIBLE_OPENSEARCH_MEMORY_GB=6 \
./scripts/env-prepare.sh setup --full opensearch --force
```

脚本内部按正确顺序调用 [第 9 节](#9-部署脚本速查) 中的所有子脚本，处理端口冲突复用、健康检查等待、优雅降级（如 Hermes/OpenClaw 未安装则跳过对应组件）。

后续各节是每种搭建方式的详细分步说明，供需要了解内部原理或手动排障时参考。

---

## 1. 组件概览

| 组件 | 语言 | 角色 | 对外端口 / 接入方式 |
|---|---|---|---|
| Bible Server | Python (FastAPI) | HTTP API 服务端 | `http://localhost:5555` |
| Bible CLI Go | Go | 命令行客户端 | 通过 `BIBLE_CLI_BASE_URL` 连接服务端 |
| Bible Hermes Plugin | Python | Hermes Agent 插件 | 安装到 `~/.hermes/plugins/` |
| Bible OC Plugin | TypeScript | OpenClaw 插件 | 安装到 `~/.openclaw/extensions/` |

### 项目部署脚本总览

| 脚本目录 | 用途 | 包含 |
|---|---|---|
| `scripts/opensearch_deploy/` | OpenSearch 多实例部署管理 | `deploy.sh`、`quickstart.sh`、`docker-compose.template.yml` |
| `scripts/redis_celery_deploy/` | Redis + Celery Worker 部署管理 | `deploy.sh`、`quickstart.sh`、`redis.conf.template` |
| `scripts/server_deploy/` | Bible Server 进程管理 | `deploy.sh`、`quickstart.sh` |
| `bible-hermes-plugin/deploy.sh` | Hermes 插件一键部署 | 同步 + pip install + enable |
| `bible-oc-plugin/scripts/install-local.mjs` | OC 插件本地安装 | 写入 `~/.openclaw/openclaw.json` |

### 测试拓扑

```
┌──────────────────────────────────────────────────────────────┐
│                     Bible Server                             │
│  http://127.0.0.1:5555                                       │
│  (Test Mode / 生产模式)                                       │
├──────────────────────────────────────────────────────────────┤
│  生产模式依赖:                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  OpenSearch  │  │    Redis     │  │  Celery Worker   │   │
│  │  (数据存储)   │  │  (消息队列)   │  │  (异步任务)       │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
└──────┬──────────────┬──────────────┬─────────────────────────┘
       │              │              │
  ┌────▼────┐   ┌─────▼─────┐  ┌────▼─────────┐
  │ Go CLI  │   │  Hermes   │  │    OC Plugin │
  │ (终端)   │   │  Plugin   │  │              │
  └─────────┘   └───────────┘  └──────────────┘
```

---

## 2. 快速路径：Test Mode（无依赖，推荐首选）

Test Mode 不需要 OpenSearch、Redis、Celery 或向量模型，通过预定义 fixture 文件模拟 API 响应。**日常功能测试和插件联调推荐此模式。**

### 2.1 前置条件

| 依赖 | 说明 |
|---|---|
| Python 3.10+ | — |
| uv | Python 包管理器 |
| Docker（可选） | 仅生产模式需要，Test Mode 不需要 |

### 2.2 安装与启动

```bash
cd BiBLE-Atlas
uv sync --all-extras
```

```bash
# 基本启动（默认监听 127.0.0.1:5555）
uv run python -m bible.test_mode.server

# 指定端口
uv run python -m bible.test_mode.server --addr 127.0.0.1:5566

# 加载外部 fixture（自定义测试场景）
uv run python -m bible.test_mode.server \
  --addr 127.0.0.1:5555 \
  --fixture tests/fixtures/test_mode/custom.json
```

`--fixture` 可指向 JSON 文件或目录。目录下所有 `*.json` 文件按文件名顺序加载，同 ID fixture 覆盖内置项。

### 2.3 验证

```bash
# 健康检查 — 响应头含 X-Bible-Test-Mode: true
curl -i http://127.0.0.1:5555/health
# 预期: {"status":"ok","service":"bible-atlas-test-mode","mode":"server"}

# Search Memory（内置 fixture）
curl -X POST http://127.0.0.1:5555/api/search/memory \
  -H "Content-Type: application/json" \
  -d '{"query":"test","tag":"memory"}'

# Knowledge 列表
curl http://127.0.0.1:5555/api/control/docs/list
```

### 2.4 停止

```bash
# Ctrl+C 终止进程，无需额外清理
```

---

## 3. 完整后端模式（生产级基础设施）

端到端功能测试和性能测试需要完整的 OpenSearch + Redis + Celery Worker 后端栈。

### 前置总览

| 依赖 | 最低版本 | 部署方式 |
|---|---|---|
| Docker | — | 脚本自动管理容器 |
| Python | 3.10+ | uv 管理 |
| OpenSearch | 2.x | `scripts/opensearch_deploy/deploy.sh` |
| Redis | 6.x+ | `scripts/redis_celery_deploy/deploy.sh` |

三层部署顺序：**OpenSearch → Redis → Celery Worker/Server**。每层脚本均位于 `scripts/` 下，运行时不需 `cd` 到子目录，在项目根目录直接调用即可。

---

### 3.1 部署 OpenSearch

**脚本目录：** `scripts/opensearch_deploy/`

#### 3.1.1 交互式创建（新手推荐）

```bash
cd scripts/opensearch_deploy
./quickstart.sh
```

按提示选择配置方案 → 输入实例名 → 确认端口 → 创建并启动。

#### 3.1.2 命令行创建

```bash
cd scripts/opensearch_deploy

# 创建测试实例（小型配置：4核/12GB）
./deploy.sh create bibletest 9800 5699 4 12

# 启动
./deploy.sh start bibletest

# 等待服务就绪（约 30-60 秒）
sleep 30
```

> **端口约定**：`bible-atlas.yaml` 默认配置 `opensearch.hosts: ["localhost:9800"]`，因此实例 HTTP 端口必须为 `9800` 以匹配默认配置。若使用其他端口，需同步修改 `bible-atlas.yaml`。

#### 3.1.3 验证

```bash
curl -u opensearch-xo:MyStr0ng!Pass#2024 http://localhost:9800/

# 集群健康
curl -u opensearch-xo:MyStr0ng!Pass#2024 \
  http://localhost:9800/_cluster/health?pretty
```

#### 3.1.4 常用管理命令

```bash
./deploy.sh status bibletest          # 查看状态
./deploy.sh logs bibletest 50         # 最近 50 行日志
./deploy.sh list                      # 列出所有实例
./deploy.sh restart bibletest         # 重启
./deploy.sh stop bibletest            # 停止
./deploy.sh delete bibletest          # 完全删除（含数据）
./deploy.sh delete bibletest --keep-data  # 删除但保留数据
```

---

### 3.2 部署 Redis + Celery Worker

**脚本目录：** `scripts/redis_celery_deploy/`

该脚本不仅管理 Redis 容器，还管理 Celery Worker 进程（基于项目 `.venv`）。

#### 3.2.1 交互式创建（新手推荐）

```bash
cd scripts/redis_celery_deploy
./quickstart.sh
```

按提示选择内存方案 → 输入实例名和端口 → 创建 → 可选同时启动 Redis 和 Celery Worker。

#### 3.2.2 命令行创建

```bash
cd scripts/redis_celery_deploy

# 确认项目 venv 中的 celery 可用
ls ../../.venv/bin/celery

# 创建测试实例（轻量 512MB，端口 9880 以匹配默认配置）
./deploy.sh redis create bibletest 9880 512

# 启动 Redis
./deploy.sh redis start bibletest
```

> **端口约定**：`bible-atlas.yaml` 默认配置 `celery.broker_url: "redis://localhost:9880/0"`，因此 Redis 端口必须为 `9880`。若使用其他端口，需同步修改 `bible-atlas.yaml`。

#### 3.2.3 启动 Celery Worker

```bash
# 启动 Worker（并发数自动 = CPU 核心数）
./deploy.sh worker start bibletest

# 或指定并发数
./deploy.sh worker start bibletest --concurrency 4

# 或一键同时启动 Redis + Worker
./deploy.sh start-all bibletest
```

#### 3.2.4 验证

```bash
# Redis 连通性
redis-cli -p 9880 ping
# 预期: PONG

# Redis Web UI（Redis Commander）
# 浏览器打开 http://localhost:109880（端口 = Redis 端口 + 10000 自动推导）
# 默认账号密码: admin / admin

# Worker 状态
./deploy.sh worker status bibletest

# 全部状态总览
./deploy.sh status
```

#### 3.2.5 常用管理命令

```bash
# Redis
./deploy.sh redis status bibletest
./deploy.sh redis logs bibletest 50
./deploy.sh redis restart bibletest

# Worker
./deploy.sh worker restart bibletest --concurrency 4
./deploy.sh worker logs bibletest 100
./deploy.sh worker stop bibletest

# 一键操作
./deploy.sh stop-all bibletest      # 先停 Worker 再停 Redis
./deploy.sh start-all bibletest     # 先启 Redis 再启 Worker

# 清空 Redis 数据（危险操作）
./deploy.sh redis flush bibletest
```

#### 3.2.6 更新 bible-atlas.yaml

启动后查看推荐配置值并确认与配置文件一致：

```bash
./deploy.sh redis info bibletest
# 输出 Celery 配置:
#   broker_url:      redis://localhost:9880/0
#   result_backend:  redis://localhost:9880/1
```

`bible-atlas.yaml` 中对应配置：

```yaml
celery:
  broker_url: "redis://localhost:9880/0"
  result_backend: "redis://localhost:9880/1"
```

---

### 3.3 部署 Bible Server

**脚本目录：** `scripts/server_deploy/`

在 OpenSearch 和 Redis 均已就绪后，使用此脚本管理 Bible Server 和 Celery Worker 进程（Worker 在前一步已启动，这里负责 Server 主进程）。

#### 3.3.1 交互式启动（新手推荐）

```bash
cd scripts/server_deploy
./quickstart.sh
```

向导会：
1. 自动解析 `bible-atlas.yaml` 中的 OpenSearch / Redis 地址并检查连通性
2. 若不通，提示是否通过 opensearch_deploy / redis_celery_deploy 脚本自动启动
3. 选择 Celery Worker 并发数和日志级别
4. 调用 `deploy.sh start` 完成启动

#### 3.3.2 命令行启动

```bash
cd scripts/server_deploy

# 确保已安装 Python 依赖
cd ../..
uv sync --all-extras

# 启动（默认并发 = CPU 核心数，日志级别 = info）
cd scripts/server_deploy
./deploy.sh start

# 指定参数
./deploy.sh start --concurrency 4 --loglevel debug

# 指定配置文件路径
./deploy.sh start --config /path/to/bible-atlas.yaml
```

> **注意**：若 `bible-atlas.yaml` 中 `vector.preload_on_startup: true`，Celery Worker 启动时会加载所有向量模型（每个约 10-15 秒），`deploy.sh start` 会等待最多 120 秒。

#### 3.3.3 验证

```bash
./deploy.sh health      # 探活 /health
./deploy.sh status      # 查看 Server + Worker 进程状态
./deploy.sh logs        # 同时看两者最近 50 行日志
./deploy.sh logs server # 只看 Server 日志
./deploy.sh logs worker 100  # Worker 最近 100 行
```

#### 3.3.4 常用管理命令

```bash
./deploy.sh restart                     # 重启（先停 Worker 再停 Server，反序启动）
./deploy.sh restart --concurrency 8     # 重启并修改并发数
./deploy.sh stop                        # 停止（先 Worker 后 Server）
```

#### 3.3.5 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `BIBLE_PROJECT_ROOT` | 项目根目录 | 脚本向上两级 |
| `BIBLE_SERVER_HOST` | FastAPI 监听地址 | `0.0.0.0` |
| `BIBLE_SERVER_PORT` | FastAPI 监听端口 | `5555` |

---

## 4. Bible CLI Go（命令行）

#### 4.1 前置条件

| 依赖 | 最低版本 |
|---|---|
| Go | 1.25+ |

#### 4.2 构建

```bash
cd BiBLE-Atlas/bible_cli_go

# 开发态直接运行
go run ./cmd/bible-cli --help

# 编译为二进制
go build -o ./target/bible ./cmd/bible-cli
./target/bible --help
```

#### 4.3 配置

```bash
export BIBLE_CLI_BASE_URL=http://127.0.0.1:5555
export BIBLE_CLI_TIMEOUT_SECONDS=30
```

配置优先级：环境变量 `BIBLE_CLI_*` > `~/.bible/config.json` > `/etc/bible/config.json` > 内置默认值。

#### 4.4 验证

```bash
go run ./cmd/bible-cli health
# 预期: {"ok":true,"data":{"status":"ok"}}

go run ./cmd/bible-cli system status
go run ./cmd/bible-cli knowledge list
go run ./cmd/bible-cli search --query "test" --top-k 5
go run ./cmd/bible-cli search --query "test" --enable-hit --hit-types skill,memory
```

#### 4.5 运行测试

```bash
go test ./...           # 全部测试
go test ./... -race     # 竞态检测
```

#### 4.6 清理

```bash
rm -rf ./target                    # 构建产物
rm -f ~/.bible/config.json         # 用户配置（可选）
```

---

## 5. Bible Hermes Plugin（Hermes 插件）

#### 5.1 前置条件

| 依赖 | 说明 |
|---|---|
| Hermes Agent | 已安装于 `~/.hermes` |
| uv | Python 包管理器 |
| Bible Server | 已启动（推荐 Test Mode `127.0.0.1:5555`） |

#### 5.2 安装

**方式一：一键部署脚本（推荐）**

```bash
cd BiBLE-Atlas/bible-hermes-plugin

# 部署（不重启 Hermes）
./deploy.sh

# 部署 + 自动重启 Hermes
./deploy.sh --restart

# 部署 + 监控日志
./deploy.sh --watch
```

**方式二：手动安装**

```bash
# 1. 同步文件到 Hermes plugins 目录
rsync -av --delete \
  --exclude '__pycache__/' --exclude '.venv/' --exclude '.pytest_cache/' \
  --exclude 'deploy.sh' --exclude '.git/' \
  ./ ~/.hermes/plugins/bible-hermes-plugin/

# 2. 安装到 Hermes Agent 的 venv（⚠️ 不是插件自己的 .venv）
uv pip install --python ~/.hermes/hermes-agent/venv/bin/python \
  ~/.hermes/plugins/bible-hermes-plugin/

# 3. 启用插件
hermes plugins enable bible-hermes-plugin
```

> **关键**：插件必须安装到 `~/.hermes/hermes-agent/venv/`（Hermes 运行时 Python），而非插件目录下的 `.venv`。

#### 5.3 配置

两种方式（环境变量优先）：

**环境变量：**

```bash
export BIBLE_ATLAS_BASE_URL=http://127.0.0.1:5555
```

**配置文件 `~/.hermes/config.yaml`：**

```yaml
bible:
  base_url: "http://127.0.0.1:5555"
  enable_memory_recall: true
  enable_skill_recall: true
  recall_top_k: 8
  recall_min_score: 0.35
  injection_token_budget: 1200
  capture_enabled: true
  bypass_session_patterns:
    - "^scratch:"
    - "^test-"
```

完整配置项见 `bible-hermes-plugin/plugin.yaml` 中的 `config_schema`。

#### 5.4 验证

```bash
hermes plugins list | grep bible
hermes bible --help

# Dry-run setup
hermes bible setup --base-url http://127.0.0.1:5555

# 写入配置
hermes bible setup --base-url http://127.0.0.1:5555 --write

# 查看状态
hermes bible status
```

确认：`enabled: yes`、`health: ok`、`tools: 7 registered`。

#### 5.5 功能验证

1. 重启 Hermes（`/reset` 或 `hermes server restart`）
2. 会话中发送与已保存 memory 相关的问题
3. 确认日志出现 `recall.pipeline start`、`runtime.searchMemory`
4. 输入 `/bible status` 验证 slash command
5. 逐一调用 7 个 agent tools 确认返回结构
6. 创建 session ID 匹配 `bypass_session_patterns` 的会话，确认不触发 recall

#### 5.6 运行测试

```bash
cd bible-hermes-plugin
uv sync && uv run pytest tests/ -v
```

#### 5.7 清理

```bash
hermes plugins disable bible-hermes-plugin
rm -rf ~/.hermes/plugins/bible-hermes-plugin
# 或使用总控脚本：./scripts/env-prepare.sh teardown hermes --uninstall-plugins
```

---

## 6. Bible OC Plugin（OpenClaw 插件）

#### 6.1 前置条件

| 依赖 | 最低版本 |
|---|---|
| OpenClaw | >= 2026.5.18（推荐 >= 2026.5.22） |
| Node.js | >= 20 |
| Bible Server | 已启动（推荐 Test Mode `127.0.0.1:5555`） |

#### 6.2 构建

```bash
cd BiBLE-Atlas/bible-oc-plugin

npm install
npm run typecheck
npm test
npm run build

# 确认产物
test -f dist/index.js && echo "OK: dist/index.js"
test -f openclaw.plugin.json && echo "OK: openclaw.plugin.json"
```

#### 6.3 安装到 OpenClaw

```bash
# 方式一：OpenClaw CLI（推荐）
openclaw plugins install . --force

# 方式二：本地安装脚本（直接写入 openclaw.json）
node scripts/install-local.mjs --write
# Dry-run 预览（不写入）:
node scripts/install-local.mjs
```

#### 6.4 配置

```bash
# Dry-run（验证连通性）
openclaw bible setup --base-url http://127.0.0.1:5555

# 写入配置
openclaw bible setup --base-url http://127.0.0.1:5555 --write
```

或手动编辑 `~/.openclaw/openclaw.json`：

```json
{
  "plugins": {
    "entries": {
      "bible-oc-plugin": {
        "config": {
          "baseUrl": "http://127.0.0.1:5555",
          "enableMemoryRecall": true,
          "enableSkillRecall": true,
          "recallTopK": 8,
          "recallMinScore": 0.35,
          "captureEnabled": true,
          "bypassSessionPatterns": ["^scratch:", "^test-"]
        }
      }
    },
    "slots": {
      "contextEngine": "bible-oc-plugin"
    }
  }
}
```

#### 6.5 重启 Gateway

```bash
openclaw gateway restart
```

#### 6.6 验证

```bash
openclaw plugins inspect bible-oc-plugin
openclaw bible --help
openclaw bible status
openclaw bible status --json
```

确认：`enabled: yes`、`contextEngine slot: bible-oc-plugin`、`health: ok`、`tools: 7 registered / 7 declared`。

#### 6.7 Contract 验证（高级）

```bash
node --input-type=module -e "
const plugin = (await import(
  process.env.HOME + '/.openclaw/extensions/bible-oc-plugin/dist/index.js'
)).default;
let factory;
const api = {
  config: { baseUrl: 'http://127.0.0.1:5555', contextEngineId: 'bible-oc-plugin' },
  logger: { info() {}, warn() {}, error() {} },
  registerCli() {}, registerTool() {}, on() {},
  registerContextEngine(id, f) { factory = f; }
};
plugin.register(api);
const engine = await factory({});
console.log(JSON.stringify({
  info: engine.info,
  ingest: typeof engine.ingest,
  assemble: typeof engine.assemble,
  compact: typeof engine.compact
}));
"
```

预期：

```json
{"info":{"id":"bible-oc-plugin","name":"BiBLE Atlas","version":"0.1.0"},"ingest":"function","assemble":"function","compact":"function"}
```

#### 6.8 功能验证

1. 跟踪日志：`openclaw logs --follow`
2. 会话中发送与已保存 memory 相关的问题
3. 确认日志出现 `context.assemble start`、`recall.pipeline start`
4. 确认 7 个 tools 可用
5. 创建匹配 `bypassSessionPatterns` 的 session，确认不触发 recall

#### 6.9 清理

```bash
openclaw plugins uninstall bible-oc-plugin
openclaw config remove plugins.entries.bible-oc-plugin
openclaw gateway restart
```

---

## 7. 全组件联合测试

以下流程验证 Test Mode + 三个客户端的端到端连通性。

### 7.1 启动服务端

```bash
# 终端 1：启动 Test Mode
cd BiBLE-Atlas
uv run python -m bible.test_mode.server --addr 127.0.0.1:5555
```

### 7.2 Go CLI

```bash
# 终端 2
export BIBLE_CLI_BASE_URL=http://127.0.0.1:5555
cd BiBLE-Atlas/bible_cli_go

go run ./cmd/bible-cli health
go run ./cmd/bible-cli system status
go run ./cmd/bible-cli knowledge list
go run ./cmd/bible-cli search --query "test" --top-k 5
```

### 7.3 Hermes Plugin

```bash
cd BiBLE-Atlas/bible-hermes-plugin
./deploy.sh --restart

export BIBLE_ATLAS_BASE_URL=http://127.0.0.1:5555
hermes bible setup --base-url http://127.0.0.1:5555 --write
hermes bible status
```

### 7.4 OC Plugin

```bash
cd BiBLE-Atlas/bible-oc-plugin
npm install && npm run build

openclaw plugins install . --force
openclaw bible setup --base-url http://127.0.0.1:5555 --write
openclaw gateway restart
openclaw bible status
```

### 7.5 回归测试

```bash
# Python 服务端
cd BiBLE-Atlas && uv run pytest tests/ -v

# Go CLI
cd bible_cli_go && go test ./... -race

# Hermes 插件
cd bible-hermes-plugin && uv run pytest tests/ -v

# OC 插件
cd bible-oc-plugin && npm test
```

---

## 8. 环境清理

> **懒人首选**: `./scripts/env-prepare.sh teardown --force`（或 `--full --force` 含 Docker 容器删除）

以下为分步手动清理方式。

### 8.1 停止 Bible Server（使用 server_deploy 脚本）

```bash
cd scripts/server_deploy
./deploy.sh stop
```

### 8.2 停止 Redis + Celery Worker（使用 redis_celery_deploy 脚本）

```bash
cd scripts/redis_celery_deploy

# 先停 Worker 再停 Redis
./deploy.sh stop-all bibletest

# 如需删除实例（含数据）
./deploy.sh redis delete bibletest
```

### 8.3 停止 OpenSearch（使用 opensearch_deploy 脚本）

```bash
cd scripts/opensearch_deploy

./deploy.sh stop bibletest

# 如需完全删除（含数据）
./deploy.sh delete bibletest
```

### 8.4 停止 Test Mode / Mock Server（手动进程）

```bash
pkill -f "bible.test_mode.server" 2>/dev/null || true
pkill -f "bible-mock-server" 2>/dev/null || true
```

### 8.5 卸载插件

```bash
# Hermes 插件
hermes plugins disable bible-hermes-plugin 2>/dev/null || true
rm -rf ~/.hermes/plugins/bible-hermes-plugin

# OC 插件
openclaw plugins uninstall bible-oc-plugin 2>/dev/null || true
```

### 8.6 清理配置

```bash
./scripts/env-prepare.sh teardown cli hermes oc --purge-config --uninstall-plugins
```

### 8.7 清理运行时数据

```bash
cd BiBLE-Atlas
rm -rf ./workspace ./release ./dist
rm -rf bible_cli_go/target
rm -rf bible-oc-plugin/dist bible-oc-plugin/node_modules
rm -rf bible-hermes-plugin/.venv bible-hermes-plugin/__pycache__
```

### 8.8 一键清理

直接使用 `scripts/env-prepare.sh`：

```bash
# 基础清理（保留 Docker 容器和数据）
./scripts/env-prepare.sh teardown --force

# 完整清理（含 Docker 容器和数据删除）
./scripts/env-prepare.sh teardown --full --force
```

---

## 9. 部署脚本速查

### 9.0 总控脚本（`scripts/env-prepare.sh`）

| 命令 | 说明 |
|---|---|
| `./scripts/env-prepare.sh setup` | 一键搭建（Test Mode + 全部客户端） |
| `./scripts/env-prepare.sh setup --full` | 完整后端（OpenSearch + Redis + Server + 全部客户端） |
| `./scripts/env-prepare.sh setup <c1> <c2>` | 只搭建指定组件 |
| `./scripts/env-prepare.sh teardown` | 一键清理（停止进程、删除本地构建产物，默认保留用户级配置/插件） |
| `./scripts/env-prepare.sh teardown --full` | 完整清理（额外删除 Docker 容器和数据） |
| `./scripts/env-prepare.sh status` | 查看所有组件状态 |
| `./scripts/env-prepare.sh status --json` | JSON 格式状态输出 |

| 清理选项 | 说明 |
|---|---|
| `--purge-workspace` | 删除项目 `workspace/` 运行时数据 |
| `--purge-config` | 删除用户级 BiBLE 配置，如 `~/.bible/config.json` |
| `--uninstall-plugins` | 卸载/移除 Hermes 与 OpenClaw 用户级插件配置 |

| 环境变量 | 说明 | 默认行为 |
|---|---|---|
| `BIBLE_DOCKER_REGISTRY_PREFIX` | Docker Hub 镜像前缀/镜像站，例如 `docker.m.daocloud.io/` | 交互式询问；非交互留空 |
| `BIBLE_OPENSEARCH_CPU_CORES` | OpenSearch CPU 核数 | 交互式根据 Docker CPU 建议；非交互默认 `4` |
| `BIBLE_OPENSEARCH_MEMORY_GB` | OpenSearch 内存 GB | 交互式根据 CPU 建议；非交互默认 `12` |

使用 `--force` 会跳过交互提示；此时若 Docker 可用 CPU 少于请求 CPU，脚本会在前置检查阶段失败。

### 9.1 OpenSearch（`scripts/opensearch_deploy/deploy.sh`）

| 命令 | 说明 |
|---|---|
| `./deploy.sh create <name> <http_port> <dash_port> <cpu> <mem_gb>` | 创建实例 |
| `./deploy.sh start <name>` | 启动实例 |
| `./deploy.sh stop <name>` | 停止实例 |
| `./deploy.sh restart <name>` | 重启实例 |
| `./deploy.sh status [name]` | 查看状态（不加 name = 全部） |
| `./deploy.sh logs <name> [lines]` | 查看日志 |
| `./deploy.sh list` | 列出所有实例 |
| `./deploy.sh info <name>` | 显示详情 |
| `./deploy.sh delete <name> [--keep-data]` | 删除实例 |
| `./deploy.sh pull` | 预拉取 Docker 镜像 |
| `./quickstart.sh` | 交互式创建向导 |

### 9.2 Redis + Celery（`scripts/redis_celery_deploy/deploy.sh`）

| 命令 | 说明 |
|---|---|
| `./deploy.sh redis create <name> <port> [mem_mb]` | 创建 Redis 实例 |
| `./deploy.sh redis start/stop/restart <name>` | 管理 Redis 生命周期 |
| `./deploy.sh redis status [name]` | Redis 状态 |
| `./deploy.sh redis logs <name> [lines]` | Redis 日志 |
| `./deploy.sh redis list` | 列出所有实例 |
| `./deploy.sh redis info <name>` | 详情 + 推荐配置 |
| `./deploy.sh redis delete <name>` | 删除实例 |
| `./deploy.sh redis flush <name>` | 清空 Redis 数据 |
| `./deploy.sh worker start/stop/restart <name>` | 管理 Worker |
| `./deploy.sh worker status [name]` | Worker 状态 |
| `./deploy.sh worker logs <name> [lines]` | Worker 日志 |
| `./deploy.sh start-all <name>` | 一键启 Redis + Worker |
| `./deploy.sh stop-all <name>` | 一键停 Worker + Redis |
| `./deploy.sh status` | 全部实例 + Worker 总览 |
| `./quickstart.sh` | 交互式创建向导 |

**Worker start 选项：**

| 选项 | 说明 | 默认值 |
|---|---|---|
| `--concurrency N` | Worker 进程数 | CPU 核心数 |
| `--loglevel <level>` | 日志级别 | `info` |
| `--config <path>` | bible-atlas.yaml 路径 | 项目根目录 |

### 9.3 Bible Server（`scripts/server_deploy/deploy.sh`）

| 命令 | 说明 |
|---|---|
| `./deploy.sh start [--config ...] [--concurrency N] [--loglevel ...]` | 启动 Server + Worker |
| `./deploy.sh stop` | 停止（先 Worker 后 Server） |
| `./deploy.sh restart [选项]` | 重启 |
| `./deploy.sh status` | Server + Worker 进程状态 |
| `./deploy.sh logs [server\|worker] [lines]` | 查看日志 |
| `./deploy.sh health` | `/health` 探活 |
| `./quickstart.sh` | 交互式启动向导（含连通性检查） |

### 9.4 Hermes Plugin（`bible-hermes-plugin/deploy.sh`）

| 命令 | 说明 |
|---|---|
| `./deploy.sh` | 仅同步 + 安装，不重启 |
| `./deploy.sh --restart` | 部署后重启 Hermes Server |
| `./deploy.sh --watch` | 部署后 tail -f 插件日志 |

### 9.5 OC Plugin（`bible-oc-plugin/scripts/install-local.mjs`）

| 命令 | 说明 |
|---|---|
| `node scripts/install-local.mjs` | Dry-run 预览 openclaw.json 变更 |
| `node scripts/install-local.mjs --write` | 写入 openclaw.json |

---

## 10. 故障排查速查表

| 症状 | 可能原因 | 处置 |
|---|---|---|
| `ModuleNotFoundError: No module named 'fastapi'` | 未使用项目 `.venv` | `uv sync --all-extras` |
| Test Mode `curl /health` 无响应 | 端口冲突 | 换端口 `--addr 127.0.0.1:5566` |
| Test Mode 业务路由返回 `NOT_FOUND` | fixture 未命中 | 检查请求参数，或 `--fixture` 添加自定义 fixture |
| 响应头没有 `X-Bible-Test-Mode` | 请求打到了生产服务 | 确认 base URL 指向 Test Mode |
| Go CLI 返回 `CLI_NOT_IMPLEMENTED` | 命令尚未实现 | 预期行为，参考 `go-cli-user-guide.md` |
| `No module named 'bible_hermes_plugin'` | 插件未安装到 Hermes venv | `uv pip install --python ~/.hermes/hermes-agent/venv/bin/python ~/.hermes/plugins/bible-hermes-plugin/` |
| `openclaw bible` unknown command | 插件未安装或 gateway 未重启 | `openclaw plugins install . --force && openclaw gateway restart` |
| `setup --write` 失败 | Bible Server 不可达 | `curl http://127.0.0.1:5555/health` |
| `status` 显示 slot 不正确 | contextEngine slot 未设置 | 设置 `plugins.slots.contextEngine` 为 `bible-oc-plugin` |
| 插件没有召回内容 | 无可用 memory 或 score 太低 | 确认已有 memory，调低 `recallMinScore` |
| Celery Worker 无法连接 | Redis 未启动或端口不匹配 | `./deploy.sh redis status bibletest` 确认端口，检查 `bible-atlas.yaml` |
| OpenSearch 连接拒绝 | 容器未启动或端口不匹配 | `./deploy.sh status bibletest` 确认端口，检查 `bible-atlas.yaml` |
| Worker 启动后立即退出 | Redis 未运行、配置端口不匹配、或依赖缺失 | 依次检查 Redis 状态 → `bible-atlas.yaml` 端口 → `uv sync --all-extras` |
| OpenSearch 容器权限错误 | 数据目录权限不匹配（UID 1000） | `sudo chown -R 1000:1000 scripts/opensearch_deploy/opensearch/<name>/data` |

---

## 参考文档

| 文档 | 路径 |
|---|---|
| Go CLI 用户指南 | `docs/manual/go-cli-user-guide.md` |
| Test Mode 使用指南 | `docs/manual/test-mode-user-guide.md` |
| CLI API 契约 | `docs/manual/cli-contract-v1.md` |
| OpenSearch 部署 README | `scripts/opensearch_deploy/README.md` |
| OpenSearch 部署示例 | `scripts/opensearch_deploy/EXAMPLES.md` |
| Redis+Celery 部署 README | `scripts/redis_celery_deploy/README.md` |
| Redis+Celery 部署示例 | `scripts/redis_celery_deploy/EXAMPLES.md` |
| Server 部署 README | `scripts/server_deploy/README.md` |
| OC Plugin 测试指南 | `bible-oc-plugin/TESTING_GUIDE.md` |
| Hermes Plugin README | `bible-hermes-plugin/README.md` |
| 项目架构 | `CLAUDE_local.md` |
| 服务端配置 | `bible-atlas.yaml` |

> 如有未覆盖的故障场景，请提 issue 到 BiBLE Atlas 仓库并附上日志。
