#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

TEST_ROOT="$TMP_DIR/repo"
mkdir -p "$TMP_DIR/bin"
mkdir -p "$TEST_ROOT/scripts/server_deploy" "$TEST_ROOT/.venv/bin"
cp "$ROOT_DIR/scripts/env-prepare.sh" "$TEST_ROOT/scripts/env-prepare.sh"

cat > "$TMP_DIR/bin/uv" <<'STUB'
#!/bin/sh
exit 0
STUB

cat > "$TMP_DIR/bin/lsof" <<'STUB'
#!/bin/sh
exit 1
STUB

cat > "$TMP_DIR/bin/curl" <<'STUB'
#!/bin/sh
exit 0
STUB

cat > "$TMP_DIR/bin/bash" <<'STUB'
#!/bin/sh
printf 'bash %s\n' "$*" >> "$CALL_LOG"
if [ "${FAIL_SERVER_DEPLOY:-false}" = "true" ]; then
  exit 1
fi
exit 0
STUB

cat > "$TEST_ROOT/.venv/bin/python" <<'STUB'
#!/bin/sh
printf 'python %s\n' "$*" >> "$CALL_LOG"
exit 0
STUB

chmod +x "$TMP_DIR/bin/uv" "$TMP_DIR/bin/lsof" "$TMP_DIR/bin/curl" "$TMP_DIR/bin/bash"
chmod +x "$TEST_ROOT/.venv/bin/python"

wait_for_call_log() {
  local file=$1
  for _ in $(seq 1 20); do
    [ -s "$file" ] && return 0
    sleep 0.1
  done
  return 1
}

CALL_LOG="$TMP_DIR/default-server.log"
touch "$CALL_LOG"
PATH="$TMP_DIR/bin:$PATH" CALL_LOG="$CALL_LOG" \
  /bin/bash "$TEST_ROOT/scripts/env-prepare.sh" setup server --force >/dev/null
wait_for_call_log "$CALL_LOG" || true

if ! grep -q 'bash .*/scripts/server_deploy/deploy.sh start' "$CALL_LOG"; then
  echo "expected setup server to start the real server by default" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

if grep -q 'python -m bible.test_mode.server' "$CALL_LOG"; then
  echo "expected setup server default not to start Test Mode" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

CALL_LOG="$TMP_DIR/explicit-test-mode.log"
touch "$CALL_LOG"
PATH="$TMP_DIR/bin:$PATH" CALL_LOG="$CALL_LOG" \
  /bin/bash "$TEST_ROOT/scripts/env-prepare.sh" setup --test-mode server --force >/dev/null
wait_for_call_log "$CALL_LOG" || true

if ! grep -q 'python -m bible.test_mode.server' "$CALL_LOG"; then
  echo "expected --test-mode server setup to start Test Mode explicitly" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

if grep -q 'bash .*/scripts/server_deploy/deploy.sh start' "$CALL_LOG"; then
  echo "expected --test-mode server setup not to start the real server deploy script" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

CALL_LOG="$TMP_DIR/base-url-server.log"
touch "$CALL_LOG"
PATH="$TMP_DIR/bin:$PATH" CALL_LOG="$CALL_LOG" \
  /bin/bash "$TEST_ROOT/scripts/env-prepare.sh" setup server --base-url http://127.0.0.1:5566 --force >/dev/null

if ! grep -q 'bash .*/scripts/server_deploy/deploy.sh start --host 127.0.0.1 --port 5566' "$CALL_LOG"; then
  echo "expected real server setup to pass --base-url host and port to server_deploy" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

CALL_LOG="$TMP_DIR/server-deploy-failure.log"
touch "$CALL_LOG"
if PATH="$TMP_DIR/bin:$PATH" CALL_LOG="$CALL_LOG" FAIL_SERVER_DEPLOY=true \
  /bin/bash "$TEST_ROOT/scripts/env-prepare.sh" setup server --force >/dev/null 2>&1; then
  echo "expected setup server to fail when server_deploy start fails" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi
