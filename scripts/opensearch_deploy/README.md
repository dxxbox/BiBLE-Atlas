# OpenSearch 多用户部署方案

本目录提供了完整的多用户 OpenSearch 部署解决方案，支持在同一台服务器上运行多个独立的 OpenSearch 实例。

## 📁 目录结构

```
opensearch_deploy/
├── deploy.sh                      # 部署脚本（主要工具）
├── quickstart.sh                  # 交互式快速配置向导
├── docker-compose.template.yml    # Docker Compose 模板
├── opensearch.yml                 # OpenSearch 配置模板
├── README.md                      # 本文档
└── EXAMPLES.md                    # 使用示例
```

## 🚀 快速开始

### 方式一：交互式向导（推荐新手）

```bash
# 运行交互式快速配置向导，按提示选择配置方案
./quickstart.sh
```

向导会引导你：
1. 选择预设配置方案（小型/中型/大型/超大/自定义）
2. 输入用户名（实例名称）
3. 确认或修改端口（自动推荐可用端口）
4. 确认创建，并可选择立即启动

### 方式二：命令行直接创建

### 1. 创建实例

```bash
# 基本语法
./deploy.sh create <用户名> <HTTP端口> <Dashboard端口> <CPU核心数> <内存GB>

# 示例：创建用户1的实例（中型配置：6核/20GB）
./deploy.sh create user1 9201 5602 6 20

# 示例：创建用户2的实例（小型配置：4核/12GB）
./deploy.sh create user2 9202 5603 4 12
```

### 2. 启动实例

```bash
./deploy.sh start user1
```

### 3. 查看状态

```bash
# 查看所有实例
./deploy.sh status

# 查看指定实例
./deploy.sh status user1
```

### 4. 访问服务

```bash
# OpenSearch API
curl http://localhost:9201

# 查看集群健康
curl http://localhost:9201/_cluster/health?pretty

# 访问 Dashboard（浏览器）
http://localhost:5602
```

## 📋 完整命令列表

| 命令 | 说明 | 示例 |
|------|------|------|
| `create` | 创建新实例 | `./deploy.sh create user1 9201 5602 6 20` |
| `pull` | 拉取 Docker 镜像 | `./deploy.sh pull` 或 `./deploy.sh pull user1` |
| `start` | 启动实例 | `./deploy.sh start user1` |
| `stop` | 停止实例 | `./deploy.sh stop user1` |
| `restart` | 重启实例 | `./deploy.sh restart user1` |
| `delete` | 删除实例 | `./deploy.sh delete user1` |
| `status` | 查看状态 | `./deploy.sh status [user1]` |
| `logs` | 查看日志 | `./deploy.sh logs user1 [100]` |
| `list` | 列出所有实例 | `./deploy.sh list` |
| `info` | 显示详细信息 | `./deploy.sh info user1` |
| `help` | 显示帮助 | `./deploy.sh help` |

## 🐳 Docker 镜像管理

### 镜像拉取时机

脚本会在以下情况自动处理镜像：

1. **首次启动实例时自动拉取**
   ```bash
   ./deploy.sh start user1
   # 如果本地没有镜像，会自动拉取（约1.2GB）
   ```

2. **预先拉取镜像（推荐）**
   ```bash
   # 在创建实例前预先拉取，避免首次启动等待
   ./deploy.sh pull
   
   # 或为特定实例拉取
   ./deploy.sh pull user1
   ```

### 镜像说明

脚本使用以下 Docker 镜像：

- **OpenSearch**: `opensearchproject/opensearch:latest` (最新版本)
- **OpenSearch Dashboards**: `opensearchproject/opensearch-dashboards:latest` (最新版本)

> 注：使用 `latest` 标签会自动获取最新稳定版本（目前为 3.x 系列）

### 镜像管理命令

