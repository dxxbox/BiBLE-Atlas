# Bible VSCode Extension — 架构设计文档

> 本文档是面向开发者和架构师的设计决策文档，解释系统的目标、组件职责、关键决策和权衡取舍。
> 实现细节、完整代码和精确接口见《可执行技术规格》。

## 文档关系与使用方式

为避免设计、规格、迁移计划三份文档口径漂移，本文件与以下文档形成固定关系：

1. `docs/designs/client_part/01-bible-vscode-extension-design.md`（本文）：回答 "Why"，即架构目标、边界和设计取舍。
2. `docs/designs/client_part/02-bible-vscode-extension-spec.md`：回答 "How"，即可执行接口、命令、输入输出、代码骨架。
3. `backlog/bible-cli-go-full-rewrite-plan-zh.md`：回答 "When/Status"，即分阶段推进、当前进度、验收与风险。

使用建议：

1. 先读本文理解设计边界，再读 `02` 落地实现细节。
2. 任何 "是否已经完成" 的问题，以 rewrite plan 的 "当前状态" 为准。
3. 当设计描述与实现约束冲突时，以 `cli-contract-v1.md` 与 `02` 的可执行约束优先。

---

## 一、系统目标

**Bible** 是一套个人知识管理系统，核心组件包括：

- **bible-server**（Python/FastAPI）：知识库存储、全文+语义检索、Skill 管理
- **bible CLI**（Go）：bible-server 的命令行客户端，所有能力的唯一统一入口
- **bible VSCode Extension**（TypeScript）：将 bible CLI 的全部能力以 VSCode LLM 工具的形式暴露给 Copilot Agent，以及提供用户手动操作的 VSCode 命令

**两个使用场景：**

**场景 A — 被动增强（agent 自动调用）**
> 用户在任意 Copilot agent 对话中提问，agent 自动调用 bible 工具查询知识库和 skill，将检索到的相关内容注入上下文，让回答更贴合用户私有知识。用户无需感知工具的存在。

**场景 B — 主动操作（用户触发）**
> 用户主动将对话记录或 `.skill` 包上传到知识库，搜索/下载 skill，或管理知识条目。两种触发方式：通过 **VSCode 命令面板**直接操作（文件选择器、搜索 QuickPick）；或在任意 Copilot agent 对话中，直接指示 agent 调用相应工具（如"把这段对话存入知识库"）。

---

## 二、组件与职责边界

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户侧                                       │
│                                                                      │
│  Copilot Agent mode（任意 agent 调用全局工具）  VSCode 命令面板       │
│          │                                           │               │
│          └───────────────────────────────────────────┘               │
│                                   │                                   │
│                    bible VSCode Extension (TypeScript)                 │
│                    ┌──────────────────────────┐                       │
│                    │  10 个 LLM 工具（全局）   │                       │
│                    │  2 个 VSCode 命令          │                       │
│                    └──────────────┬───────────┘                       │
│                                   │ execFile(cliPath, args[])         │
└───────────────────────────────────┼─────────────────────────────────┘
                                    │
┌───────────────────────────────────┼─────────────────────────────────┐
│                    bible CLI (Go binary)                              │
│                    ┌──────────────┴───────────┐                       │
│                    │  bible search             │                       │
│                    │  bible skills ls/search/  │                       │
│                    │    get/upload/download    │                       │
│                    │  bible session list/get/  │                       │
│                    │    save                   │                       │
│                    │  bible data delete        │                       │
│                    └──────────────┬───────────┘                       │
│                                   │ HTTP/JSON                         │
└───────────────────────────────────┼─────────────────────────────────┘
                                    │
