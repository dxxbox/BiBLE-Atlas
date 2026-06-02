# bible-oc-plugin vs V4 Server Part 设计文档 — 缺口分析与开发计划

本文档对照 V4 版 server part 设计文档，分析 `bible-oc-plugin`（OpenClaw 客户端插件）当前代码与设计的一致性，并对不一致部分给出以插件为中心的下一步开发计划。

> **范围**: 聚焦 `bible-oc-plugin` TypeScript 代码。Server 端（Python/FastAPI/Celery）的实现不在本计划范围内，但会在“依赖”栏标注前提条件。

> **对照设计文档**（按任务要求列出的 7 篇）:
> - `memory_import_implementation.md`
> - `memory_meta_parser_implementation.md`
> - `meta.json.sample.json`
> - `Skill_import_implementation.md`（`skill_import_implementation.md`）
> - `skill_package_parser_implementation.md`
> - `memory_download_implementation.md`
> - `skill_download_implementation.md`

---

## 一、一致部分总结（无需开发）

以下模块当前代码已与 V4 设计文档对齐，无需修改。

### 1.1 工具层（tools/）

| 工具名 | API Endpoint | 设计文档对应 | 说明 |
|--------|-------------|-------------|------|
| `bible_memory_search` | `POST /api/search/memory` | V4 search 设计 | ✅ 关键字/向量/混合搜索，topK、minScore、searchType 参数完整 |
| `bible_memory_save` | `POST /api/import/memory` | `memory_import_implementation.md` | ✅ 提交异步导入任务，支持 wait 轮询 |
| `bible_skill_search` | `POST /api/search/skill` | V4 search 设计 | ✅ 搜索参数与 memory 一致 |
| `bible_knowledge_search` | `POST /api/search/knowledge-base` | V4 search 设计 | ✅ 额外需要 tag 参数 |
| `bible_knowledge_list` | `GET /api/control/docs/list` | V4 设计 | ✅ 含 fallback endpoint |

### 1.2 运行时（runtime/）

| 组件 | 说明 |
|------|------|
| `BibleRuntime` | ✅ 覆盖 searchMemory / searchSkill / searchKnowledge / saveMemory / getMemory / getSkill / listKnowledge / commitSessionMemory / getTask / pollTask |
| `BibleAtlasClient` | ✅ HTTP 客户端的请求构造、超时控制、Bearer token、envelope 解包 |
| `ENDPOINTS` | ✅ 所有已实现 API 的路径定义 |

### 1.3 上下文引擎（context/）

| 组件 | 说明 |
|------|------|
| `recall.ts`（召回管线） | ✅ 从 memory / skill / knowledge 并行检索，异步 Promise.allSettled |
| `engine.ts`（ContextEngine） | ✅ assemble / afterTurn / compact 生命周期实现 |
| `injection.ts` | ✅ token 预算估算、上下文注入渲染 |
| `ranking.ts` | ✅ 分数过滤、排序、裁剪 |
| `capture.ts` | ✅ SessionCaptureStore — 按 turn 累积消息、阈值触发 flush、in-flight 去重 |

### 1.4 钩子层（hooks/）

| 组件 | 说明 |
|------|------|
| `lifecycle.ts` | ✅ session_start / before_reset / session_end 三个钩子 |
| `bypass.ts` | ✅ bypass session patterns 匹配（正则表达式） |

### 1.5 CLI（cli/）

| 命令 | 说明 |
|------|------|
| `bible setup` | ✅ 健康检查 + 写入 openclaw.json |
| `bible status` | ✅ 插件状态、健康检查、recall/capture/tools 完整报告 |

### 1.6 配置层（config/）

| 组件 | 说明 |
|------|------|
| `schema.ts` | ✅ BiblePluginConfig 完整校验、默认值、unwrapOpenClawConfig |
| `types.ts` | ✅ ResolvedBibleConfig 类型（含 compiledBypassPatterns） |

### 1.7 Meta 数据格式

| 文件 | 说明 |
|------|------|
| `meta.json.sample.json` | ✅ 字段结构（memory_id, title, abstract, overview, task_ids, feature_tags, domain_tags, component_tags 等）与 V4 设计完全一致 |

---

## 二、不一致部分 — 缺口分析

以下按功能域列出当前 bible-oc-plugin 中缺失、或与 V4 设计不一致的部分。

### 2.1 缺失：Skill Import 工具（bible_skill_save）

**设计文档**: `Skill_import_implementation.md` + `skill_package_parser_implementation.md`

**设计中的 API**: `POST /api/import/skill`

**当前插件状态**: 有 `bible_memory_save`（对应 memory import），但**没有** `bible_skill_save`。

