# bible-hermes-plugin 演进分析

> 2026-06-04 — 分析 Hermes session 上下文处理机制中 plugin 的角色与扩展方向

## 背景

Hermes 对 session 上下文的处理采用"存储但选择性记忆"模型：

- 所有对话完整保存（SQLite `state.db` + JSONL）
- 只有通过 `memory` 工具显式保存的内容才会自动出现在新 session
- 可通过 `session_search` 主动检索，`--resume`/`--continue` 恢复特定 session

bible-hermes-plugin 在这个基础上增加了"session → BiBLE Atlas"的双向管道。

---

## 当前已有的能力

### Hook 介入点

| 时机 | Hook | 做了什么 |
|------|------|---------|
| 每轮 LLM 调用前 | `pre_llm_call` | 用当前消息+最近6轮历史构建查询 → 并行搜索 BiBLE Atlas 的 memory/skill/knowledge → 排名去重 → 以 `<relevant-memories>` XML 块注入上下文（预算 1200 token） |
| 每轮 LLM 调用后 | `post_llm_call` | 缓冲 user + assistant + tool_calls → 达到阈值（8轮 / 16K字符）时异步 flush 到 BiBLE Atlas 作为结构化 memory |
| session start | `on_session_start` | 初始化该 session 的 buffer 状态 |
| session end | `on_session_end` | 阻塞式 flush 所有剩余 turns → 存入 BiBLE Atlas → 清理 session 状态 |
| session reset | `on_session_reset` | flush 后保留 session 状态继续 |

### Agent Tools（7个）

- `bible_memory_search` / `bible_memory_save` / `bible_memory_get`
- `bible_knowledge_search` / `bible_knowledge_list`
- `bible_skill_search` / `bible_skill_get`

### 双层记忆体系

```
Hermes memory（内置）    → 用户偏好、环境事实（轻量、高信号、自动注入 system prompt）
BiBLE Atlas（plugin）    → 完整对话记忆 + 知识库 + skill（重量、可搜索、跨 agent 共享）
```

---

## 可扩展方向

### 1. Session 启动时的"上下文预热"

**现状**：`pre_llm_call` 只在有用户消息时才触发检索。新 session 的第一个 turn 之前没有主动注入。

**可做**：`on_session_start` 时主动查询 BiBLE Atlas，找到最近的 session memory 或高频记忆，生成 "session preamble" 注入。

```
<session-context>
You previously worked on: "修复 elasticsearch 索引延迟问题" (2 hours ago)
Recent decisions: 切换到 hybrid search 模式，recall_min_score 降为 0.25
Open tasks: 验证 10K 文档批量的导入性能
</session-context>
```

Hermes 的 `--continue` 只能恢复同一个 session，无法跨越"不同 session 但相关工作"的场景。

### 2. 对话摘要/压缩与 BiBLE Atlas 联动

**现状**：Hermes 有内置的 context compression（`compression.enabled`），但 plugin 不感知压缩事件。压缩时被丢弃的对话细节永远丢失。

**可做**：监听压缩事件（需要 Hermes 暴露相关 hook），将被丢弃的内容作为摘要存入 BiBLE Atlas。

### 3. 结构化知识抽取

**现状**：capture 存的是原始对话 turns，没有结构化提取。

**可做**：flush 前增加轻量抽取步骤：

- 决策记录（"决定使用 hybrid search 替代纯向量搜索"）
- 事实记录（"elasticsearch 索引 shard 数设为 3"）
- 代码模式（识别并标记代码片段）

可打上不同 domain tags，增强检索精度。

### 4. 跨 session 的 Goal 持久化

**现状**：Hermes 的 `/goal` 命令只在 session 内存活。session 结束即丢失。

**可做**：监听 goal 创建/更新（需要 Hermes 暴露 hook），存入 BiBLE Atlas。下次 session 启动时自动恢复。

### 5. Skill 自动发现

**现状**：OC 版设计中有 context engine 可辅助 skill 发现。Hermes 版目前没有。

**可做**：分析 capture 的对话模式，检测重复出现的复杂工作流时提示用户保存为 skill。

### 6. 主动记忆整理（Memory Curation）

**现状**：存入 BiBLE Atlas 的 memory 只增不减，不做整理。

**可做**：session end 时对本次产生的 memory 做去重+合并（类似 Hermes curator 对 skill 的逻辑）。

---

## 总结矩阵

| 维度 | 当前状态 | 可扩展方向 | 依赖 |
|------|---------|-----------|------|
| 会话持久化 | ✅ capture → BiBLE Atlas | 结构化抽取 | BiBLE Atlas LLM 能力 |
| 会话恢复 | ❌ 无主动预热 | session preamble 注入 | `on_session_start` 已有 |
| 上下文压缩 | ❌ 不感知 | 压缩时存入摘要 | 需要 Hermes 暴露 hook |
| 知识抽取 | ❌ 只有原始 turns | 决策/事实/模式提取 | BiBLE Atlas 或本地 LLM |
| Goal 持久化 | ❌ 无 | 跨 session goal | 需要 Hermes 暴露 hook |
| Skill 发现 | ❌ 无 | 自动建议/生成 skill | 需要分析逻辑 |
| 记忆整理 | ❌ 无 | 去重+合并 | 可在 flush 时做 |

