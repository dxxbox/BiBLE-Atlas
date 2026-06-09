#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

TEST_ROOT="$TMP_DIR/repo"
mkdir -p "$TMP_DIR/bin" "$TMP_DIR/home/.bible" "$TMP_DIR/home/.hermes/plugins/bible-hermes-plugin"
mkdir -p "$TEST_ROOT/scripts" "$TEST_ROOT/bible_cli_go" "$TEST_ROOT/bible-hermes-plugin" "$TEST_ROOT/bible-oc-plugin"
cp "$ROOT_DIR/scripts/env-prepare.sh" "$TEST_ROOT/scripts/env-prepare.sh"
printf 'keep me\n' > "$TMP_DIR/home/.bible/config.json"
printf 'keep plugin\n' > "$TMP_DIR/home/.hermes/plugins/bible-hermes-plugin/marker.txt"
cat > "$TMP_DIR/home/.hermes/config.yaml" <<'YAML'
theme: dark
bible:
  base_url: "http://127.0.0.1:5555"
  enable_memory_recall: true
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

cat > "$TMP_DIR/bin/hermes" <<'STUB'
#!/bin/sh
printf 'hermes %s\n' "$*" >> "$CALL_LOG"
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

chmod +x "$TMP_DIR/bin/pkill" "$TMP_DIR/bin/bash" "$TMP_DIR/bin/hermes" "$TMP_DIR/bin/openclaw"

CALL_LOG="$TMP_DIR/calls.log"
touch "$CALL_LOG"
PATH="$TMP_DIR/bin:$PATH" HOME="$TMP_DIR/home" CALL_LOG="$CALL_LOG" \
  /bin/bash "$TEST_ROOT/scripts/env-prepare.sh" teardown cli hermes oc --force >/dev/null

if [ ! -f "$TMP_DIR/home/.bible/config.json" ]; then
  echo "expected CLI user config to be preserved without --purge-config" >&2
  exit 1
fi

if [ ! -f "$TMP_DIR/home/.hermes/plugins/bible-hermes-plugin/marker.txt" ]; then
  echo "expected Hermes plugin files to be preserved without --uninstall-plugins" >&2
  exit 1
fi

if ! grep -q '^bible:' "$TMP_DIR/home/.hermes/config.yaml"; then
  echo "expected Hermes bible config to be preserved without --uninstall-plugins" >&2
  exit 1
fi

if grep -q '^hermes plugins disable' "$CALL_LOG"; then
  echo "expected Hermes global plugin disable to require --uninstall-plugins" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

if grep -q '^openclaw plugins uninstall\|^openclaw config remove\|^openclaw gateway restart' "$CALL_LOG"; then
  echo "expected OpenClaw global plugin changes to require --uninstall-plugins" >&2
  cat "$CALL_LOG" >&2
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
  /bin/bash "$TEST_ROOT/scripts/env-prepare.sh" teardown cli hermes oc \
    --purge-config --uninstall-plugins --force >/dev/null

if [ -f "$TMP_DIR/home/.bible/config.json" ]; then
  echo "expected --purge-config to remove CLI user config" >&2
  exit 1
fi

if [ -d "$TMP_DIR/home/.hermes/plugins/bible-hermes-plugin" ]; then
  echo "expected --uninstall-plugins to remove Hermes plugin files" >&2
  exit 1
fi

if grep -q '^bible:' "$TMP_DIR/home/.hermes/config.yaml"; then
  echo "expected --uninstall-plugins to remove Hermes bible config section" >&2
  cat "$TMP_DIR/home/.hermes/config.yaml" >&2
  exit 1
fi

if ! grep -q '^theme: dark' "$TMP_DIR/home/.hermes/config.yaml" || ! grep -q '^other:' "$TMP_DIR/home/.hermes/config.yaml"; then
  echo "expected --uninstall-plugins to preserve unrelated Hermes config" >&2
  cat "$TMP_DIR/home/.hermes/config.yaml" >&2
  exit 1
fi

if ! grep -q '^hermes plugins disable bible-hermes-plugin' "$CALL_LOG"; then
  echo "expected --uninstall-plugins to disable Hermes plugin" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

if ! grep -q '^openclaw plugins uninstall bible-oc-plugin' "$CALL_LOG"; then
  echo "expected --uninstall-plugins to uninstall OpenClaw plugin" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

if ! grep -q '^openclaw config remove plugins.slots.contextEngine' "$CALL_LOG"; then
  echo "expected --uninstall-plugins to remove OpenClaw contextEngine slot when owned by bible-oc-plugin" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi
