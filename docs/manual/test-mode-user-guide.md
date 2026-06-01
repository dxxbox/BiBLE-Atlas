# Test Mode 使用指南

本文介绍 Test Mode 的启动、验证和常见问题处理方式，面向测试人员、插件接入和客户端联调同学。

## 1. 适用范围

Test Mode 是独立于生产服务的 HTTP 测试入口，用于稳定验证 v4 API 契约。它不复用 `bible.main:create_app()`，因此不会在启动时初始化数据库、OpenSearch、向量模型、Celery 或真实 import container。

当前已支持：

- 独立 FastAPI app factory：`bible.test_mode.app:create_app`
- 独立服务入口：`python -m bible.test_mode.server`
- `GET /health`
- 内置 Search、Import、Download、Control fixture 路由
- 通过 `--fixture` 导入外部 fixture JSON 文件或目录
- 默认 Test Mode 响应头：`X-Bible-Test-Mode: true`
- 未知路由的平铺错误响应

## 2. 前置条件

- 在仓库根目录 `bibleV` 下操作
- 已同步 Python 依赖

```bash
uv sync --all-extras
```

如果 IDE 显示 `fastapi` 无法 import，请确认 Cursor 使用的是项目虚拟环境：

```text
.venv/bin/python
```

## 3. 启动 Test Mode

### 3.1 日常启动

如果已经执行过 `uv sync --all-extras`，日常测试可以直接使用项目虚拟环境里的 Python：

```bash
.venv/bin/python -m bible.test_mode.server
```

默认监听地址：

```text
127.0.0.1:5555
```

也可以先激活虚拟环境，后续在同一个终端里使用短命令：

```bash
source .venv/bin/activate
python -m bible.test_mode.server
```

如果不确定依赖是否已经同步，或希望命令自动进入 uv 管理的环境，可以使用兜底写法：

```bash
uv run --all-extras python -m bible.test_mode.server
```

### 3.2 指定监听地址

```bash
.venv/bin/python -m bible.test_mode.server --addr 127.0.0.1:5566
```

`--addr` 必须使用 `host:port` 格式。

### 3.3 指定外部 fixture

```bash
.venv/bin/python -m bible.test_mode.server \
  --addr 127.0.0.1:5555 \
  --fixture tests/fixtures/test_mode/custom.json \
  --strict true
```

说明：

- `--fixture`：外部 fixture JSON 文件或 fixture 目录路径。
- `--strict`：是否在 fixture schema 错误或冲突时启动失败，默认 `true`。

当 `--fixture` 指向目录时，Test Mode 会按文件名顺序加载该目录下一级 `*.json` 文件。外部 fixture 与内置 fixture 按身份键合并：同 `route.id`、`task_id`、`artifact_id` 时覆盖内置项，否则扩展内置场景。这样外部 fixture 不会因为内容较少而整层遮蔽内置 happy path。

外部 artifact 的相对 `file_path` 以声明它的 fixture JSON 文件所在目录为基准。例如：

```text
tests/fixtures/test_mode/
  download.json
  artifacts/project-context.json
```

## 4. 健康检查

```bash
curl -i http://127.0.0.1:5555/health
```

预期响应头包含：

```text
X-Bible-Test-Mode: true
Content-Type: application/json
```

预期响应体：

```json
{
  "status": "ok",
  "service": "bible-atlas-test-mode",
  "mode": "server"
}
```

## 5. 与客户端联调

如果使用 Go CLI 或插件联调，请将客户端 base URL 指向 Test Mode 服务地址。例如：

```bash
export BIBLE_CLI_BASE_URL=http://127.0.0.1:5555
```

联调时可以先用内置 fixture 验证 Search、Import、Download 和任务轮询的基本路径，再通过 `--fixture` 增加外部场景。业务路由返回 `NOT_FOUND` 通常表示该请求没有内置或外部 fixture 命中，或请求参数未通过基础契约校验。

## 6. 响应格式注意事项

Test Mode 默认遵守 v4 HTTP API 响应形状，不使用 CLI 输出信封，也不默认使用 legacy 服务信封。

不要把以下格式作为 Test Mode HTTP 默认契约：

- CLI 格式：`{"ok":true,"data":...}`
- legacy 格式：`{"status":"ok","result":...}`
- legacy 错误格式：`{"status":"error","error":...}`

错误响应默认是平铺 JSON：

```json
{
  "code": "NOT_FOUND",
  "message": "Route not found",
  "details": {
    "path": "/missing"
  }
}
```

## 7. 常见问题处理

### 7.1 `ModuleNotFoundError: No module named 'fastapi'`

原因通常是命令或 IDE 没有使用项目 `.venv`。

处理方式：

```bash
uv sync --all-extras
.venv/bin/python -c "import fastapi; print(fastapi.__version__)"
```

IDE 中请确认 Python 解释器为：

```text
/home/x61zhang/workspace/gitlab/bibleV/.venv/bin/python
```

### 7.2 `python: command not found`

当前环境可能没有 `python` 命令别名。优先使用项目虚拟环境里的 Python：

```bash
.venv/bin/python -m bible.test_mode.server
```

如果没有提前同步依赖，可以使用 uv 兜底启动：

```bash
uv run --all-extras python -m bible.test_mode.server
```

### 7.3 启动时报 `--addr must use host:port format`

`--addr` 缺少主机或端口。正确示例：

```bash
--addr 127.0.0.1:5555
--addr 0.0.0.0:5555
```

错误示例：

```bash
--addr 5555
--addr 127.0.0.1
```

### 7.4 端口被占用

如果启动失败并提示端口已被占用，请换一个端口：

```bash
.venv/bin/python -m bible.test_mode.server --addr 127.0.0.1:5566
```

客户端也需要同步修改 base URL。

### 7.5 `/api/...` 业务接口返回 `NOT_FOUND`

Test Mode 业务路由由 fixture 驱动。Search 未命中会返回空结果；Download、Control 等路由未命中通常返回 `NOT_FOUND`；Skill 单文件下载未命中会返回 `SKILL_NOT_FOUND`。

测试用例应先区分：

- `/health` 返回 200：Test Mode 服务本身可用。
- 请求返回参数校验错误：请求不符合 v4 API 基础契约。
- 业务路由返回 `NOT_FOUND`：该请求没有命中内置或外部 fixture。

### 7.6 响应里没有 `X-Bible-Test-Mode: true`

这通常表示请求打到了生产服务或其他 mock server，而不是 Test Mode。请检查：

- 服务启动命令是否为 `python -m bible.test_mode.server`
- 客户端 base URL 是否指向 Test Mode 地址
- 端口是否与预期一致

## 8. 测试建议

基础验收命令：

```bash
uv run --extra test python -m pytest tests/test_test_mode.py
```

代码检查命令：

```bash
uv run --extra dev ruff check bible/test_mode tests/test_test_mode.py
```

手工验收建议：

1. 启动 Test Mode。
2. `curl -i /health`，确认响应体和 `X-Bible-Test-Mode`。
3. 使用内置 Search fixture 请求 `/api/search/memory`。
4. 使用 `--fixture` 指向一个外部 JSON 文件或目录，确认同 id fixture 覆盖、不同 id fixture 扩展。
5. 确认启动日志或行为没有触发数据库、OpenSearch、向量模型或 Celery。

## 9. 关联文档

- `docs/designs/server_part/v4/08_Test_Mode详细设计.md`
- `meditation/biblep-test-mode-requirements.md`
- `docs/designs/server_part/v4/02_API接口文档.md`