```bash
# 查看本地镜像
docker images | grep opensearch

# 手动拉取最新镜像
docker pull opensearchproject/opensearch:latest
docker pull opensearchproject/opensearch-dashboards:latest

# 或拉取特定版本（如果需要）
# docker pull opensearchproject/opensearch:3.0.0
# docker pull opensearchproject/opensearch-dashboards:3.0.0

# 清理未使用的镜像
docker image prune -a

# 查看镜像大小
docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}" | grep opensearch
```

### 首次使用建议

```bash
# 1. 预先拉取镜像（避免首次启动等待）
./deploy.sh pull

# 2. 创建实例
./deploy.sh create user1 9201 5602 6 20

# 3. 启动实例（镜像已存在，启动更快）
./deploy.sh start user1
```

## 🎯 资源配置预设

根据你的服务器配置（36核/133GB），推荐以下配置方案：

### 方案一：使用一半资源（18核/66GB）

**单实例（独占）：**
```bash
./deploy.sh create main 9201 5601 18 66
```

**性能预期：**
- 批量索引：25,000-40,000 docs/s
- 查询延迟：<15ms (P95)
- 并发查询：1,000-1,500 QPS

### 方案二：3个用户均分（每人6核/20GB）

```bash
./deploy.sh create user1 9201 5602 6 20
./deploy.sh create user2 9202 5603 6 20
./deploy.sh create user3 9203 5604 6 20
```

**每个实例性能预期：**
- 批量索引：8,000-12,000 docs/s
- 查询延迟：<30ms (P95)
- 并发查询：300-500 QPS

### 方案三：混合配置

```bash
# 主实例（生产）：12核/40GB
./deploy.sh create prod 9201 5601 12 40

# 开发实例：4核/12GB
./deploy.sh create dev 9202 5602 4 12

# 测试实例：2核/8GB
./deploy.sh create test 9203 5603 2 8
```

## 📊 端口规划

建议按照以下规则分配端口：

| 用户 | HTTP端口 | 性能监控端口 | Dashboard端口 |
|------|----------|-------------|---------------|
| user1 | 9201 | 9601 | 5602 |
| user2 | 9202 | 9602 | 5603 |
| user3 | 9203 | 9603 | 5604 |
| user4 | 9204 | 9604 | 5605 |
| ... | ... | ... | ... |

**计算公式：**
- HTTP端口 = 9200 + N
- 性能监控端口 = HTTP端口 + 400
- Dashboard端口 = 5601 + N

## 🗂️ 数据目录结构

默认数据目录：`<脚本目录>/opensearch/<用户名>/`

```
./opensearch/user1/
├── data/                    # OpenSearch 数据
├── logs/                    # 日志文件
├── backup/                  # 备份目录
├── config/                  # 配置文件
│   └── opensearch.yml
├── docker-compose.yml       # Docker Compose 配置
└── instance.info            # 实例信息
```

## 🔧 自定义配置

### 修改数据存储位置

```bash
# 默认情况下，实例数据存储在脚本目录下的 opensearch/ 子目录
# 例如：./opensearch/user1/

# 如果需要修改存储位置，设置环境变量：
export OPENSEARCH_BASE_DIR=/data/opensearch

# 然后创建实例
./deploy.sh create user1 9201 5602 6 20

# 或者一次性指定：
OPENSEARCH_BASE_DIR=/data/opensearch ./deploy.sh create user1 9201 5602 6 20
```

### 修改实例配置

1. 编辑实例的 `docker-compose.yml`：
   ```bash
   # 默认路径：
   vi ./opensearch/user1/docker-compose.yml
   
   # 或者自定义路径：
   vi /data/opensearch/user1/docker-compose.yml
   ```

2. 重启实例：
   ```bash
   ./deploy.sh restart user1
   ```

### 启用安全插件

编辑 `docker-compose.yml`，修改以下配置：

```yaml
environment:
  - plugins.security.disabled=false
  - OPENSEARCH_INITIAL_ADMIN_PASSWORD=YourStrongPassword123!
  - plugins.security.ssl.http.enabled=true
```

## 🔍 故障排查

### 1. 容器无法启动

