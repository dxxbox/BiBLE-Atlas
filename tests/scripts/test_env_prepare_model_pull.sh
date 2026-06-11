#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

TEST_ROOT="$TMP_DIR/repo"
mkdir -p "$TMP_DIR/bin"
mkdir -p "$TEST_ROOT/scripts/server_deploy" "$TEST_ROOT/.venv/bin" "$TEST_ROOT/tools/model_puller"
cp "$ROOT_DIR/scripts/env-prepare.sh" "$TEST_ROOT/scripts/env-prepare.sh"
cp "$ROOT_DIR/tools/model_puller/main.py" "$TEST_ROOT/tools/model_puller/main.py"

write_config() {
  local preload=$1
  cat > "$TEST_ROOT/bible-atlas.yaml" <<YAML
workspace:
  root: ./workspace
vector:
  preload_on_startup: ${preload}
  hf_cache_dir: ./workspace/hf_cache
  available_models:
    - id: mini
      name: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
rerank:
  preload_on_startup: false
  hf_cache_dir: ./workspace/hf_cache
  available_models:
    - id: rerank
      name: BAAI/bge-reranker-base
YAML
}

cat > "$TMP_DIR/bin/uv" <<'STUB'
#!/bin/sh
printf 'uv %s\n' "$*" >> "$CALL_LOG"
if [ "${FAIL_MODEL_PULL:-false}" = "true" ]; then
  exit 7
fi
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
exit 0
STUB

cat > "$TEST_ROOT/.venv/bin/python" <<'STUB'
#!/bin/sh
printf 'python %s\n' "$*" >> "$CALL_LOG"
exit 0
STUB

chmod +x "$TMP_DIR/bin/uv" "$TMP_DIR/bin/lsof" "$TMP_DIR/bin/curl" "$TMP_DIR/bin/bash"
chmod +x "$TEST_ROOT/.venv/bin/python"

write_config true
CALL_LOG="$TMP_DIR/pull-models.log"
touch "$CALL_LOG"
PATH="$TMP_DIR/bin:$PATH" CALL_LOG="$CALL_LOG" \
  /bin/bash "$TEST_ROOT/scripts/env-prepare.sh" pull-models --force >/dev/null

if ! grep -q 'uv run python .*/tools/model_puller/main.py pull --config .*/bible-atlas.yaml --repo-root .*/repo' "$CALL_LOG"; then
  echo "expected pull-models to invoke standalone model puller" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

if grep -q 'server_deploy/deploy.sh start' "$CALL_LOG"; then
  echo "expected standalone pull-models not to start server" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

CALL_LOG="$TMP_DIR/pull-models-options.log"
touch "$CALL_LOG"
PATH="$TMP_DIR/bin:$PATH" CALL_LOG="$CALL_LOG" \
  /bin/bash "$TEST_ROOT/scripts/env-prepare.sh" pull-models --type vector --model mini --dry-run --force >/dev/null

if ! grep -q 'tools/model_puller/main.py pull .* --type vector --model mini --dry-run' "$CALL_LOG"; then
  echo "expected pull-models wrapper to pass model selection options to standalone tool" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

write_config true
CALL_LOG="$TMP_DIR/setup-server-prepull.log"
touch "$CALL_LOG"
PATH="$TMP_DIR/bin:$PATH" CALL_LOG="$CALL_LOG" \
  /bin/bash "$TEST_ROOT/scripts/env-prepare.sh" setup server --force >/dev/null

pull_line=$(grep -n 'tools/model_puller/main.py pull' "$CALL_LOG" | cut -d: -f1 | head -1)
server_line=$(grep -n 'server_deploy/deploy.sh start' "$CALL_LOG" | cut -d: -f1 | head -1)
if [ -z "$pull_line" ] || [ -z "$server_line" ] || [ "$pull_line" -ge "$server_line" ]; then
  echo "expected setup server to pull models before starting server" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

if ! grep -q 'tools/model_puller/main.py pull .* --type vector' "$CALL_LOG"; then
  echo "expected vector-only preload config to auto pull only vector models" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

cat > "$TEST_ROOT/bible-atlas.yaml" <<'YAML'
workspace:
  root: ./workspace
vector:
  preload_on_startup: ${VECTOR_PRELOAD}
  hf_cache_dir: ./workspace/hf_cache
  available_models:
    - id: mini
      name: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
rerank:
  preload_on_startup: false
YAML
CALL_LOG="$TMP_DIR/setup-server-env-preload.log"
touch "$CALL_LOG"
PATH="$TMP_DIR/bin:$PATH" CALL_LOG="$CALL_LOG" VECTOR_PRELOAD=true \
  /bin/bash "$TEST_ROOT/scripts/env-prepare.sh" setup server --force >/dev/null

if ! grep -q 'tools/model_puller/main.py pull .* --type vector' "$CALL_LOG"; then
  echo "expected env-var-backed preload flag to trigger vector model pull" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

rm -rf "$TMP_DIR/reuse-bin"
mkdir -p "$TMP_DIR/reuse-bin"
cp "$TMP_DIR/bin/uv" "$TMP_DIR/reuse-bin/uv"
cp "$TMP_DIR/bin/bash" "$TMP_DIR/reuse-bin/bash"
cat > "$TMP_DIR/reuse-bin/lsof" <<'STUB'
#!/bin/sh
exit 0
STUB
cat > "$TMP_DIR/reuse-bin/curl" <<'STUB'
#!/bin/sh
exit 0
STUB
chmod +x "$TMP_DIR/reuse-bin/lsof" "$TMP_DIR/reuse-bin/curl"
write_config true
CALL_LOG="$TMP_DIR/setup-server-reuse.log"
touch "$CALL_LOG"
PATH="$TMP_DIR/reuse-bin:$PATH" CALL_LOG="$CALL_LOG" \
  /bin/bash "$TEST_ROOT/scripts/env-prepare.sh" setup server --force >/dev/null

if grep -q 'tools/model_puller/main.py pull' "$CALL_LOG"; then
  echo "expected setup server to skip pre-pull when reusing a healthy running server" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

if grep -q 'server_deploy/deploy.sh start' "$CALL_LOG"; then
  echo "expected setup server reuse path not to start server" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

CUSTOM_CONFIG="$TEST_ROOT/custom-atlas.yaml"
cp "$TEST_ROOT/bible-atlas.yaml" "$CUSTOM_CONFIG"
CALL_LOG="$TMP_DIR/setup-server-custom-config.log"
touch "$CALL_LOG"
PATH="$TMP_DIR/bin:$PATH" CALL_LOG="$CALL_LOG" \
  /bin/bash "$TEST_ROOT/scripts/env-prepare.sh" setup server --config "$CUSTOM_CONFIG" --force >/dev/null

if ! grep -q "tools/model_puller/main.py pull --config $CUSTOM_CONFIG" "$CALL_LOG"; then
  echo "expected setup server custom config to be passed to model puller" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

if ! grep -q "server_deploy/deploy.sh start .*--config $CUSTOM_CONFIG" "$CALL_LOG"; then
  echo "expected setup server custom config to be passed to server_deploy" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

write_config false
CALL_LOG="$TMP_DIR/setup-server-no-prepull.log"
touch "$CALL_LOG"
OUTPUT="$(
  PATH="$TMP_DIR/bin:$PATH" CALL_LOG="$CALL_LOG" \
    /bin/bash "$TEST_ROOT/scripts/env-prepare.sh" setup server --force
)"

if grep -q 'tools/model_puller/main.py pull' "$CALL_LOG"; then
  echo "expected preload_on_startup=false not to auto pull models" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

if ! echo "$OUTPUT" | grep -q '模型未预拉取'; then
  echo "expected setup server to remind user when model auto pull is disabled" >&2
  echo "$OUTPUT" >&2
  exit 1
fi

write_config true
CALL_LOG="$TMP_DIR/setup-server-pull-failure.log"
touch "$CALL_LOG"
PATH="$TMP_DIR/bin:$PATH" CALL_LOG="$CALL_LOG" FAIL_MODEL_PULL=true \
  /bin/bash "$TEST_ROOT/scripts/env-prepare.sh" setup server --force >/dev/null

if ! grep -q 'tools/model_puller/main.py pull' "$CALL_LOG"; then
  echo "expected setup server to attempt model pull" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

if ! grep -q 'server_deploy/deploy.sh start' "$CALL_LOG"; then
  echo "expected setup server to continue after model pull failure" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi
