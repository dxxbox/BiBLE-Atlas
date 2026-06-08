# Redis + Celery 部署使用示例

本文档提供详细的使用示例，帮助你快速上手 Redis + Celery Worker 部署方案。

## 📖 目录

- [示例 0：交互式向导](#示例-0交互式向导quickstartsh)
- [示例 1：单实例快速部署](#示例-1单实例快速部署)
- [示例 2：多用户独立实例](#示例-2多用户独立实例)
- [示例 3：Worker 高级配置](#示例-3worker-高级配置)
- [示例 4：更新 bible-atlas.yaml 配置](#示例-4更新-bible-atlasyaml-配置)
- [示例 5：监控与运维](#示例-5监控与运维)
- [示例 6：完整部署工作流](#示例-6完整部署工作流)

---

## 示例 0：交互式向导（quickstart.sh）

`quickstart.sh` 是面向新手的交互式快速配置向导。

```bash
./quickstart.sh
```

运行后，向导会逐步提示你：

```
╔══════════════════════════════════════════╗
║   Redis + Celery Worker 快速配置向导    ║
╚══════════════════════════════════════════╝

请选择 Redis 配置方案：

  1. 轻量配置（开发/单机测试）     - 512MB 内存
  2. 标准配置（小规模生产）         - 1024MB 内存
  3. 大型配置（高并发任务队列）     - 2048MB 内存
  4. 自定义配置

? 请输入选项 (1-4): 2
? 请输入实例名称（字母/数字/中划线）[默认: myredis]: alice
? Redis 端口 [默认: 6379]:        ← 直接回车使用推荐端口

即将创建实例：
  实例名称:   alice
  配置方案:   标准 (1024MB)
  Redis 端口: 6379
  Commander:  http://localhost:7379  (admin/admin)

? 确认创建？(yes/no) [默认: yes]: yes
...
? 是否立即启动 Redis 实例？(yes/no) [默认: yes]: yes
...
? 是否同时启动 Celery Worker？(yes/no) [默认: yes]: yes
? Worker 并发进程数（0=自动）[默认: 0]: 4
```

完成后打印访问地址和常用命令：

```
Redis 连接:  redis://localhost:6379
Commander:   http://localhost:7379  (admin/admin)

将以下配置写入 bible-atlas.yaml：

  celery:
    broker_url: "redis://localhost:6379/0"
    result_backend: "redis://localhost:6379/1"

常用命令：
  查看状态:    ./deploy.sh status
  Worker 日志: ./deploy.sh worker logs alice
  停止所有:    ./deploy.sh stop-all alice
```

> **提示**：`quickstart.sh` 底层调用 `deploy.sh`，如需批量创建或脚本自动化，请直接使用 `deploy.sh`。

---

## 示例 1：单实例快速部署

### 1.1 标准流程

```bash
# 进入部署目录
cd scripts/redis_celery_deploy/

# 创建实例（实例名 myredis，端口 6379，内存 1024MB）
./deploy.sh redis create myredis 6379 1024

# 启动 Redis
./deploy.sh redis start myredis

# 等待 Redis 就绪后启动 Celery Worker
./deploy.sh worker start myredis

# 查看整体状态
./deploy.sh status
```

### 1.2 一键启动（等价于上面三步）

```bash
./deploy.sh redis create myredis 6379 1024
./deploy.sh start-all myredis
```

### 1.3 验证服务正常

```bash
# 验证 Redis
redis-cli -p 6379 ping
# → PONG

# 查看 Redis 信息
redis-cli -p 6379 info server | grep redis_version

# 查看 Worker 进程
./deploy.sh worker status myredis
```

---

## 示例 2：多用户独立实例

每个用户独享一个 Redis 实例和对应的 Celery Worker。

### 2.1 为三个用户分别部署

```bash
# 用户 alice：Redis 6379，内存 1GB
./deploy.sh redis create alice 6379 1024
./deploy.sh start-all alice

# 用户 bob：Redis 6380，内存 512MB
./deploy.sh redis create bob 6380 512
./deploy.sh start-all bob

# 用户 charlie：Redis 6381，内存 2GB
./deploy.sh redis create charlie 6381 2048
./deploy.sh start-all charlie
```

### 2.2 批量操作

```bash
# 批量创建和启动
for config in "alice:6379:1024" "bob:6380:512" "charlie:6381:2048"; do
    IFS=':' read -r name port mem <<< "$config"
    ./deploy.sh redis create "$name" "$port" "$mem"
    ./deploy.sh start-all "$name"
done
```

### 2.3 查看所有实例

```bash
./deploy.sh redis list
./deploy.sh status
```

---

## 示例 3：Worker 高级配置

### 3.1 指定并发数

```bash
# 8 个并发 worker 进程（适合高并发任务场景）
./deploy.sh worker start myredis --concurrency 8
```

### 3.2 指定日志级别

```bash
# 调试模式（输出详细日志）
./deploy.sh worker start myredis --loglevel debug
```

### 3.3 指定配置文件路径

```bash
# Worker 默认读取项目根目录的 bible-atlas.yaml
# 如需指定其他路径：
./deploy.sh worker start myredis --config /path/to/my-bible-atlas.yaml
```

### 3.4 组合选项

```bash
./deploy.sh worker start myredis \
    --concurrency 4 \
    --loglevel info \
    --config /opt/bibleV/bible-atlas.yaml
```

### 3.5 重启 Worker（更新代码后）

```bash
./deploy.sh worker restart myredis
# 或带选项重启：
./deploy.sh worker restart myredis --concurrency 6
```

---

## 示例 4：更新 bible-atlas.yaml 配置

查看实例的推荐配置值：

```bash
./deploy.sh redis info myredis
```

输出：

```
Redis 实例 'myredis' 详细信息：

基本信息：
  实例名:       myredis
  数据目录:     /path/to/redis/myredis
  创建时间:     2026-05-27 10:00:00

网络配置：
  Redis 端口:   6379
  Commander 端口: 7379

Celery 配置（供 bible-atlas.yaml 使用）：
  broker_url:      redis://localhost:6379/0
  result_backend:  redis://localhost:6379/1
```

将输出的配置值更新到 `bible-atlas.yaml`：

```yaml
# bible-atlas.yaml
celery:
  broker_url: "redis://localhost:6379/0"
  result_backend: "redis://localhost:6379/1"
  task_acks_late: true
  worker_prefetch_multiplier: 1
```

---

## 示例 5：监控与运维

### 5.1 查看实时日志

```bash
# Celery Worker 实时日志
./deploy.sh worker logs myredis 100

# Redis 容器日志
./deploy.sh redis logs myredis 50
```

### 5.2 Redis 监控命令

```bash
# 基础健康检查
redis-cli -p 6379 ping

# 内存使用情况
redis-cli -p 6379 info memory | grep -E "used_memory_human|maxmemory_human"

# Celery 任务队列长度
redis-cli -p 6379 llen celery

# 所有 key 数量
redis-cli -p 6379 dbsize

# 实时监控命令（会打印所有执行的命令，调试用）
redis-cli -p 6379 monitor
```

### 5.3 Celery Worker 监控

```bash
# 查看当前活跃任务（需 Worker 运行中）
cd ../..
.venv/bin/celery -A bible.features.async_task.worker inspect active

# 查看已注册的任务列表
.venv/bin/celery -A bible.features.async_task.worker inspect registered

# 查看 Worker 统计信息
.venv/bin/celery -A bible.features.async_task.worker inspect stats
```

### 5.4 清空测试数据

```bash
# 清空 Redis 数据（危险操作！）
./deploy.sh redis flush myredis

# 或只清空特定数据库
./deploy.sh redis flush myredis --db 0
```

---

## 示例 6：完整部署工作流

以下是从零开始部署到上线的完整流程：

```bash
# ── 步骤 1：检查依赖 ──────────────────────────────────────────────────────────
# 检查 docker 和 docker-compose
docker --version
docker-compose --version

# 检查项目 venv
ls ../../.venv/bin/celery

# ── 步骤 2：创建 Redis 实例 ───────────────────────────────────────────────────
cd scripts/redis_celery_deploy/
./deploy.sh redis create myredis 6379 1024

# ── 步骤 3：启动 Redis ────────────────────────────────────────────────────────
./deploy.sh redis start myredis

# 验证 Redis 启动（等待 ~3 秒）
sleep 3
redis-cli -p 6379 ping
# → PONG

# ── 步骤 4：更新 bible-atlas.yaml ─────────────────────────────────────────────
# 查看推荐配置
./deploy.sh redis info myredis

# 手动更新项目配置文件
# vim ../../bible-atlas.yaml
# 将 celery.broker_url 和 celery.result_backend 改为 redis://localhost:6379/x

# ── 步骤 5：启动 Celery Worker ────────────────────────────────────────────────
./deploy.sh worker start myredis --concurrency 4

# 验证 Worker 已启动
./deploy.sh worker status myredis

# ── 步骤 6：验证端到端 ────────────────────────────────────────────────────────
# 查看 Worker 日志确认连接成功
./deploy.sh worker logs myredis 20

# 整体状态总览
./deploy.sh status

# ── 日常运维 ──────────────────────────────────────────────────────────────────
# 重启 Worker（部署新代码后）
./deploy.sh worker restart myredis

# 停止所有服务
./deploy.sh stop-all myredis

# 再次启动
./deploy.sh start-all myredis
```

---

## 常见问题

### Q: Worker 启动后日志显示 "Cannot connect to redis://localhost:6379/0"

**原因**：Redis 未启动或端口不对。

```bash
# 检查 Redis 状态
./deploy.sh redis status myredis

# 确认端口
./deploy.sh redis info myredis

# 确认 bible-atlas.yaml 中的端口与 Redis 实例端口一致
grep -A3 "^celery:" ../../bible-atlas.yaml
```

### Q: 如何修改 Redis 最大内存

```bash
# 方法一：删除实例重建（数据会丢失）
./deploy.sh redis delete myredis
./deploy.sh redis create myredis 6379 2048  # 改为 2048MB

# 方法二：运行时动态调整（重启后失效）
redis-cli -p 6379 config set maxmemory 2gb
```

### Q: 如何设置 Redis 密码

编辑生成的配置文件：

```bash
# 取消注释并设置密码
vim ./redis/myredis/config/redis.conf
# 找到并修改：requirepass your_strong_password

# 重启 Redis
./deploy.sh redis restart myredis

# 更新 bible-atlas.yaml
# broker_url: "redis://:your_strong_password@localhost:6379/0"
# result_backend: "redis://:your_strong_password@localhost:6379/1"
```

### Q: 如何查看 Celery 任务是否在执行

```bash
# 实时查看 Worker 日志
./deploy.sh worker logs myredis 50

# 或通过 Redis Commander
# 打开 http://localhost:7379，查看 DB0 中的 celery 列表
```