┌───────────────────────────────────┼─────────────────────────────────┐
│                    bible-server (Python/FastAPI)                      │
│                    ┌──────────────┴───────────┐                       │
│                    │  Elasticsearch            │                       │
│                    │  Vector Search            │                       │
│                    │  Storage (local/MinIO/S3) │                       │
│                    └───────────────────────────┘                       │
└─────────────────────────────────────────────────────────────────────┘
```

**职责边界原则：**
- **VSCode Extension 只做 UI 适配**：将 CLI 的 JSON 输出翻译为 LLM 工具结果，不含任何业务逻辑
- **CLI 是唯一业务入口**：所有与 server 的通信、认证、数据处理都在 CLI 里，Extension 不直连 server
- **Server 只做数据服务**：存储、检索、向量化，不了解客户端形态

---

## 三、技术栈决策

### 3.1 CLI 用 Go

**原因：**
- 编译为单静态二进制，零运行时依赖（无 Node.js、无 Python）
- 原生跨平台交叉编译：`GOOS=darwin/linux/windows go build`，一条命令三平台
- 用户独立安装和升级，不依赖 VSCode Extension 的发布周期
- 未来在其他平台（终端工作流、Raycast、CI/CD）复用同一个 CLI，无需适配

**分发策略：** 用户通过包管理器（Homebrew tap、`go install`、GitHub Releases）独立安装。默认可执行名为 `bible`（建议通过 `PATH` 提供），`bible-cli-go` 作为兼容别名保留。Extension 通过 `PATH` 查找或 `bible.cliPath` 配置项定位二进制。

**可执行名约定（当前）**：
- 默认：`bible`
- 兼容别名：`bible-cli-go`
- 文档示例中的 `bible ...` 为首选调用方式
- 子命令短写兼容：`ls` 视为 `list` 简写（例如 `skills ls` 等价 `skills list`）

**不选 Python/Node.js 的原因：** Python 需要 virtualenv 或 pipx，跨平台分发体验差；Node.js 单文件打包（pkg/ncc）在 Windows 上有已知问题，且体积大。

### 3.2 CLI 输出格式用 JSON

Extension 解析 CLI 的 JSON 输出后格式化展示给用户，而非直接透传原始文本。

**原因：**
- LLM 处理结构化输入比非结构化文本更稳定
- Extension 可以对不同字段做不同展示（分段、高亮分数、标签格式化）
- 错误可区分：`{"ok": false, "error": {"code": "NOT_FOUND"}}` 让 Extension 精准给出提示

**统一响应格式：**
```
成功：{"ok": true, "data": {...}}
失败：{"ok": false, "error": {"code": "ERROR_CODE", "message": "Human-readable message"}}
```

---

## 四、Skill 系统设计

### 4.1 什么是 Skill

Skill 是用户创建的**可复用能力单元**，打包为 `.skill` 文件（标准 ZIP 归档）：

```
my_skill.skill  (ZIP 归档)
├── SKILL.md           # 必须：YAML frontmatter（name/description/author/tags）+ 文档正文
├── *.py / *.sh        # 可选：辅助脚本
└── assets/            # 可选：静态资源
```

**SKILL.md frontmatter 规范：**
```yaml
---
name: memory_leak_checker         # 必须，唯一键，同名覆盖
description: 检查 C++ 代码的内存泄漏  # 必须，向量索引字段
author: xiapei                     # 可选
tags: [cpp, memory, analysis]      # 可选，辅助过滤和检索
---
正文（不参与全文索引）...
```

**搜索索引只基于轻量元数据**：`name + description + tags` 向量化，不对正文或脚本建索引。唯一键是 `name`，同名导入直接覆盖，暂不做版本管理。

### 4.2 Skill 生命周期

```
创建
  用户用 skill-creator 生成 .skill 包
    ↓
上传（bible_skill_upload 工具 / Bible: Upload Skill 命令）
  → POST /api/v1/skills/upload
  → Server: 解析 frontmatter → ZIP 安全校验 → 向量化 → ES upsert
    ↓
发现（被动）                        发现（主动）
  知识库搜索附带 results.skill        bible_skill_list / bible_skill_search
    ↓                                      ↓
使用（VSCode 环境）                  使用（Claude Code 环境）
  bible_skill_get → SKILL.md 注入      bible_skill_download → ~/.claude/skills/<name>/
  上下文（文档层面）                   → Claude Code Skill tool（含脚本执行）
```

### 4.3 两种执行环境的差异

| 环境 | Skill 使用方式 | 能力上限 |
|---|---|---|
| VSCode Copilot | `bible_skill_get` 返回 SKILL.md 内容，注入 LM 上下文 | 仅文档指导，不执行脚本 |
| Claude Code CLI | `bible skills download` 下载到 `~/.claude/skills/`，Skill tool 执行脚本 | 完整脚本执行能力 |

这是平台限制，不是设计选择。VSCode Extension 里没有 Claude Code 的 Skill tool 执行机制。用户需要完整脚本执行时，在 Claude Code 中用 `bible skills download <name>` 下载后调用。`bible_skill_download` 工具在 VSCode 里也被暴露（用于准备 Claude Code 所需的本地文件），但执行入口仍是 Claude Code。

### 4.4 被动搜索设计

知识库检索统一使用顶层命令 `bible search --query <Q>`。当启用 `--enable-hit` 时，默认同时附带 `skill` 与 `memory` 两类命中（默认 `--hit-types=skill,memory`）。

附带检索遵循降级原则：`skill` 或 `memory` 任一分支失败，不影响主知识检索返回；CLI 在结果中附带 `hit_warnings` 说明失败分支，调用方可继续消费主结果与其余成功命中。

---

## 五、工具设计

### 5.1 工具全局可见性

Bible 工具注册为**全局工具**（不绑定到任何特定 participant），VSCode 内所有 Copilot agent 均可自动发现和调用。

工具注册机制：在 `package.json` 的 `contributes.languageModelTools` 中声明工具元数据（name、modelDescription、inputSchema），在 `extension.ts` 激活时通过 `vscode.lm.registerTool()` 绑定实现。注册后，`vscode.lm.tools` 数组在整个 VSCode 范围内可查询，任何 agent 在推理阶段都能看到这些工具并决定是否调用。

**注册代码：**
```typescript
vscode.lm.registerTool('bible_knowledge_search', new KnowledgeSearchTool())
// 注册后，所有 agent 的 vscode.lm.tools 数组中都能看到此工具
```

`modelDescription` 字段是工具被 LM 正确使用的关键——它告诉 LM **何时调用**、**期望得到什么**、以及**有哪些限制**。每个工具的 `modelDescription` 需要明确这三点，而非仅描述功能。

### 5.2 完整工具列表

所有 CLI 命令（交互式命令除外）均有对应 VSCode 工具：

| 工具名 | 对应 CLI 命令 | 类型 | 是否需要确认 | Status |
|---|---|---|---|---|
| `bible_knowledge_search` | `bible search --query Q [--top-k N] [--enable-hit] [--hit-types skill,memory]` | 只读 | 否 | Planned |
| `bible_skill_list` | `bible skills ls [--tag TAG]` | 只读 | 否 | Planned |
| `bible_skill_search` | `bible skills search --query Q` | 只读 | 否 | Planned |
| `bible_skill_get` | `bible skills get <name> --content` | 只读 | 否 | Planned |
| `bible_skill_upload` | `bible skills upload --file PATH` | 写 | 是 | Planned |
| `bible_skill_download` | `bible skills download <name>` | 写（本地文件） | 是 | Planned |
| `bible_session_list` | `bible session list [--limit N]` | 只读 | 否 | Planned |
| `bible_session_get` | `bible session get --id ID` | 只读 | 否 | Planned |
| `bible_session_save` | `bible session save --input JSON` | 写 | 是 | Planned |
| `bible_data_delete` | `bible data delete --key KEY [--hard]` | 写 | 是 | Planned |

说明：本表命令优先使用简写风格（如 `skills ls`）；CLI 兼容全写别名（如 `skills list`）。

### 5.3 工具调用确认规则

写操作必须通过 `prepareInvocation.confirmationMessages` 向用户展示确认对话框，由 VSCode 原生 UI 处理，Extension 不自行实现确认逻辑。

| 操作类型 | 确认策略 |
|---|---|
| 只读操作（search、list、get）| 自动执行，无需确认 |
| 上传操作（skill upload、session save）| 展示将要上传的内容和目标，确认后执行 |
| 下载操作（skill download）| 展示目标路径，是否覆盖已存在的版本 |
| 删除操作（data delete）| 展示 key 和删除类型（软/硬），明确后果 |

---

## 六、VSCode 命令

Extension 提供 2 个 VSCode 命令，供用户在不进入对话的情况下直接操作知识库。这些命令绕过 LLM，直接调用 CLI 并展示结果。

| 命令 ID | 面板标题 | 行为 |
|---|---|---|
| `bible.searchKnowledge` | Bible: Search Knowledge Base | InputBox 输入查询词 → QuickPick 展示知识条目和 skill 命中 |
| `bible.uploadSkill` | Bible: Upload Skill Package | 文件选择器（过滤 `.skill`）→ 确认对话框 → 上传并展示结果 |

命令与 LLM 工具是互补关系：命令适合用户有明确操作意图（"我要上传这个文件"）；工具适合 agent 在推理过程中自动决策。两者共享同一个底层 CLI 调用封装（`runCli`），行为完全一致。

---

## 七、完整交互流程

### 7.1 场景 A：知识库增强（agent 自动调用）

```
用户在 Copilot agent mode 里提问：
  "我的项目里怎么处理 C++ 内存泄漏？"
      │
      ▼
