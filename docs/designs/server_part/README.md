# FastAPI 架构文档索引（v3）

本目录包含 FastAPI 架构设计的完整文档。

---

## 文档列表

### 核心文档

1. **[00_勘误与并发说明.md](./00_勘误与并发说明.md)**  
   - 纠正 v3 初版的设计问题
   - Celery/Redis 配置不能热更新的说明
   - 索引映射的正确使用方式
   - 多用户并发支持详解

2. **[01_架构总览.md](./01_架构总览.md)**  
   - 整体架构设计
   - 目录结构
   - 分层职责概览
   - 核心设计模式

3. **[02_分层职责详解.md](./02_分层职责详解.md)**  
   - API / Service / Repository 各层详细职责
   - 代码规范和示例
   - 依赖注入设计
   - 异常处理规范

4. **[03_配置管理设计.md](./03_配置管理设计.md)** ⭐ **已修正**
   - 静态配置（settings.py）：ES/Redis/Celery 连接
   - 动态配置（dynamic_config.yaml）：业务参数
   - 向量模型配置（简化版，删除 max_length 和 device）
   - 检索类型配置列表
   - 热更新边界说明

5. **[04_API接口文档.md](./04_API接口文档.md)** ⭐ **新增**
   - 完整的 API 端点列表
   - 请求/响应格式详解
   - 与现有 API（doc/claude/API_REFERENCE.md）保持一致
   - Python / JavaScript 使用示例

6. **[05_存储方案选型与大文档处理.md](./05_存储方案选型与大文档处理.md)** ⭐ **新增**
   - Elasticsearch / OpenSearch / PostgreSQL+pgvector 全面对比
   - 许可证与商业化分析
   - 中文分词能力对比（ik_smart vs zhparser）
   - 性能数据对比（量化指标）
   - session/skill 大文档处理方案（分块存储详解）
   - 三种方案的实现细节与迁移路径

7. **[Redis_Celery_FAQ.md](./Redis_Celery_FAQ.md)** ⭐ **新增**
   - Redis 是什么？用途和特点
   - Redis 和 Celery 的关系
   - 为什么需要 Redis？没有 Redis 能用 Celery 吗？
   - Redis 可以和 FastAPI 部署在同一服务器吗？
   - FastAPI 的其他异步任务方案（BackgroundTasks、asyncio、线程池、ARQ）
   - FastAPI 的并发模型和线程使用
   - 部署方案对比（开发环境、小型生产、大型生产）
   - 技术选型决策说明

---

## PlantUML 流程图可视化

本文档包含多个 PlantUML (`.puml`) 流程图文件，用于可视化系统架构和业务流程。

### 可视化方式

您可以通过以下 Web 服务在线查看 PlantUML 流程图：

**在线可视化地址**: http://earth.benben.eecloud.dynamic.nsn-net.net:9400/uml/

**使用方法**：
1. 打开上述 URL
2. 将 `.puml` 文件内容粘贴到编辑器中
3. 点击"生成图表"或等待自动渲染

### 可用的流程图

1. **[search_flow_with_hit_and_rerank.puml](./search_flow_with_hit_and_rerank.puml)**  
   **检索流程** - 支持 enable_hit 和 rerank
   - 描述完整的检索请求处理流程
   - 包含 TAG 解析和 index_name 确定逻辑
   - enable_hit 关联知识库检索机制
   - top_k 计算和 rerank 精排流程
   - 多索引并行检索和结果合并
   - 展示 API 层 → Service 层 → Repository 层的分层架构

2. **[upload_import_flow.puml](./upload_import_flow.puml)**  
   **上传导入流程** - 文件上传和异步导入
   - **支持两种上传模式**：
     - 单文件上传（常规文档：CODE/SCT/BUILD 等）
     - 多文件上传（Session/Skill 支持批量上传和两阶段上传）
   - **文件上传协议**：multipart/form-data，服务器读取文件流并保存到本地存储
   - **文件存储路径**：
     - Session/Skill: `/app/uploads/{doc_type}/{session_id}/{filename}`
     - 其他类型: `/app/uploads/{doc_type}/{date}/{doc_id}.{ext}`
   - **Session/Skill 多文件处理**：
     - 支持不同文件角色（main_document/attachment/reference_material/code_example）
     - 支持不同处理方式（parse_and_index/store_only）
     - 灵活的文件元数据管理
   - **Celery 异步任务**：按 doc_type 区分处理逻辑（Session/Skill vs 其他类型）
   - **分块处理**：Session/Skill 文档自动分块（默认 1000 tokens）
   - **向量生成和索引**：根据 process_type 决定是否解析和索引
   - **任务状态轮询**：区分常规文档和 Session/Skill 的返回结果
   - 展示 API 层 → Service 层 → Celery Worker 的完整流程

