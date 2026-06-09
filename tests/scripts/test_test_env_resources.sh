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
  echo "2"
  exit 0
fi
if [ "${1:-}" = "info" ]; then
  exit 0
fi
exit 0
STUB

cat > "$TMP_DIR/bin/bash" <<'STUB'
#!/bin/sh
echo "deploy script should not be invoked when Docker CPU is insufficient" >&2
exit 99
STUB

chmod +x "$TMP_DIR/bin/uv" "$TMP_DIR/bin/docker" "$TMP_DIR/bin/bash"

set +e
OUTPUT="$(
  PATH="$TMP_DIR/bin:$PATH" \
  BIBLE_INSTANCE_NAME=test-cpu-guard \
  BIBLE_OPENSEARCH_CPU_CORES=4 \
  BIBLE_OPENSEARCH_MEMORY_GB=12 \
  /bin/bash "$ROOT_DIR/scripts/env-prepare.sh" setup --full opensearch --force 2>&1
)"
STATUS=$?
set -e

if [ "$STATUS" -eq 0 ]; then
  echo "expected setup to fail when Docker has fewer CPUs than requested" >&2
  echo "$OUTPUT" >&2
  exit 1
fi

if echo "$OUTPUT" | grep -q "deploy script should not be invoked"; then
  echo "expected failure during preflight, before invoking deploy script" >&2
  echo "$OUTPUT" >&2
  exit 1
fi

if ! echo "$OUTPUT" | grep -q "Docker 可用 CPU.*2.*OpenSearch 请求.*4"; then
  echo "expected error to report available and requested OpenSearch CPUs" >&2
  echo "$OUTPUT" >&2
  exit 1
fi

rm -rf "$TMP_DIR/bin"
mkdir -p "$TMP_DIR/bin"

cat > "$TMP_DIR/bin/uv" <<'STUB'
#!/bin/sh
exit 0
STUB

cat > "$TMP_DIR/bin/docker" <<'STUB'
#!/bin/sh
if [ "${1:-}" = "info" ] && [ "${2:-}" = "--format" ]; then
  echo "8"
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

cat > "$TMP_DIR/bin/curl" <<'STUB'
#!/bin/sh
exit 0
STUB

cat > "$TMP_DIR/bin/bash" <<'STUB'
#!/bin/sh
printf 'registry=%s command=%s\n' "${BIBLE_DOCKER_REGISTRY_PREFIX:-}" "$*" >> "$CALL_LOG"
exit 0
STUB

chmod +x "$TMP_DIR/bin/uv" "$TMP_DIR/bin/docker" "$TMP_DIR/bin/lsof" "$TMP_DIR/bin/curl" "$TMP_DIR/bin/bash"

CALL_LOG="$TMP_DIR/calls.log"
PATH="$TMP_DIR/bin:$PATH" \
CALL_LOG="$CALL_LOG" \
BIBLE_INSTANCE_NAME=test-resource \
BIBLE_OPENSEARCH_CPU_CORES=2 \
BIBLE_OPENSEARCH_MEMORY_GB=6 \
/bin/bash "$ROOT_DIR/scripts/env-prepare.sh" setup --full opensearch --force >/dev/null

if ! grep -q "opensearch_deploy/deploy.sh create test-resource 9800 5699 2 6" "$CALL_LOG"; then
  echo "expected OpenSearch deploy create command to receive configured CPU and memory" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

if ! grep -q "registry= command=.*opensearch_deploy/deploy.sh create test-resource" "$CALL_LOG"; then
  echo "expected default non-interactive setup to leave Docker registry prefix empty" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

rm -rf "$TMP_DIR/bin"
mkdir -p "$TMP_DIR/bin"

cat > "$TMP_DIR/bin/uv" <<'STUB'
#!/bin/sh
exit 0
STUB

cat > "$TMP_DIR/bin/docker" <<'STUB'
#!/bin/sh
if [ "${1:-}" = "info" ] && [ "${2:-}" = "--format" ]; then
  echo "2"
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

cat > "$TMP_DIR/bin/curl" <<'STUB'
#!/bin/sh
exit 0
STUB

cat > "$TMP_DIR/bin/bash" <<'STUB'
#!/bin/sh
printf 'registry=%s command=%s\n' "${BIBLE_DOCKER_REGISTRY_PREFIX:-}" "$*" >> "$CALL_LOG"
exit 0
STUB

chmod +x "$TMP_DIR/bin/uv" "$TMP_DIR/bin/docker" "$TMP_DIR/bin/lsof" "$TMP_DIR/bin/curl" "$TMP_DIR/bin/bash"

CALL_LOG="$TMP_DIR/interactive-calls.log"
OUTPUT_LOG="$TMP_DIR/interactive-output.log"
PATH="$TMP_DIR/bin:$PATH" \
CALL_LOG="$CALL_LOG" \
BIBLE_INSTANCE_NAME=test-interactive \
ROOT_DIR="$ROOT_DIR" \
OUTPUT_LOG="$OUTPUT_LOG" \
python3 <<'PY'
import os
import pty
import select
import subprocess
import sys
import time

env = os.environ.copy()
env.pop("BIBLE_OPENSEARCH_CPU_CORES", None)
env.pop("BIBLE_OPENSEARCH_MEMORY_GB", None)

master_fd, slave_fd = pty.openpty()
proc = subprocess.Popen(
    [
        "/bin/bash",
        os.path.join(env["ROOT_DIR"], "scripts/env-prepare.sh"),
        "setup",
        "--full",
        "opensearch",
    ],
    stdin=slave_fd,
    stdout=slave_fd,
    stderr=slave_fd,
    env=env,
    close_fds=True,
)
os.close(slave_fd)

output = bytearray()
input_step = 0
deadline = time.time() + 15
while time.time() < deadline:
    ready, _, _ = select.select([master_fd], [], [], 0.1)
    if ready:
        try:
            chunk = os.read(master_fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        output.extend(chunk)
        text = output.decode(errors="replace")
        if input_step == 0 and "Docker Hub 镜像前缀" in text:
            os.write(master_fd, b"docker.m.daocloud.io/\n")
            input_step = 1
        elif input_step == 1 and "OpenSearch CPU" in text:
            os.write(master_fd, b"\n")
            input_step = 2
        elif input_step == 2 and "OpenSearch 内存" in text:
            os.write(master_fd, b"\n")
            input_step = 3
        elif input_step == 3 and "确认继续" in text:
            os.write(master_fd, b"yes\n")
            input_step = 4
    if proc.poll() is not None:
        break

try:
    os.close(master_fd)
except OSError:
    pass

if proc.poll() is None:
    proc.kill()
    proc.wait()

text = output.decode(errors="replace")
with open(env["OUTPUT_LOG"], "w", encoding="utf-8") as fh:
    fh.write(text)

if proc.returncode != 0:
    print(text, file=sys.stderr)
    raise SystemExit(proc.returncode)
PY

if ! grep -q "opensearch_deploy/deploy.sh create test-interactive 9800 5699 2 6" "$CALL_LOG"; then
  echo "expected interactive defaults to pass detected-safe CPU and memory to OpenSearch deploy" >&2
  cat "$OUTPUT_LOG" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

if ! grep -q "registry=docker.m.daocloud.io/ command=.*opensearch_deploy/deploy.sh create test-interactive" "$CALL_LOG"; then
  echo "expected interactive Docker registry prefix to be exported to OpenSearch deploy" >&2
  cat "$OUTPUT_LOG" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi
