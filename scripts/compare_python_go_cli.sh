#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY_CMD=(uv run python -m bible_cli.python_cli)
GO_CMD=(go run ./cmd/bible-cli)

if [[ "${1:-}" == "--help" ]]; then
  cat <<'EOF'
Compare Python and Go CLI outputs for selected commands.

Usage:
  scripts/compare_python_go_cli.sh

Requirements:
  - Run from repository root or any path under repo.
  - Python dependencies installed via uv.
  - Go toolchain installed.
EOF
  exit 0
fi

cd "$ROOT_DIR"

if [[ ! -d "bible_cli_go" ]]; then
  echo "bible_cli_go directory is missing" >&2
  exit 1
fi

cases=(
  "health"
  "system status"
  "system info"
  "knowledge list"
  "knowledge search"
  "knowledge search faith"
  "memory show"
  "skills list"
)

normalize_json() {
  python - <<'PY'
import json,sys
text=sys.stdin.read().strip()
if not text:
    print("")
    raise SystemExit(0)
try:
    obj=json.loads(text)
except Exception:
    print(text)
else:
    print(json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":")))
PY
}

run_cmd() {
  local mode="$1"
  shift
  if [[ "$mode" == "python" ]]; then
    "${PY_CMD[@]}" "$@"
  else
    (cd "$ROOT_DIR/bible_cli_go" && "${GO_CMD[@]}" "$@")
  fi
}

echo "Running CLI parity checks..."

failed=0
for raw in "${cases[@]}"; do
  IFS=' ' read -r -a args <<< "$raw"

  py_stdout_file="$(mktemp)"
  py_stderr_file="$(mktemp)"
  go_stdout_file="$(mktemp)"
  go_stderr_file="$(mktemp)"

  if run_cmd python "${args[@]}" >"$py_stdout_file" 2>"$py_stderr_file"; then
    py_code=0
  else
    py_code=$?
  fi

  if run_cmd go "${args[@]}" >"$go_stdout_file" 2>"$go_stderr_file"; then
    go_code=0
  else
    go_code=$?
  fi

  py_stdout_norm="$(cat "$py_stdout_file" | normalize_json)"
  go_stdout_norm="$(cat "$go_stdout_file" | normalize_json)"
  py_stderr="$(cat "$py_stderr_file")"
  go_stderr="$(cat "$go_stderr_file")"

  match=yes
  if [[ "$py_code" != "$go_code" ]]; then
    match=no
  fi
  if [[ "$py_stdout_norm" != "$go_stdout_norm" ]]; then
    match=no
  fi

  if [[ "$match" == "yes" ]]; then
    echo "[PASS] $raw"
  else
    echo "[FAIL] $raw"
    echo "  python exit: $py_code"
    echo "  go exit:     $go_code"
    echo "  python stdout: $py_stdout_norm"
    echo "  go stdout:     $go_stdout_norm"
    echo "  python stderr: $py_stderr"
    echo "  go stderr:     $go_stderr"
    failed=1
  fi

  rm -f "$py_stdout_file" "$py_stderr_file" "$go_stdout_file" "$go_stderr_file"
done

if [[ "$failed" -ne 0 ]]; then
  echo "Parity check failed." >&2
  exit 1
fi

echo "Parity check passed."