3. **[system_startup_flow.puml](./system_startup_flow.puml)**  
   **系统启动流程** - 从启动到就绪的完整过程
   - **分层结构展示**：配置层、数据库层、任务队列层、向量模型层、应用层
   - 静态配置和动态配置加载
   - 日志系统初始化
   - **三种数据库方案选择**：Elasticsearch / PostgreSQL+pgvector / OpenSearch
   - **Redis 可选初始化**：Redis 可用时使用 Redis broker，不可用时自动降级为 Memory broker
   - **Celery 自动降级**：Redis → Memory broker，确保异步任务总是可用
   - **后台模型加载**：使用 fork/join 语法展示 Celery 后台异步加载向量模型
   - **模型存储位置说明**：~/.cache/huggingface/ 或自定义路径
   - Rerank 模型预加载（可选，后台加载）
   - FastAPI 应用创建和路由注册
   - 系统健康检查
   - Uvicorn 服务器启动

**其他流程图** (位于 doc/ 目录):
- [doc/architecture_puml.puml](../architecture_puml.puml) - 系统架构图
- [doc/data_flow.puml](../data_flow.puml) - 数据流程图
- [doc/class_diagram.puml](../class_diagram.puml) - 类图
- 等等等...

---

## 修正说明（v3.1）

### 配置管理（03_配置管理设计.md）

#### 删除的内容
- ❌ **索引映射配置**：索引创建后映射固定，不需要在配置文件中维护
- ❌ **向量模型的 max_length 和 device**：这些是实现细节，不需要配置
- ❌ **每个模型的 load_on_startup**：改为所有模型共用一个配置

#### 新增的内容
- ✅ **检索类型列表配置**：`search_types.available` 和 `search_types.descriptions`
- ✅ **知识库标签配置**：`search_types.tags`（CODE, SCT, BUILD, SYNTAX, SPEC, ALG, DESIGN, FLOW）
- ✅ **全局 load_on_startup**：`vector_models.load_on_startup`（true=启动时下载所有模型，false=懒加载）

#### 简化的向量模型配置
```yaml
vector_models:
  default: "bge-large"
  load_on_startup: true    # ✅ 所有模型共用
  models:
    bge-large:
      name: "BAAI/bge-large-zh-v1.5"
      dimension: 1024
      description: "中文优化高精度（推荐）"
      # ❌ 删除了 max_length、device、load_on_startup
```

### API 文档（04_API接口文档.md）

#### 新增内容
- ✅ 完整的 API 端点文档
- ✅ 检索 API 消息格式（与 doc/claude/API_REFERENCE.md 保持一致）
- ✅ 上传 API、索引管理 API、文档管理 API、配置管理 API
- ✅ Python 和 JavaScript 使用示例
- ✅ 错误响应格式说明

---

## 配置热更新边界

| 配置类型 | 位置 | 热更新 | 生效方式 |
|---------|------|--------|----------|
| **ES/Redis/Celery 连接** | settings.py | ❌ | 重启应用/worker |
| **向量模型列表** | dynamic_config.yaml | ✅ | 调用 `/admin/config/reload` |
| **检索类型列表** | dynamic_config.yaml | ✅ | 立即生效 |
| **搜索参数** | dynamic_config.yaml | ✅ | 立即生效 |
| **上传配置** | dynamic_config.yaml | ✅ | 立即生效 |

---

## API 端点列表

```
健康检查:
  GET  /api/v1/health

检索:
  POST /api/v1/search

上传:
  POST /api/v1/upload
  GET  /api/v1/tasks/{task_id}

索引管理:
  GET  /api/v1/indices
  GET  /api/v1/indices/{index_name}

文档管理:
  GET    /api/v1/docs/{doc_id}
  PUT    /api/v1/docs/{doc_id}
  DELETE /api/v1/docs/{doc_id}

配置管理:
  POST /api/v1/admin/config/reload
  GET  /api/v1/admin/config
  GET  /api/v1/admin/config/vector-models
  GET  /api/v1/admin/config/search-types
```

---

## 阅读顺序建议

### 快速入门路径
1. **架构概览**：[01_架构总览.md](./01_架构总览.md)
2. **分层职责**：[02_分层职责详解.md](./02_分层职责详解.md)
3. **配置管理**：[03_配置管理设计.md](./03_配置管理设计.md)
4. **API 接口**：[04_API接口文档.md](./04_API接口文档.md)

### 技术选型路径
1. **存储方案对比**：[05_存储方案选型与大文档处理.md](./05_存储方案选型与大文档处理.md) ⭐ 先看这个
2. **架构总览**：[01_架构总览.md](./01_架构总览.md)
3. **配置管理**：[03_配置管理设计.md](./03_配置管理设计.md)

### 问题排查路径
- **勘误说明**：[00_勘误与并发说明.md](./00_勘误与并发说明.md)

---

## 版本历史

