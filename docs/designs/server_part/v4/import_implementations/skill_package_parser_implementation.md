# SKILL `.skill` 包与 `<skill-name>/SKILL.md` 解析实现（v4）

本文档给出 SKILL 导入的专项方案，聚焦 `.skill` 包（ZIP 改后缀）与 `<skill-name>/SKILL.md` 解析链路。  
目标是在现有 v4 通用导入框架下，将 SKILL 业务语义落成可直接编码的实现设计。

---

## 1. 设计目标

1. 上传输入可包含多文件，`parse_skill.py` 作为唯一总入口处理全部文件，且 `.skill` 业务包必须且仅有一个。
2. `.skill` 按标准 ZIP 算法解压，且具备安全防护（路径穿越、解压炸弹等）。
3. `.skill` 解压后必须且只能包含一个顶层目录 `<skill-name>/`，目录内必须存在固定文件 `<skill-name>/SKILL.md`，并作为语义主数据来源。
4. `parse_skill.py` 输出符合通用 `ParseResult` 契约（`chunks/search_profile`）。
5. 与现有 `SkillUploadService` / `StoreSkill` 编排兼容，支持绑定校验、可选向量化、内容写库和文件注册。

---

## 2. 高层流程（SKILL 专项）

1. API 校验 `tag == "skill"` 并创建任务（不在 API/Service 层按后缀分流）。
2. `SkillUploadService` 完成脚本选择与 `ASTGuard.validate(...)`。
3. 调用 `StoreSkill.stage_upload_files(...)` 临时落地全部上传文件。
4. 调用 `StoreSkill.build_parse_manifest(...)` 生成 `skill_request_manifest.json`。
5. `SandboxRunner.run_parse(parser_script_path, file_path=<manifest_path>, parser_context)`（单次）。
6. `parse_skill.py` 内部作为唯一总入口执行：
   - 读取 manifest 的全部上传文件
   - 校验 `.skill` 文件必须且仅有一个（允许其他类型文件）
   - 对 `.skill` 做安全解压，校验单一顶层目录，并解析 `<skill-name>/SKILL.md`
   - 为全部文件构建 `local_file_storage_plan`
   - 生成 `chunks/search_profile/local_file_storage_plan`
7. 服务层校验 `ParseResult`，调用 `StoreSkill.store(...)` 执行本地存储、位置回填、绑定/向量化/写库。
8. 在 `finally` 清理任务临时目录（支持失败保留 + TTL 兜底）。

---

## 3. 上传输入契约

## 3.1 API 层约束

- `files[]` 中必须存在且仅存在一个 `.skill` 文件。
- 允许存在其他非 `.skill` 文件（如图片、配置、样例输入等）。
- `.skill` 计数与文件分类在 `parse_skill.py`（manifest 解析阶段）完成，而不是在服务层提前分流。
- `parser_script` 仍为可选字段（multipart 的独立字段，不计入 `files[]`）。
- MIME 可接受 `application/zip` / `application/octet-stream`，但业务判定以扩展名与可解压性为准。

## 3.2 推荐错误码

- `SKILL_PACKAGE_MISSING`
- `SKILL_PACKAGE_MULTIPLE`
- `SKILL_PACKAGE_INVALID_FORMAT`

## 3.3 非 `.skill` 文件处理策略

- 非 `.skill` 文件由 `parse_skill.py` 统一识别并纳入 `local_file_storage_plan`。
- 非 `.skill` 文件不生成语义 chunk，但会写入文件注册表，并在内容文档中通过 `metadata.related_storage_paths` 关联其存储位置。
- 服务层只负责编排 `run_parse(manifest_path, ...)`，不在解析前做后缀分流。

---

## 4. `parse_skill.py` 输入输出契约

## 4.1 输入

```python
def parse_skill(file_path: str, parser_context: dict[str, Any]) -> dict[str, Any]:
    ...
```

