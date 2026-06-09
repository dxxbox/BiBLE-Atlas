# Redis + Celery Worker 部署方案

本目录提供完整的 Redis + Celery Worker 部署管理方案，支持在同一台服务器上运行多个独立的 Redis 实例，并管理对应的 Celery Worker 进程。

## 📁 目录结构

```
redis_celery_deploy/
├── deploy.sh                      # 部署脚本（主要工具）
├── quickstart.sh                  # 交互式快速配置向导
├── docker-compose.template.yml    # Docker Compose 模板（Redis + Redis Commander）
├── redis.conf.template            # Redis 配置模板
├── README.md                      # 本文档
└── EXAMPLES.md                    # 使用示例
```

实例数据存储在 `redis/<实例名>/`（已被 `.gitignore` 排除）：

```
redis/<实例名>/
├── data/                  # Redis 持久化数据（RDB + AOF）
├── logs/                  # Redis 日志
├── config/
│   └── redis.conf         # 生成的 Redis 配置
├── worker/
│   ├── celery.pid         # Worker 进程 PID
│   └── celery.log         # Worker 日志
├── docker-compose.yml     # 生成的 Docker Compose 配置
└── instance.info          # 实例元信息
```

## 🚀 快速开始

### 方式一：交互式向导（推荐新手）

```bash
./quickstart.sh
```

向导会引导你：
1. 选择 Redis 内存方案（轻量 / 标准 / 大型 / 自定义）
2. 输入实例名称和端口
3. 创建实例，并可选择立即启动 Redis 和 Celery Worker

### 方式二：命令行直接操作

```bash
# 1. 创建 Redis 实例
./deploy.sh redis create myredis 6379

# 2. 启动 Redis
./deploy.sh redis start myredis

# 3. 启动 Celery Worker
./deploy.sh worker start myredis

# 或一键启动两者
./deploy.sh start-all myredis
```

## 📋 完整命令列表

### Redis 子命令

| 命令 | 说明 | 示例 |
|------|------|------|
| `redis create` | 创建实例 | `./deploy.sh redis create myredis 6379 1024` |
| `redis start` | 启动实例 | `./deploy.sh redis start myredis` |
| `redis stop` | 停止实例 | `./deploy.sh redis stop myredis` |
| `redis restart` | 重启实例 | `./deploy.sh redis restart myredis` |
| `redis delete` | 删除实例 | `./deploy.sh redis delete myredis` |
| `redis status` | 查看状态 | `./deploy.sh redis status [myredis]` |
| `redis logs` | 查看日志 | `./deploy.sh redis logs myredis [行数]` |
| `redis list` | 列出所有实例 | `./deploy.sh redis list` |
| `redis info` | 显示详细信息 | `./deploy.sh redis info myredis` |
| `redis flush` | 清空数据 | `./deploy.sh redis flush myredis` |

### Worker 子命令

| 命令 | 说明 | 示例 |
|------|------|------|
| `worker start` | 启动 Worker | `./deploy.sh worker start myredis` |
| `worker stop` | 停止 Worker | `./deploy.sh worker stop myredis` |
| `worker restart` | 重启 Worker | `./deploy.sh worker restart myredis` |
| `worker status` | 查看状态 | `./deploy.sh worker status [myredis]` |
| `worker logs` | 查看日志 | `./deploy.sh worker logs myredis [行数]` |

`worker start` 支持的选项：

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--concurrency N` | Worker 进程数 | CPU 核心数 |
| `--queues <queue>` | 监听队列 | `celery` |
| `--loglevel <level>` | 日志级别 | `info` |
| `--config <path>` | bible-atlas.yaml 路径 | 项目根目录 |

### 全局命令

| 命令 | 说明 |
|------|------|
| `status` | 显示所有 Redis 实例 + Worker 总览 |
| `start-all <实例名>` | 同时启动 Redis 和 Worker |
| `stop-all <实例名>` | 同时停止 Worker 和 Redis |

## 🔧 配置 bible-atlas.yaml

创建 Redis 实例后，将以下内容更新到 `bible-atlas.yaml`：

```yaml
celery:
  broker_url: "redis://localhost:6379/0"   # 替换为实际端口
  result_backend: "redis://localhost:6379/1"
