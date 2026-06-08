# FastAPI 架构文档索引（v4）

本目录是基于 `v3` 方案重构后的 `v4` 设计稿，重点解决仓储类型收敛、API 按业务域拆分、`features` 目录重组，以及 `KNOWLEDGE_BASE` 自定义解析脚本的安全执行问题。

---

## v4 核心变化

1. **仓储类型收敛为 3 类**
   - `KNOWLEDGE_BASE`：统一承载原 `CODE/SCT/ALG/DESIGN/FLOW/SYNTAX/BUILD`（历史别名 `BUIL` 也归并到此）
   - `SKILL`：保持不变
   - `MEMORY`：由原 `SESSION` 重命名

2. **API 从“单入口”改为“按域拆分”**
   - `search/import/download` 各自拆分为 `KNOWLEDGE_BASE/SKILL/MEMORY` 独立入口
   - `KNOWLEDGE_BASE` 不提供 download API

3. **移除 `app/api/v1/` 中间层**
   - `docs_api.py`、`statistics_api.py`、`admin_api.py` 统一收敛到 `app/api/control/`

4. **`features` 改为能力分层**
   - 顶层能力目录固定为：`search/`、`import/`、`download/`、`control/`
   - `import` 与 `search` 能力内部按 `knowledge_base/skill/memory` 再分域

5. **`infrastructure/storage/` 更名**
   - 统一更名为 `app/infrastructure/file_system/`
   - `skill_import` 与 `memory_import` 在通过 `database/` 写库之外必须落盘文件

6. **`KNOWLEDGE_BASE` 解析机制升级**
   - 上传可附带自定义解析脚本（不附带则按配置目录查找 `parse_{tag}.py`，找不到再走默认脚本）
   - 统一解析函数名为 `parse`
   - 统一返回两部分：`chunks + search_profile`
   - 自定义脚本必须先通过 AST 安全检查，再在容器沙箱中执行

7. **`database/` 采用分层适配**
   - 对外统一是 `app/infrastructure/database/`
   - 默认实现放在 `database/opensearch/`
   - 后续可并行增加 `database/elasticsearch/`、`database/postgres/`，不影响 features 调用

8. **导入任务调度升级为 Celery 通用异步层**
   - 新增 `app/features/async_task/` 目录承载任务提交、路由、执行器、状态管理
   - Import API 统一变为“提交任务并返回 202”，执行由 Celery Worker 完成
   - import 相关流程图与实现文档均按该异步链路更新

---

## 文档列表

1. **[01_架构总览.md](./01_架构总览.md)**
   - v4 目录结构
   - 分层职责
   - 导入/检索/下载主流程
   - 仓储类型映射规则

2. **[02_API接口文档.md](./02_API接口文档.md)**
   - `search/import/download/control` 全部 API 定义
   - API 文件与路由映射
   - 请求响应规范与错误码

3. **[03_KNOWLEDGE_BASE解析与安全执行设计.md](./03_KNOWLEDGE_BASE解析与安全执行设计.md)**
   - `parse` 统一接口与返回格式
   - 默认解析器与自定义解析器协同方式
   - AST 检查规则与容器隔离运行策略

4. **[04_v3_to_v4迁移清单.md](./04_v3_to_v4迁移清单.md)**
   - v3 到 v4 的目录、类型、API 迁移映射
   - 分阶段迁移建议
   - 兼容策略与回退建议

5. **[05_v4关键设计补全与风险清单.md](./05_v4关键设计补全与风险清单.md)**
   - 按 1.1~1.5 的设计补充定稿
   - 资深架构师视角的风险审视与补齐项
   - 落地优先级与待拍板决策

6. **[06_未来演进规划.md](./06_未来演进规划.md)**
   - 解析脚本目录从“分域”演进到“统一配置目录”
   - Download `by-search` 异步导出能力演进
   - 各演进点的迁移步骤与验收标准