- `file_path`: 指向 `skill_request_manifest.json` 绝对路径（包含全部上传文件信息）。
- `parser_context`: 由服务层透传，可用于附加任务上下文（如 `task_id/request_id`）。

## 4.2 输出（`ParseResult`）

```json
{
  "chunks": [
    {
      "doc_id": "skill_3b8f4b8d9e6d",
      "title": "k8s-log-cleaner",
      "name": "k8s-log-cleaner",
      "description": "Clean stale k8s logs safely.",
      "body": "## Usage\\n\\nrun --namespace kube-system ...",
      "content": "k8s-log-cleaner\\nClean stale k8s logs safely.\\n\\n## Usage\\n\\nrun --namespace kube-system ...",
      "metadata": {
        "source_file": "k8s-log-cleaner/SKILL.md",
        "skill_name": "k8s-log-cleaner",
        "related_file_refs": ["f_0002", "f_0003"],
        "related_storage_paths": [],
        "package_filename": "k8s-log-cleaner.skill",
        "package_sha256": "3b8f4b8d9e6d...",
        "parser_version": "v4-skill-package-1"
      }
    }
  ],
  "local_file_storage_plan": {
    "files": [
      {
        "file_ref": "f_0001",
        "filename": "k8s-log-cleaner.skill",
        "source_path": "/tmp/skill_upload/import_20260505_001/staged/k8s-log-cleaner.skill",
        "must_store_local": true,
        "storage_role": "skill_package"
      },
      {
        "file_ref": "f_0002",
        "filename": "demo.png",
        "source_path": "/tmp/skill_upload/import_20260505_001/staged/demo.png",
        "must_store_local": true,
        "storage_role": "skill_attachment"
      }
    ]
  },
  "search_profile": {
    "keyword": {
      "fields": [
        "name.keyword^5"
      ]
    },
    "text": {
      "fields": [
        "name^4",
        "description^2",
        "body^1.5",
        "content^1"
      ]
    },
    "vector": {
      "source_template": "{name}\\n{description}\\n{body}"
    },
    "hybrid": {
      "text_weight": 0.5,
      "vector_weight": 0.5
    }
  }
}
```

说明：

- `chunks` 由 `<skill-name>/SKILL.md` 语义内容生成，建议显式保留 `name/description/body` 字段。
- `search_profile` 需保持可哈希、可稳定比较（用于绑定一致性校验）。
- `local_file_storage_plan` 覆盖全部上传文件（包括 `.skill` 与非 `.skill`），由存储层执行后回填 `metadata.related_storage_paths`。
- 若未来需要把包内附件回填为检索元数据，可扩展 `metadata` 字段，不破坏主契约。
- `title` 建议与 `name` 对齐，兼容现有通用检索展示字段。

---

## 5. 代码职责拆分建议

```text
app/features/upload/skill_upload/parsers/
├── parse_skill.py                          # 入口，仅编排
└── skill_parser/
    ├── manifest_loader.py                  # 读取与校验 manifest
    ├── file_classifier.py                  # 识别 .skill 与其他文件
    ├── package_validator.py                # .skill 包格式校验
    ├── zip_safe_extractor.py               # 安全解压
    ├── skills_md_locator.py                 # 定位 <skill-name>/SKILL.md
    ├── skills_md_parser.py                  # 解析标准 SKILL.md
    ├── chunk_builder.py                    # 组装 chunks
    ├── storage_plan_builder.py             # 组装 local_file_storage_plan
    ├── search_profile_builder.py           # 组装 search_profile
    └── orchestrator.py                     # 聚合执行
```

职责边界：

- `parse_skill.py` 不做业务细节，只负责装配模块；并作为唯一解析总入口。
- `manifest_loader.py` 负责读取全部上传文件信息，服务层不应重复判断 `.skill` 个数。
- `skills_md_parser.py` 只做 `<skill-name>/SKILL.md` 语义提取，不处理 ZIP 安全逻辑。
- `zip_safe_extractor.py` 只负责解压安全，不负责业务字段校验。