Copilot LM 推理：这是个技术问题，查询知识库
      │
      ▼
调用 bible_knowledge_search
  input: { query: "C++ 内存泄漏处理", topK: 5, enableHit: true }
      │
      ▼
bible CLI: bible search --query "C++ 内存泄漏处理" --top-k 5 --enable-hit
      │
      ▼
Server: 语义搜索，返回
  knowledge: [{title: "内存管理最佳实践", score: 0.91, content: "..."}]
  skill:     [{name: "memory_leak_checker", score: 0.87, description: "..."}]
      │
      ▼
工具返回文本（格式化 JSON）给 LM
      │
LM 推理：有相关 skill，需要读取其指令
      │
      ▼
调用 bible_skill_get
  input: { name: "memory_leak_checker" }
      │
      ▼
bible CLI: bible skills get memory_leak_checker --content
      │
      ▼
返回 SKILL.md 全文给 LM
      │
      ▼
LM 综合知识条目 + skill 指令，生成回答
  → 用户看到：结合了私有知识库内容的专业回答
```

### 7.2 场景 B1：用户上传 skill（VSCode 命令）

```
用户打开命令面板 → 执行 "Bible: Upload Skill Package"
      │
      ▼
bible.uploadSkill 命令
  → showOpenDialog({ filters: { 'Skill packages': ['skill'] } })
  → 用户选择 /path/to/my_skill.skill
      │
      ▼
showWarningMessage 确认对话框：
  "Upload 'my_skill.skill' to bible? Same-name skills will be replaced."
      │
用户点击 Upload
      │
      ▼
runCli(['skills', 'upload', '--file', '/path/to/my_skill.skill'])
      → execFile(cliPath, args)
      │
      ▼
Server: 解析 frontmatter → ZIP 安全校验 → 向量化 → ES upsert
      │
      ▼
showInformationMessage: "Uploaded skill 'my_skill'"
```

### 7.3 场景 B2：用户保存对话（agent 工具调用）

```
用户在任意 Copilot agent 对话中说：
  "把我们刚才讨论的 C++ 内存泄漏方案存入知识库"
      │
      ▼
Copilot LM 推理：用户要保存对话，调用 bible_session_save
  input: {
    title: "C++ 内存泄漏处理方案",
    messages: [
      { role: "user",      content: "我的项目里怎么处理内存泄漏？" },
      { role: "assistant", content: "建议使用 Valgrind..." },
      ...
    ]
  }
      │
      ▼
bible_session_save.prepareInvocation()
  → 展示确认对话框：
    "Save 'C++ 内存泄漏处理方案'（6 messages）to knowledge base?"
      │
用户点击确认
      │
      ▼
bible_session_save.invoke()
      → execFile(cliPath, ['session', 'save', '--input', JSON.stringify({title, messages})])
      │
      ▼