7. **[07_Celery通用异步任务机制设计与实现.md](./07_Celery通用异步任务机制设计与实现.md)**
   - 基于 Celery 的通用异步任务机制设计（提交、路由、重试、取消、可观测）
   - 支持无 Redis 本地模式；import 仅作为接入示例

8. **[08_Test_Mode详细设计.md](./08_Test_Mode详细设计.md)**
   - v4 HTTP API Test Mode 的详细设计
   - fixture schema、selector 匹配、异步任务、artifact 与错误响应契约

9. **Import 流程图（PlantUML）**
   - `import_pumls/knowledge_base_import_flow.puml`
   - `import_pumls/skill_import_flow.puml`
   - `import_pumls/memory_import_flow.puml`
   - 三者都包含配置管理类读取上传限制参数（文件类型、单文件大小、总大小、文件总数）

10. **Search 流程图（PlantUML）**
   - `search_pumls/knowledge_base_search_flow.puml`
   - `search_pumls/skill_search_flow.puml`
   - `search_pumls/memory_search_flow.puml`
   - 与 `import_pumls` 保持同粒度的类/接口级时序表达

11. **Download 流程图（PlantUML）**
   - `download_pumls/skill_download_flow.puml`
   - `download_pumls/memory_download_flow.puml`
   - 与 `import_pumls/search_pumls` 保持同粒度的类/接口级时序表达

12. **Import 详细开发指南**
   - `import_implementations/README.md`
   - `import_implementations/knowledge_base_import_implementation.md`
   - `import_implementations/skill_import_implementation.md`
   - `import_implementations/memory_import_implementation.md`
   - `import_implementations/parser_runtime_implementation.md`（`ASTGuard` + `SandboxRunner` 通用实现）
   - 逐类文档聚焦导入业务编排；通用解析运行时细节统一在 `parser_runtime_implementation.md`

13. **Infrastructure 详细开发指南**
   - `infrastructure_implementation/database_implementation.md`
   - `infrastructure_implementation/file_system_implementation.md`
   - `infrastructure_implementation/README.md`
   - 统一描述 `infrastructure/database/` 与 `infrastructure/file_system/` 的类初始化、成员、接口与内部实现

14. **Search 详细开发指南**
   - `search_implementation/README.md`
   - `search_implementation/knowledge_base_search_implementation.md`
   - `search_implementation/skill_search_implementation.md`
   - `search_implementation/memory_search_implementation.md`
   - 聚焦检索业务编排、`search_profile` 编译与 DSL 构建

15. **Download 详细开发指南**
   - `download_implementation/README.md`
   - `download_implementation/skill_download_implementation.md`
   - `download_implementation/memory_download_implementation.md`
   - 聚焦下载任务异步化、artifact 生命周期与域内差异

---

## 建议阅读顺序

1. `01_架构总览.md`
2. `02_API接口文档.md`
3. `03_KNOWLEDGE_BASE解析与安全执行设计.md`
4. `04_v3_to_v4迁移清单.md`
5. `05_v4关键设计补全与风险清单.md`
6. `06_未来演进规划.md`
7. `07_Celery通用异步任务机制设计与实现.md`
8. `08_Test_Mode详细设计.md`
9. `import_pumls/*.puml`
10. `search_pumls/*.puml`
11. `download_pumls/*.puml`
12. `import_implementations/*.md`
13. `search_implementation/*.md`
14. `download_implementation/*.md`
15. `infrastructure_implementation/*.md`

---

## Test Mode 开发入口

Test Mode 是独立于生产 `bible.main:create_app()` 的 v4 HTTP API 替身，不启动真实 DB、OpenSearch、向量模型或 Celery Worker。

启动方式：

```bash
python -m bible.test_mode.server --addr 127.0.0.1:5555
python -m bible.test_mode.server --addr 127.0.0.1:5555 --fixture ./fixture.json
```

实现入口：

- `bible/test_mode/`：独立 FastAPI app、fixture resolver、内存 task/artifact store。
- `bible/test_mode/fixtures/builtin.json`：内置 happy path fixture。
- `tests/test_test_mode.py`：Test Mode 契约、路由漂移和下载链路测试。

