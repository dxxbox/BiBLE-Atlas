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
printf 'commander_enabled=%s commander_image=%s command=%s\n' \
  "${REDIS_COMMANDER_ENABLED:-}" "${REDIS_COMMANDER_IMAGE:-}" "$*" >> "$CALL_LOG"
exit 0
STUB

cat > "$TMP_DIR/bin/python3" <<'STUB'
#!/bin/sh
# Simulate Redis PING healthcheck success.
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

CALL_LOG="$TMP_DIR/force-calls.log"
PATH="$TMP_DIR/bin" \
CALL_LOG="$CALL_LOG" \
BIBLE_INSTANCE_NAME=test-commander-skip \
  /bin/bash "$ROOT_DIR/scripts/env-prepare.sh" setup --full redis --force >/dev/null

if ! grep -q 'commander_enabled=false commander_image= command=.*redis_celery_deploy/deploy.sh redis start test-commander-skip' "$CALL_LOG"; then
  echo "expected forced/non-interactive Redis setup to skip Redis Commander" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

CALL_LOG="$TMP_DIR/explicit-disabled-calls.log"
PATH="$TMP_DIR/bin" \
CALL_LOG="$CALL_LOG" \
BIBLE_INSTANCE_NAME=test-commander-explicit-disabled \
REDIS_COMMANDER_ENABLED=false \
REDIS_COMMANDER_IMAGE=stale.example/redis-commander:latest \
  /bin/bash "$ROOT_DIR/scripts/env-prepare.sh" setup --full redis --force >/dev/null

if ! grep -q 'commander_enabled=false commander_image=stale.example/redis-commander:latest command=.*redis_celery_deploy/deploy.sh redis start test-commander-explicit-disabled' "$CALL_LOG"; then
  echo "expected explicit REDIS_COMMANDER_ENABLED=false to override stale REDIS_COMMANDER_IMAGE" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi

CALL_LOG="$TMP_DIR/interactive-calls.log"
OUTPUT_LOG="$TMP_DIR/interactive-output.log"
PATH="$TMP_DIR/bin" \
CALL_LOG="$CALL_LOG" \
BIBLE_INSTANCE_NAME=test-commander-enabled \
ROOT_DIR="$ROOT_DIR" \
OUTPUT_LOG="$OUTPUT_LOG" \
/usr/bin/python3 <<'PY'
import os
import pty
import select
import subprocess
import sys
import time

env = os.environ.copy()
master_fd, slave_fd = pty.openpty()
proc = subprocess.Popen(
    [
        "/bin/bash",
        os.path.join(env["ROOT_DIR"], "scripts/env-prepare.sh"),
        "setup",
        "--full",
        "redis",
    ],
    stdin=slave_fd,
    stdout=slave_fd,
    stderr=slave_fd,
    env=env,
    close_fds=True,
)
os.close(slave_fd)

output = bytearray()
answered = {
    "registry": False,
    "confirm_full": False,
    "commander": False,
    "commander_image": False,
}
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
        if not answered["registry"] and "Docker Hub 镜像前缀" in text:
            os.write(master_fd, b"\n")
            answered["registry"] = True
        elif not answered["confirm_full"] and "确认继续" in text:
            os.write(master_fd, b"yes\n")
            answered["confirm_full"] = True
        elif not answered["commander"] and "启用 Redis Commander" in text:
            os.write(master_fd, b"yes\n")
            answered["commander"] = True
        elif not answered["commander_image"] and "Redis Commander 完整镜像名" in text:
            os.write(master_fd, b"mirror.example/redis-commander:latest\n")
            answered["commander_image"] = True
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

if ! grep -q 'commander_enabled=true commander_image=mirror.example/redis-commander:latest command=.*redis_celery_deploy/deploy.sh redis start test-commander-enabled' "$CALL_LOG"; then
  echo "expected interactive Redis setup to pass user-provided Redis Commander image" >&2
  cat "$OUTPUT_LOG" >&2
  cat "$CALL_LOG" >&2
  exit 1
fi
