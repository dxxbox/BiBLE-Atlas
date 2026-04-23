# Bible CLI Go 性能基线报告（2026-04-23）

本文档记录 `bible_cli_go` 当前实现的本地性能基线，用于后续回归对比。

## 1. 测试对象

- 二进制：`bible_cli_go/dist/bible-cli-go`
- 构建命令：

```bash
go build -buildvcs=false -trimpath -ldflags='-s -w' -o dist/bible-cli-go ./cmd/bible-cli
```

- 采样命令（稳定无外部依赖路径）：`./dist/bible-cli-go --help`
- 采样时间：2026-04-23

## 2. 采样方法

- 冷启动：构建后单次执行，使用纳秒时间戳计算 wall-clock 延迟。
- 延迟分位：预热 3 次后，采样 30 次，计算 `P50/P95`。
- 内存峰值：使用 `/usr/bin/time -f '%M'` 采样 30 次，取最大 `maxrss`（KB）。

说明：
- `--help` 作为基线命令用于度量 CLI 进程启动与参数解析开销，不包含网络调用时延。
- `maxrss` 为进程峰值常驻集大小（KB），受系统与采样环境影响。

## 3. 基线结果

- 冷启动（cold start）：`6.543 ms`
- 延迟 P50：`6.053 ms`
- 延迟 P95：`6.568 ms`
- 内存峰值（peak RSS）：`8020 KB`（约 `7.83 MB`）

## 4. 原始样本规模

- 延迟样本数：`N=30`
- 内存样本数：`N=30`

## 5. 后续建议

1. 增加网络命令基线（如 `health/system status`），并在本地 mock server 下复测 P50/P95。
2. 在 CI 中固化基线文件（如 `perf-baseline.json`）并加入阈值门禁。
3. 对关键命令扩展到 `N=100` 采样，降低抖动影响。
