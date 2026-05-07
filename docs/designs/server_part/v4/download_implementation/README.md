# Download 实现文档索引（v4）

本目录聚焦下载业务编排（API -> AsyncTaskService/Celery -> DownloadTaskExecutor -> DownloadService -> Artifact 拉取）。

## 业务域实现

- `skill_download_implementation.md`
- `memory_download_implementation.md`

## 下载流程图

- `../download_pumls/skill_download_flow.puml`
- `../download_pumls/memory_download_flow.puml`

## 关联文档

- `../02_API接口文档.md`
- `../07_Celery通用异步任务机制设计与实现.md`
- `../infrastructure_implementation/database_implementation.md`
- `../infrastructure_implementation/file_system_implementation.md`
- `../search_implementation/skill_search_implementation.md`
- `../search_implementation/memory_search_implementation.md`

说明：

- v4 Download 当前仅覆盖 `SKILL/MEMORY`，且单文件、批量下载都走异步任务。
- `by-search` 下载不在当前实现范围，放在 `../06_未来演进规划.md` 中。
- 本目录优先描述下载业务编排、任务结果产物（artifact）生命周期与域内差异；数据库和文件系统底层实现细节不重复展开。
