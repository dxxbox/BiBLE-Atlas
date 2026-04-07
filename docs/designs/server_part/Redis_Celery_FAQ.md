# Redis、Celery 和 FastAPI 异步任务说明

## 1. Redis 是什么？

**Redis**（Remote Dictionary Server）是一个开源的内存数据结构存储系统，可以用作：
- **消息队列（Message Broker）**：Celery 的消息中间件
- **缓存数据库**：高速缓存
- **分布式锁**：协调分布式系统
- **会话存储**：存储用户会话

**特点**：
- 基于内存，速度极快（微秒级响应）
- 支持多种数据结构（字符串、列表、集合、哈希表等）
- 支持持久化（可选）
- 单线程模型，原子操作

---

## 2. Redis 和 Celery 的关系

### Celery 需要 Redis 吗？

**不是必须 Redis，但 Redis 是最常用的选择。**

Celery 需要一个 **消息代理（Message Broker）** 来：
- 接收任务请求
- 分发任务给 Worker
- 存储任务结果

**Celery 支持的 Broker：**
| Broker | 推荐度 | 说明 |
|--------|--------|------|
| **Redis** | ⭐⭐⭐⭐⭐ | 最常用，性能好，功能全 |
| **RabbitMQ** | ⭐⭐⭐⭐⭐ | 功能最全，企业级，但部署复杂 |
| **Amazon SQS** | ⭐⭐⭐ | 云服务，无需维护，但有延迟 |
| **Database (SQLAlchemy)** | ⭐⭐ | 不推荐，性能差 |
| **Memory (开发用)** | ⭐ | 仅适合测试，重启丢失任务 |

**为什么我们选择 Redis？**
- ✅ 轻量级，易部署
- ✅ 性能优秀
- ✅ 可以同时用作缓存
- ✅ 社区支持好

### 没有 Redis 就不能用 Celery 吗？

**不需要 Redis！我们的设计支持降级方案：**

**Redis 可用时：**
- 使用 Redis 作为 Broker（推荐）
- 支持分布式 Worker
- 任务持久化，重启不丢失

**Redis 不可用时：**
- 自动降级为 **Memory Broker**
- 单机模式，任务存储在内存
- 适用场景：
  - ✅ 开发环境
  - ✅ 单机部署
  - ✅ 非关键任务（模型加载等）
- 限制：
  - ⚠️ 应用重启时，未完成任务会丢失
  - ⚠️ 不支持分布式多 Worker

**配置示例：**
```python
# config/celery_config.py
import os

redis_host = os.getenv('REDIS_HOST')
redis_port = os.getenv('REDIS_PORT', 6379)

if redis_host:
    # Redis 可用
    broker_url = f'redis://{redis_host}:{redis_port}/0'
    result_backend = f'redis://{redis_host}:{redis_port}/1'
    print("✓ Using Redis broker")
else:
    # 降级到 Memory
    broker_url = 'memory://'
    result_backend = 'cache+memory://'
    print("⚠ Using Memory broker (tasks will be lost on restart)")
```

**为什么 Memory Broker 在我们的场景中可以接受？**
- 主要用于 **模型加载任务**（启动时执行，非关键）
- 文档导入任务虽然重要，但失败后用户可以重新上传
- 单机部署时，简化架构，降低运维成本

---

## 3. Redis 可以和 FastAPI 部署在同一服务器吗？

**完全可以！非常常见的部署方式。**

### 单机部署（开发/小型应用）

```
同一服务器：
┌─────────────────────────────────┐
│  服务器 (1台)                    │
│                                 │
│  ┌─────────────────┐            │
│  │ FastAPI (8000)  │            │
│  └─────────────────┘            │
│           ↓                     │
│  ┌─────────────────┐            │
│  │ Redis (6379)    │ ← 本地连接 │
│  └─────────────────┘            │
│           ↓                     │
│  ┌─────────────────┐            │
│  │ Celery Worker   │            │
│  └─────────────────┘            │
│                                 │
└─────────────────────────────────┘

连接配置：
REDIS_HOST=localhost
REDIS_PORT=6379
```

### 生产环境部署（推荐）