**缺口详情**:
- `tools/skill.ts` 仅包含 `bible_skill_search` + `bible_skill_get`，缺少 import 工具
- `http/endpoints.ts` 缺少 `skillImport` endpoint
- `http/client.ts` 缺少 `importSkill()` 方法
- `runtime/bible-runtime.ts` 缺少 `importSkill()` runtime 方法
- `tools/register.ts` 的 `CORE_TOOL_NAMES` 缺少 `"bible_skill_save"`

**V4 设计中的 Skill Import 关键参数**:
- `files[]`（multipart，必须包含且仅一个 `.skill` 文件，允许其他附件）
- `kb_index`（必填）
- `tag`（固定为 `"skill"`）
- `parser_script`（可选，独立 multipart 字段）
- `vector_model`（可选）
- `parser_context`（可选 JSON）
- 返回 `202 + { task_id, domain, kb_index, tag, status }`

### 2.2 缺失：Memory Download 工具

**设计文档**: `memory_download_implementation.md`

**设计中的 API**:
- `POST /api/download/memory/file` — 单文件下载任务
- `POST /api/download/memory/batch` — 批量下载（ZIP 打包）
- `GET /api/download/memory/artifact/{artifact_id}` — 拉取 artifact

**当前插件状态**: 无任何 download 工具。

**缺口详情**:
- 无 `bible_memory_download` 或 `bible_memory_download_artifact` 工具
- `http/endpoints.ts` 缺少 download 相关 endpoint
- `http/client.ts` 缺少 `downloadMemoryFile()` / `downloadMemoryBatch()` / `fetchDownloadArtifact()` 方法
- `runtime/bible-runtime.ts` 缺少对应 runtime 方法

**V4 设计中的 Memory Download 关键参数**:
- **单文件**: `tag=memory`, `storage_path`, `download_name`（可选）
- **批量**: `tag=memory`, `storage_paths[]`, `package_name`（可选）, `include_metadata`（可选）
- **artifact 拉取**: `artifact_id`, 需校验 domain、过期时间
- **artifact 响应**: 流式文件，Content-Disposition 头

### 2.3 缺失：Skill Download 工具

**设计文档**: `skill_download_implementation.md`

**设计中的 API**:
- `POST /api/download/skill/file`
- `POST /api/download/skill/batch`
- `GET /api/download/skill/artifact/{artifact_id}`

**当前插件状态**: 无任何 skill download 工具。

**缺口详情**:
- 结构与 Memory Download 完全对称，tag 固定为 `"skill"`
- 同样缺少 tool / endpoint / client / runtime 四个层次的实现

### 2.4 `bible_memory_get` / `bible_skill_get` 使用遗留 API

**当前插件状态**: `bible_memory_get` 调用 `POST /api/memory/get`，`bible_skill_get` 调用 `POST /api/skill/get`。

**V4 API 文档确认**: `v4/02_API接口文档.md` 中 **不存在** `GET /api/memory/get` 和 `GET /api/skill/get` 这两个 endpoint。V4 的唯一"获取"入口是 Search API（`POST /api/search/memory` / `POST /api/search/skill`）。

**影响**: 当前实现调用的 endpoint 不在 V4 设计中：
| 工具 | 当前 endpoint | V4 文档状态 | 后果 |
|------|-------------|------------|------|
| `bible_memory_get` | `POST /api/memory/get` | **不存在** | 需改造 |
| `bible_skill_get` | `POST /api/skill/get` | **不存在** | 需改造 |

**改造方案**: 不新增 server 端 endpoint，而是改为使用 V4 Search API 的 keyword 精确匹配实现"按 ID 获取"。V4 Search API 的 search_profile 已经为此提供了支持：

| 工具 | 改造后调用 | 参数映射 | 设计依据 |
|------|-----------|---------|----------|
| `bible_memory_get` | `POST /api/search/memory` | `search_type=keyword`, `query=memoryId`, `topK=1` | V4 memory search_profile 中 `memory_id.keyword` weight=5.0 |
| `bible_skill_get` | `POST /api/search/skill` | `search_type=keyword`, `query=skillId \|\| name`, `topK=1` | V4 skill search_profile 中 `name.keyword` weight=5 |

**改造优势**:
- 不需要 server 端新增 endpoint，利用已有搜索基础设施
- 工具对外接口（参数名 `memoryId`/`skillId`/`name`）保持不变，只改底层 HTTP 调用
- keyword 精确匹配天然保证语义正确

**改造涉及文件**:
- `src/http/endpoints.ts` — 删除 `memoryGet`、`skillGet`；新增 `memorySearch`、`skillSearch` 已存在无需改
- `src/http/client.ts` — 删除 `getMemory()`、`getSkill()`；在 search 方法调用已有接口
- `src/runtime/bible-runtime.ts` — 删除 `getMemory()`、`getSkill()` 的独立 client 调用
- `src/tools/memory.ts` — `bible_memory_get` execute 改为调用 `runtime.searchMemory()`
- `src/tools/skill.ts` — `bible_skill_get` execute 改为调用 `runtime.searchSkill()`

