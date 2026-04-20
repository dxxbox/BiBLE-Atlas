# Celery + Redis 部署与配置文档

## 目录
- [1. 系统要求](#1-系统要求)
- [2. 架构概览](#2-架构概览)
- [3. 安装依赖](#3-安装依赖)
- [4. Redis部署与配置](#4-redis部署与配置)
- [5. Celery配置](#5-celery配置)
- [6. 部署流程](#6-部署流程)
- [7. 启动与停止服务](#7-启动与停止服务)
- [8. 监控与维护](#8-监控与维护)
- [9. 故障排查](#9-故障排查)
- [10. 性能优化](#10-性能优化)

---

## 1. 系统要求

### 1.1 硬件要求
- **CPU**: 4核以上推荐（多worker并发）
- **内存**: 8GB以上推荐
  - Redis: ~1GB
  - Celery Workers: 每个worker ~500MB-1GB
  - 应用主进程: ~1-2GB
- **磁盘**: 
  - Redis持久化: 根据任务量，建议预留10GB+
  - 日志文件: 建议预留5GB+

### 1.2 软件要求
- **操作系统**: Linux (推荐 Ubuntu 20.04+, CentOS 7+)
- **Python**: 3.8+
- **Redis**: 5.0+
- **pip**: 最新版本

---

## 2. 架构概览

### 2.1 系统架构图

```
┌─────────────────┐
│   Flask API     │
│  (Web Service)  │
└────────┬────────┘
         │
         |
         │                                     
         ▼                                     
┌────────────────────┐      
│  Celery Broker     │        
│     (Redis)        │         
│  - 任务队列管理     │         
│  - 任务分发        │
└─────────┬──────────┘
          │
          ├──────────────┬──────────────┬──────────────┐
          ▼              ▼              ▼              ▼
   ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐
   │  Worker 1  │ │  Worker 2  │ │  Worker 3  │ │  Worker N  │
   │   (导入)   │ │  (默认)    │ │  (维护)    │ │   (扩展)   │
   │ 4并发/100任务│ │ 4并发     │ │ 2并发     │ │   ...     │
   └────────────┘ └────────────┘ └────────────┘ └────────────┘
          │              │              │              │
          └──────────────┴──────────────┴──────────────┘
                               │
                               ▼
                    ┌──────────────────┐
                    │ Result Backend   │
                    │    (Redis)       │
                    │  - 任务状态存储   │
                    │  - 结果缓存      │
                    └──────────────────┘
```

### 2.2 任务队列设计

| 队列名称      | Worker名称         | 并发数 | 任务限制      | 用途                 |
|--------------|-------------------|-------|--------------|---------------------|
| `import`     | import_worker     | 4     | 100任务/重启  | 文档导入（CPU密集型） |
| `default`    | default_worker    | 4     | 1000任务/重启 | 通用任务             |
| `maintenance`| maintenance_worker| 2     | 1000任务/重启 | 维护任务（低优先级）  |

---

## 3. 安装依赖

### 3.1 安装Python依赖

```bash
# 进入项目目录
cd PRJECTPATH

# 安装依赖
pip install -r requirements.txt
```

**requirements.txt 核心依赖：**
```txt
celery>=5.3.0
redis>=5.0.0
flask>=3.0.0
elasticsearch==8.13.0
sentence-transformers>=2.2.2
```

### 3.2 验证安装

```bash
# 检查Celery版本
celery --version

# 检查Python包
python -c "import celery, redis; print(f'Celery: {celery.__version__}, Redis: {redis.__version__}')"
```

---

## 4. Redis部署与配置

### 4.1 安装Redis

#### 方式1: Docker部署（推荐开发环境）

```bash
# 拉取Redis镜像
docker pull redis:latest

# 启动Redis容器（持久化数据）
docker run -d \
  --name bible-redis \
  -p 6379:6379 \
  -v /var/fpwork/redis_data:/data \
  redis:latest \
  redis-server --appendonly yes
```

#### 方式2: 系统包管理器（推荐生产环境）

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install redis-server -y

# CentOS/RHEL
sudo yum install redis -y
```

#### 方式3: 源码编译

```bash
# 下载Redis
wget https://download.redis.io/releases/redis-7.0.15.tar.gz
tar xzf redis-7.0.15.tar.gz
cd redis-7.0.15

# 编译安装
make
sudo make install

# 复制配置文件
sudo cp redis.conf /etc/redis.conf
```

### 4.2 Redis配置文件

编辑 `/etc/redis.conf` 或 `/etc/redis/redis.conf`:

```conf
# ==================== 基础配置 ====================
# 绑定地址（生产环境设置为具体IP）
bind 127.0.0.1

# 端口
port 6379

# 守护进程模式
daemonize yes

# PID文件
pidfile /var/run/redis_6379.pid

# 日志级别: debug, verbose, notice, warning
loglevel notice

# 日志文件
logfile /var/log/redis/redis.log

# 数据库数量
databases 16

# ==================== 持久化配置 ====================
# RDB快照
save 900 1      # 900秒内至少1个键变化
save 300 10     # 300秒内至少10个键变化
save 60 10000   # 60秒内至少10000个键变化

# RDB文件名
dbfilename dump.rdb

# 工作目录
dir /var/lib/redis

# AOF持久化（推荐开启）
appendonly yes
appendfilename "appendonly.aof"
appendfsync everysec  # 每秒同步一次

# ==================== 内存管理 ====================
# 最大内存（根据实际情况调整）
maxmemory 2gb

# 内存淘汰策略（重要！）
# allkeys-lru: 所有键LRU淘汰（推荐Celery使用）
# volatile-lru: 仅淘汰设置了过期时间的键
maxmemory-policy allkeys-lru

# ==================== 安全配置 ====================
# 设置密码（生产环境强烈推荐）
# requirepass your_strong_password_here

# 禁用危险命令
rename-command FLUSHDB ""
rename-command FLUSHALL ""
rename-command CONFIG ""

# ==================== 性能优化 ====================
# TCP连接队列
tcp-backlog 511

# 超时时间（0表示禁用）
timeout 0

# TCP keepalive
tcp-keepalive 300

# 最大客户端连接数
maxclients 10000
```

### 4.3 启动Redis

```bash
# 方式1: 系统服务
sudo systemctl start redis
sudo systemctl enable redis  # 开机自启
sudo systemctl status redis

# 方式2: 直接启动
redis-server /etc/redis.conf

# 方式3: Docker
docker start bible-redis
```

### 4.4 验证Redis

```bash
# 测试连接
redis-cli ping
# 应该返回: PONG

# 查看信息
redis-cli info

# 测试读写
redis-cli set test "hello"
redis-cli get test
redis-cli del test
```

---

## 5. Celery配置

### 5.1 配置文件说明

#### config.py - Redis连接配置

```python
# ==================== Celery配置 ====================
# Redis配置（用作Celery的broker和backend）
REDIS_HOST = "localhost"       # Redis服务器地址
REDIS_PORT = 6379              # Redis端口
REDIS_DB = 0                   # 使用的数据库编号（0-15）
REDIS_PASSWORD = None          # Redis密码（如有）

# 构建Redis URL
if REDIS_PASSWORD:
    REDIS_URL = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
else:
    REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

# 是否使用Celery
USE_CELERY = True  # True: 使用Celery异步, False: 使用TaskManager同步
```

#### celery_app.py - Celery应用实例

```python
#!/usr/bin/env python3
"""
Celery应用配置
"""
from celery import Celery
from config import REDIS_URL

# 创建Celery实例
celery_app = Celery(
    'bible_server',                    # 应用名称
    broker=REDIS_URL,                  # 任务队列（Redis）
    backend=REDIS_URL,                 # 结果存储（Redis）
    include=['x_logic.celery_tasks']   # 自动发现任务模块
)

# 从配置文件加载
from celery_config import configure_celery
configure_celery(celery_app)

if __name__ == '__main__':
    celery_app.start()
```

#### celery_config.py - Celery详细配置

```python
#!/usr/bin/env python3
"""
Celery配置
"""
from celery.schedules import crontab

def configure_celery(app):
    """配置Celery应用"""
    
    app.conf.update(
        # ==================== 任务路由配置 ====================
        task_routes={
            # 导入任务 -> import队列
            'tasks.import_documents': {
                'queue': 'import',
                'routing_key': 'import.documents',
            },
            # 维护任务 -> maintenance队列
            'tasks.cleanup_old_tasks': {
                'queue': 'maintenance',
                'routing_key': 'maintenance.cleanup',
            },
        },
        
        # ==================== 默认队列配置 ====================
        task_default_queue='default',
        task_default_exchange='tasks',
        task_default_routing_key='default',
        
        # ==================== 序列化配置 ====================
        task_serializer='json',          # 任务序列化格式
        result_serializer='json',        # 结果序列化格式
        accept_content=['json'],         # 接受的内容类型
        
        # ==================== 时区配置 ====================
        timezone='Asia/Shanghai',        # 时区
        enable_utc=True,                 # 启用UTC
        
        # ==================== 任务执行配置 ====================
        task_track_started=True,         # 跟踪任务开始状态
        task_time_limit=3600,            # 任务硬超时（秒）
        task_soft_time_limit=3300,       # 任务软超时（秒）
        task_acks_late=True,             # 任务完成后才确认
        task_reject_on_worker_lost=True, # worker挂了重新排队
        
        # ==================== Worker配置 ====================
        worker_prefetch_multiplier=4,    # 每个worker预取任务数
        worker_max_tasks_per_child=1000, # worker处理N个任务后重启
        
        # ==================== 结果后端配置 ====================
        result_expires=86400,            # 结果过期时间（24小时）
        result_backend_transport_options={
            'master_name': 'mymaster',   # Redis Sentinel配置（如使用）
        },
        
        # ==================== Broker配置 ====================
        broker_connection_retry_on_startup=True,  # 启动时重试连接
        broker_connection_retry=True,             # 连接失败时重试
        broker_connection_max_retries=10,         # 最大重试次数
        
        # ==================== 性能优化 ====================
        worker_disable_rate_limits=True,          # 禁用速率限制
        task_compression='gzip',                  # 任务压缩
        result_compression='gzip',                # 结果压缩
    )
    
    # ==================== 定时任务配置（可选） ====================
    app.conf.beat_schedule = {
        'cleanup-old-tasks': {
            'task': 'tasks.cleanup_old_tasks',
            'schedule': crontab(hour=2, minute=0),  # 每天凌晨2点
        },
    }
```

### 5.2 环境变量配置（可选）

创建 `.env` 文件：

```bash
# Redis配置
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

# Celery配置
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# 应用配置
USE_CELERY=True
```

---

## 6. 部署流程

### 6.1 部署前检查清单

- [ ] Redis服务已启动并可访问
- [ ] Python依赖已安装
- [ ] 配置文件已正确填写
- [ ] 日志目录有写权限
- [ ] 网络端口已开放（Redis: 6379, Flower: 5555）

### 6.2 创建必要目录

```bash
cd /var/fpwork/jerzhang/BiBLE-Atlas

# 创建日志目录
mkdir -p logs

# 设置权限
chmod 755 logs

# 创建Redis数据目录（如需）
sudo mkdir -p /var/lib/redis
sudo chown redis:redis /var/lib/redis
```

### 6.3 配置文件权限

```bash
# 启动脚本加执行权限
chmod +x start_celery.sh
chmod +x stop_celery.sh
chmod +x start_flower.sh
```

### 6.4 测试连接

```bash
# 测试Redis连接
python3 << EOF
import redis
from config import REDIS_HOST, REDIS_PORT, REDIS_DB
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
print("Redis连接:", r.ping())
EOF
```

---

## 7. 启动与停止服务

### 7.1 启动服务

#### 步骤1: 启动Redis

```bash
# 系统服务方式
sudo systemctl start redis

# 或Docker方式
docker start bible-redis

# 验证Redis
redis-cli ping
```

#### 步骤2: 启动Celery Workers

```bash
# 使用启动脚本（推荐）
./start_celery.sh

# 查看输出
========================================
启动 Celery Workers
========================================
启动 Worker 1: import 队列
启动 Worker 2: default 队列
启动 Worker 3: maintenance 队列

========================================
✓ 所有 Celery Workers 已启动
========================================
```

#### 步骤3: 启动Flower监控（可选）

```bash
./start_flower.sh

# 访问监控界面
# http://localhost:5555
```

#### 步骤4: 启动Flask应用

```bash
# 开发环境
python app.py

# 生产环境（使用Gunicorn）
gunicorn -w 4 -b 0.0.0.0:9220 app:server
```

### 7.2 验证服务

```bash
# 检查Worker状态
celery -A celery_app status

# 查看活动任务
celery -A celery_app inspect active

# 查看注册的任务
celery -A celery_app inspect registered

# 查看统计信息
celery -A celery_app inspect stats

# 检查队列
celery -A celery_app inspect active_queues
```

### 7.3 停止服务

#### 停止Celery Workers

```bash
# 使用停止脚本（推荐）
./stop_celery.sh

========================================
停止 Celery Workers
========================================
停止 celery_import_worker (PID: 12345)
  ✓ celery_import_worker 已停止
停止 celery_default_worker (PID: 12346)
  ✓ celery_default_worker 已停止
停止 celery_maintenance_worker (PID: 12347)
  ✓ celery_maintenance_worker 已停止

✓ 所有 Celery Workers 已停止
```

#### 停止Flower

```bash
# 查找Flower进程
ps aux | grep flower

# 停止Flower
pkill -f 'celery.*flower'

# 或使用PID文件
if [ -f logs/flower.pid ]; then
    kill $(cat logs/flower.pid)
    rm logs/flower.pid
fi
```

#### 停止Redis

```bash
# 系统服务方式
sudo systemctl stop redis

# 或Docker方式
docker stop bible-redis

# 直接停止
redis-cli shutdown
```

### 7.4 重启服务

```bash
# 重启Workers
./stop_celery.sh && sleep 2 && ./start_celery.sh

# 清空所有任务（慎用！）
celery -A celery_app purge
```

---

## 8. 监控与维护

### 8.1 Flower监控界面

访问 `http://localhost:5555` 查看：
- ✅ Workers状态和统计
- ✅ 任务执行情况
- ✅ 队列长度
- ✅ 任务成功/失败率
- ✅ Worker资源使用

### 8.2 命令行监控

#### 实时监控

```bash
# 实时查看任务
celery -A celery_app events

# 实时查看活动任务
watch -n 2 'celery -A celery_app inspect active'
```

#### 队列监控

```bash
# 查看队列长度
redis-cli llen celery

# 查看所有队列
redis-cli keys "celery*"

# 查看队列详情
celery -A celery_app inspect active_queues
```

#### Worker监控

```bash
# Worker统计
celery -A celery_app inspect stats

# Worker配置
celery -A celery_app inspect conf

# Worker注册的任务
celery -A celery_app inspect registered
```

### 8.3 日志管理

#### 日志文件位置

```bash
logs/
├── celery_import_worker.log       # 导入Worker日志
├── celery_default_worker.log      # 默认Worker日志
├── celery_maintenance_worker.log  # 维护Worker日志
└── flower.log                     # Flower日志
```

#### 查看日志

```bash
# 实时查看日志
tail -f logs/celery_import_worker.log

# 查看最近100行
tail -n 100 logs/celery_default_worker.log

# 搜索错误
grep -i "error" logs/*.log

# 搜索特定任务
grep "task_id" logs/*.log
```

#### 日志轮转配置

创建 `/etc/logrotate.d/bible_celery`:

```conf
/var/fpwork/jerzhang/BiBLE-Atlas/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0644 jerzhang jerzhang
    postrotate
        # 重新打开日志文件
        pkill -HUP -f 'celery.*worker'
    endscript
}
```

### 8.4 健康检查

创建健康检查脚本 `health_check.sh`:

```bash
#!/bin/bash

echo "==================== 健康检查 ===================="

# 检查Redis
echo -n "Redis: "
if redis-cli ping > /dev/null 2>&1; then
    echo "✓ OK"
else
    echo "✗ FAILED"
    exit 1
fi

# 检查Celery Workers
echo -n "Celery Workers: "
worker_count=$(celery -A celery_app status 2>/dev/null | grep -c "OK")
if [ "$worker_count" -ge 3 ]; then
    echo "✓ OK ($worker_count workers)"
else
    echo "✗ FAILED (expected 3, got $worker_count)"
    exit 1
fi

# 检查队列
echo -n "Queue lengths: "
import_queue=$(redis-cli llen import 2>/dev/null || echo 0)
default_queue=$(redis-cli llen default 2>/dev/null || echo 0)
echo "import=$import_queue, default=$default_queue"

# 检查Flower
echo -n "Flower: "
if curl -s http://localhost:5555 > /dev/null; then
    echo "✓ OK"
else
    echo "✗ FAILED"
fi

echo "=================================================="
```

使用：

```bash
chmod +x health_check.sh
./health_check.sh
```

### 8.5 任务清理

定期清理过期任务：

```bash
# 清理所有待处理任务（慎用！）
celery -A celery_app purge

# 清理特定队列
celery -A celery_app purge -Q import

# 清理Redis中的过期结果
redis-cli --scan --pattern "celery-task-meta-*" | xargs redis-cli del
```

---

## 9. 故障排查

### 9.1 Redis连接问题

#### 症状
```
kombu.exceptions.OperationalError: Error 111 connecting to localhost:6379. Connection refused.
```

#### 排查步骤

```bash
# 1. 检查Redis是否运行
redis-cli ping
sudo systemctl status redis

# 2. 检查端口是否监听
sudo netstat -tlnp | grep 6379
sudo lsof -i :6379

# 3. 检查防火墙
sudo iptables -L -n | grep 6379

# 4. 检查Redis日志
sudo tail -f /var/log/redis/redis.log

# 5. 测试连接
redis-cli -h localhost -p 6379 ping
```

#### 解决方案

```bash
# 启动Redis
sudo systemctl start redis

# 或
redis-server /etc/redis.conf

# 检查绑定地址（如需远程访问）
# 编辑 /etc/redis.conf
# bind 127.0.0.1 改为 bind 0.0.0.0（注意安全性！）
```

### 9.2 Worker无法启动

#### 症状
```
[ERROR/MainProcess] consumer: Cannot connect to redis://localhost:6379/0
```

#### 排查步骤

```bash
# 1. 检查配置
python3 -c "from config import REDIS_URL; print(REDIS_URL)"

# 2. 测试Python连接
python3 << EOF
import redis
from config import REDIS_HOST, REDIS_PORT, REDIS_DB
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
print(r.ping())
EOF

# 3. 检查PID文件冲突
rm -f logs/*.pid

# 4. 检查日志目录权限
ls -ld logs/
chmod 755 logs/
```

### 9.3 任务堆积

#### 症状
- 队列长度持续增长
- 任务处理缓慢

#### 排查步骤

```bash
# 1. 查看队列长度
redis-cli llen celery

# 2. 查看活动任务
celery -A celery_app inspect active

# 3. 查看Worker状态
celery -A celery_app inspect stats
```

#### 解决方案

```bash
# 1. 增加Worker并发数
# 编辑 start_celery.sh，将 --concurrency=4 改为 --concurrency=8

# 2. 启动额外的Worker
celery -A celery_app worker -Q import --concurrency=4 -n import_worker_2@%h

# 3. 清理无用任务（慎用）
celery -A celery_app purge
```

### 9.4 内存泄漏

#### 症状
- Worker内存持续增长
- 系统OOM

#### 排查步骤

```bash
# 1. 查看进程内存
ps aux | grep celery

# 2. 监控内存增长
watch -n 5 'ps aux | grep celery | grep -v grep'
```

#### 解决方案

```bash
# 1. 减少每个worker处理的任务数
# 编辑 start_celery.sh
# 将 --max-tasks-per-child=1000 改为 --max-tasks-per-child=100

# 2. 减少预取任务数
# 编辑 celery_config.py
# 将 worker_prefetch_multiplier=4 改为 worker_prefetch_multiplier=1

# 3. 重启Worker
./stop_celery.sh && ./start_celery.sh
```

### 9.5 任务状态丢失

#### 症状
- API查询任务返回PENDING
- 任务实际已完成

#### 排查步骤

```bash
# 1. 检查Redis数据
redis-cli keys "celery-task-meta-*"

# 2. 检查result过期时间
redis-cli ttl "celery-task-meta-<task_id>"

# 3. 检查Backend配置
python3 -c "from celery_app import celery_app; print(celery_app.conf.result_backend)"
```

#### 解决方案

```bash
# 1. 增加结果过期时间
# 编辑 celery_config.py
# result_expires=86400  # 改为更长时间

# 2. 确保任务更新状态
# 在任务中使用 self.update_state()
```

### 9.6 Flower无法访问

#### 症状
- http://localhost:5555 无法打开

#### 排查步骤

```bash
# 1. 检查Flower进程
ps aux | grep flower

# 2. 检查端口
netstat -tlnp | grep 5555

# 3. 检查日志
tail -f logs/flower.log
```

#### 解决方案

```bash
# 重新启动Flower
pkill -f 'celery.*flower'
./start_flower.sh

# 或手动启动
celery -A celery_app flower --port=5555
```

---

## 10. 性能优化

### 10.1 Redis优化

#### 配置优化

```conf
# /etc/redis.conf

# 1. 内存优化
maxmemory 4gb
maxmemory-policy allkeys-lru

# 2. 持久化优化
# 如果不需要持久化（任务可重做），可以禁用
# save ""
# appendonly no

# 3. 网络优化
tcp-backlog 511
tcp-keepalive 300

# 4. 慢查询日志
slowlog-log-slower-than 10000  # 10ms
slowlog-max-len 128
```

#### 监控慢查询

```bash
# 查看慢查询
redis-cli slowlog get 10

# 重置慢查询日志
redis-cli slowlog reset
```

### 10.2 Celery优化

#### Worker并发策略

根据任务类型选择并发模型：

```bash
# CPU密集型（默认prefork）
celery -A celery_app worker --pool=prefork --concurrency=4

# I/O密集型（使用gevent）
pip install gevent
celery -A celery_app worker --pool=gevent --concurrency=100

# 混合型（使用eventlet）
pip install eventlet
celery -A celery_app worker --pool=eventlet --concurrency=100
```

#### 任务优化配置

```python
# celery_config.py

app.conf.update(
    # 1. 禁用速率限制
    worker_disable_rate_limits=True,
    
    # 2. 启用压缩
    task_compression='gzip',
    result_compression='gzip',
    
    # 3. 优化预取
    worker_prefetch_multiplier=1,  # 公平调度
    
    # 4. 优化序列化
    task_serializer='msgpack',     # 比JSON更快
    result_serializer='msgpack',
    accept_content=['msgpack'],
    
    # 5. 禁用结果存储（如不需要）
    task_ignore_result=True,
)
```

#### 任务设计优化

```python
# x_logic/celery_tasks.py

from celery_app import celery_app

@celery_app.task(
    bind=True,
    max_retries=3,                  # 最大重试次数
    default_retry_delay=60,         # 重试延迟（秒）
    autoretry_for=(Exception,),     # 自动重试的异常
    retry_backoff=True,             # 指数退避
    retry_jitter=True,              # 添加随机延迟
    time_limit=3600,                # 硬超时
    soft_time_limit=3300,           # 软超时
)
def import_documents(self, ...):
    try:
        # 定期更新状态
        self.update_state(state='PROGRESS', meta={'current': 10, 'total': 100})
        
        # 分批处理（避免内存峰值）
        batch_size = 100
        for i in range(0, total, batch_size):
            batch = items[i:i+batch_size]
            process_batch(batch)
            
            # 更新进度
            progress = int((i + batch_size) / total * 100)
            self.update_state(state='PROGRESS', meta={'progress': progress})
        
        return {'status': 'success', 'total': total}
    
    except Exception as exc:
        # 重试
        raise self.retry(exc=exc, countdown=60)
```

### 10.3 系统级优化

#### 文件描述符限制

```bash
# 检查当前限制
ulimit -n

# 临时提高限制
ulimit -n 65535

# 永久修改 /etc/security/limits.conf
* soft nofile 65535
* hard nofile 65535
```

#### 进程数限制

```bash
# 检查
ulimit -u

# 修改 /etc/security/limits.conf
* soft nproc 65535
* hard nproc 65535
```

#### 内核参数优化

```bash
# /etc/sysctl.conf

# TCP优化
net.core.somaxconn = 1024
net.ipv4.tcp_max_syn_backlog = 2048

# 内存优化
vm.overcommit_memory = 1

# 应用配置
sudo sysctl -p
```

### 10.4 监控指标

#### 关键指标

| 指标 | 阈值 | 说明 |
|------|------|------|
| Redis内存使用率 | < 80% | 超过需扩容或清理 |
| 队列长度 | < 1000 | 超过需增加Worker |
| 任务平均执行时间 | < 5分钟 | 超过需优化任务 |
| Worker CPU使用率 | < 80% | 超过需增加Worker |
| 任务失败率 | < 1% | 超过需排查问题 |

#### 监控命令

```bash
# 1. Redis监控
redis-cli info memory
redis-cli info stats
redis-cli --stat

# 2. Celery监控
celery -A celery_app inspect stats

# 3. 系统监控
top -p $(pgrep -d',' -f celery)
htop -p $(pgrep -d',' -f celery)
```

---

## 附录

### A. 完整启动脚本

#### start_all.sh - 一键启动所有服务

```bash
#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "========================================="
echo "  启动 Bible Server 所有服务"
echo "========================================="

# 1. 启动Redis
echo "✓ 启动 Redis..."
if ! redis-cli ping > /dev/null 2>&1; then
    sudo systemctl start redis
    sleep 2
fi

# 2. 启动Celery Workers
echo "✓ 启动 Celery Workers..."
./start_celery.sh

# 3. 启动Flower
echo "✓ 启动 Flower 监控..."
./start_flower.sh

# 4. 启动Flask应用
echo "✓ 启动 Flask 应用..."
nohup python app.py > logs/flask.log 2>&1 &
echo $! > logs/flask.pid

sleep 2

echo ""
echo "========================================="
echo "  所有服务已启动"
echo "========================================="
echo "Flask API: http://localhost:9220"
echo "Flower监控: http://localhost:5555"
echo ""
```

#### stop_all.sh - 一键停止所有服务

```bash
#!/bin/bash

cd "$(dirname "$0")"

echo "========================================="
echo "  停止 Bible Server 所有服务"
echo "========================================="

# 1. 停止Flask
echo "✓ 停止 Flask..."
if [ -f logs/flask.pid ]; then
    kill $(cat logs/flask.pid) 2>/dev/null || true
    rm -f logs/flask.pid
fi

# 2. 停止Flower
echo "✓ 停止 Flower..."
pkill -f 'celery.*flower' || true

# 3. 停止Celery Workers
echo "✓ 停止 Celery Workers..."
./stop_celery.sh

# 4. 清理PID文件
rm -f logs/*.pid

echo ""
echo "✓ 所有服务已停止"
echo ""
```

### B. 常用命令速查

```bash
# ==================== Redis ====================
redis-cli ping                           # 测试连接
redis-cli info                           # 查看信息
redis-cli monitor                        # 实时监控
redis-cli --stat                         # 统计信息
redis-cli keys "celery*"                 # 查看Celery键
redis-cli flushdb                        # 清空数据库（慎用！）

# ==================== Celery ====================
celery -A celery_app status              # Worker状态
celery -A celery_app inspect active      # 活动任务
celery -A celery_app inspect stats       # 统计信息
celery -A celery_app inspect registered  # 注册的任务
celery -A celery_app purge               # 清空所有队列
celery -A celery_app control shutdown    # 关闭所有Worker

# ==================== 监控 ====================
tail -f logs/celery_import_worker.log    # 查看日志
watch -n 2 'celery -A celery_app status' # 实时监控
./health_check.sh                        # 健康检查

# ==================== 启动/停止 ====================
./start_celery.sh                        # 启动Workers
./stop_celery.sh                         # 停止Workers
./start_flower.sh                        # 启动Flower
./start_all.sh                           # 启动所有服务
./stop_all.sh                            # 停止所有服务
```

### C. 生产环境清单

部署到生产环境前的检查项：

- [ ] Redis配置了持久化（AOF）
- [ ] Redis设置了密码
- [ ] Redis禁用了危险命令
- [ ] Celery配置了任务超时
- [ ] Celery配置了任务重试
- [ ] 配置了日志轮转
- [ ] 设置了进程监控（systemd/supervisor）
- [ ] 配置了备份策略
- [ ] 配置了监控告警
- [ ] 测试了故障恢复流程

### D. 参考资料

- Celery官方文档: https://docs.celeryq.dev/
- Redis官方文档: https://redis.io/documentation
- Flower文档: https://flower.readthedocs.io/
- 最佳实践: https://docs.celeryq.dev/en/stable/userguide/tasks.html#best-practices

---

**文档版本**: 1.0  
**最后更新**: 2026-04-15  
**维护者**: jerzhang  

如有问题或建议，请联系技术团队。