```
多服务器（高可用）：
┌──────────────┐     ┌──────────────┐
│ FastAPI 1    │     │ FastAPI 2    │
│ (Web 服务器)  │     │ (Web 服务器)  │
└──────────────┘     └──────────────┘
       ↓                    ↓
       └────────┬───────────┘
                ↓
        ┌──────────────┐
        │ Redis        │ ← 独立服务器
        │ (消息队列)    │
        └──────────────┘
                ↓
       ┌────────┴────────┐
       ↓                 ↓
┌──────────────┐  ┌──────────────┐
│ Celery       │  │ Celery       │
│ Worker 1     │  │ Worker 2     │
└──────────────┘  └──────────────┘
```

**Docker Compose 单机部署示例：**

```yaml
version: '3.8'

services:
  fastapi:
    image: my-fastapi-app
    ports:
      - "8000:8000"
    environment:
      - REDIS_HOST=redis
      - REDIS_PORT=6379
    depends_on:
      - redis
      - elasticsearch

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  celery_worker:
    image: my-fastapi-app
    command: celery -A app.infrastructure.celery.app worker --loglevel=info
    environment:
      - REDIS_HOST=redis
    depends_on:
      - redis
      - elasticsearch

  elasticsearch:
    image: elasticsearch:8.11.3
    ports:
      - "9200:9200"
    environment:
      - discovery.type=single-node

volumes:
  redis_data:
```

---

## 4. FastAPI 还有其他支持异步任务的方式吗？

**是的！除了 Celery，还有多种选择：**

### 方案对比

| 方案 | 优点 | 缺点 | 适用场景 |
|------|------|------|---------|
| **Celery + Redis** | 成熟稳定，功能全，分布式 | 需要额外组件 | 生产环境，复杂任务 || **Celery + Memory** | 无需外部依赖，即开即用 | 重启丢失，不支持分布式 | 开发/单机部署 || **FastAPI BackgroundTasks** | 简单，无需外部依赖 | 单机，任务丢失风险 | 简单异步任务 |
| **asyncio.create_task** | 原生异步，轻量 | 单进程，任务丢失 | 轻量异步操作 |
| **线程池 ThreadPoolExecutor** | 简单，CPU密集任务 | 受 GIL 限制，不适合高并发 | CPU 密集型任务 |
| **进程池 ProcessPoolExecutor** | 真并行，绕过 GIL | 开销大，通信复杂 | CPU 密集型任务 |
| **Dramatiq** | 类似 Celery，更简单 | 生态小 | 中小型项目 |
| **ARQ** | Redis-only，简单 | 功能少 | 简单任务队列 |

### 1️⃣ FastAPI BackgroundTasks（内置）

**无需外部依赖，适合简单任务。**

```python
from fastapi import BackgroundTasks

def send_email(email: str, message: str):
    print(f"Sending email to {email}: {message}")
    # 实际发送邮件逻辑

@app.post("/send-notification/")
async def send_notification(
    email: str,
    background_tasks: BackgroundTasks
):
    background_tasks.add_task(send_email, email, "Welcome!")
    return {"message": "Notification sent in background"}
```

**缺点**：
- ❌ 任务在同一进程中执行，应用重启任务丢失
- ❌ 不支持分布式
- ❌ 不适合长时间运行的任务

### 2️⃣ asyncio.create_task（原生异步）

```python
import asyncio

async def load_model_async():
    print("Loading model...")
    await asyncio.sleep(10)  # 模拟加载
    print("Model loaded!")

@app.on_event("startup")
async def startup_event():
    # 后台加载模型，不阻塞启动
    asyncio.create_task(load_model_async())
```

**优点**：
- ✅ 原生 Python，无需外部依赖
- ✅ 轻量级

**缺点**：
- ❌ 单进程，重启丢失
- ❌ 不支持分布式

### 3️⃣ ThreadPoolExecutor（线程池）

**适合 I/O 密集型或调用同步库。**

```python
from concurrent.futures import ThreadPoolExecutor
import time

executor = ThreadPoolExecutor(max_workers=4)

def load_model_sync():
    print("Loading model in thread...")
    time.sleep(10)
    print("Model loaded!")

@app.on_event("startup")
async def startup_event():
    # 在线程中加载模型
    executor.submit(load_model_sync)
```

**优点**：
- ✅ 不阻塞主线程
- ✅ 适合调用同步库（如某些 ML 模型加载库）

**缺点**：
- ❌ 受 Python GIL 限制（CPU 密集型任务性能差）
- ❌ 不支持分布式
- ❌ 线程开销

### 4️⃣ ARQ（Redis 队列，轻量级）

**基于 Redis 的简单任务队列。**

