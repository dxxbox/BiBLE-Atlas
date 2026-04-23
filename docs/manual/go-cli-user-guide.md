# Bible CLI Go 版本用户指南

本文介绍当前 `bible_cli_go` 的使用方式，面向开发、测试和插件接入同学。

## 1. 前置条件

- Go 1.25 或更高版本
- 在仓库根目录 `BiBLE-Atlas` 下操作

## 2. 启动方式

### 2.1 开发态直接运行

```bash
cd bible_cli_go
go run ./cmd/bible-cli --help
```

### 2.2 编译后运行

```bash
cd bible_cli_go
mkdir -p dist
go build -buildvcs=false -o dist/bible-cli-go ./cmd/bible-cli
./dist/bible-cli-go --help
```

说明：`-buildvcs=false` 用于避免本地 VCS stamping 干扰构建。

## 3. 当前可用命令

- `health`
- `system status`
- `system info`
- `knowledge list`
- `knowledge search [query]`
- `memory show`（已声明，暂未实现）
- `skills list`（已声明，暂未实现）

查看帮助：

```bash
go run ./cmd/bible-cli --help
```

## 4. 使用示例

### 4.1 健康检查

```bash
go run ./cmd/bible-cli health
```

### 4.2 系统状态与信息

```bash
go run ./cmd/bible-cli system status
go run ./cmd/bible-cli system info
```

### 4.3 知识库查询

```bash
go run ./cmd/bible-cli knowledge list
go run ./cmd/bible-cli knowledge search
go run ./cmd/bible-cli knowledge search faith
```

参数说明：`knowledge search` 只接受一个可选参数 `query`。

### 4.4 未实现命令

```bash
go run ./cmd/bible-cli memory show
go run ./cmd/bible-cli skills list
```

上述命令当前会返回 `CLI_NOT_IMPLEMENTED`，这是预期行为。

## 5. 输出与错误格式

### 5.1 成功输出

- 输出到 `stdout`
- 单行 JSON
- 统一结构：`{"ok":true,"data":...}`

示例：

```json
{"ok":true,"data":{"status":"ok"}}
```

### 5.2 错误输出

- 默认输出到 `stdout`
- 单行 JSON，统一结构：`{"ok":false,"error":{"code":"...","message":"..."}}`
- `stderr` 默认不承载业务错误正文

示例：

```json
{"ok":false,"error":{"code":"INVALID_ARGS","message":"Unknown command 'abc'."}}
{"ok":false,"error":{"code":"CLI_NOT_IMPLEMENTED","message":"Command 'skills list' is not implemented yet."}}
```

### 5.3 兼容模式（迁移窗口）

- 设置 `BIBLE_CLI_LEGACY_STDERR=1` 后，CLI 会在保留 `stdout` JSON 的同时，额外输出历史格式到 `stderr`：`Error[<CODE>]: <message>`

## 6. 退出码

- `0`：成功
- `1`：通用错误（参数错误、网络/接口错误、内部错误等）
- `3`：命令路径已声明但未实现

## 7. 环境变量

支持以下配置项：

- `BIBLE_CLI_BASE_URL`：服务地址（优先）
- `BIBLE_ATLAS_BASE_URL`：服务地址（回退）
- `BIBLE_CLI_TIMEOUT_SECONDS`：超时秒数，默认 `30`
- `BIBLE_CLI_TRUST_ENV`：是否信任系统代理环境，默认 `false`
- `BIBLE_CLI_LEGACY_STDERR`：是否附加历史 stderr 文本错误（`1` 开启，默认关闭）

示例：

```bash
export BIBLE_CLI_BASE_URL="http://127.0.0.1:5555"
export BIBLE_CLI_TIMEOUT_SECONDS="20"
go run ./cmd/bible-cli system status
```

### 7.1 配置优先级

当前生效优先级（高 -> 低）：

1. 环境变量：`BIBLE_CLI_*`（`BIBLE_ATLAS_*` 仅作为 base_url 回退）
2. 用户配置：`~/.bible/config.json`
3. 系统配置：`/etc/bible/config.json`
4. 内置默认值

优先级矩阵：

| 配置项 | 环境变量 | 用户配置 | 系统配置 | 默认值 |
|---|---|---|---|---|
| `base_url` | `BIBLE_CLI_BASE_URL`，回退 `BIBLE_ATLAS_BASE_URL` | `base_url` 或 `server_url` | `base_url` 或 `server_url` | `http://127.0.0.1:5555` |
| `timeout_seconds` | `BIBLE_CLI_TIMEOUT_SECONDS` | `timeout_seconds` | `timeout_seconds` | `30` |
| `trust_env` | `BIBLE_CLI_TRUST_ENV` | `trust_env` | `trust_env` | `false` |

### 7.2 冲突与回退示例

示例 1：用户配置与环境变量冲突时，环境变量优先。

```bash
# ~/.bible/config.json 里设为 http://user.local
export BIBLE_CLI_BASE_URL="http://env.local"
go run ./cmd/bible-cli system status
# 实际使用 http://env.local
```

示例 2：`BIBLE_CLI_BASE_URL` 未设置时，使用 `BIBLE_ATLAS_BASE_URL` 回退。

```bash
unset BIBLE_CLI_BASE_URL
export BIBLE_ATLAS_BASE_URL="http://atlas.local"
go run ./cmd/bible-cli system status
# 实际使用 http://atlas.local
```

示例 3：环境变量值非法时，回退到下一优先级（用户/系统/默认）。

```bash
# ~/.bible/config.json: {"timeout_seconds": 20}
export BIBLE_CLI_TIMEOUT_SECONDS="invalid"
go run ./cmd/bible-cli system status
# 实际 timeout_seconds 回退为 20
```

## 8. 接口调用说明

客户端默认调用 `/api/v1/*`：

- `system status` -> `/api/v1/system/status`，若 404 则回退 `/health`
- `system info` -> `/api/v1/system/info`，若 404 则回退 `/info`

建议服务端返回 envelope：

```json
{"status":"ok","result":{}}
```

或

```json
{"status":"error","error":{"code":"NOT_FOUND","message":"..."}}
```

## 9. 自检命令

```bash
cd bible_cli_go
go test ./...
```

交叉构建冒烟：

```bash
cd bible_cli_go
mkdir -p dist
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -buildvcs=false -o dist/bible-cli-go_linux_amd64 ./cmd/bible-cli
GOOS=darwin GOARCH=arm64 CGO_ENABLED=0 go build -buildvcs=false -o dist/bible-cli-go_darwin_arm64 ./cmd/bible-cli
```

## 10. 参考文档

- `docs/manual/cli-contract-v1.md`
- `backlog/bible-cli-go-full-rewrite-plan-zh.md`