> **注意**: 工具 `bible_memory_get` / `bible_skill_get` 本身的声明和 CORE_TOOL_NAMES 不需要改动，只是内部的 HTTP 调用目标变了。

---

## 三、开发计划（以 bible-oc-plugin 为中心）

### Phase 1: Skill Import 工具（bible_skill_save）

> **依赖**: Server 端需先实现 `POST /api/import/skill`（SkillImportAPI + SkillImportService + StoreSkill + parse_skill.py）

| 步骤 | 文件 | 变更 |
|------|------|------|
| 1.1 | `src/http/endpoints.ts` | 新增 `skillImport: "/api/import/skill"` |
| 1.2 | `src/http/client.ts` | 新增 `importSkill(req)` 方法（multipart 上传 .skill + 附件 + 可选 parser_script） |
| 1.3 | `src/runtime/bible-runtime.ts` | 新增 `importSkill()` runtime 方法（含日志、错误处理、可选 wait 轮询） |
| 1.4 | `src/tools/skill.ts` | 新增 `bible_skill_save` 工具定义（inputSchema、execute） |
| 1.5 | `src/tools/register.ts` | `CORE_TOOL_NAMES` 追加 `"bible_skill_save"` |
| 1.6 | `tests/unit/` | 新增 skill import 工具单元测试 |

**工具设计草案**:

```typescript
// 工具名: bible_skill_save
// 描述: Import a BiBLE Atlas skill package (.skill file) and optional attachments.
// 参数:
//   - skillPackage: { type: "string" }  // .skill 文件名或路径（需主机支持文件上传）
//   - kbIndex: { type: "string" }       // 可选，知识库索引名
//   - attachments: { type: "array" }    // 可选，附件文件名列表
//   - wait: { type: "boolean" }         // 可选，是否同步等待完成
// 返回: { taskId, status, domain }
```

### Phase 2: Memory Download 工具

> **依赖**: Server 端需先实现 `POST /api/download/memory/file`、`POST /api/download/memory/batch`、`GET /api/download/memory/artifact/{artifact_id}`

| 步骤 | 文件 | 变更 |
|------|------|------|
| 2.1 | `src/http/endpoints.ts` | 新增 `memoryDownloadFile`、`memoryDownloadBatch`、`memoryDownloadArtifact(artifactId)` |
| 2.2 | `src/http/client.ts` | 新增 `downloadMemoryFile(req)`、`downloadMemoryBatch(req)`、`fetchMemoryArtifact(artifactId)` 方法 |
| 2.3 | `src/runtime/bible-runtime.ts` | 新增 `downloadMemoryFile()`、`downloadMemoryBatch()`、`getDownloadArtifact()` runtime 方法 |
| 2.4 | `src/tools/memory.ts` | 新增 `bible_memory_download` 工具（同时支持单文件和批量模式） |
| 2.5 | `src/tools/register.ts` | `CORE_TOOL_NAMES` 追加 `"bible_memory_download"` |

**工具设计草案**:

```typescript
// 工具名: bible_memory_download
// 描述: Download BiBLE Atlas memory files (single or batch).
// 参数:
//   - storagePath: { type: "string" }   // 单文件模式：存储路径
//   - storagePaths: { type: "array" }   // 批量模式：存储路径列表
//   - downloadName: { type: "string" }  // 可选，下载文件名
//   - includeMetadata: { type: "boolean" } // 可选，是否包含 metadata.json
//   - wait: { type: "boolean" }         // 可选，是否同步等待 artifact 就绪
// 返回: { artifactId, artifactName, sizeBytes, expiresAt }（通过轮询获取）
```

### Phase 3: Skill Download 工具

> **依赖**: Server 端需先实现 `POST /api/download/skill/file`、`POST /api/download/skill/batch`、`GET /api/download/skill/artifact/{artifact_id}`

| 步骤 | 文件 | 变更 |
|------|------|------|
| 3.1 | `src/http/endpoints.ts` | 新增 `skillDownloadFile`、`skillDownloadBatch`、`skillDownloadArtifact(artifactId)` |
| 3.2 | `src/http/client.ts` | 新增 `downloadSkillFile(req)`、`downloadSkillBatch(req)`、`fetchSkillArtifact(artifactId)` 方法 |
| 3.3 | `src/runtime/bible-runtime.ts` | 新增 `downloadSkillBatch()` 等 runtime 方法 |
| 3.4 | `src/tools/skill.ts` | 新增 `bible_skill_download` 工具 |
| 3.5 | `src/tools/register.ts` | `CORE_TOOL_NAMES` 追加 `"bible_skill_download"` |

