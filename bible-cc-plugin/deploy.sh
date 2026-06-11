#!/usr/bin/env bash
# =============================================================================
# deploy.sh — deploy bible-cc-plugin to Claude Code
#
# Usage:
#   ./deploy.sh                  # deploy only
#   ./deploy.sh --setup          # deploy + run bible-cc setup wizard
#   ./deploy.sh --restart        # deploy + restart bible-cc-daemon
#   ./deploy.sh --watch          # deploy + tail -f plugin log
#   ./deploy.sh --help           # show help
#
# Prerequisites:
#   - Claude Code installed
#   - uv installed
#   - BiBLE Atlas server running (for --setup connectivity check)
# =============================================================================

set -euo pipefail

# ── path constants ────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_SRC="$SCRIPT_DIR"
CC_HOME="${CLAUDE_CODE_HOME:-$HOME/.claude}"
PLUGIN_DST="$CC_HOME/plugins/bible-cc-plugin"
CC_PLUGIN_DATA="$HOME/.bible-cc"

# ── colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}[deploy]${NC} $*"; }
warn() { echo -e "${YELLOW}[deploy]${NC} $*"; }
err()  { echo -e "${RED}[deploy]${NC} $*"; }
info() { echo -e "${CYAN}[deploy]${NC} $*"; }

# ── flags ─────────────────────────────────────────────────────────────────────
SETUP=false
RESTART=false
WATCH=false

usage() {
  echo "Usage: $0 [--setup] [--restart] [--watch] [--help]"
  echo ""
  echo "  (no flags)    sync + install only"
  echo "  --setup       deploy then run bible-cc setup wizard"
  echo "  --restart     deploy then restart bible-cc-daemon"
  echo "  --watch       deploy then tail -f plugin log"
  echo "  --help        show this help"
  exit 0
}

for arg in "$@"; do
  case "$arg" in
    --setup)   SETUP=true ;;
    --restart) RESTART=true ;;
    --watch)   WATCH=true ;;
    --help)    usage ;;
    *)         err "unknown flag: $arg"; usage ;;
  esac
done

# ── preflight ─────────────────────────────────────────────────────────────────

if ! command -v uv &>/dev/null; then
  err "uv not found — install from https://docs.astral.sh/uv/"
  exit 1
fi

# Find a workable Python. Prefer the project venv if present, fall back.
PYTHON_BIN=""
for candidate in \
  "$SCRIPT_DIR/../.venv/bin/python" \
  "$SCRIPT_DIR/.venv/bin/python" \
  "$(command -v python3 2>/dev/null || true)" \
  "$(command -v python 2>/dev/null || true)"; do
  if [[ -n "$candidate" && -x "$candidate" ]]; then
    PYTHON_BIN="$candidate"
    break
  fi
done

if [[ -z "$PYTHON_BIN" ]]; then
  err "no Python interpreter found"
  exit 1
fi
info "using Python: $PYTHON_BIN"

# ── Step 1: sync source files ─────────────────────────────────────────────────
log "Step 1/4: sync source files → $PLUGIN_DST"

mkdir -p "$PLUGIN_DST"

RSYNC_EXCLUDES=(
  --exclude '__pycache__/'
  --exclude '*.pyc'
  --exclude '*.pyo'
  --exclude '.pytest_cache/'
  --exclude '.venv/'
  --exclude 'build/'
  --exclude '*.egg-info/'
  --exclude '.DS_Store'
  --exclude 'uv.lock'
  --exclude 'deploy.sh'
  --exclude '.git/'
  --exclude '.gitignore'
)

rsync -av --delete "${RSYNC_EXCLUDES[@]}" "$PLUGIN_SRC"/ "$PLUGIN_DST"/

log "sync complete"

# ── Step 2: install into Python environment ───────────────────────────────────
log "Step 2/4: install bible-cc-plugin"

uv pip install --python "$PYTHON_BIN" "$PLUGIN_DST"

log "install complete"

# ── Step 3: enable plugin in Claude Code ──────────────────────────────────────
log "Step 3/4: enable plugin"

if command -v claude &>/dev/null; then
  claude plugins enable bible-cc-plugin 2>/dev/null && \
    log "plugin enabled" || \
    warn "claude plugins enable failed — you may need to enable it manually"
else
  warn "claude CLI not on PATH — skip enable."
  info "Add to ~/.claude/settings.json: \"bible-cc-plugin\": true"
fi

# ── Step 4 (optional): setup wizard ───────────────────────────────────────────
if $SETUP; then
  log "Step 4/4: running setup wizard"
  echo ""
  "$PYTHON_BIN" -m bible_cc_plugin.cli setup
fi

# ── Step 5 (optional): restart daemon ─────────────────────────────────────────
if $RESTART; then
  log "restarting daemon..."
  bible-cc-daemon --stop 2>/dev/null || true
  sleep 1
  bible-cc-daemon --start 2>/dev/null || \
    warn "daemon start failed — it will auto-start on next Claude Code session via Setup hook"
fi

# ── Step 6 (optional): watch log ──────────────────────────────────────────────
if $WATCH; then
  LOG_FILE="$CC_PLUGIN_DATA/logs/bible-cc-plugin.log"
  if [[ -f "$LOG_FILE" ]]; then
    log "watching log: $LOG_FILE (Ctrl+C to exit)"
    exec tail -f "$LOG_FILE"
  else
    warn "log file not yet created: $LOG_FILE"
    info "log will appear on first daemon start"
  fi
fi

# ── done ──────────────────────────────────────────────────────────────────────
echo ""
log "=============================================="
log "  deploy complete!"
log "=============================================="
info "plugin dir: $PLUGIN_DST"
info "config dir: $CC_PLUGIN_DATA"
if ! $RESTART; then
  info "tip: daemon auto-starts on next Claude Code session via Setup hook."
  info "     or start it now: bible-cc-daemon --start"
fi
if ! $SETUP; then
  info "tip: run 'bible-cc setup' to configure BiBLE Atlas connection."
fi
