#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

mkdir -p "$TMP_DIR/bin"

cat > "$TMP_DIR/bin/uv" <<'STUB'
#!/bin/sh
exit 0
STUB

cat > "$TMP_DIR/bin/docker" <<'STUB'
#!/bin/sh
if [ "${1:-}" = "info" ] && [ "${2:-}" = "--format" ]; then
  case "${3:-}" in
    "{{.NCPU}}") echo "8" ;;
    "{{.MemTotal}}") echo "17179869184" ;;
    *) echo "8" ;;
  esac
  exit 0
fi
if [ "${1:-}" = "info" ]; then
  exit 0
fi
exit 0
STUB

cat > "$TMP_DIR/bin/lsof" <<'STUB'
#!/bin/sh
exit 1
STUB

cat > "$TMP_DIR/bin/bash" <<'STUB'
#!/bin/sh
printf '%s\n' "$*" >> "$CALL_LOG"
exit 0
STUB

cat > "$TMP_DIR/bin/python3" <<'STUB'
#!/bin/sh
# Simulate the Python Redis PING fallback succeeding when redis-cli is absent.
exit 0
STUB

cat > "$TMP_DIR/bin/sleep" <<'STUB'
#!/bin/sh
exit 0
STUB

ln -s "$(command -v dirname)" "$TMP_DIR/bin/dirname"
ln -s "$(command -v mkdir)" "$TMP_DIR/bin/mkdir"

chmod +x "$TMP_DIR/bin/uv" "$TMP_DIR/bin/docker" "$TMP_DIR/bin/lsof" \
  "$TMP_DIR/bin/bash" "$TMP_DIR/bin/python3" "$TMP_DIR/bin/sleep"

CALL_LOG="$TMP_DIR/calls.log"
set +e
OUTPUT="$(
  PATH="$TMP_DIR/bin" \
  CALL_LOG="$CALL_LOG" \
  BIBLE_INSTANCE_NAME=test-redis-healthcheck \
  /bin/bash "$ROOT_DIR/scripts/env-prepare.sh" setup --full redis --force 2>&1
)"
STATUS=$?
set -e

if [ "$STATUS" -ne 0 ]; then
  echo "expected env-prepare redis setup to succeed without host redis-cli" >&2
  echo "$OUTPUT" >&2
  exit 1
fi

if ! echo "$OUTPUT" | grep -q "Redis 就绪"; then
  echo "expected Redis healthcheck to pass without host redis-cli" >&2
  echo "$OUTPUT" >&2
  exit 1
fi

if ! grep -q "redis_celery_deploy/deploy.sh redis start test-redis-healthcheck" "$CALL_LOG"; then
  echo "expected redis start deploy command to be invoked" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

if ! grep -q "redis_celery_deploy/deploy.sh worker start test-redis-healthcheck" "$CALL_LOG"; then
  echo "expected worker start deploy command to be invoked after Redis healthcheck" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi
