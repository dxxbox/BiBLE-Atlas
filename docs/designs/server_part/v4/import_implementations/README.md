# Import 实现文档索引（v4）

本目录聚焦导入业务编排（API -> AsyncTaskService/Celery -> ImportTaskExecutor -> Service -> Store）。

## 业务域实现

- `knowledge_base_import_implementation.md`
- `skill_import_implementation.md`
- `skill_package_parser_implementation.md`（SKILL 专用 `.skill`/`SKILL.md` 解析实现）
- `memory_import_implementation.md`
- `memory_meta_parser_implementation.md`（MEMORY 专用 `meta.json` 解析实现）

## MEMORY 专用样例文件

- `meta.json.sample.json`

## 通用解析运行时

- `parser_runtime_implementation.md`
  - `ASTGuard`
  - `SandboxRunner`
  - 三域共用

## 基础设施实现（外链）

- `../infrastructure_implementation/database_implementation.md`
- `../infrastructure_implementation/file_system_implementation.md`

说明：
- `import_implementations/*.md` 不再展开 `database/file_system` 与 `ASTGuard/SandboxRunner` 的底层实现细节，仅描述调用点和业务侧编排。
- 导入任务调度统一复用 `v4/07_Celery通用异步任务机制设计与实现.md`，本目录只描述 import 侧如何接入该通用机制。