```bash
# 查看日志
./deploy.sh logs user1

# 检查端口占用
netstat -tlnp | grep 9201

# 检查目录权限（使用实际的路径）
ls -la ./opensearch/user1/data
# 或
 ls -la $OPENSEARCH_BASE_DIR/user1/data
```

### 2. 内存不足

```bash
# 查看容器资源使用
docker stats opensearch-user1

# 查看 JVM 内存
curl http://localhost:9201/_nodes/stats/jvm?pretty
```

### 3. 数据目录权限错误

```bash
# 修复权限（需要 root 权限）
# OpenSearch 容器使用 UID 1000
sudo chown -R 1000:1000 ./opensearch/user1/data
sudo chown -R 1000:1000 ./opensearch/user1/logs

# 或者使用自定义路径：
# sudo chown -R 1000:1000 $OPENSEARCH_BASE_DIR/user1/data
# sudo chown -R 1000:1000 $OPENSEARCH_BASE_DIR/user1/logs
```

### 4. 端口冲突

```bash
# 删除实例并使用新端口重建
./deploy.sh delete user1 --keep-data
./deploy.sh create user1 9211 5612 6 20
```

## 📈 监控和维护

### 健康检查

```bash
# 集群健康
curl http://localhost:9201/_cluster/health?pretty

# 节点统计
curl http://localhost:9201/_nodes/stats?pretty

# 索引列表
curl http://localhost:9201/_cat/indices?v
```

### 性能监控

```bash
# 实时监控容器资源
docker stats opensearch-user1

# 查看线程池状态
curl "http://localhost:9201/_cat/thread_pool?v"

# 查看节点负载
curl "http://localhost:9201/_cat/nodes?v&h=name,heap.percent,ram.percent,cpu,load_1m"
```

### 数据备份

```bash
# 创建快照仓库
curl -X PUT "http://localhost:9201/_snapshot/my_backup" \
  -H 'Content-Type: application/json' -d'
{
  "type": "fs",
  "settings": {
    "location": "/usr/share/opensearch/backup"
  }
}'

# 创建快照
curl -X PUT "http://localhost:9201/_snapshot/my_backup/snapshot_$(date +%Y%m%d)?wait_for_completion=true"
```

## ⚙️ 高级功能

### 批量操作

```bash
# 批量启动
for user in user1 user2 user3; do
    ./deploy.sh start $user
done

# 批量停止
for user in user1 user2 user3; do
    ./deploy.sh stop $user
done
```

### 自动化部署脚本

创建 `batch_deploy.sh`：

```bash
#!/bin/bash

# 定义用户列表和配置
users=(
    "user1:9201:5602:6:20"
    "user2:9202:5603:6:20"
    "user3:9203:5604:6:20"
)

# 批量创建和启动
for user_config in "${users[@]}"; do
    IFS=':' read -r name http dash cpu mem <<< "$user_config"
    ./deploy.sh create $name $http $dash $cpu $mem
    ./deploy.sh start $name
done
```

### 定时任务

添加到 crontab 进行定期备份：

```bash
# 每天凌晨2点备份
0 2 * * * /path/to/backup_script.sh

# 每小时检查集群健康
0 * * * * curl -s http://localhost:9201/_cluster/health | jq .status
```

## 🔒 安全建议

1. **网络隔离**：使用防火墙限制端口访问
2. **启用认证**：生产环境启用安全插件
3. **数据加密**：配置 SSL/TLS
4. **定期备份**：设置自动备份策略
5. **监控告警**：配置资源和性能监控

## 📚 参考文档

- [OpenSearch 官方文档](https://opensearch.org/docs/)
- [Docker Compose 文档](https://docs.docker.com/compose/)
- [完整部署指南](../08_OpenSearch容器部署与配置指南.md)

## 🆘 获取帮助

```bash
# 查看完整帮助
./deploy.sh help

# 查看实例信息
./deploy.sh info user1

# 查看所有实例
./deploy.sh list
```

## 📝 更新日志

- 2026-05-14：初始版本
  - 支持多用户独立部署
  - 自动资源配置
  - 完整的管理命令

## 👤 维护者

如有问题或建议，请联系开发团队。
