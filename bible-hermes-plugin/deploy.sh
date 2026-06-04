#!/usr/bin/env bash
# =============================================================================
# deploy.sh — 一键部署 bible-hermes-plugin 到本地 Hermes Agent
#
# 用法:
#   ./deploy.sh              # 部署（不重启 hermes）
#   ./deploy.sh --restart     # 部署后重启 hermes server
#   ./deploy.sh --watch       # 部署后 tail -f 插件日志
#   ./deploy.sh --help        # 显示帮助
#
# 前提:
#   - Hermes Agent 已安装于 ~/.hermes
#   - uv 已安装
# =============================================================================

set -euo pipefail

# ── 路径常量 ──────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_SRC="$SCRIPT_DIR"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PLUGIN_DST="$HERMES_HOME/plugins/bible-hermes-plugin"
HERMES_PYTHON="$HERMES_HOME/hermes-agent/venv/bin/python"
HERMES_UV_PIP="uv pip install --python $HERMES_PYTHON"

# ── 颜色 ──────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log()  { echo -e "${GREEN}[deploy]${NC} $*"; }
warn() { echo -e "${YELLOW}[deploy]${NC} $*"; }
err()  { echo -e "${RED}[deploy]${NC} $*"; }
info() { echo -e "${CYAN}[deploy]${NC} $*"; }

# ── 参数 ──────────────────────────────────────────────────────────────────────
RESTART=false
WATCH=false

usage() {
  echo "用法: $0 [--restart] [--watch] [--help]"
  echo ""
  echo "  (无参数)      仅同步 + 安装，不重启 Hermes"
  echo "  --restart     部署后自动重启 Hermes server"
  echo "  --watch       部署后 tail -f 插件日志"
  echo "  --help        显示本帮助"
  exit 0
}

for arg in "$@"; do
  case "$arg" in
    --restart) RESTART=true ;;
    --watch)   WATCH=true ;;
    --help)    usage ;;
    *)         err "未知参数: $arg"; usage ;;
  esac
done

# ── 前置检查 ──────────────────────────────────────────────────────────────────
if [[ ! -d "$HERMES_HOME" ]]; then
  err "Hermes 目录不存在: $HERMES_HOME"
  exit 1
fi

if [[ ! -f "$HERMES_PYTHON" ]]; then
  err "Hermes Python 解释器不存在: $HERMES_PYTHON"
  err "请确认 Hermes Agent 已正确安装"
  exit 1
fi

if ! command -v uv &>/dev/null; then
  err "未找到 uv，请先安装: https://docs.astral.sh/uv/"
  exit 1
fi

# ── Step 1: 同步源文件 ───────────────────────────────────────────────────────
log "Step 1/3: 同步源文件 → $PLUGIN_DST"

mkdir -p "$PLUGIN_DST"

# rsync 排除列表
RSYNC_EXCLUDES=(
  --exclude '__pycache__/'
  --exclude '*.pyc'
  --exclude '*.pyo'
  --exclude '.pytest_cache/'
  --exclude '.venv/'
  --exclude '.DS_Store'
  --exclude 'uv.lock'
  --exclude 'deploy.sh'
  --exclude '.git/'
  --exclude '.gitignore'
)

rsync -av --delete "${RSYNC_EXCLUDES[@]}" "$PLUGIN_SRC"/ "$PLUGIN_DST"/

log "源文件同步完成"

# ── Step 2: 安装到 Hermes venv ───────────────────────────────────────────────
log "Step 2/3: 安装到 Hermes Agent 的 Python 环境"

info "  → uv pip install --python $HERMES_PYTHON $PLUGIN_DST"

$HERMES_UV_PIP "$PLUGIN_DST"

log "安装完成"

# ── Step 3: Enable plugin (idempotent) ───────────────────────────────────────
log "Step 3/3: 确保插件已启用"

if command -v hermes &>/dev/null; then
  hermes plugins enable bible-hermes-plugin 2>/dev/null && \
    log "插件已启用" || \
    warn "hermes plugins enable 失败（可能 hermes CLI 不可用，可手动执行）"
else
  warn "hermes CLI 不在 PATH 中，跳过 enable。请手动执行: hermes plugins enable bible-hermes-plugin"
fi

# ── Step 4 (可选): 重启 Hermes ──────────────────────────────────────────────
if $RESTART; then
  log "重启 Hermes server..."
  if command -v hermes &>/dev/null; then
    hermes server restart 2>/dev/null || warn "hermes server restart 失败，请手动重启"
  else
    warn "hermes CLI 不在 PATH 中，请手动重启 Hermes"
  fi
fi

# ── Step 5 (可选): tail -f 插件日志 ─────────────────────────────────────────
if $WATCH; then
  LOG_FILE="$HERMES_HOME/logs/bible-hermes-plugin.log"
  if [[ -f "$LOG_FILE" ]]; then
    log "监控日志: $LOG_FILE (Ctrl+C 退出)"
    exec tail -f "$LOG_FILE"
  else
    warn "日志文件尚未生成: $LOG_FILE"
    info "插件首次运行后日志会自动创建，届时可手动: tail -f $LOG_FILE"
  fi
fi

# ── 完成 ──────────────────────────────────────────────────────────────────────
echo ""
log "=============================================="
log "  部署完成!"
log "=============================================="
if ! $RESTART; then
  info "提示: 如果 Hermes 正在运行，请在 session 中执行 /reset 或重启 server 使变更生效。"
  info "      或下次部署时使用: $0 --restart"
fi
