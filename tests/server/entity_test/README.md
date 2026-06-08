# Server Entity Live API 测试

本目录用于对 BiBLE-Atlas 后端发起真实 HTTP 请求，验证后端 API 响应。
pytest 默认会自动检查并启动测试专用 OpenSearch、Redis、FastAPI Server 和 Celery Worker。

```bash
uv run python -m pytest tests/server/entity_test -q
```

测试服务默认使用 `bible-atlas.entity-test.yaml`，并使用独立端口避免影响正式服务：

- OpenSearch: `localhost:19800`
- Redis: `localhost:19880`
- FastAPI: `http://127.0.0.1:15555`

如果需要关闭自动启动，可以设置：

```bash
BIBLE_ENTITY_TEST_AUTOSTART=0 uv run python -m pytest tests/server/entity_test -q
```

如果希望 pytest 自动启动缺失服务，但测试结束后保留这些服务用于排查，可以设置：

```bash
BIBLE_ENTITY_TEST_KEEP_SERVICES=1 uv run python -m pytest tests/server/entity_test -q
```

保留服务后，如需手动停止本次测试使用的服务，可以执行：

```bash
bash scripts/server_deploy/deploy.sh stop --profile test
bash scripts/redis_celery_deploy/deploy.sh redis stop bible_entity_test
bash scripts/opensearch_deploy/deploy.sh stop bible_entity_test
```

如需指定其他后端地址，可以设置：

```bash
BIBLE_API_BASE_URL=http://127.0.0.1:15555 uv run python -m pytest tests/server/entity_test -q
```

测试 profile 也可以手动管理：

```bash
bash scripts/server_deploy/deploy.sh start-test
bash scripts/server_deploy/deploy.sh stop-test
```

## 测试文件结构

- `test_health.py`: `/health` 接口测试，只有一个用例。
- `test_info.py`: `/info` 接口测试，只有一个用例。
- `test_import.py`: `memory import`、import task 查询，以及导入完成后的数据库写入检查。
- `test_search.py`: `memory search` 与 `knowledge-base search` 相关测试。
- `test_memory_import_search.py`: 复制 `test_import.py` 的用例，并为每个用例增加 memory search 检查。
- `conftest.py`: 共享的 live HTTP client fixture。
- `_helpers.py`: 共享断言、测试数据构造函数。

## 运行方式

运行全部 server entity 测试：

```bash
uv run python -m pytest tests/server/entity_test -q
```

运行单个测试文件：

```bash
uv run python -m pytest tests/server/entity_test/test_import.py -q
uv run python -m pytest tests/server/entity_test/test_memory_import_search.py -q
```

运行单个测试用例：

```bash
uv run python -m pytest tests/server/entity_test/test_health.py::test_health -q
```

按关键字运行参数化用例：

```bash
uv run python -m pytest tests/server/entity_test/test_search.py -k "unknown_search_type" -q
```

也可以通过部署脚本运行。`api-test` 默认运行 `tests/server/entity_test`，并会把后续参数转发给 pytest：

```bash
bash scripts/server_deploy/deploy.sh api-test -q
bash scripts/server_deploy/deploy.sh api-test tests/server/entity_test/test_info.py::test_info -q
```

## 日志

测试运行时会记录每一次 HTTP 请求和响应，默认写入：

```text
tests/server/entity_test/logs/api_requests.log
```

可以通过 `BIBLE_API_TEST_LOG` 指定其他测试日志文件：

```bash
BIBLE_API_TEST_LOG=/tmp/bible-api-test.log uv run python -m pytest tests/server/entity_test/test_health.py -q
```

后端服务也会记录每一次 HTTP 请求的 method、path、status code、client 和耗时。该日志使用项目的应用 logger，因此会遵循 `bible-atlas.yaml` 中的 `log` 配置。当前默认配置为 `log.output: file`，日志会写入 `workspace/log/bible-atlas.log`。

`test_memory_import_search.py` 会在每个用例结束时检查本用例新增的后端日志片段，确认关键 import/search 日志出现，并确认没有未预期的 `WARNING` 或 `ERROR`。默认会检查这些后端日志文件：

```text
scripts/server_deploy/runs/server.log
scripts/server_deploy/runs/worker.log
workspace/log/bible-atlas.log
```

如果需要指定其他后端日志文件，可以设置 `BIBLE_BACKEND_LOGS`，多个路径之间使用系统 path separator（Linux 下是 `:`）分隔。

如果刚修改了后端日志中间件，需要重启后端后才能在后端日志中看到新的 access log：

```bash
bash scripts/server_deploy/deploy.sh restart
```

## 数据库检查

`test_import.py` 中每个用例都会执行数据库检查：

- 成功导入类用例会等待异步任务完成，然后检查数据库中确实写入了 binding 和 memory 文档。
- 失败/拒绝类用例会检查对应测试数据没有写入数据库，避免接口返回错误但后台仍产生脏数据。

成功导入类用例的完整链路是：

1. 提交 `POST /api/import/memory`。
2. 轮询 `/api/import/memory/task/{task_id}`，直到任务进入终态。
3. 如果任务成功完成，查询 OpenSearch：
   - `v4_index_binding` 中是否存在 `MEMORY::<kb_index>` binding。
   - `memory_<kb_index>` 中是否存在以 `memory_id` 为 `_id` 的文档。

这些数据库检查需要 Redis、Celery worker 和 OpenSearch 都正常运行。如果 OpenSearch 不可达，相关用例会标记为 `xfail`；如果任务进入 `failed`、成功用例找不到数据库记录，或者失败用例发现写入了数据库，则测试失败。

`test_memory_import_search.py` 会在数据库检查之外额外执行 search 检查：

- 成功导入类用例会使用导入时的唯一 `kb_index` 和 `memory_id` 调用 `/api/search/memory`，确认能搜索到本次导入的数据。
- 失败/拒绝类用例会调用 `/api/search/memory`，确认对应 `kb_index` 没有 binding，不会误搜到脏数据。

由于 OpenSearch 写入后对搜索可见可能存在短暂延迟，成功导入后的 search 检查会轮询等待，默认最多 15 秒。可以通过 `BIBLE_SEARCH_VISIBILITY_TIMEOUT` 调整：

```bash
BIBLE_SEARCH_VISIBILITY_TIMEOUT=30 uv run python -m pytest tests/server/entity_test/test_memory_import_search.py -q
```

可以用 `BIBLE_IMPORT_TASK_TIMEOUT` 调整等待任务完成的超时时间，默认是 120 秒：

```bash
BIBLE_IMPORT_TASK_TIMEOUT=180 uv run python -m pytest tests/server/entity_test/test_import.py::test_import_memory_completed_task_writes_database -q
```

## 注意事项

这些测试刻意使用真实 HTTP 请求，而不是 FastAPI `TestClient`。因此它们验证的是已经启动的后端实体服务。

Search 成功路径依赖 OpenSearch 以及已配置的索引绑定。如果 live search 后端不可用，search 成功路径测试会标记为 `xfail`；只验证参数校验的 search 用例仍会正常运行。