---

## 6. 关键实现点

## 6.0 manifest 全量入口

- `parse_skill.py` 首先读取 `skill_request_manifest.json`。
- 在解析脚本内部完成：
  - `.skill` 个数校验（必须且仅一个）
  - 非 `.skill` 文件分类
  - 后续统一构建 `local_file_storage_plan`
- 服务层不应在 `run_parse(...)` 前做文件类型分流，避免重蹈 MEMORY 方案里“解析前预判类型”的问题。

## 6.1 `.skill` 包安全解压

必须校验：

1. ZIP 文件可正常打开（坏包直接失败）。
2. 每个 entry 解压目标路径必须位于工作目录内（防 Zip Slip）。
3. 限制 entry 数量与总解压体积（防解压炸弹）。
4. 拒绝可疑链接类型（软链接/硬链接）与绝对路径 entry。
5. 解压后必须且只能有一个顶层目录 `<skill-name>/`；根目录文件或多个顶层目录均失败。
6. 顶层目录名应与包名 `<skill-name>.skill` 保持一致，或至少满足同一命名规范校验。

建议参数：

- `max_entries`: 2000
- `max_total_uncompressed_bytes`: 512MB
- `max_single_entry_bytes`: 64MB

## 6.2 `SKILL.md` 定位规则

- 文件名必须大小写严格匹配 `SKILL.md`。
- 必须位于唯一顶层目录下，即 `<skill-name>/SKILL.md`。
- 要求唯一；0 个或 >1 个都失败。
- 不支持 root-level `SKILL.md`，避免多个 skill 解压到同一个 `.skills/` 目录时互相覆盖。

## 6.3 `SKILL.md` 解析规则

- 解析逻辑遵循“标准 SKILL.md 规范”（`name/description/正文` 等）。
- 强校验关键字段非空（至少 `name`、`description`、正文语义内容）。
- 正文过长可在 `chunk_builder.py` 做受控切分；若不切分，需保证单 chunk 大小在可接受范围。
- 字段映射建议：
  - `name` -> `chunk.name`（并同步 `chunk.title`）
  - `description` -> `chunk.description`
  - 正文 -> `chunk.body`
  - 统一拼接文本 -> `chunk.content`

## 6.4 检索映射规则（SKILL）

- `keyword` 检索：主要匹配 `name`（建议 `name.keyword`）。
- `text` 检索：匹配 `name + description + body`（可保留 `content` 作为兜底拼接字段）。
- `vector` 检索：向量输入模板使用 `name + description + body`。
- `hybrid` 检索：沿用文本与向量混合打分。

## 6.5 存储位置回填规则

- `local_file_storage_plan` 执行后形成 `file_ref -> storage_path` 映射。
- 存储层必须将映射回填到 `chunk.metadata.related_storage_paths`。
- 文件注册表（`bulk_upsert_file_registry`）中必须保留每个上传文件的 `storage_path`。
- 这部分约束与 MEMORY 方案保持一致：最终入库数据可追溯到本地存储位置。

---

## 7. 参考代码骨架

```python
from __future__ import annotations

from typing import Any

from .skill_parser.orchestrator import parse_skill_manifest


def parse_skill(file_path: str, parser_context: dict[str, Any] | None = None) -> dict[str, Any]:
    return parse_skill_manifest(manifest_path=file_path, parser_context=parser_context or {})
```