返回：Saved session "C++ 内存泄漏处理方案" (6 messages, ID: sess-xyz)
```

**说明：** `messages` 由调用工具的 LM 从其上下文中提取并作为输入传入，无需 Extension 层任何注入机制。LM 在 agent 对话中已持有完整的对话历史，可以直接构造 messages 数组传给工具。

---

## 八、错误处理策略

错误分为两类，处理方式不同：

**CLI 层错误（通过 JSON 传递）：**

| 错误码 | 场景 | Extension 处理 |
|---|---|---|
| `NOT_FOUND` | 请求的 skill/session 不存在 | 工具 throw，LM 告知用户并建议用 list 命令查看 |
| `INVALID_SKILL_PACKAGE` | .skill 包格式错误 | 工具 throw，LM 告知具体缺少的字段 |
| `SEV_NOT_IMPLEMENTED` | 服务端能力未实现（HTTP 501） | 工具 throw，LM 明确提示该服务能力尚未落地，可稍后重试 |
| `UNAVAILABLE` / `INTERNAL` | 服务暂不可用或内部错误 | 工具 throw，LM 建议稍后重试或检查服务状态 |
| `TIMEOUT` | 对外主码：CLI 30s 内无响应 | 工具 throw，LM 建议检查网络或服务可用性 |

错误码约束：
- 服务端错误保留细分语义，不使用单一 `SERVER_ERROR` 聚合码。
- 对外文档与调用方优先使用 `TIMEOUT`；调试信息可携带 `DEADLINE_EXCEEDED`。
- `SEV_NOT_IMPLEMENTED`（HTTP 501）与 `CLI_NOT_IMPLEMENTED`（命令占位未实现）必须显式区分。
- Extension/调用方需在错误处理分支中显式接收 `SEV_NOT_IMPLEMENTED`。

**进程层错误（通过 execFile 异常传递）：**

| 场景 | Extension 处理 |
|---|---|
| CLI 二进制不存在（ENOENT）| 明确提示 "bible CLI not found"，建议安装或设置 `bible.cliPath` |
| 非 JSON 输出 | 提示 CLI 版本可能不兼容，建议升级 |
| 超时（>30s）| 按 TIMEOUT 处理 |

---

## 九、平台限制说明

| 限制 | 原因 | 应对方案 |
|---|---|---|
| 无法执行 .skill 脚本 | VSCode 扩展无 Claude Code Skill tool 执行机制 | VSCode 中注入 SKILL.md 文档；完整执行通过 `bible_skill_download` 下载后在 Claude Code 中使用 |
| `bible_session_save` 只能保存 LM 上下文内的消息 | `bible_session_save` 工具的 `messages` 字段由调用 LM 提供，LM 只能访问当前 agent 对话范围内的历史 | 若需保存其他来源的内容，用户可在当前 agent 对话中描述内容后让 LM 整理保存 |

---

## 十、里程碑

| 阶段 | 交付物 | 验收标准 |
|---|---|---|
| **M0** | Go CLI 骨架：search/skills/session/data 所有命令框架，统一 JSON 输出 | `bible search --query test` 返回合法 JSON；`bible --help` 列出所有子命令 |
| **M1** | VSCode Extension 骨架：10 个工具注册，`bible_knowledge_search` 端到端工作 | 在 Copilot agent mode 里，agent 能自动调用 `bible_knowledge_search` 并得到知识库结果 |
| **M2** | Skill 读取链路：`bible_skill_list`、`bible_skill_search`、`bible_skill_get`、`bible_skill_download` | 从 agent 说"查找内存相关的 skill"到完整读取 SKILL.md 内容全部可用 |
| **M3** | Skill 写入链路：`bible_skill_upload`（含确认）；VSCode 命令 `bible.uploadSkill` | 工具和命令两路均可上传 `.skill` 包，同名覆盖有提示 |
| **M4** | Session 链路：list/get/save | agent 能保存对话（LM 提供 messages）；能检索和读取历史 session |
| **M5** | `bible_data_delete`；VSCode 命令 `bible.searchKnowledge` | 命令面板 QuickPick 可搜索知识库；delete 工具有二次确认 |
| **M6** | CLI 安装检测 + 引导；错误处理完整覆盖 | CLI 缺失时有安装引导通知；NOT_FOUND 等错误时 LM 给出明确提示 |
