# BiBLE-Atlas 系统级通用定义（草案）

本文定义 BiBLE-Atlas 在服务端 API 设计中的跨模块共性约定，目标是统一调用体验、降低前后端协作成本，并为后续网关、SDK、监控与审计能力打下稳定基础。

适用范围：

- 所有 HTTP/JSON API（`/api/v1/*`）
- 需要认证鉴权的业务接口
- 需要统一错误处理、分页、筛选、幂等的接口

不强制范围：

- 健康检查探针（如 `/health`、`/ready`、`/api/v1/system/status`）
- 文件流/下载流等非标准 JSON 响应接口（需在接口文档显式声明）

---

## 1. 统一响应结构（Response Envelope）

### 1.1 标准响应模型

```json
{
  "status": "ok | error",
  "result": {},
  "error": {
    "code": "INVALID_ARGUMENT",
    "message": "Invalid field: limit",
    "details": {
      "field": "limit",
      "reason": "must be >= 1"
    },
    "retryable": false
  },
  "meta": {
    "request_id": "req_20260417_xxx",
    "timestamp": "2026-04-17T12:00:00Z",
    "cost_ms": 12
  }
}
```

字段语义：

- `status`：`ok` 或 `error`，客户端第一判断字段。
- `result`：成功时业务数据载荷；失败时可省略或置空对象。
- `error`：失败时错误对象；成功时可省略或为 `null`。
- `meta`：跨接口通用元信息。
  - `request_id`：请求唯一标识，用于日志追踪。
  - `timestamp`：服务端响应时间（UTC ISO8601）。
  - `cost_ms`：服务端处理耗时（毫秒）。

### 1.2 成功响应约定

- `status` 必须为 `ok`。
- 必须返回 `result`（空对象 `{}` 也视为合法）。
- 不返回业务错误对象。

示例：

```json
{
  "status": "ok",
  "result": {
    "id": "bk_123",
    "name": "Romans",
    "created_at": "2026-04-17T12:00:00Z"
  },
  "meta": {
    "request_id": "req_20260417_0001",
    "timestamp": "2026-04-17T12:00:00Z",
    "cost_ms": 8
  }
}
```

### 1.3 失败响应约定

- `status` 必须为 `error`。
- `error.code` 与 HTTP 状态码保持语义一致。
- `error.message` 面向调用方可读，但客户端逻辑分支必须基于 `error.code`。
- `error.details` 用于机器可解析上下文（字段名、资源 ID、约束信息等）。
- `error.retryable` 标识是否建议重试（例如 429/503/504 通常为 `true`）。

示例：

```json
{
  "status": "error",
  "error": {
    "code": "RESOURCE_EXHAUSTED",
    "message": "Rate limit exceeded",
    "details": {
      "limit": 100,
      "window_sec": 60
    },
    "retryable": true
  },
  "meta": {
    "request_id": "req_20260417_0002",
    "timestamp": "2026-04-17T12:01:00Z",
    "cost_ms": 2
  }
}
```

### 1.4 健康探针例外（Probe Exception）

为兼顾运维探针与历史客户端兼容性，健康类接口允许不采用完整 envelope：

- `GET /health`：轻量探针，返回 `{ "status": "ok" }`。
- `GET /api/v1/system/status`：可返回更丰富健康信息对象（用于运维观察）。

约束：

- 以上探针接口用于“存活/就绪/健康观测”，不承载业务数据语义。
- 业务接口（除探针例外外）仍必须遵循统一 envelope（`status/result/error/meta`）。

---

## 2. 错误模型与错误码体系

### 2.1 错误模型

`ErrorInfo` 建议统一包含：

- `code: str`：稳定错误码（对 SDK 与客户端兼容承诺）。
- `message: str`：人类可读描述。
- `details: object | null`：结构化上下文。
- `retryable: bool`：是否建议重试。

### 2.2 错误码分层

建议三层命名：

1. 通用平台层（跨域复用）：如 `INVALID_ARGUMENT`、`NOT_FOUND`、`INTERNAL`
2. 领域层（业务域可复用）：如 `AUTH_INVALID_TOKEN`、`TENANT_NOT_FOUND`
3. 模块细粒度层（必要时）：如 `VERSE_REF_INVALID_FORMAT`

为避免客户端分支复杂，HTTP API 默认暴露“通用平台层”与少量高价值领域层，模块细粒度信息放在 `details`。

### 2.3 标准错误码与 HTTP 映射

| 错误码 | HTTP 状态码 | 含义 | retryable |
|---|---:|---|---|
| `INVALID_ARGUMENT` | 400 | 参数非法/缺失 | false |
| `UNAUTHENTICATED` | 401 | 未认证（API Key/Token 无效） | false |
| `PERMISSION_DENIED` | 403 | 鉴权通过但无权限 | false |
| `NOT_FOUND` | 404 | 资源不存在 | false |
| `ALREADY_EXISTS` | 409 | 资源冲突/已存在 | false |
| `FAILED_PRECONDITION` | 412 | 前置条件不满足 | false |
| `CONFLICT` | 409 | 并发冲突/状态冲突 | false |
| `RESOURCE_EXHAUSTED` | 429 | 限流/配额不足 | true |
| `CANCELLED` | 499 | 客户端取消（可选） | false |
| `INTERNAL` | 500 | 未分类内部错误 | false |
| `NOT_IMPLEMENTED` | 501 | 功能未实现 | false |
| `UNAVAILABLE` | 503 | 下游依赖不可用 | true |
| `DEADLINE_EXCEEDED` | 504 | 超时 | true |

### 2.4 领域建议错误码（BiBLE-Atlas）

- 认证与租户：
  - `AUTH_INVALID_API_KEY`
  - `AUTH_TOKEN_EXPIRED`
  - `TENANT_NOT_FOUND`
  - `TENANT_DISABLED`
- 资源与内容：
  - `SCRIPTURE_NOT_FOUND`
  - `VERSE_NOT_FOUND`
  - `LANGUAGE_NOT_SUPPORTED`
  - `CONTENT_VERSION_CONFLICT`
- 检索与处理：
  - `SEARCH_BACKEND_UNAVAILABLE`
  - `INDEX_NOT_READY`

说明：领域错误码需与上表中的 HTTP 状态码语义对齐，并保留回退到通用错误码的能力。

---

## 3. 通用请求模式（Request Patterns）

### 3.1 通用请求头

建议所有业务接口支持以下请求头：

- 认证：
  - `X-API-Key: <key>`（首选）
  - `Authorization: Bearer <token>`（兼容）
- 身份与租户上下文：
  - `X-Bible-Account`（可选）
  - `X-Bible-User`（可选）
  - `X-Bible-Agent`（可选）
- 追踪与幂等：
  - `X-Request-Id`（客户端可传，服务端可补全）
  - `Idempotency-Key`（写操作建议支持）

> 备注：当前 `bible/common/identity.py` 已定义 `Role` 与 `Identity`，可作为请求上下文模型的基础。

### 3.2 查询类接口（List/Search）统一参数

建议标准化参数命名：

- 分页：
  - `page`（从 1 开始）
  - `page_size`（默认 20，最大 100）
  - 或游标分页：`cursor` + `limit`
- 排序：
  - `sort_by`
  - `sort_order`（`asc`/`desc`）
- 过滤：
  - `filters`（对象，键值过滤）
  - `keyword`（全文搜索关键字）
- 时间范围：
  - `start_time`
  - `end_time`

列表响应建议包含：

```json
{
  "items": [],
  "page": 1,
  "page_size": 20,
  "total": 105,
  "has_more": true,
  "next_cursor": "cur_xxx"
}
```

### 3.3 写操作通用模式

创建（`POST`）：

- 返回创建后的资源或资源标识。
- 幂等创建场景支持 `Idempotency-Key`，重复请求返回同一结果。

更新（`PUT/PATCH`）：

- 推荐支持版本控制字段（如 `version` 或 `etag`）以避免覆盖写。
- 冲突时返回 `CONFLICT` 或 `FAILED_PRECONDITION`。

删除（`DELETE`）：

- 成功可返回空 `result` 或最小确认对象（如 `{ "deleted": true }`）。

### 3.4 批量接口模式（可选）

批量操作建议返回“逐项结果”：

```json
{
  "status": "ok",
  "result": {
    "succeeded": 8,
    "failed": 2,
    "items": [
      { "id": "1", "ok": true },
      {
        "id": "2",
        "ok": false,
        "error": { "code": "NOT_FOUND", "message": "Resource not found" }
      }
    ]
  }
}
```

---

## 4. 认证、角色与请求上下文

### 4.1 角色模型

沿用现有角色定义：

- `root`
- `admin`
- `user`

建议在服务内统一注入 `RequestContext`：

```text
RequestContext {
  identity: Identity,
  request_id: str,
  account_id: str | null,
  user_id: str | null,
  agent_id: str | null
}
```

### 4.2 认证解析流程（建议）

1. 提取 API Key/Bearer Token。
2. 解析为 `Identity(role, user_id, account_id, email)`。
3. 合并可选租户头（仅在允许范围内覆盖）。
4. 构建 `RequestContext` 并透传到 Service/Repository 层。
5. 在路由层或服务层统一执行角色校验。

---

## 5. 可观测性与审计字段（通用）

为支撑线上排障，建议每个请求日志最少包含：

- `request_id`
- `route`
- `status_code`
- `error_code`（失败时）
- `account_id/user_id/agent_id`（如可用）
- `cost_ms`

响应头建议回传：

- `X-Request-Id`
- `X-Process-Time`（秒或毫秒，需统一单位）

---

## 6. 版本兼容与演进规则

- 新增响应字段应保持向后兼容（仅新增，不移除既有字段）。
- 错误码一旦对外发布，不应复用旧语义。
- 废弃字段需至少经历一个次版本周期，并在文档中标注弃用计划。
- SDK 解析应容忍未知字段，避免严格 schema 导致兼容问题。

---

## 7. 落地建议（当前仓库）

建议分三步推进：

1. 模型统一
   - 在服务端公共模块定义 `ResponseEnvelope`、`ErrorInfo`、`MetaInfo`。
2. 异常统一
   - 建立统一异常基类与错误码枚举，集中做异常到 HTTP 的映射。
3. 中间件统一
   - 在中间件中注入 `request_id`、计时、上下文构建与统一错误渲染。

---

## 8. 与现有文档关系

- 本文档是 BiBLE-Atlas 的系统通用定义基线。
- 后续可在以下专题文档继续细化：
  - 多租户与权限边界
  - API 认证生命周期（密钥轮换、吊销）
  - 可观测性规范（指标、日志、追踪）