```python
def parse_skill_manifest(manifest_path: str, parser_context: dict[str, Any]) -> dict[str, Any]:
    files = load_manifest(manifest_path)
    skill_package, other_files = classify_files(files)  # validate exactly one .skill

    package = validate_skill_package(skill_package.abs_path)
    extracted_dir = safe_extract_skill_package(package.path)
    skills_md_path = locate_skills_md(extracted_dir)
    skill_doc = parse_standard_skills_md(skills_md_path)

    chunks = build_chunks(skill_doc=skill_doc, package=package, parser_context=parser_context)
    search_profile = build_search_profile(skill_doc=skill_doc)
    local_file_storage_plan = build_local_storage_plan(skill_package, other_files)

    return {
        "chunks": chunks,
        "search_profile": search_profile,
        "local_file_storage_plan": local_file_storage_plan,
    }
```

---

## 8. 与服务层/存储层的集成约束

`SkillUploadService.execute_task(...)` 建议顺序：

1. 脚本选择 + `ASTGuard.validate(...)`
2. `StoreSkill.stage_upload_files(...)`
3. `StoreSkill.build_parse_manifest(...)`
4. `SandboxRunner.run_parse(...)`（单次，输入 manifest）
5. `validate_parse_result_schema(...)`
6. `StoreSkill.store(...)`（执行 `local_file_storage_plan`、回填 `related_storage_paths`、绑定/向量化/写库/文件注册）
7. `finally` 清理任务临时目录

说明：

- `.skill` 校验与非 `.skill` 分类在 `parse_skill.py` 中执行，服务层不预判文件类型。
- `stage_upload_files(...)` 负责临时落地，不等同于最终本地持久化。
- `StoreSkill.cleanup_task_workspace(...)` 只清理临时目录，不影响已持久化文件。
- 失败保留由 `import.skill.staging.keep_failed_workspace` 控制，并配合 `sweep_expired_task_workspaces(...)`。

---

## 9. 错误码建议（SKILL 专项）

- `SKILL_PACKAGE_MISSING`：未找到 `.skill` 文件
- `SKILL_PACKAGE_MULTIPLE`：发现多个 `.skill` 文件
- `SKILL_PACKAGE_INVALID_FORMAT`：不是有效 ZIP 包
- `SKILL_PACKAGE_UNSAFE_PATH`：解压路径穿越或非法 entry
- `SKILL_PACKAGE_TOO_LARGE`：解压体积超限
- `SKILL_MD_NOT_FOUND`：包内缺少 `SKILL.md`
- `SKILL_MD_MULTIPLE`：包内存在多个 `SKILL.md`
- `SKILL_MD_PARSE_INVALID`：`SKILL.md` 不符合标准格式
- `SKILL_MD_REQUIRED_FIELD_MISSING`：关键字段缺失

与通用运行时错误码的关系：

- 解析超时 -> `PARSER_SCRIPT_TIMEOUT`
- 运行异常 -> `PARSER_SCRIPT_RUNTIME_ERROR`
- 输出不符合 ParseResult -> `PARSE_RESULT_SCHEMA_INVALID`

---

## 10. 测试清单（建议）

1. 正常 `.skill` 包（含单一 `SKILL.md`）成功导入
2. 上传中存在一个 `.skill` + 多个非 `.skill` 文件时，`parse_skill.py` 成功分类并产出完整 `local_file_storage_plan`
3. 缺少 `.skill` 文件拒绝
4. 多 `.skill` 文件拒绝
5. `.skill` 非法 ZIP 格式拒绝
6. 路径穿越 entry（`../`）被拦截
7. 解压总量超过阈值被拦截
8. 缺少 `SKILL.md` 失败
9. 多个 `SKILL.md` 失败
10. `SKILL.md` 缺少必填字段失败
11. `keyword` 检索命中 `name`
12. `text` 检索命中 `name/description/body`
13. `vector` 检索基于 `name/description/body` 向量命中
14. `hybrid` 检索为文本+向量混合
15. 绑定首次创建与重复导入一致性通过
16. `vector_model` 有/无两条路径均可写库
17. `metadata.related_storage_paths` 与文件注册表中的 `storage_path` 一致
18. 任务结束后临时目录清理（成功/失败/失败保留/TTL）