```python
# 安装: pip install arq

from arq import create_pool
from arq.connections import RedisSettings

async def load_model_task(ctx):
    print("Loading model...")
    await asyncio.sleep(10)
    print("Model loaded!")

# 配置
class WorkerSettings:
    redis_settings = RedisSettings(host='localhost', port=6379)
    functions = [load_model_task]

# 启动 worker
# arq app.worker.WorkerSettings
```

**对比 Celery：**
- ✅ 更简单，代码少
- ✅ 只需 Redis
- ❌ 功能少（无任务优先级、无复杂路由）
- ❌ 社区小

---

## 5. FastAPI 使用线程的方式

**FastAPI 本身就使用线程池来处理同步函数！**

### FastAPI 的并发模型

```python
# 异步路由（在事件循环中执行）
@app.get("/async")
async def async_endpoint():
    await asyncio.sleep(1)
    return {"message": "async"}

# 同步路由（FastAPI 自动在线程池中执行）
@app.get("/sync")
def sync_endpoint():
    time.sleep(1)  # 阻塞调用
    return {"message": "sync"}
```

**FastAPI 内部机制：**
1. **异步函数** (`async def`)：在主事件循环中执行
2. **同步函数** (`def`)：自动提交到 **线程池** 执行（不阻塞事件循环）

**线程池大小：** 默认由 `uvicorn` 控制，可调整：
```bash
uvicorn main:app --workers 4 --limit-concurrency 1000
```

### 手动使用线程池

```python
from fastapi import FastAPI
from concurrent.futures import ThreadPoolExecutor
import asyncio

app = FastAPI()
executor = ThreadPoolExecutor(max_workers=10)

def cpu_intensive_task(n: int):
    """模拟 CPU 密集型任务"""
    result = sum(i * i for i in range(n))
    return result

@app.get("/compute/{n}")
async def compute(n: int):
    loop = asyncio.get_event_loop()
    # 在线程池中运行 CPU 密集型任务
    result = await loop.run_in_executor(executor, cpu_intensive_task, n)
    return {"result": result}
```

---

## 6. 我们的设计决策

### 为什么选择 Celery + Redis？

| 需求 | Celery + Redis | 其他方案 |
|------|---------------|---------|
| **模型加载（耗时>1分钟）** | ✅ 后台加载，不阻塞启动 | BackgroundTasks：重启丢失 |
| **文档导入（耗时任务）** | ✅ 分布式处理，可扩展 | 线程池：不能分布式 |
| **任务重试** | ✅ 内置重试机制 | 需要自己实现 |
| **任务监控** | ✅ Flower 监控工具 | 需要自己实现 |
| **任务优先级** | ✅ 支持 | 不支持 |
| **分布式扩展** | ✅ 多 Worker | 单机 |

### 我们的设计：优雅降级

```python
# 启动时检查 Redis 可用性
if redis_available:
    # 使用 Celery：后台加载模型
    init_celery()
    if config.load_on_startup:
        load_vector_models_task.delay()  # 异步加载
else:
    # 降级方案：同步加载
    logger.warning("Redis not available, loading models synchronously")
    if config.load_on_startup:
        load_vector_models_sync()  # 阻塞启动
```

**优势：**
- ✅ 有 Redis：最佳体验（后台加载）
- ✅ 无 Redis：仍可启动（同步加载）
- ✅ 灵活可配置

---

## 7. 推荐部署方案

### 开发环境
```bash
# 单机，所有服务在一起
docker-compose up
```

### 生产环境（小型）
```bash
# 单服务器，Redis 在本地
FastAPI + Redis + Celery Worker (同一台服务器)
```

### 生产环境（大型）
```bash
# 分布式部署
- FastAPI 服务器 × 2-4（负载均衡）
- Redis 服务器 × 1（独立，或 Redis Cluster）
- Celery Worker × 2-8（独立，可动态扩展）
- Elasticsearch 集群 × 3+
```

---

## 总结

1. **Redis 是什么**：内存数据库，用作 Celery 的消息队列
2. **Redis 必需吗**：不是，但是推荐；没有 Redis 时系统改用同步加载
3. **同服务器部署**：完全可以，开发环境常用
4. **FastAPI 其他异步方案**：BackgroundTasks、asyncio.create_task、线程池、ARQ 等
5. **线程使用**：FastAPI 内置线程池处理同步函数；可手动使用 ThreadPoolExecutor
6. **我们的选择**：Celery + Redis（最佳），同时支持降级到同步加载