```

也可用 `./deploy.sh redis info <实例名>` 直接查看推荐的配置值。

## 🌐 Redis Commander（Web UI）

每个 Redis 实例都会启动一个 Redis Commander 可视化界面，端口为 `Redis端口 + 1000`：

- Redis 端口 `6379` → Commander: `http://localhost:7379`
- Redis 端口 `6380` → Commander: `http://localhost:7380`
- 默认账号密码: `admin / admin`

可在 `docker-compose.yml` 中修改 `HTTP_USER` / `HTTP_PASSWORD` 环境变量。

## 📊 多用户端口规划

| 用户 | Redis 端口 | Commander 端口 |
|------|-----------|----------------|
| user1 | 6379 | 7379 |
| user2 | 6380 | 7380 |
| user3 | 6381 | 7381 |
| ... | ... | ... |

## ⚙️ 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `REDIS_BASE_DIR` | Redis 实例数据根目录 | `脚本目录/redis` |
| `BIBLE_PROJECT_ROOT` | 项目根目录（用于 Worker） | `脚本向上两级` |
| `BIBLE_DOCKER_REGISTRY_PREFIX` | Docker Hub 镜像前缀/镜像站 | 空 |
| `REDIS_IMAGE` | Redis 完整镜像名覆盖 | `redis:<tag>` |
| `REDIS_COMMANDER_IMAGE` | Redis Commander 完整镜像名覆盖 | `rediscommander/redis-commander:<tag>` |
| `REDIS_IMAGE_TAG` | Redis 镜像标签 | `7-alpine` |
| `REDIS_COMMANDER_IMAGE_TAG` | Redis Commander 镜像标签 | `latest` |

示例：

```bash
REDIS_BASE_DIR=/data/redis ./deploy.sh redis create myredis 6379

# 使用 Docker Hub 镜像站启动（适合网络受限地区）
BIBLE_DOCKER_REGISTRY_PREFIX=docker.m.daocloud.io/ ./deploy.sh redis start myredis

# 固定 Redis 版本
BIBLE_DOCKER_REGISTRY_PREFIX=docker.m.daocloud.io/ \
REDIS_IMAGE_TAG=7.2-alpine \
./deploy.sh redis start myredis

# 使用私有仓库完整镜像名
REDIS_IMAGE=registry.example.com/redis:7.2-alpine \
REDIS_COMMANDER_IMAGE=registry.example.com/redis-commander:latest \
./deploy.sh redis start myredis
```

## 🔍 故障排查

### Redis 无法启动

```bash
# 查看容器日志
./deploy.sh redis logs myredis 100

# 检查端口占用
ss -tlnp | grep 6379

# 检查数据目录权限
ls -la ./redis/myredis/data
```

### Worker 无法启动

```bash
# 查看 Worker 日志
./deploy.sh worker logs myredis 100

# 检查 venv 是否存在
ls ../../.venv/bin/celery

# 手动测试启动（前台模式，便于调试）
cd ../..
.venv/bin/celery -A bible.features.async_task.worker worker --loglevel=debug
```

### Worker 启动后立即退出

通常原因：
1. Redis 未启动 → 先执行 `./deploy.sh redis start myredis`
2. bible-atlas.yaml 中 `broker_url` 端口不匹配 → 检查配置
3. Python 依赖缺失 → `cd ../.. && .venv/bin/pip install -e .`

## 📈 监控和维护

```bash
# 查看 Redis 内存使用
redis-cli -p 6379 info memory

# 查看 Redis 队列长度（Celery 默认队列）
redis-cli -p 6379 llen celery

# 实时监控 Worker 日志
./deploy.sh worker logs myredis 50

# 查看 Celery Worker 状态（需 Worker 运行中）
cd ../..
.venv/bin/celery -A bible.features.async_task.worker inspect active
```

## 📝 更新日志

- 2026-05-27：初始版本
  - 支持多实例 Redis Docker 部署
  - Celery Worker 进程管理（启动/停止/重启/日志）
  - Redis Commander Web UI 集成
  - 交互式快速配置向导