> **说明**: Phase 3 结构与 Phase 2 完全对称，代码大部分可复用。建议 Phase 2 完成后直接复制模式实现 Phase 3。也可考虑抽取公共 download 逻辑到 `tools/download-helpers.ts`。

### Phase 4: `bible_memory_get` / `bible_skill_get` 迁移到 V4 Search API

> **依赖**: Server 端已有 `POST /api/search/memory` 和 `POST /api/search/skill`

| 步骤 | 文件 | 变更 |
|------|------|------|
| 4.1 | `src/http/endpoints.ts` | 删除 `memoryGet: "/api/memory/get"`、`skillGet: "/api/skill/get"` |
| 4.2 | `src/http/client.ts` | 删除 `getMemory()`, `getSkill()` 方法；`bible_memory_get` execute 改为调用 `searchMemory()`（参数 `searchType=keyword, query=memoryId, topK=1`） |
| 4.3 | `src/runtime/bible-runtime.ts` | 删除 `getMemory()`, `getSkill()` 方法及其独立 client 调用 |
| 4.4 | `src/tools/memory.ts` | `bible_memory_get` execute：`runtime.searchMemory({ query: memoryId, searchType: "keyword", topK: 1 })` |
| 4.5 | `src/tools/skill.ts` | `bible_skill_get` execute：`runtime.searchSkill({ query: skillId ?? name, searchType: "keyword", topK: 1 })` |
| 4.6 | `tests/unit/` | 更新 get 工具的测试用例，验证 keyword search 调用 |

---

## 四、实现完成后的完整工具矩阵

| 工具名 | 功能域 | 当前状态 | 计划 Phase |
|--------|--------|----------|------------|
| `bible_memory_search` | Memory 搜索 | ✅ 已实现 | — |
| `bible_memory_save` | Memory 导入 | ✅ 已实现 | — |
| `bible_memory_get` | Memory 查询 | ⚠️ 使用遗留 API，需迁移到 Search | Phase 4 |
| `bible_memory_download` | Memory 下载 | ❌ 缺失 | Phase 2 |
| `bible_skill_search` | Skill 搜索 | ✅ 已实现 | — |
| `bible_skill_get` | Skill 查询 | ⚠️ 使用遗留 API，需迁移到 Search | Phase 4 |
| `bible_skill_save` | Skill 导入 | ❌ 缺失 | Phase 1 |
| `bible_skill_download` | Skill 下载 | ❌ 缺失 | Phase 3 |
| `bible_knowledge_search` | KB 搜索 | ✅ 已实现 | — |
| `bible_knowledge_list` | KB 列表 | ✅ 已实现 | — |

---

## 五、文件变更总览

### 需要修改的现有文件

```
bible-oc-plugin/src/
├── http/
│   ├── endpoints.ts          ← 新增 download + skill import 路径
│   └── client.ts             ← 新增 importSkill / downloadMemory / downloadSkill 方法
├── runtime/
│   └── bible-runtime.ts      ← 新增 importSkill / downloadMemory / downloadSkill runtime 方法
├── tools/
│   ├── memory.ts             ← 新增 bible_memory_download 工具
│   ├── skill.ts              ← 新增 bible_skill_save + bible_skill_download 工具
│   └── register.ts           ← CORE_TOOL_NAMES 追加 3 个新工具名
```

### 可选新增文件

```
bible-oc-plugin/src/
├── tools/
│   └── download-helpers.ts   ← 抽取 Memory/Skill download 公共逻辑
```

### 测试文件

```
bible-oc-plugin/tests/
└── unit/
    ├── tools-memory.test.ts  ← 追加 memory download 测试
    └── tools-skill.test.ts   ← 追加 skill import + skill download 测试
```

---

## 六、风险与注意事项

1. **multipart 上传复杂度**: `bible_skill_save` 需要上传 .skill 二进制文件 + 可选附件 + 可选 parser_script。OpenClaw 工具框架对文件上传的支持能力需要确认（当前 `bible_memory_save` 只传 JSON，不传文件）。
2. **artifact 拉取流式响应**: download 工具需要在 artifact 就绪后拉取文件流。当前 `BibleAtlasClient` 只处理 JSON 响应，需要扩展支持二进制流响应。
3. **Server 端依赖性**: Phase 1-3 所有步骤都依赖 Server 端先实现对应的 API endpoint。如果 Server 端未实现，插件侧无法独立开发和测试。
4. **`bible_memory_get` / `bible_skill_get` 迁移风险**: 已确认 `POST /api/memory/get` 和 `POST /api/skill/get` 不在 V4 规范中。迁移到 Search keyword 方案语义兼容（keyword 匹配 `memory_id.keyword` / `name.keyword`），但搜索结果可能返回多条，需取 topK=1 并断言为唯一匹配。