---

## 讨论记录

### 第 1 条：Session 启动时的"上下文预热"

**决策：独立新插件 `session-auto-recover`，不做进 bible-hermes-plugin。**

- bible-hermes-plugin 只管 BiBLE Atlas 层，不做本地 session 的事。
- 新建独立插件 `session-auto-recover`，职责单一：新 session 启动时提供自动补全建议。

**UX 设计（借鉴 zsh-autosuggestions）：**

- 用户打开 Hermes 新 session → 输入行出现灰色 ghost text
- 格式：`/resume-session {Session_Title}|{Session_Description}`
- 内容：上一个结束的 session 的 title + description
- 用户按 Tab → ghost text 变为实际输入 → 按 Enter 执行
- Slash command 行为：加载上一个 session 的上下文/摘要，或直接恢复

**架构问题待解决：**

1. Hermes 的 plugin hook 是否支持在 session start 时向 prompt_toolkit 注入 suggestion？
   - prompt_toolkit 原生支持 `AutoSuggest`，但需要 Hermes 暴露 hook 或扩展点
   - 当前已知 hook：`on_session_start` — 没有机制向 CLI 输入行写入内容
2. 如果不支持，可能的替代方案：
   - A) 提交 PR 给 Hermes，增加 `on_session_start` 返回 suggestion 的能力
   - B) 用 banner/welcome message 展示建议，用户手动输入 slash command
   - C) plugin 注册 slash command，在欢迎信息中提示用户可用 `/resume-session`

**下一步：确认 Hermes 是否支持 session-start 时的 suggestion 注入。**

**架构分析结论（2026-06-04）：**

改动可行性确认 — 需要 patch Hermes 3 个文件约 30 行代码：

1. `hermes_cli/plugins.py` — PluginContext 加 `set_session_suggestion()`，PluginManager 加 `_session_suggestion` 字段
2. `hermes_cli/commands.py` — SlashCommandAutoSuggest 在空 buffer 时读取 suggestion
3. `cli.py` — 构造 SlashCommandAutoSuggest 时传入 suggestion getter

不依赖 hook 签名变化，不依赖 agent loop 改动。

**执行计划：本地 patch + session-auto-recover 原型 + 联调验证**

1. Patch Hermes 三个文件
2. 创建 `~/.hermes/plugins/session-auto-recover/` 插件骨架
3. 插件实现：`on_session_start` → 读 state.db 最后 session → `set_session_suggestion()`
4. 注册 `/resume-session` slash command
5. 启动 Hermes 验证 ghost text 出现
6. 保存验证结果

**session-auto-recover 设计决策（2026-06-04）：**

1. `/resume-session` 行为：注入上一个 session 的摘要/上下文作为当前 session 的 preamble，不跳转 session。
2. 数据源：仅本地 `state.db`。无历史 session 则不显示 suggestion。不从 BiBLE Atlas 补。
3. 多候选浏览：→ 键逐个切换历史 session（类似 zsh-autosuggestions 按 → 浏览更早的 suggestion）。

**待澄清：**
- 注入的具体内容是什么？最后 N 条消息？session title + summary？
- 如何读取 state.db？Hermes 是否有公开的 session 查询 API？
- → 键浏览需要改 SlashCommandAutoSuggest，是否在本次原型范围内？
- "上一个 session" 如何定义——排除当前 session_id，按 `last_active` 倒序取第一条。

**#1 决策：可配置三级注入**

```yaml
session_auto_recover:
  inject_level: "metadata"    # metadata | messages | summary
  inject_messages_count: 5    # messages 级：注入最后 N 轮
  summary_model: null         # summary 级：null = 继承当前 model
```

| level | 注入内容 | 开销 | 默认 |
|-------|---------|------|------|
| `metadata` | title + preview + 时间范围 + 消息数 | 零 | ✅ |
| `messages` | 最后 N 轮原文 | get_session() | |
| `summary` | LLM 结构化摘要 | 一次 LLM call | |

**#3 决策：→ 键浏览放 V2。V1 只做最近一个 session 的单 suggestion。**

**#4 决策：排除当前 session_id，按 last_active 倒序取第一条。**

**所有决策已定，可以开始实施。**

**B 决策：不包装，直接注入原文/元数据/摘要。不额外加 XML 标签。**

**A 决策：直接用 `HermesState` 读 state.db。**

**Token 预估决策：在 `on_session_end` 预计算三种级别的 token 开销，写入 `cache.json`，`on_session_start` 直接读缓存显示在 ghost text 中。异步执行。**