- **v3.5** (2026-04-01)
  - **Session/Skill 多文件上传支持**：
    - 新增批量上传 API：`POST /api/v1/sessions/upload` 和 `/api/v1/skills/upload`
    - 新增两阶段上传 API：
      - 创建：`POST /api/v1/sessions`
      - 上传文件：`POST /api/v1/sessions/{id}/files`
      - 查询详情：`GET /api/v1/sessions/{id}`
      - 删除文件：`DELETE /api/v1/sessions/{id}/files/{file_id}`
    - 支持灵活的文件角色（main_document/attachment/reference_material/code_example）
    - 支持不同处理方式（parse_and_index/store_only）
  - **文件存储优化**：
    - Session/Skill 使用专用目录结构：`/app/uploads/{doc_type}/{session_id}/{filename}`
    - 其他类型保持原有结构：`/app/uploads/{doc_type}/{date}/{doc_id}.{ext}`
  - **upload_import_flow.puml 重构**：
    - 文件格式判断简化：只区分 Session/Skill 和其他类型
    - 新增 Session/Skill 多文件处理分区（黄色高亮）
    - 详细的文件元数据管理说明
    - 区分不同任务类型的返回结果
  - **API 文档完善**：
    - 上传 API 拆分为 3 个子节（5.1-5.4）
    - 新增完整的 Session/Skill 管理 API 文档
    - 新增 files_config 参数详细说明

- **v3.4** (2026-04-01)
  - **文件上传流程增强**：
    - upload_import_flow.puml 增加文件上传详细说明
    - 明确文件内容上传方式（multipart/form-data）
    - 新增文件保存路径结构说明（/app/uploads/{doc_type}/{date}/{doc_id}.{ext}）
    - 明确 Celery 任务参数传递（file_path 等）
  - **Redis/Celery 架构优化**：
    - **核心改进**：Redis 不可用时自动降级为 Memory broker
    - Celery 支持两种 broker 模式：
      - Redis broker（生产环境推荐）
      - Memory broker（开发环境/单机部署）
    - 模型加载总是异步执行（不再有同步加载路径）
  - **文档增强**：
    - Redis_Celery_FAQ.md 更新 broker 降级方案
    - system_startup_flow.puml 更新 Celery 初始化流程
    - 01_架构总览.md 更新启动代码示例

- **v3.3** (2026-03-31)
  - **API 增强**：
    - 检索 API 新增 `enable_hit` 参数（关联知识库检索）
    - 支持 SESSION 和 SKILL 标签
  - **配置增强**：
    - 新增全局 `kb_index_list` 配置
    - 新增 `hit_list` 配置（CODE, BUILD, SESSION, SKILL）
    - 新增 `tag_to_index_mapping` 配置（TAG 到索引的映射关系）
    - 搜索配置新增 `rerank` 配置（重排序功能）
  - **文档增强**：
    - 新增检索流程 PlantUML 图（search_flow_with_hit_and_rerank.puml）
    - 新增上传导入流程 PlantUML 图（upload_import_flow.puml）
    - 新增系统启动流程 PlantUML 图（system_startup_flow.puml）
    - README 新增 PlantUML 在线可视化说明
  - **架构优化**：
    - API 层文件重命名：search.py → search_api.py（所有 API 文件统一）
    - Service 层文件重命名：service.py → {feature}_service.py（更明确）
    - Repository 层文件重命名：repository.py → {feature}_repository.py
  - **启动流程优化**：
    - 支持三种数据库方案（Elasticsearch / PostgreSQL+pgvector / OpenSearch）
    - Redis 改为可选组件（不启用时系统仍可启动，但 Celery 功能不可用）
    - **Celery 后台模型加载**：向量模型和 Rerank 模型在后台异步加载，不阻塞系统启动
    - 新增模型存储目录说明（infrastructure/models/）
    - 启动流程图增加分层结构（配置层、数据库层、任务队列层、模型层、应用层）

- **v3.2** (2026-03-31)
  - 新增存储方案选型文档（ES/OpenSearch/PG+pgvector 对比）
  - 新增 session/skill 大文档处理方案（分块存储详解）
  - 更新 infrastructure/ 目录结构（新增 opensearch/、postgres/、storage/）
  - 许可证与商业化分析
  - 中文分词能力量化对比
  - 性能数据对比（QPS、延迟、内存占用）

- **v3.1** (2026-03-30)
  - 删除索引映射配置（索引创建后不可变）
  - 简化向量模型配置（删除 max_length、device、load_on_startup）
  - 新增检索类型列表配置
  - 新增 API 接口文档

- **v3.0** (2026-03-30)
  - 初始版本
  - 统一配置管理系统
  - 完整的分层架构设计

---

**与 v2 的主要区别**：
- ✅ 配置更简洁（删除不必要的配置项）
- ✅ 热更新边界明确（ES/Redis 不支持热更新）
- ✅ 新增 API 文档（与现有 API 格式一致）
- ✅ 检索类型可配置
- ✅ 支持关联知识库检索（enable_hit）
- ✅ 支持 rerank 精排功能
