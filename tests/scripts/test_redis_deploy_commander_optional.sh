#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

mkdir -p "$TMP_DIR/bin"

cat > "$TMP_DIR/bin/docker" <<'STUB'
#!/bin/sh
if [ "${1:-}" = "images" ]; then
  exit 0
fi
exit 0
STUB

cat > "$TMP_DIR/bin/docker-compose" <<'STUB'
#!/bin/sh
printf '%s\n' "$*" >> "$CALL_LOG"

if [ "$*" = "pull redis" ]; then
  exit 0
fi

if [ "$*" = "up -d redis" ]; then
  exit 0
fi

if [ "$*" = "up -d redis-commander" ]; then
  echo 'failed to resolve reference "docker.m.daocloud.io/rediscommander/redis-commander:latest": 403 Forbidden' >&2
  exit 1
fi

if [ "$*" = "up -d" ]; then
  echo 'redis-commander image pull failed' >&2
  exit 1
fi

exit 0
STUB

chmod +x "$TMP_DIR/bin/docker" "$TMP_DIR/bin/docker-compose"

CALL_LOG="$TMP_DIR/calls.log"
OUTPUT_LOG="$TMP_DIR/output.log"

PATH="$TMP_DIR/bin:$PATH" \
CALL_LOG="$CALL_LOG" \
REDIS_BASE_DIR="$TMP_DIR/redis" \
BIBLE_DOCKER_REGISTRY_PREFIX="docker.m.daocloud.io" \
  /bin/bash "$ROOT_DIR/scripts/redis_celery_deploy/deploy.sh" redis create commander-fallback 19880 128 \
  >"$OUTPUT_LOG" 2>&1

PATH="$TMP_DIR/bin:$PATH" \
CALL_LOG="$CALL_LOG" \
REDIS_BASE_DIR="$TMP_DIR/redis" \
BIBLE_DOCKER_REGISTRY_PREFIX="docker.m.daocloud.io" \
  /bin/bash "$ROOT_DIR/scripts/redis_celery_deploy/deploy.sh" redis start commander-fallback \
  >>"$OUTPUT_LOG" 2>&1

if ! grep -q '^up -d redis$' "$CALL_LOG"; then
  echo "expected redis service to be started independently" >&2
  cat "$CALL_LOG" >&2
  cat "$OUTPUT_LOG" >&2
  exit 1
fi

if ! grep -q '^up -d redis-commander$' "$CALL_LOG"; then
  echo "expected redis-commander startup to be attempted separately" >&2
  cat "$CALL_LOG" >&2
  cat "$OUTPUT_LOG" >&2
  exit 1
fi

if ! grep -q 'Redis Commander.*启动失败.*跳过' "$OUTPUT_LOG"; then
  echo "expected redis-commander failure to be reported as a non-fatal skip" >&2
  cat "$OUTPUT_LOG" >&2
  exit 1
fi

if grep -q 'Commander: http://localhost:20880' "$OUTPUT_LOG"; then
  echo "expected skipped redis-commander not to be advertised as available" >&2
  cat "$OUTPUT_LOG" >&2
  exit 1
fi

if ! grep -q 'Commander: 跳过' "$OUTPUT_LOG"; then
  echo "expected final summary to report redis-commander as skipped" >&2
  cat "$OUTPUT_LOG" >&2
  exit 1
fi

CALL_LOG="$TMP_DIR/disabled-calls.log"
OUTPUT_LOG="$TMP_DIR/disabled-output.log"

PATH="$TMP_DIR/bin:$PATH" \
CALL_LOG="$CALL_LOG" \
REDIS_BASE_DIR="$TMP_DIR/redis" \
BIBLE_DOCKER_REGISTRY_PREFIX="docker.m.daocloud.io" \
  /bin/bash "$ROOT_DIR/scripts/redis_celery_deploy/deploy.sh" redis create commander-disabled 19881 128 \
  >"$OUTPUT_LOG" 2>&1

PATH="$TMP_DIR/bin:$PATH" \
CALL_LOG="$CALL_LOG" \
REDIS_BASE_DIR="$TMP_DIR/redis" \
BIBLE_DOCKER_REGISTRY_PREFIX="docker.m.daocloud.io" \
REDIS_COMMANDER_ENABLED=false \
  /bin/bash "$ROOT_DIR/scripts/redis_celery_deploy/deploy.sh" redis start commander-disabled \
  >>"$OUTPUT_LOG" 2>&1

if grep -q '^up -d redis-commander$' "$CALL_LOG"; then
  echo "expected redis-commander not to be started when disabled" >&2
  cat "$CALL_LOG" >&2
  cat "$OUTPUT_LOG" >&2
  exit 1
fi

if ! grep -q 'Redis Commander 已按配置跳过' "$OUTPUT_LOG"; then
  echo "expected disabled redis-commander to be reported as configured skip" >&2
  cat "$OUTPUT_LOG" >&2
  exit 1
fi

CALL_LOG="$TMP_DIR/non-true-calls.log"
OUTPUT="$(
  PATH="$TMP_DIR/bin:$PATH" \
  CALL_LOG="$CALL_LOG" \
  REDIS_BASE_DIR="$TMP_DIR/redis" \
  REDIS_COMMANDER_ENABLED=flase \
    /bin/bash "$ROOT_DIR/scripts/redis_celery_deploy/deploy.sh" redis start commander-disabled 2>&1
)"

if grep -q '^up -d redis-commander$' "$CALL_LOG"; then
  echo "expected non-true REDIS_COMMANDER_ENABLED value to skip redis-commander" >&2
  cat "$CALL_LOG" >&2
  echo "$OUTPUT" >&2
  exit 1
fi

if ! echo "$OUTPUT" | grep -q 'Redis Commander 已按配置跳过'; then
  echo "expected non-true REDIS_COMMANDER_ENABLED value to be treated as disabled" >&2
  echo "$OUTPUT" >&2
  exit 1
fi
