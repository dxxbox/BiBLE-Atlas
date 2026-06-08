# BiBLE-Atlas 后端服务部署

管理 FastAPI Server 和 Celery Worker 两个后端进程。

## 前提条件

在启动后端服务之前，确保以下依赖已就绪：

1. **OpenSearch** — 参见 `scripts/opensearch_deploy/`
2. **Redis** — 参见 `scripts/redis_celery_deploy/`
3. **uv** 已安装（项目使用 uv 管理 Python 环境）：
   ```bash
   # 若尚未安装 uv：
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
4. **`bible-atlas.yaml`** 中的 OpenSearch / Redis 地址与已启动实例一致

## 快速开始

```bash
# 交互式向导（推荐首次使用）
bash quickstart.sh

# 或直接启动（使用默认配置）
bash deploy.sh start
```

## deploy.sh 命令参考

### 启动服务

```bash
bash deploy.sh start [选项]

选项：
  --config <path>       bible-atlas.yaml 路径（默认：项目根目录）
  --concurrency <N>     Celery Worker 并发数（默认：CPU 核心数）
  --loglevel <level>    日志级别：debug | info | warning（默认：info）

示例：
  bash deploy.sh start
  bash deploy.sh start --config /path/to/bible-atlas.yaml --concurrency 4
```

### 停止 / 重启

```bash
bash deploy.sh stop
bash deploy.sh restart
bash deploy.sh restart --concurrency 8
```

### 查看状态

```bash
bash deploy.sh status
```

输出示例：
```
BiBLE-Atlas 服务状态
──────────────────────────────────────────
  FastAPI Server:  运行中 (PID=12345)
                   CPU=0.5%  MEM=128.3 MB

  Celery Worker:   运行中 (PID=12346)
                   CPU=1.2%  MEM=256.7 MB
```

### 查看日志

```bash
# 同时显示两者最近 50 行
bash deploy.sh logs

# 只看 Server 日志并持续跟踪
bash deploy.sh logs server

# 看 Worker 最近 100 行
bash deploy.sh logs worker 100
```

日志文件位置：`scripts/server_deploy/runs/`

### 健康检查

```bash
bash deploy.sh health
```

对 `http://127.0.0.1:5555/health` 发起探活，HTTP 200 即为正常。

## 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `BIBLE_PROJECT_ROOT` | 项目根目录 | 脚本向上两级 |
| `BIBLE_ATLAS_CONFIG_PATH` | 配置文件路径 | `<PROJECT_ROOT>/bible-atlas.yaml` |
| `BIBLE_SERVER_HOST` | FastAPI 监听地址 | `0.0.0.0`（允许外部访问） |
| `BIBLE_SERVER_PORT` | FastAPI 监听端口 | `5555` |

可通过环境变量覆盖默认值：

```bash
BIBLE_PROJECT_ROOT=/custom/path bash deploy.sh start
```

## 运行时文件

```
runs/
  server.pid   # FastAPI 进程 PID
  server.log   # FastAPI 日志
  worker.pid   # Celery Worker 进程 PID
  worker.log   # Celery Worker 日志
```

> `runs/` 目录已被 `.gitignore` 排除，不会提交到版本库。

## 注意事项

- **向量模型预加载**：若 `bible-atlas.yaml` 中 `vector.preload_on_startup: true`，Celery Worker 启动时会同步加载所有向量模型（每个约 10-15 秒），`deploy.sh start` 会等待最多 120 秒。
- **FastAPI 绑定地址**：默认绑定 `127.0.0.1:5555`，如需修改请编辑 `bible/main.py` 中的 `uvicorn.run()` 调用。
- **停止顺序**：`stop` 命令会先停 Worker 再停 Server，确保 Worker 不会向已关闭的服务发请求。
