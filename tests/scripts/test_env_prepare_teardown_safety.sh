#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

TEST_ROOT="$TMP_DIR/repo"
mkdir -p "$TMP_DIR/bin" "$TMP_DIR/home/.bible" "$TMP_DIR/home/.hermes"
mkdir -p "$TEST_ROOT/scripts" "$TEST_ROOT/bible_cli_go" "$TEST_ROOT/bible-oc-plugin"
cp "$ROOT_DIR/scripts/env-prepare.sh" "$TEST_ROOT/scripts/env-prepare.sh"
printf 'keep me\n' > "$TMP_DIR/home/.bible/config.json"
cat > "$TMP_DIR/home/.hermes/config.yaml" <<'YAML'
theme: dark
other:
  keep: true
YAML

cat > "$TMP_DIR/bin/pkill" <<'STUB'
#!/bin/sh
printf 'pkill %s\n' "$*" >> "$CALL_LOG"
exit 0
STUB

cat > "$TMP_DIR/bin/bash" <<'STUB'
#!/bin/sh
printf 'bash %s\n' "$*" >> "$CALL_LOG"
exit 0
STUB

cat > "$TMP_DIR/bin/openclaw" <<'STUB'
#!/bin/sh
printf 'openclaw %s\n' "$*" >> "$CALL_LOG"
if [ "${1:-}" = "config" ] && [ "${2:-}" = "get" ] && [ "${3:-}" = "plugins.slots.contextEngine" ]; then
  echo "bible-oc-plugin"
fi
exit 0
STUB

chmod +x "$TMP_DIR/bin/pkill" "$TMP_DIR/bin/bash" "$TMP_DIR/bin/openclaw"

CALL_LOG="$TMP_DIR/calls.log"
touch "$CALL_LOG"
PATH="$TMP_DIR/bin:$PATH" HOME="$TMP_DIR/home" CALL_LOG="$CALL_LOG" \
  /bin/bash "$TEST_ROOT/scripts/env-prepare.sh" teardown cli --force >/dev/null

if [ ! -f "$TMP_DIR/home/.bible/config.json" ]; then
  echo "expected CLI user config to be preserved without --purge-config" >&2
  exit 1
fi

mkdir -p "$TEST_ROOT/workspace"
printf 'test workspace marker\n' > "$TEST_ROOT/workspace/DO_NOT_DELETE_TEST"
PATH="$TMP_DIR/bin:$PATH" HOME="$TMP_DIR/home" CALL_LOG="$CALL_LOG" \
  /bin/bash "$TEST_ROOT/scripts/env-prepare.sh" teardown server --force >/dev/null

if [ ! -f "$TEST_ROOT/workspace/DO_NOT_DELETE_TEST" ]; then
  echo "expected repo workspace to be preserved without --purge-workspace" >&2
  exit 1
fi

rm -f "$TEST_ROOT/workspace/DO_NOT_DELETE_TEST"
rmdir "$TEST_ROOT/workspace" 2>/dev/null || true

PATH="$TMP_DIR/bin:$PATH" HOME="$TMP_DIR/home" CALL_LOG="$CALL_LOG" \
  /bin/bash "$TEST_ROOT/scripts/env-prepare.sh" teardown cli \
    --purge-config --force >/dev/null

if [ -f "$TMP_DIR/home/.bible/config.json" ]; then
  echo "expected --purge-config to remove CLI user config" >&2
  exit 1
fi
