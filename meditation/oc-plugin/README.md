# bible-oc-plugin 设计文档索引

`bible-oc-plugin` 不是单一的知识库、记忆或技能检索插件，而是 OpenClaw 到 BiBLE Atlas 的全生命周期集成层。它以远程模式连接已有的 BiBLE Atlas HTTP 服务，在一个 OpenClaw 插件内同时承担 Context Engine、Hook、工具注册、运行时配置和 CLI 管理职责。

## 文档导航

- [总体架构与插件契约](./01-architecture-and-contracts.md)
  - 插件定位、OpenClaw 基线、运行时耦合与编译时解耦策略
  - `package.json`、`openclaw.plugin.json`、本地鸭子类型 `OpenClawPluginApi`
  - Context Engine 槽位、Hook、工具、CLI 的注册边界
- [自动召回设计](./02-auto-recall.md)
  - 引擎构造、`assemble` 主流程、查询预处理
  - memory / skill / knowledge 并行检索、去重、阈值过滤、重排
  - `<relevant-memories>` 注入格式与 token 预算控制
- [自动捕获、归档与记忆抽取](./03-capture-archive-compact.md)
  - `afterTurn` 增量写入与阈值异步 commit
  - `compact` 同步 commit、会话摘要和压缩返回
  - `session_start`、`session_end`、`before_reset` 的归档语义
- [工具层与运行时 CLI](./04-tools-and-cli.md)
  - memory、knowledge、skill 工具注册策略
  - 对 `bible_cli_go` 当前和未来能力的 HTTP 封装
  - `openclaw bible setup/status` 与配置管理
- [工程编译、部署与开发计划](./05-implementation-plan.md)
  - 本地手动安装、构建产物、验证矩阵
  - 分阶段开发计划、测试策略、漂移防护
  - 后续升级到 ClawHub 的预留路径
- [两版设计对比分析报告](./06-comparison-with-legacy-plan.md)
  - 对比 `docs/bible-oc-plugin-plan.md` 与本目录设计文档
  - 梳理共识、差异、风险和融合建议

## 设计结论

插件应声明为 `kind: "context-engine"`，由 `plugins.slots.contextEngine` 选择生效。运行时通过宿主注入的 `registerContextEngine`、`registerTool`、`on`、`registerCli` 等能力完成注册；编译时不依赖 OpenClaw 内部源码，只在插件本地定义最小鸭子类型和 context-engine 所需类型。

纯本地安装不要求 BiBLE Atlas HTTP 服务可访问；执行 `openclaw bible setup --write` 启用插件前必须确保远程服务可访问。`setup/status` 只负责验证远程服务、写入 OpenClaw 插件配置、检查槽位占用和工具契约，不在本地启动或内嵌 BiBLE Atlas 服务。

## 关键边界

- `bible-oc-plugin` 替换 OpenClaw 默认记忆系统的上下文检索职责，但不取代 BiBLE Atlas Server 的索引、持久化、摘要和任务调度能力。
- 第一开发阶段自动召回默认只检索 memory；skill 和 knowledge 作为后续 preset 可配置并行启用。
- 捕获与归档以 OpenClaw 会话生命周期为触发源，以 BiBLE Atlas memory ingest/commit API 为持久化目标。
- 工具层对外暴露 OpenClaw agent tool，对内统一走插件 HTTP client；`bible_cli_go` 的命令能力作为行为契约参考，不要求插件 shell 调用 CLI。
- `bypassSessionPatterns` 是运行时旁路策略。命中后插件不注入召回内容、不捕获会话内容，只保留必要的 session lifecycle 观测日志。
