# OpenSearch 部署使用示例

本文档提供详细的使用示例，帮助你快速上手 OpenSearch 多用户部署方案。

## 📖 目录

- [基础示例](#基础示例)
- [典型场景](#典型场景)
- [完整工作流](#完整工作流)
- [Python 客户端示例](#python-客户端示例)
- [常见问题](#常见问题)

---

## 基础示例

### 示例 0：使用交互式向导（quickstart.sh）

`quickstart.sh` 是面向新手的交互式快速配置向导，免去手动填写参数的麻烦。

```bash
# 运行向导
./quickstart.sh
```

运行后，向导会逐步提示你：

```
OpenSearch 快速配置向导
================================

请选择配置方案：

1. 小型配置（开发/测试）      - 4核 / 12GB
2. 中型配置（小规模生产）     - 6核 / 20GB
3. 大型配置（生产环境）       - 12核 / 40GB
4. 超大配置（高性能需求）     - 18核 / 66GB
5. 自定义配置

请输入选项 (1-5): 2          # ← 选择中型配置
请输入用户名（实例名称）: alice
HTTP 端口 [默认: 9201]:      # ← 直接回车使用推荐端口
Dashboard 端口 [默认: 5602]: # ← 直接回车使用推荐端口

即将创建实例：
  用户名: alice
  配置: 中型 (6 核 / 20 GB)
  HTTP 端口: 9201
  Dashboard 端口: 5602

确认创建？(yes/no): yes
开始创建实例...
...
是否立即启动实例？(yes/no): yes
```

实例启动后，向导会打印访问地址和常用命令：

```
访问地址：
  OpenSearch:  http://localhost:9201
  Dashboard:   http://localhost:5602

常用命令：
  查看状态:    ./deploy.sh status alice
  查看日志:    ./deploy.sh logs alice
  停止实例:    ./deploy.sh stop alice
  删除实例:    ./deploy.sh delete alice
```

> **提示**：`quickstart.sh` 底层调用 `deploy.sh`，如需批量创建或脚本自动化，请直接使用 `deploy.sh`。

---

### 示例 1：创建单个实例

```bash
# 进入部署目录
cd opensearch_deploy/

# 创建实例（用户名: test, HTTP端口: 9201, Dashboard端口: 5602, 6核, 20GB内存）
./deploy.sh create test 9201 5602 6 20

# 输出示例：
# [STEP] 开始创建用户 test 的 OpenSearch 实例...
# [STEP] 检查端口可用性...
# [INFO] 端口检查通过：HTTP=9201, Perf=9601, Dashboard=5602
# [STEP] 计算资源配置...
# [INFO] 资源配置：
#   - CPU: 6核 (预留: 3核)
#   - 内存: 20GB (预留: 10GB)
#   - JVM堆: 8g
#   - 搜索线程: 9
#   - 写入线程: 6
#   - k-NN线程: 2
# [INFO] 实例创建成功！

# 启动实例
./deploy.sh start test

# 等待 30-60 秒后，验证服务
curl http://localhost:9201

# 查看集群健康
curl http://localhost:9201/_cluster/health?pretty
```

### 示例 2：管理实例生命周期

```bash
# 查看实例状态
./deploy.sh status test

# 查看详细信息
./deploy.sh info test

# 查看日志（最近 50 行）
./deploy.sh logs test

# 查看日志（最近 100 行）
./deploy.sh logs test 100

# 重启实例
./deploy.sh restart test

# 停止实例
./deploy.sh stop test

# 删除实例（保留数据）
./deploy.sh delete test --keep-data

# 完全删除实例（包括数据）
./deploy.sh delete test
```

---

## 典型场景

### 场景 1：开发、测试、生产环境隔离

```bash
# 生产环境（12核/40GB）
./deploy.sh create prod 9201 5601 12 40
./deploy.sh start prod

# 测试环境（6核/20GB）
./deploy.sh create staging 9202 5602 6 20
./deploy.sh start staging

# 开发环境（4核/12GB）
./deploy.sh create dev 9203 5603 4 12
./deploy.sh start dev

# 查看所有实例
./deploy.sh list

# 输出示例：
# 用户名          状态       HTTP端口        Dashboard端口   CPU        内存       创建时间
# --------------------------------------------------------------------------------------------------------
# prod           运行中     9201           5601           12核       40GB       2026-05-14 10:00:00
# staging        运行中     9202           5602           6核        20GB       2026-05-14 10:05:00
# dev            运行中     9203           5603           4核        12GB       2026-05-14 10:10:00
```

### 场景 2：多团队共享服务器

```bash
# 团队 A（6核/20GB）
./deploy.sh create team_a 9201 5602 6 20
./deploy.sh start team_a

# 团队 B（6核/20GB）
./deploy.sh create team_b 9202 5603 6 20
./deploy.sh start team_b

# 团队 C（6核/20GB）
./deploy.sh create team_c 9203 5604 6 20
./deploy.sh start team_c

# 每个团队独立管理自己的实例
# 团队 A 查看自己的实例状态
./deploy.sh status team_a

# 团队 B 查看自己的日志
./deploy.sh logs team_b
```

### 场景 3：个人研究和实验

```bash
# 实验 1：测试向量搜索（4核/12GB）
./deploy.sh create exp_vector 9201 5602 4 12
./deploy.sh start exp_vector

# 实验 2：测试全文搜索（4核/12GB）
./deploy.sh create exp_fulltext 9202 5603 4 12
./deploy.sh start exp_fulltext

# 实验完成后清理
./deploy.sh stop exp_vector
./deploy.sh delete exp_vector

./deploy.sh stop exp_fulltext
./deploy.sh delete exp_fulltext
```

---

## 完整工作流

### 工作流 1：从零开始部署

```bash
# 步骤 1：检查端口可用性
netstat -tlnp | grep -E "9201|5602"

# 步骤 2：创建实例
./deploy.sh create myapp 9201 5602 6 20

# 步骤 3：启动实例
./deploy.sh start myapp

# 步骤 4：等待服务就绪（30-60秒）
sleep 60

# 步骤 5：验证服务
curl http://localhost:9201
# 预期输出：
# {
#   "name" : "opensearch-myapp-node1",
#   "cluster_name" : "opensearch-myapp-cluster",
#   "version" : { ... }
# }

# 步骤 6：检查集群健康
curl http://localhost:9201/_cluster/health?pretty
# 预期输出：status: "green"

# 步骤 7：访问 Dashboard
# 浏览器打开：http://localhost:5602

# 步骤 8：创建测试索引
curl -X PUT "http://localhost:9201/test_index" \
  -H 'Content-Type: application/json' -d'
{
  "settings": {
    "number_of_shards": 2,
    "number_of_replicas": 0
  }
}'

# 步骤 9：插入测试数据
curl -X POST "http://localhost:9201/test_index/_doc/1" \
  -H 'Content-Type: application/json' -d'
{
  "title": "Test Document",
  "content": "This is a test"
}'

# 步骤 10：搜索数据
curl -X GET "http://localhost:9201/test_index/_search?pretty"
```

### 工作流 2：批量部署多个实例

创建批量部署脚本 `batch_deploy.sh`：

```bash
#!/bin/bash

# 批量部署配置
declare -a INSTANCES=(
    "user1:9201:5602:6:20"
    "user2:9202:5603:6:20"
    "user3:9203:5604:6:20"
)

# 部署函数
deploy_instance() {
    local config=$1
    IFS=':' read -r name http dash cpu mem <<< "$config"
    
    echo "====== 部署 $name ======"
    
    # 创建实例
    ./deploy.sh create $name $http $dash $cpu $mem
    
    # 启动实例
    ./deploy.sh start $name
    
    echo "等待 $name 启动..."
    sleep 30
    
    # 验证
    if curl -s http://localhost:$http > /dev/null; then
        echo "✓ $name 启动成功"
    else
        echo "✗ $name 启动失败"
    fi
    
    echo ""
}

# 批量部署
for instance in "${INSTANCES[@]}"; do
    deploy_instance "$instance"
done

# 显示所有实例状态
echo "====== 所有实例状态 ======"
./deploy.sh list
```

运行批量部署：

```bash
chmod +x batch_deploy.sh
./batch_deploy.sh
```

### 工作流 3：迁移和升级

```bash
# 1. 备份旧实例数据（使用实际路径）
BASE_DIR="${OPENSEARCH_BASE_DIR:-./opensearch}"
OLD_DATA="$BASE_DIR/old_user/data"
BACKUP_DIR="$BASE_DIR/backups/$(date +%Y%m%d)"
mkdir -p $BACKUP_DIR
cp -r $OLD_DATA $BACKUP_DIR/

# 2. 创建新实例
./deploy.sh create new_user 9201 5602 8 30

# 3. 停止旧实例
./deploy.sh stop old_user

# 4. 复制数据到新实例（可选）
# 注意：通常建议使用 OpenSearch 的快照/恢复功能

# 5. 启动新实例
./deploy.sh start new_user

# 6. 验证数据迁移
curl http://localhost:9201/_cat/indices?v

# 7. 确认无误后删除旧实例
./deploy.sh delete old_user
```

---

## Python 客户端示例

### 基础连接和操作

```python
#!/usr/bin/env python3
"""
OpenSearch Python 客户端使用示例
"""

from opensearchpy import OpenSearch
from opensearchpy.helpers import bulk
import json

# 连接配置（根据你的实例配置修改）
HOST = 'localhost'
PORT = 9201  # 根据实例的 HTTP 端口修改

# 创建客户端
client = OpenSearch(
    hosts=[{'host': HOST, 'port': PORT}],
    use_ssl=False,  # 如果禁用了安全插件
    # 如果启用了安全插件，使用以下配置：
    # http_auth=('admin', 'AdminPassword123!'),
    # use_ssl=True,
    # verify_certs=False,
    # ssl_show_warn=False
)

# 测试连接
def test_connection():
    info = client.info()
    print(f"✓ 连接成功")
    print(f"  集群名称: {info['cluster_name']}")
    print(f"  版本: {info['version']['number']}")
    print()

# 创建索引
def create_index():
    index_name = 'demo_index'
    
    index_body = {
        "settings": {
            "number_of_shards": 2,
            "number_of_replicas": 0,
            "refresh_interval": "5s"
        },
        "mappings": {
            "properties": {
                "title": {"type": "text"},
                "content": {"type": "text"},
                "category": {"type": "keyword"},
                "score": {"type": "float"},
                "created_at": {"type": "date"}
            }
        }
    }
    
    # 删除已存在的索引（如果有）
    if client.indices.exists(index=index_name):
        client.indices.delete(index=index_name)
        print(f"✓ 删除旧索引: {index_name}")
    
    # 创建新索引
    client.indices.create(index=index_name, body=index_body)
    print(f"✓ 创建索引: {index_name}")
    print()
    
    return index_name

# 批量插入数据
def bulk_insert(index_name, num_docs=1000):
    print(f"✓ 开始批量插入 {num_docs} 个文档...")
    
    docs = []
    for i in range(num_docs):
        docs.append({
            "_index": index_name,
            "_id": i,
            "_source": {
                "title": f"Document {i}",
                "content": f"This is the content of document {i}. " * 10,
                "category": f"category_{i % 10}",
                "score": (i % 100) / 10.0,
                "created_at": "2026-05-14T10:00:00"
            }
        })
    
    success, failed = bulk(client, docs)
    print(f"✓ 成功插入: {success} 个文档")
    if failed:
        print(f"✗ 失败: {failed} 个文档")
    print()

# 搜索数据
def search_data(index_name):
    print("✓ 执行搜索查询...")
    
    # 简单搜索
    query1 = {
        "query": {
            "match": {
                "content": "document"
            }
        },
        "size": 5
    }
    
    result1 = client.search(index=index_name, body=query1)
    print(f"  查询1: match 查询，找到 {result1['hits']['total']['value']} 个结果")
    
    # 过滤查询
    query2 = {
        "query": {
            "bool": {
                "must": [
                    {"match": {"content": "document"}}
                ],
                "filter": [
                    {"term": {"category": "category_5"}},
                    {"range": {"score": {"gte": 5.0}}}
                ]
            }
        }
    }
    
    result2 = client.search(index=index_name, body=query2)
    print(f"  查询2: bool + filter 查询，找到 {result2['hits']['total']['value']} 个结果")
    
    # 聚合查询
    query3 = {
        "size": 0,
        "aggs": {
            "categories": {
                "terms": {
                    "field": "category",
                    "size": 10
                }
            },
            "avg_score": {
                "avg": {
                    "field": "score"
                }
            }
        }
    }
    
    result3 = client.search(index=index_name, body=query3)
    print(f"  查询3: 聚合查询")
    print(f"    平均分数: {result3['aggregations']['avg_score']['value']:.2f}")
    print(f"    分类统计: {len(result3['aggregations']['categories']['buckets'])} 个分类")
    print()

# 查看索引统计
def show_stats(index_name):
    print("✓ 索引统计信息:")
    
    stats = client.indices.stats(index=index_name)
    index_stats = stats['indices'][index_name]['total']
    
    print(f"  文档数量: {index_stats['docs']['count']}")
    print(f"  索引大小: {index_stats['store']['size_in_bytes'] / 1024 / 1024:.2f} MB")
    print(f"  搜索次数: {index_stats['search']['query_total']}")
    print(f"  索引次数: {index_stats['indexing']['index_total']}")
    print()

# 主函数
def main():
    print("=" * 60)
    print("OpenSearch Python 客户端示例")
    print("=" * 60)
    print()
    
    # 测试连接
    test_connection()
    
    # 创建索引
    index_name = create_index()
    
    # 批量插入数据
    bulk_insert(index_name, num_docs=10000)
    
    # 刷新索引
    client.indices.refresh(index=index_name)
    
    # 搜索数据
    search_data(index_name)
    
    # 查看统计
    show_stats(index_name)
    
    print("=" * 60)
    print("✓ 示例执行完成")
    print("=" * 60)

if __name__ == "__main__":
    main()
```

### 向量搜索示例

```python
#!/usr/bin/env python3
"""
OpenSearch 向量搜索（k-NN）示例
"""

from opensearchpy import OpenSearch
from opensearchpy.helpers import bulk
import numpy as np

# 创建客户端
client = OpenSearch(
    hosts=[{'host': 'localhost', 'port': 9201}],
    use_ssl=False
)

def create_vector_index():
    """创建向量索引"""
    index_name = 'vector_index'
    
    # 删除已存在的索引
    if client.indices.exists(index=index_name):
        client.indices.delete(index=index_name)
    
    # 创建包含向量字段的索引
    index_body = {
        "settings": {
            "index": {
                "knn": True,
                "knn.algo_param.ef_search": 100,
                "number_of_shards": 2,
                "number_of_replicas": 0
            }
        },
        "mappings": {
            "properties": {
                "text": {"type": "text"},
                "vector": {
                    "type": "knn_vector",
                    "dimension": 128,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "nmslib",
                        "parameters": {
                            "ef_construction": 128,
                            "m": 16
                        }
                    }
                }
            }
        }
    }
    
    client.indices.create(index=index_name, body=index_body)
    print(f"✓ 创建向量索引: {index_name}")
    
    return index_name

def insert_vectors(index_name, num_docs=1000):
    """插入向量数据"""
    print(f"✓ 插入 {num_docs} 个向量...")
    
    docs = []
    for i in range(num_docs):
        # 生成随机向量（128维）
        vector = np.random.rand(128).tolist()
        
        docs.append({
            "_index": index_name,
            "_id": i,
            "_source": {
                "text": f"Document {i}",
                "vector": vector
            }
        })
    
    success, failed = bulk(client, docs)
    print(f"✓ 成功插入: {success} 个向量")
    
    # 刷新索引
    client.indices.refresh(index=index_name)

def search_vectors(index_name):
    """向量搜索"""
    print("✓ 执行向量搜索...")
    
    # 生成查询向量
    query_vector = np.random.rand(128).tolist()
    
    # k-NN 搜索
    search_body = {
        "size": 5,
        "query": {
            "knn": {
                "vector": {
                    "vector": query_vector,
                    "k": 5
                }
            }
        }
    }
    
    result = client.search(index=index_name, body=search_body)
    
    print(f"  找到 {len(result['hits']['hits'])} 个最近邻")
    for i, hit in enumerate(result['hits']['hits'], 1):
        print(f"  {i}. ID: {hit['_id']}, Score: {hit['_score']:.4f}")

def main():
    print("=" * 60)
    print("OpenSearch 向量搜索示例")
    print("=" * 60)
    print()
    
    # 创建向量索引
    index_name = create_vector_index()
    
    # 插入向量
    insert_vectors(index_name, num_docs=10000)
    
    # 执行向量搜索
    search_vectors(index_name)
    
    print()
    print("✓ 向量搜索示例完成")

if __name__ == "__main__":
    main()
```

运行示例：

```bash
# 安装依赖
pip install opensearch-py numpy

# 运行基础示例
python3 basic_example.py

# 运行向量搜索示例
python3 vector_example.py
```

---

## 常见问题

### Q1: 如何查看实例使用了多少资源？

```bash
# 查看容器资源使用
docker stats opensearch-myapp

# 查看 OpenSearch 内存使用
curl http://localhost:9201/_nodes/stats/jvm?pretty | grep -A 5 "mem"
```

### Q2: 如何修改实例的资源限制？

```bash
# 1. 停止实例
./deploy.sh stop myapp

# 2. 编辑配置文件（使用实际路径）
vi ./opensearch/myapp/docker-compose.yml
# 或者： vi $OPENSEARCH_BASE_DIR/myapp/docker-compose.yml

# 修改 deploy.resources.limits 部分

# 3. 重启实例
./deploy.sh start myapp
```

### Q3: 如何在不同实例间迁移数据？

```bash
# 方法1：使用快照和恢复（推荐）
# 在源实例创建快照
curl -X PUT "http://localhost:9201/_snapshot/my_backup/snapshot_1?wait_for_completion=true"

# 在目标实例恢复快照
curl -X POST "http://localhost:9202/_snapshot/my_backup/snapshot_1/_restore"

# 方法2：使用 reindex API
curl -X POST "http://localhost:9202/_reindex" -H 'Content-Type: application/json' -d'
{
  "source": {
    "remote": {
      "host": "http://localhost:9201"
    },
    "index": "source_index"
  },
  "dest": {
    "index": "dest_index"
  }
}'
```

### Q4: 如何监控所有实例的健康状态？

创建监控脚本 `monitor_all.sh`：

```bash
#!/bin/bash

echo "OpenSearch 实例健康监控"
echo "========================"
echo ""

# 获取所有实例
BASE_DIR="${OPENSEARCH_BASE_DIR:-./opensearch}"
for instance_dir in $BASE_DIR/*/; do
    if [ -f "$instance_dir/instance.info" ]; then
        source "$instance_dir/instance.info"
        
        echo "实例: $USER_NAME"
        
        # 检查容器状态
        if docker ps | grep -q "opensearch-$USER_NAME"; then
            # 获取集群健康状态
            health=$(curl -s http://localhost:$HTTP_PORT/_cluster/health | jq -r .status)
            
            if [ "$health" == "green" ]; then
                echo "  状态: ✓ 健康 (green)"
            elif [ "$health" == "yellow" ]; then
                echo "  状态: ⚠ 警告 (yellow)"
            else
                echo "  状态: ✗ 异常 (red)"
            fi
        else
            echo "  状态: ✗ 未运行"
        fi
        
        echo ""
    fi
done
```

### Q5: 如何清理未使用的数据？

```bash
# 删除特定索引
curl -X DELETE "http://localhost:9201/old_index"

# 删除所有以 test_ 开头的索引
curl -X DELETE "http://localhost:9201/test_*"

# 清理旧的快照
curl -X DELETE "http://localhost:9201/_snapshot/my_backup/snapshot_20260101"

# 完全重置实例（删除所有数据）
./deploy.sh stop myapp
# 使用实际路径：
sudo rm -rf ./opensearch/myapp/data/*
# 或者： sudo rm -rf $OPENSEARCH_BASE_DIR/myapp/data/*
./deploy.sh start myapp
```

---

## 总结

本文档提供了 OpenSearch 多用户部署的完整示例，涵盖了：

- ✅ 基础操作示例
- ✅ 典型应用场景
- ✅ 完整工作流程
- ✅ Python 客户端使用
- ✅ 常见问题解决

更多信息请参考：
- [README.md](README.md) - 完整使用说明
- [部署指南](../08_OpenSearch容器部署与配置指南.md) - 详细配置文档
