# Search 实现文档索引（v4）

本目录聚焦检索业务编排（API -> Service -> Searcher -> DSL 编译 -> Database）。

## 业务域实现

- `knowledge_base_search_implementation.md`
- `skill_search_implementation.md`
- `memory_search_implementation.md`

## 检索流程图

- `../search_pumls/knowledge_base_search_flow.puml`
- `../search_pumls/skill_search_flow.puml`
- `../search_pumls/memory_search_flow.puml`

## 关联文档

- `../02_API接口文档.md`
- `../03_KNOWLEDGE_BASE解析与安全执行设计.md`
- `../infrastructure_implementation/database_implementation.md`
- `../import_implementations/skill_import_implementation.md`
- `../import_implementations/skill_package_parser_implementation.md`

说明：

- 本目录优先描述检索业务编排、`search_profile` 编译策略和域内差异。
- 数据库与向量基础设施底层实现细节不在本目录重复展开。
