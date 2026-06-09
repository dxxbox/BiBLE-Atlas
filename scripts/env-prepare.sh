#!/usr/bin/env bash
# =============================================================================
# env-prepare.sh — BiBLE Atlas 测试环境一站式管理脚本
#
# 用法:
#   ./scripts/env-prepare.sh setup                     # 一键搭建（Test Mode + 全部客户端）
#   ./scripts/env-prepare.sh setup --full              # 完整后端模式（含 OpenSearch/Redis）
#   ./scripts/env-prepare.sh setup cli hermes          # 只搭建指定组件
#   ./scripts/env-prepare.sh teardown                  # 一键清理
#   ./scripts/env-prepare.sh teardown --full           # 清理含 Docker 容器删除
#   ./scripts/env-prepare.sh status                    # 查看所有组件状态
#
# 组件: opensearch | redis | server | cli | hermes | oc | all
# =============================================================================
set -euo pipefail

# ── 路径常量 ──────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

OS_DEPLOY="$SCRIPT_DIR/opensearch_deploy/deploy.sh"
REDIS_DEPLOY="$SCRIPT_DIR/redis_celery_deploy/deploy.sh"
SERVER_DEPLOY="$SCRIPT_DIR/server_deploy/deploy.sh"
HERMES_DEPLOY="$REPO_ROOT/bible-hermes-plugin/deploy.sh"

CLI_DIR="$REPO_ROOT/bible_cli_go"
OC_DIR="$REPO_ROOT/bible-oc-plugin"
HERMES_DIR="$REPO_ROOT/bible-hermes-plugin"

# ── 默认值 ────────────────────────────────────────────────────────────────────
MODE="test"              # test | full
BASE_URL="http://127.0.0.1:5555"
SKIP_TEST=false
FORCE=false
PURGE_CONFIG=false
PURGE_WORKSPACE=false
UNINSTALL_PLUGINS=false
INSTANCE_NAME="${BIBLE_INSTANCE_NAME:-bibletest}"
DOCKER_REGISTRY_PREFIX="${BIBLE_DOCKER_REGISTRY_PREFIX:-}"

# OpenSearch 端口（必须匹配 bible-atlas.yaml 默认值）
OS_HTTP_PORT=9800
OS_DASH_PORT=5699
DEFAULT_OS_CPU_CORES=4
DEFAULT_OS_MEMORY_GB=12
OPENSEARCH_DASHBOARDS_MEMORY_GB=2
OS_CPU_CORES="${BIBLE_OPENSEARCH_CPU_CORES:-}"
OS_MEMORY_GB="${BIBLE_OPENSEARCH_MEMORY_GB:-}"

# Redis 端口（必须匹配 bible-atlas.yaml 默认值）
REDIS_PORT=9880
REDIS_MEMORY_MB=512
REDIS_COMMANDER_MEMORY_MB=256
REDIS_COMMANDER_ENABLED="${REDIS_COMMANDER_ENABLED:-}"

# ── 颜色（$'...' ANSI-C quoting，直接内嵌转义字节，避免依赖 echo -e）─────
BOLD=$'\033[1m'
DIM=$'\033[2m'
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[0;33m'
BLUE=$'\033[0;34m'
CYAN=$'\033[0;36m'
NC=$'\033[0m'

icon_ok="${GREEN}✓${NC}"
icon_skip="${YELLOW}○${NC}"
icon_fail="${RED}✗${NC}"
icon_warn="${YELLOW}⚠${NC}"

# ── 日志 ──────────────────────────────────────────────────────────────────────
step()     { echo; echo "${BOLD}${CYAN}── $* ──────────────────────────────────${NC}"; }
ok()       { echo "  ${icon_ok} $*"; }
skip()     { echo "  ${icon_skip} $* (已跳过)"; }
fail()     { echo "  ${icon_fail} $*"; }
info()     { echo "  ${BLUE}ℹ${NC}  $*"; }
warn()     { echo "  ${icon_warn} $*"; }
detail()   { echo "    ${DIM}$*${NC}"; }

die() {
  echo "${RED}${BOLD}FATAL:${NC} $*" >&2
  exit 1
}

# ── 工具函数 ──────────────────────────────────────────────────────────────────
check_cmd()  { command -v "$1" &>/dev/null; }

is_positive_integer() {
  [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

is_interactive() {
  [ -t 0 ] && [ -t 1 ]
}

require_cmd() {
  check_cmd "$1" || die "缺少命令 '$1'。${2:-请先安装。}"
}

require_env() {
  if [ ! -f "$REPO_ROOT/.venv/bin/python" ]; then
    die "未找到 .venv，请先执行: cd '$REPO_ROOT' && uv sync --all-extras"
  fi
}

port_free() {
  local port=$1
  if command -v lsof &>/dev/null; then
    ! lsof -i ":$port" -sTCP:LISTEN &>/dev/null
  elif command -v ss &>/dev/null; then
    ! ss -tln 2>/dev/null | grep -q ":$port "
  else
    return 0
  fi
}

confirm() {
  $FORCE && return 0
  local prompt=$1
  read -rp "$(echo "${YELLOW}?${NC} ${prompt} (yes/no) [no]: ")" answer
  [ "$answer" = "yes" ] || [ "$answer" = "y" ]
}

ask_with_default() {
  local prompt=$1
  local default=$2
  local answer
  read -rp "$(echo "${YELLOW}?${NC} ${prompt} [${default}]: ")" answer
  echo "${answer:-$default}"
}

normalize_registry_prefix() {
  local prefix=$1
  prefix="${prefix#http://}"
  prefix="${prefix#https://}"
  prefix="${prefix%/}"
  echo "$prefix"
}

bytes_to_gb_floor() {
  local bytes=$1
  is_positive_integer "$bytes" || return 1
  echo $((bytes / 1024 / 1024 / 1024))
}

bytes_to_mb_floor() {
  local bytes=$1
  is_positive_integer "$bytes" || return 1
  echo $((bytes / 1024 / 1024))
}

resolve_opensearch_resources() {
  local docker_cpus=${1:-}
  local docker_memory_gb=${2:-}
  local suggested_cpu=$DEFAULT_OS_CPU_CORES

  if is_positive_integer "$docker_cpus" && [ "$docker_cpus" -lt "$suggested_cpu" ]; then
    suggested_cpu=$docker_cpus
  fi

  local suggested_memory=$DEFAULT_OS_MEMORY_GB
  if [ "$suggested_cpu" -le 2 ]; then
    suggested_memory=6
  fi
  if is_positive_integer "$docker_memory_gb"; then
    local available_opensearch_memory_gb=$((docker_memory_gb - OPENSEARCH_DASHBOARDS_MEMORY_GB))
    if [ "$available_opensearch_memory_gb" -lt 1 ]; then
      available_opensearch_memory_gb=1
    fi
    if [ "$available_opensearch_memory_gb" -lt "$suggested_memory" ]; then
      suggested_memory=$available_opensearch_memory_gb
    fi
  fi

  if [ -z "$OS_CPU_CORES" ] && ! $FORCE && is_interactive; then
    info "Docker 可用 CPU: ${docker_cpus:-未知}"
    OS_CPU_CORES="$(ask_with_default "OpenSearch CPU 核数" "$suggested_cpu")"
  fi

  if [ -z "$OS_MEMORY_GB" ] && ! $FORCE && is_interactive; then
    info "Docker 可用内存: ${docker_memory_gb:-未知} GB（Dashboards 预留 ${OPENSEARCH_DASHBOARDS_MEMORY_GB}GB）"
    OS_MEMORY_GB="$(ask_with_default "OpenSearch 内存 GB" "$suggested_memory")"
  fi

  OS_CPU_CORES="${OS_CPU_CORES:-$DEFAULT_OS_CPU_CORES}"
  OS_MEMORY_GB="${OS_MEMORY_GB:-$DEFAULT_OS_MEMORY_GB}"

  is_positive_integer "$OS_CPU_CORES" || die "BIBLE_OPENSEARCH_CPU_CORES 必须是正整数，当前值: $OS_CPU_CORES"
  is_positive_integer "$OS_MEMORY_GB" || die "BIBLE_OPENSEARCH_MEMORY_GB 必须是正整数，当前值: $OS_MEMORY_GB"
}

resolve_docker_registry_prefix() {
  if [ -z "$DOCKER_REGISTRY_PREFIX" ] && ! $FORCE && is_interactive; then
    DOCKER_REGISTRY_PREFIX="$(ask_with_default "Docker Hub 镜像前缀/镜像站（留空使用默认 Docker Hub）" "")"
  fi

  DOCKER_REGISTRY_PREFIX="$(normalize_registry_prefix "$DOCKER_REGISTRY_PREFIX")"
  export BIBLE_DOCKER_REGISTRY_PREFIX="$DOCKER_REGISTRY_PREFIX"
}

resolve_redis_commander_config() {
  local commander_image="${REDIS_COMMANDER_IMAGE:-}"

  if [ "$REDIS_COMMANDER_ENABLED" = "true" ]; then
    :
  elif [ -z "$REDIS_COMMANDER_ENABLED" ] && [ -n "$commander_image" ]; then
    REDIS_COMMANDER_ENABLED="true"
  elif [ -z "$REDIS_COMMANDER_ENABLED" ] && ! $FORCE && is_interactive; then
    if confirm "启用 Redis Commander 可选 Web UI？需要提供可访问的完整镜像名"; then
      commander_image="$(ask_with_default "Redis Commander 完整镜像名" "")"
      [ -n "$commander_image" ] || die "启用 Redis Commander 时必须提供完整镜像名"
      REDIS_COMMANDER_ENABLED="true"
    else
      REDIS_COMMANDER_ENABLED="false"
    fi
  else
    REDIS_COMMANDER_ENABLED="false"
  fi

  REDIS_COMMANDER_ENABLED="${REDIS_COMMANDER_ENABLED:-false}"

  if [ "$REDIS_COMMANDER_ENABLED" = "true" ] && [ -z "$commander_image" ]; then
    die "启用 Redis Commander 时必须设置 REDIS_COMMANDER_IMAGE 为完整镜像名"
  fi

  export REDIS_COMMANDER_ENABLED
  if [ -n "$commander_image" ]; then
    export REDIS_COMMANDER_IMAGE="$commander_image"
  fi
}

remove_hermes_bible_config() {
  local config_file="$HOME/.hermes/config.yaml"
  [ -f "$config_file" ] || return 0

  local tmp_file="${config_file}.tmp.$$"
  awk '
    /^bible:[[:space:]]*$/ { skip = 1; next }
    skip && /^[^[:space:]#][^:]*:/ { skip = 0 }
    !skip { print }
  ' "$config_file" > "$tmp_file"
  mv "$tmp_file" "$config_file"
}

wait_for_url() {
  local url=$1
  local timeout=${2:-30}
  local interval=${3:-2}
  for i in $(seq 1 $((timeout / interval))); do
    if curl -s "$url" &>/dev/null; then return 0; fi
    sleep "$interval"
  done
  return 1
}

redis_ping() {
  local port=${1:-$REDIS_PORT}
  if check_cmd redis-cli; then
    redis-cli -p "$port" ping &>/dev/null
    return $?
  fi

  check_cmd python3 || return 1
  python3 - "$port" <<'PY' &>/dev/null
import socket
import sys

port = int(sys.argv[1])
with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
    sock.sendall(b"*1\r\n$4\r\nPING\r\n")
    response = sock.recv(16)
if response != b"+PONG\r\n":
    raise SystemExit(1)
PY
}

# ── 帮助 ──────────────────────────────────────────────────────────────────────
usage() {
  cat <<EOF
${BOLD}BiBLE Atlas — 测试环境一站式管理${NC}

${BOLD}命令:${NC}
  $0 ${CYAN}setup${NC}    [选项] [组件...]   从零搭建测试环境
  $0 ${CYAN}teardown${NC} [选项] [组件...]   清理测试环境
  $0 ${CYAN}status${NC}   [选项]             查看组件状态

${BOLD}组件（可多个，默认 all）:${NC}
  opensearch     OpenSearch 容器
  redis          Redis 容器 + Celery Worker
  server         Bible Server
  cli            Go CLI 构建
  hermes         Hermes 插件部署
  oc             OpenClaw 插件构建 + 安装
  all            全部组件（默认值）

${BOLD}选项:${NC}
  -n, --instance-name <name>  实例名称（默认: ${INSTANCE_NAME}，覆盖 \$BIBLE_INSTANCE_NAME）
  --test-mode                  使用 Test Mode（默认，无需 Docker）
  --full                       完整后端模式（OpenSearch + Redis + Server）
  --base-url <url>             Bible Server 地址（默认: ${BASE_URL}）
  --skip-test                  跳过组件自检
  --force                      跳过确认提示
  --purge-config               清理用户级 BiBLE 配置（如 ~/.bible/config.json）
  --purge-workspace            删除项目 workspace/ 运行时数据
  --uninstall-plugins          卸载/移除 Hermes 与 OpenClaw 用户级插件配置
  --json                       status 命令输出 JSON
  -h, --help                   显示本帮助

${BOLD}镜像源环境变量:${NC}
  BIBLE_DOCKER_REGISTRY_PREFIX  Docker Hub 镜像前缀/镜像站（例如 docker.m.daocloud.io/）
  OPENSEARCH_IMAGE_TAG          OpenSearch 镜像标签（默认 latest）
  REDIS_IMAGE_TAG               Redis 镜像标签（默认 7-alpine）
  REDIS_COMMANDER_ENABLED       是否启动 Redis Commander（仅 true 启用；其它值跳过）
  REDIS_COMMANDER_IMAGE         Redis Commander 完整镜像名（启用时必填）

${BOLD}OpenSearch 资源环境变量:${NC}
  BIBLE_OPENSEARCH_CPU_CORES     OpenSearch CPU 核数（默认 ${DEFAULT_OS_CPU_CORES}）
  BIBLE_OPENSEARCH_MEMORY_GB     OpenSearch 内存 GB（默认 ${DEFAULT_OS_MEMORY_GB}）

${BOLD}常用示例:${NC}
  # 一键搭建（Test Mode + 全部客户端，日常首选）
  $0 setup

  # 完整后端（含 OpenSearch / Redis / Celery Worker）
  $0 setup --full

  # 网络受限地区使用 Docker Hub 镜像站
  BIBLE_DOCKER_REGISTRY_PREFIX=docker.m.daocloud.io/ $0 setup --full

  # 已有服务端，只搭客户端
  $0 setup cli hermes oc

  # 只搭 OpenSearch + Redis，指定实例名
  $0 setup --full opensearch redis -n mytest

  # 一键清理
  $0 teardown --force

  # 完整清理（含 Docker 容器删除）
  $0 teardown --full --force

  # 只清理插件
  $0 teardown hermes oc

  # 查看状态
  $0 status
  $0 status --json

${BOLD}环境变量:${NC}
  BIBLE_INSTANCE_NAME     实例名称（默认: bibletest，可被 --instance-name 覆盖）
  BIBLE_ATLAS_BASE_URL    服务地址（插件使用，可被 --base-url 覆盖）

EOF
  exit 0
}

# ── 参数解析 ──────────────────────────────────────────────────────────────────
parse_args() {
  COMPONENTS=()
  COMMAND=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      setup|teardown|status)
        COMMAND="$1"
        ;;
      --test-mode) MODE="test" ;;
      -n|--instance-name)  shift; INSTANCE_NAME="$1" ;;
      --full)      MODE="full" ;;
      --base-url)  shift; BASE_URL="$1" ;;
      --skip-test) SKIP_TEST=true ;;
      --force)     FORCE=true ;;
      --purge-config) PURGE_CONFIG=true ;;
      --purge-workspace) PURGE_WORKSPACE=true ;;
      --uninstall-plugins) UNINSTALL_PLUGINS=true ;;
      --json)      JSON_OUT=true ;;
      -h|--help)   usage ;;
      -*)
        die "未知选项: $1（使用 --help 查看帮助）"
        ;;
      *)
        COMPONENTS+=("$1")
        ;;
    esac
    shift
  done

  if [ -z "$COMMAND" ]; then
    die "缺少命令。请指定 setup、teardown 或 status。（使用 --help 查看帮助）"
  fi

  # 默认全部
  if [ ${#COMPONENTS[@]} -eq 0 ]; then
    COMPONENTS=("all")
  fi

  # 展开 all → 具体列表
  local expanded=()
  for c in "${COMPONENTS[@]}"; do
    if [ "$c" = "all" ]; then
      if [ "$MODE" = "full" ]; then
        expanded+=(opensearch redis server cli hermes oc)
      else
        expanded+=(server cli hermes oc)
      fi
    else
      expanded+=("$c")
    fi
  done

  # 去重保持顺序
  COMPONENTS=()
  for c in "${expanded[@]}"; do
    local dup=false
    for e in "${COMPONENTS[@]:-}"; do [ "$e" = "$c" ] && dup=true && break; done
    $dup || COMPONENTS+=("$c")
  done

  # 校验组件名
  for c in "${COMPONENTS[@]}"; do
    case "$c" in
      opensearch|redis|server|cli|hermes|oc) ;;
      *) die "未知组件: $c（有效值: opensearch, redis, server, cli, hermes, oc, all）" ;;
    esac
  done
}

# ══════════════════════════════════════════════════════════════════════════════
# 前置检查
# ══════════════════════════════════════════════════════════════════════════════

preflight_setup() {
  echo "${BOLD}模式:${NC} $( [ "$MODE" = "full" ] && echo '完整后端 (OpenSearch + Redis + Server)' || echo 'Test Mode (轻量，无需 Docker)')"
  echo "${BOLD}组件:${NC} ${COMPONENTS[*]}"
  echo "${BOLD}地址:${NC} ${BASE_URL}"
  echo ""

  require_cmd uv "安装: curl -LsSf https://astral.sh/uv/install.sh | sh"

  local need_docker=false need_go=false need_node=false need_opensearch=false need_redis=false
  for c in "${COMPONENTS[@]}"; do
    case "$c" in
      opensearch)       need_docker=true; need_opensearch=true ;;
      redis)            need_docker=true; need_redis=true ;;
      cli)              need_go=true ;;
      oc)               need_node=true ;;
    esac
  done

  if $need_docker; then
    local docker_cpus=""
    local docker_memory_gb=""
    local docker_memory_mb=""
    # 优先检测 docker，docker 不可用时回退到 podman
    local container_cmd=""
    if check_cmd docker; then
      if docker info &>/dev/null; then
        container_cmd="docker"
        docker_cpus="$(docker info --format '{{.NCPU}}' 2>/dev/null || true)"
        local docker_memory_bytes
        docker_memory_bytes="$(docker info --format '{{.MemTotal}}' 2>/dev/null || true)"
        docker_memory_gb="$(bytes_to_gb_floor "$docker_memory_bytes" || true)"
        docker_memory_mb="$(bytes_to_mb_floor "$docker_memory_bytes" || true)"
      elif check_cmd colima; then
        # Docker CLI 已安装但 daemon 未运行，尝试通过 Colima 启动
        if colima status 2>/dev/null | grep -q "Running"; then
          die "Colima 已在运行但 docker 不可用，请检查: docker info"
        fi
        info "Colima 未运行，按需启动 ..."
        colima start 2>/dev/null || die "Colima 启动失败，请手动执行: colima start"
        docker info &>/dev/null || die "Colima 已启动但 docker 仍不可用，请检查: docker info"
        ok "Colima 已启动，docker daemon 就绪"
        container_cmd="colima"
        docker_cpus="$(docker info --format '{{.NCPU}}' 2>/dev/null || true)"
        local docker_memory_bytes
        docker_memory_bytes="$(docker info --format '{{.MemTotal}}' 2>/dev/null || true)"
        docker_memory_gb="$(bytes_to_gb_floor "$docker_memory_bytes" || true)"
        docker_memory_mb="$(bytes_to_mb_floor "$docker_memory_bytes" || true)"
      else
        die "Docker 未运行，请启动 Docker Desktop、dockerd，或安装 Colima: brew install colima"
      fi
    elif check_cmd podman; then
      if [[ "$(uname -s)" == "Darwin" ]]; then
        # macOS 上 podman 需要先启动 machine
        podman machine list 2>/dev/null | grep -q "Running" || {
          info "Podman machine 未运行，尝试启动 ..."
          podman machine start 2>/dev/null || die "Podman machine 启动失败，请手动执行: podman machine start"
        }
      fi
      podman info &>/dev/null || die "Podman 不可用，请检查 podman 安装或执行: podman machine start"
      container_cmd="podman"

      # Podman 用户检查 docker-compose 兼容层
      # 底层 deploy.sh 使用 docker / docker-compose 命令，需要 shim
      local need_shim=false
      check_cmd docker    || need_shim=true
      check_cmd docker-compose || need_shim=true

      if $need_shim; then
        warn "检测到 Podman，但缺少 docker / docker-compose 命令。"
        warn "底层脚本（deploy.sh）依赖这些命令，需要安装 podman-docker 兼容层。"
        if [[ "$(uname -s)" == "Darwin" ]]; then
          info "安装方法: brew install podman-docker docker-compose"
          if confirm "是否现在安装 podman-docker + docker-compose？"; then
            brew install podman-docker docker-compose 2>/dev/null || \
              die "安装失败，请手动执行: brew install podman-docker docker-compose"
            ok "podman-docker + docker-compose 已安装"
          else
            warn "已跳过，请注意底层脚本可能因缺少 docker 命令而失败"
          fi
        else
          info "Linux: 安装 podman-docker 包（如 apt install podman-docker）"
          info "或安装 docker-compose 独立包 + 配置 DOCKER_HOST 指向 podman socket"
          warn "缺少 docker-compose 兼容层，底层脚本可能失败"
        fi
      fi
    else
      die "未找到 Docker 或 Podman。请安装其中之一:\n  Docker:  https://docs.docker.com/get-docker/\n  Podman: https://podman.io/docs/installation"
    fi
    resolve_docker_registry_prefix
    $need_redis && resolve_redis_commander_config
    if $need_opensearch; then
      resolve_opensearch_resources "$docker_cpus" "$docker_memory_gb"
      if is_positive_integer "$docker_cpus" && [ "$docker_cpus" -lt "$OS_CPU_CORES" ]; then
        die "Docker 可用 CPU 为 ${docker_cpus}，OpenSearch 请求 ${OS_CPU_CORES}。请调低 BIBLE_OPENSEARCH_CPU_CORES，或增加 Docker/Colima CPU。"
      fi
      local required_memory_gb=$((OS_MEMORY_GB + OPENSEARCH_DASHBOARDS_MEMORY_GB))
      if is_positive_integer "$docker_memory_gb" && [ "$docker_memory_gb" -lt "$required_memory_gb" ]; then
        die "Docker 可用内存为 ${docker_memory_gb}GB，OpenSearch 请求 ${OS_MEMORY_GB}GB，Dashboards 还需 ${OPENSEARCH_DASHBOARDS_MEMORY_GB}GB。请调低 BIBLE_OPENSEARCH_MEMORY_GB，或增加 Docker/Colima 内存。"
      fi
    fi
    local required_docker_memory_mb=0
    if $need_opensearch; then
      required_docker_memory_mb=$((required_docker_memory_mb + (OS_MEMORY_GB + OPENSEARCH_DASHBOARDS_MEMORY_GB) * 1024))
    fi
    for c in "${COMPONENTS[@]}"; do
      if [ "$c" = "redis" ]; then
        required_docker_memory_mb=$((required_docker_memory_mb + REDIS_MEMORY_MB))
        if [ "$REDIS_COMMANDER_ENABLED" = "true" ]; then
          required_docker_memory_mb=$((required_docker_memory_mb + REDIS_COMMANDER_MEMORY_MB))
        fi
        break
      fi
    done
    if is_positive_integer "$docker_memory_mb" && [ "$docker_memory_mb" -lt "$required_docker_memory_mb" ]; then
      local redis_memory_detail="Redis ${REDIS_MEMORY_MB}MB"
      if [ "$REDIS_COMMANDER_ENABLED" = "true" ]; then
        redis_memory_detail="${redis_memory_detail} + Commander ${REDIS_COMMANDER_MEMORY_MB}MB"
      fi
      die "Docker 可用内存为 ${docker_memory_mb}MB，当前 Docker 组件请求约 ${required_docker_memory_mb}MB（${redis_memory_detail}）。请减少组件/内存，或增加 Docker/Colima 内存。"
    fi
    info "容器运行时: ${container_cmd}"
  fi
  $need_go   && require_cmd go "安装: https://go.dev/dl/"
  $need_node && require_cmd node "安装: https://nodejs.org/"

  # Python 环境
  if [ ! -f "$REPO_ROOT/.venv/bin/python" ]; then
    info "首次运行，安装 Python 依赖 ..."
    (cd "$REPO_ROOT" && uv sync --all-extras) || die "uv sync 失败"
    ok "依赖安装完成"
  fi

  # 确保 logs 目录存在
  mkdir -p "$SCRIPT_DIR/server_deploy/runs"
}

preflight_teardown() {
  echo "${BOLD}模式:${NC} $( [ "$MODE" = "full" ] && echo '完整清理 (含 Docker 容器)' || echo '基础清理 (保留容器)')"
  echo "${BOLD}组件:${NC} ${COMPONENTS[*]}"
  echo ""
}

# ══════════════════════════════════════════════════════════════════════════════
# SETUP 各组件
# ══════════════════════════════════════════════════════════════════════════════

setup_opensearch() {
  step "OpenSearch — 部署 Docker 容器"

  # 如果端口已占用且可以连通，则复用
  if ! port_free "$OS_HTTP_PORT"; then
    if curl -s -u "opensearch-xo:MyStr0ng!Pass#2024" \
       "http://localhost:${OS_HTTP_PORT}/" &>/dev/null; then
      ok "OpenSearch 已在运行 (复用 localhost:${OS_HTTP_PORT})"
      return 0
    fi
    die "端口 ${OS_HTTP_PORT} 被占用且无法连接，请排查"
  fi

  info "创建实例 '${INSTANCE_NAME}' (${OS_HTTP_PORT}, ${OS_CPU_CORES}核/${OS_MEMORY_GB}GB) ..."
  bash "$OS_DEPLOY" create "$INSTANCE_NAME" "$OS_HTTP_PORT" "$OS_DASH_PORT" "$OS_CPU_CORES" "$OS_MEMORY_GB" \
    || die "实例创建失败"

  info "拉取镜像并启动（首次约 1-2 分钟）..."
  bash "$OS_DEPLOY" pull 2>/dev/null || warn "镜像拉取有警告，继续..."
  bash "$OS_DEPLOY" start "$INSTANCE_NAME" || die "启动失败，查看: bash $OS_DEPLOY logs $INSTANCE_NAME"

  info "等待服务就绪（最多 60s）..."
  if wait_for_url "http://localhost:${OS_HTTP_PORT}/" 60; then
    ok "OpenSearch 就绪 → http://localhost:${OS_HTTP_PORT}"
  else
    die "OpenSearch 启动超时。日志: bash $OS_DEPLOY logs $INSTANCE_NAME 50"
  fi
}

setup_redis() {
  step "Redis + Celery Worker — 部署"

  if ! port_free "$REDIS_PORT"; then
    if redis_ping "$REDIS_PORT"; then
      ok "Redis 已在运行 (复用 localhost:${REDIS_PORT})"
      return 0
    fi
    die "端口 ${REDIS_PORT} 被占用且无法连接，请排查"
  fi

  info "创建实例 '${INSTANCE_NAME}' (端口 ${REDIS_PORT}, ${REDIS_MEMORY_MB}MB) ..."
  bash "$REDIS_DEPLOY" redis create "$INSTANCE_NAME" "$REDIS_PORT" "$REDIS_MEMORY_MB" \
    || die "实例创建失败"

  info "启动 Redis ..."
  bash "$REDIS_DEPLOY" redis start "$INSTANCE_NAME" || die "Redis 启动失败"

  sleep 2
  if redis_ping "$REDIS_PORT"; then
    ok "Redis 就绪 → redis://localhost:${REDIS_PORT}"
  else
    die "Redis 启动失败。日志: bash $REDIS_DEPLOY redis logs $INSTANCE_NAME"
  fi

  info "启动 Celery Worker ..."
  bash "$REDIS_DEPLOY" worker start "$INSTANCE_NAME" || warn "Worker 启动有警告"

  sleep 2
  if bash "$REDIS_DEPLOY" worker status "$INSTANCE_NAME" &>/dev/null; then
    ok "Celery Worker 运行中"
  else
    warn "Worker 状态异常，查看日志: bash $REDIS_DEPLOY worker logs $INSTANCE_NAME"
  fi
}

setup_server() {
  step "Bible Server — 启动"

  local server_port="${BASE_URL##*:}"
  require_env

  # 如果端口已占用且 health 可通，复用
  if ! port_free "$server_port"; then
    if curl -s "${BASE_URL}/health" &>/dev/null; then
      ok "Bible Server 已在运行 (复用 ${BASE_URL})"
      return 0
    fi
    die "端口 ${server_port} 被占用且 /health 无响应，请排查"
  fi

  if [ "$MODE" = "test" ]; then
    info "启动 Test Mode (${BASE_URL}) ..."
    cd "$REPO_ROOT"

    local log_dir="$SCRIPT_DIR/server_deploy/runs"
    mkdir -p "$log_dir"

    nohup .venv/bin/python -m bible.test_mode.server \
      --addr "${BASE_URL#http://}" \
      > "$log_dir/test-mode.log" 2>&1 &
    local pid=$!
    echo "$pid" > "$log_dir/test-mode.pid"

    if wait_for_url "${BASE_URL}/health" 15; then
      ok "Test Mode 已启动 (PID=$pid)"
      detail "日志: $log_dir/test-mode.log"
    else
      die "Test Mode 启动超时。日志: tail -50 $log_dir/test-mode.log"
    fi
  else
    info "启动生产模式 (${BASE_URL}) ..."
    cd "$SCRIPT_DIR/server_deploy"

    bash "$SERVER_DEPLOY" start || true

    if wait_for_url "${BASE_URL}/health" 30; then
      ok "Bible Server 已启动 (${BASE_URL})"
      bash "$SERVER_DEPLOY" status 2>/dev/null || true
    else
      warn "Server 启动中（/health 尚未就绪），如持续失败请查看日志"
    fi
  fi
}

setup_cli() {
  step "Go CLI — 构建"
  require_cmd go "安装: https://go.dev/dl/"

  cd "$CLI_DIR"

  info "go vet ..."
  go vet ./... || die "go vet 失败"

  info "go build ..."
  mkdir -p target
  go build -o ./target/bible ./cmd/bible-cli || die "编译失败"
  ok "Go CLI → bible_cli_go/target/bible"

  echo ""
  info "使用方式:"
  detail "export BIBLE_CLI_BASE_URL=${BASE_URL}"
  detail "cd bible_cli_go && BIBLE_CLI_BASE_URL=${BASE_URL} go run ./cmd/bible-cli health"

  if ! $SKIP_TEST; then
    info "运行 go test ..."
    go test ./... -count=1 -timeout=60s && ok "go test 通过" || warn "测试有失败（不影响搭建）"
  fi
}

setup_hermes() {
  step "Hermes Plugin — 部署"

  if ! check_cmd hermes; then
    warn "hermes CLI 不可用，跳过 Hermes 插件部署"
    detail "请先安装 Hermes Agent: https://hermes-agent.nousresearch.com"
    return 0
  fi

  cd "$HERMES_DIR"

  if [ ! -f "$HERMES_DEPLOY" ]; then
    die "未找到 deploy.sh: $HERMES_DEPLOY"
  fi

  info "执行 deploy.sh ..."
  bash "$HERMES_DEPLOY" || die "部署失败"
  ok "插件已部署"

  hermes plugins enable bible-hermes-plugin 2>/dev/null && ok "插件已启用" || true

  export BIBLE_ATLAS_BASE_URL="${BASE_URL}"
  info "执行 setup --write ..."
  if hermes bible setup --base-url "${BASE_URL}" --write 2>/dev/null; then
    ok "setup --write 完成"
  else
    warn "setup 失败（可能已配置或 Hermes 未运行）"
  fi

  # 验证
  hermes bible status 2>/dev/null || warn "无法获取状态（Hermes 可能未运行）"

  if ! $SKIP_TEST; then
    info "运行测试 ..."
    cd "$HERMES_DIR"
    uv run pytest tests/ -q 2>/dev/null && ok "pytest 通过" || warn "测试有失败（不影响搭建）"
  fi

  info "下一步: 重启 Hermes (会话中 /reset 或 hermes server restart)"
}

setup_oc() {
  step "OpenClaw Plugin — 构建与安装"
  require_cmd node "安装: https://nodejs.org/"

  if ! check_cmd openclaw; then
    warn "openclaw CLI 不可用，跳过 OC 插件部署"
    detail "请先安装 OpenClaw"
    return 0
  fi

  cd "$OC_DIR"

  info "npm install ..."
  npm install --no-audit --no-fund --silent || die "npm install 失败"

  info "typecheck ..."
  npm run typecheck || die "typecheck 失败，请修复类型错误后重试"

  if ! $SKIP_TEST; then
    info "vitest ..."
    npm test || warn "测试有失败（不影响搭建）"
  fi

  info "npm run build ..."
  npm run build || die "build 失败"
  ok "dist/ 就绪"

  info "openclaw plugins install ..."
  openclaw plugins install . --force 2>/dev/null && ok "插件已安装" || warn "安装失败"

  export BIBLE_ATLAS_BASE_URL="${BASE_URL}"
  info "执行 setup --write ..."
  if openclaw bible setup --base-url "${BASE_URL}" --write 2>/dev/null; then
    ok "setup --write 完成"
  else
    warn "setup 失败（可能已配置或 gateway 未运行）"
  fi

  info "重启 gateway ..."
  openclaw gateway restart 2>/dev/null && ok "gateway 已重启" || warn "请手动重启"

  # 验证
  openclaw bible status 2>/dev/null || warn "无法获取状态（gateway 可能未运行）"
}

# ══════════════════════════════════════════════════════════════════════════════
# TEARDOWN 各组件
# ══════════════════════════════════════════════════════════════════════════════

teardown_opensearch() {
  step "OpenSearch — 清理"

  if [ "$MODE" = "full" ]; then
    info "停止 + 删除实例 '${INSTANCE_NAME}' ..."
    bash "$OS_DEPLOY" stop "$INSTANCE_NAME" 2>/dev/null || true
    bash "$OS_DEPLOY" delete "$INSTANCE_NAME" 2>/dev/null && \
      ok "OpenSearch 实例已删除" || \
      skip "实例不存在或已删除"
  else
    bash "$OS_DEPLOY" stop "$INSTANCE_NAME" 2>/dev/null && \
      ok "OpenSearch 已停止" || \
      skip "OpenSearch 未运行"
  fi
}

teardown_redis() {
  step "Redis + Celery Worker — 清理"

  if [ "$MODE" = "full" ]; then
    info "停止 Worker + Redis，删除实例 '${INSTANCE_NAME}' ..."
    bash "$REDIS_DEPLOY" stop-all "$INSTANCE_NAME" 2>/dev/null || true
    bash "$REDIS_DEPLOY" redis delete "$INSTANCE_NAME" 2>/dev/null && \
      ok "Redis 实例已删除" || \
      skip "实例不存在或已删除"
  else
    bash "$REDIS_DEPLOY" stop-all "$INSTANCE_NAME" 2>/dev/null && \
      ok "Redis + Worker 已停止" || \
      skip "未运行"
  fi
}

teardown_server() {
  step "Bible Server — 清理"

  # Test Mode PID
  local pid_file="$SCRIPT_DIR/server_deploy/runs/test-mode.pid"
  if [ -f "$pid_file" ]; then
    local pid
    pid=$(cat "$pid_file" 2>/dev/null || true)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      ok "Test Mode 已终止 (PID=$pid)"
    fi
    rm -f "$pid_file"
  fi

  # server_deploy 管理的进程
  if [ -f "$SERVER_DEPLOY" ]; then
    bash "$SERVER_DEPLOY" stop 2>/dev/null && ok "Server 已停止" || true
  fi

  # 兜底
  pkill -f "bible.test_mode.server" 2>/dev/null || true
  pkill -f "bible-mock-server" 2>/dev/null || true
  pkill -f "celery.*bible.features" 2>/dev/null || true
  pkill -f "bible.main" 2>/dev/null || true

  # workspace
  if [ -d "$REPO_ROOT/workspace" ]; then
    if $PURGE_WORKSPACE && { $FORCE || confirm "删除运行时数据 workspace/？"; }; then
      rm -rf "$REPO_ROOT/workspace"
      ok "workspace/ 已删除"
    else
      skip "workspace/ 保留（使用 --purge-workspace 删除）"
    fi
  fi
}

teardown_cli() {
  step "Go CLI — 清理"
  rm -rf "$CLI_DIR/target"
  if $PURGE_CONFIG; then
    rm -f "$HOME/.bible/config.json"
    ok "构建产物 + 用户配置已清理"
  else
    ok "构建产物已清理"
    skip "用户配置 ~/.bible/config.json 保留（使用 --purge-config 删除）"
  fi
}

teardown_hermes() {
  step "Hermes Plugin — 清理"
  if $UNINSTALL_PLUGINS; then
    hermes plugins disable bible-hermes-plugin 2>/dev/null && ok "插件已禁用" || true
    rm -rf "$HOME/.hermes/plugins/bible-hermes-plugin" && ok "插件文件已删除" || true
    remove_hermes_bible_config
    ok "Hermes bible 配置段已移除"
  else
    skip "Hermes 用户级插件保留（使用 --uninstall-plugins 卸载）"
  fi
  rm -rf "$HERMES_DIR/.venv" 2>/dev/null || true
  find "$HERMES_DIR" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
  ok "本地构建产物已清理"
}

teardown_oc() {
  step "OpenClaw Plugin — 清理"
  if $UNINSTALL_PLUGINS; then
    openclaw plugins uninstall bible-oc-plugin 2>/dev/null && ok "插件已卸载" || true
    openclaw config remove plugins.entries.bible-oc-plugin 2>/dev/null && ok "配置已移除" || true
    if [ "$(openclaw config get plugins.slots.contextEngine 2>/dev/null || true)" = "bible-oc-plugin" ]; then
      openclaw config remove plugins.slots.contextEngine 2>/dev/null && ok "contextEngine 插槽已移除" || true
    fi
    openclaw gateway restart 2>/dev/null && ok "gateway 已重启" || true
  else
    skip "OpenClaw 用户级插件配置保留（使用 --uninstall-plugins 卸载）"
  fi
  rm -rf "$OC_DIR/dist"
  rm -rf "$OC_DIR/node_modules"
  ok "构建产物已清理"
}

# ══════════════════════════════════════════════════════════════════════════════
# STATUS
# ══════════════════════════════════════════════════════════════════════════════

os_running() {
  curl -s -u "opensearch-xo:MyStr0ng!Pass#2024" \
    "http://localhost:${OS_HTTP_PORT}/" &>/dev/null
}

redis_running() {
  redis_ping "$REDIS_PORT"
}

server_running() {
  curl -s "${BASE_URL}/health" &>/dev/null
}

cli_built() {
  [ -f "$CLI_DIR/target/bible" ]
}

hermes_installed() {
  [ -d "$HOME/.hermes/plugins/bible-hermes-plugin" ]
}

oc_installed() {
  [ -d "$HOME/.openclaw/extensions/bible-oc-plugin" ]
}

status_all() {
  if ${JSON_OUT:-false}; then
    cat <<JSONEOF
{
  "server":    { "status": "$(server_running && echo running || echo down)", "url": "${BASE_URL}" },
  "opensearch": { "status": "$(os_running && echo running || echo down)", "port": ${OS_HTTP_PORT} },
  "redis":     { "status": "$(redis_running && echo running || echo down)", "port": ${REDIS_PORT} },
  "cli":       { "status": "$(cli_built && echo built || echo not_built)" },
  "hermes":    { "status": "$(hermes_installed && echo installed || echo not_installed)" },
  "oc":        { "status": "$(oc_installed && echo installed || echo not_installed)" }
}
JSONEOF
    return 0
  fi

  echo ""
  echo "${BOLD}BiBLE Atlas 测试环境状态${NC}"
  echo "${DIM}══════════════════════════════════════════════════════════${NC}"
  echo ""

  if server_running; then
    local tag=""
    curl -sI "${BASE_URL}/health" 2>/dev/null | grep -q "X-Bible-Test-Mode: true" && tag=" (Test Mode)"
    echo "  Server:      ${GREEN}●${NC} 运行中${tag}  — ${BASE_URL}"
  else
    echo "  Server:      ${DIM}○${NC} 未运行"
  fi

  if os_running; then
    echo "  OpenSearch:  ${GREEN}●${NC} 运行中    — localhost:${OS_HTTP_PORT}"
  else
    echo "  OpenSearch:  ${DIM}○${NC} 未运行"
  fi

  if redis_running; then
    echo "  Redis:       ${GREEN}●${NC} 运行中    — localhost:${REDIS_PORT}"
  else
    echo "  Redis:       ${DIM}○${NC} 未运行"
  fi

  if cli_built; then
    echo "  Go CLI:      ${GREEN}●${NC} 已构建    — bible_cli_go/target/bible"
  else
    echo "  Go CLI:      ${DIM}○${NC} 未构建"
  fi

  if hermes_installed; then
    echo "  Hermes:      ${GREEN}●${NC} 已安装    — ~/.hermes/plugins/bible-hermes-plugin"
  else
    echo "  Hermes:      ${DIM}○${NC} 未安装"
  fi

  if oc_installed; then
    echo "  OC Plugin:   ${GREEN}●${NC} 已安装    — ~/.openclaw/extensions/bible-oc-plugin"
  else
    echo "  OC Plugin:   ${DIM}○${NC} 未安装"
  fi

  echo ""
  echo "${DIM}──────────────────────────────────────────────────────────${NC}"
  echo "  Server URL: ${GREEN}${BASE_URL}${NC}"
  if server_running; then
    echo "  Health:     $(curl -s "${BASE_URL}/health" 2>/dev/null || echo '{}')"
  fi
  echo ""
}

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

main() {
  JSON_OUT=false
  parse_args "$@"

  case "$COMMAND" in
    setup)
      preflight_setup

      if ! $FORCE && [ "$MODE" = "full" ]; then
        echo "${YELLOW}即将搭建完整后端环境（OpenSearch + Redis + Celery + Server + 全部客户端）。${NC}"
        echo "需要 Docker 运行，预计占用 ~4-6GB 内存。"
        confirm "确认继续？" || die "已取消"
      fi

      for c in "${COMPONENTS[@]}"; do
        case "$c" in
          opensearch) setup_opensearch ;;
          redis)      setup_redis ;;
          server)     setup_server ;;
          cli)        setup_cli ;;
          hermes)     setup_hermes ;;
          oc)         setup_oc ;;
        esac
      done

      echo ""
      echo "${GREEN}${BOLD}╔══════════════════════════════════════════╗${NC}"
      echo "${GREEN}${BOLD}║  测试环境搭建完成！                      ║${NC}"
      echo "${GREEN}${BOLD}╚══════════════════════════════════════════╝${NC}"
      echo ""
      echo "  Server:   ${BOLD}${BASE_URL}${NC}"
      echo "  Health:   ${BOLD}curl ${BASE_URL}/health${NC}"
      echo "  Status:   ${BOLD}$0 status${NC}"
      echo "  Cleanup:  ${BOLD}$0 teardown$( [ "$MODE" = "full" ] && echo ' --full')${NC}"
      echo ""
      ;;

    teardown)
      preflight_teardown

      if ! $FORCE && [ ${#COMPONENTS[@]} -gt 3 ]; then
        confirm "确认清理以上组件？" || die "已取消"
      fi

      for c in "${COMPONENTS[@]}"; do
        case "$c" in
          opensearch) teardown_opensearch ;;
          redis)      teardown_redis ;;
          server)     teardown_server ;;
          cli)        teardown_cli ;;
          hermes)     teardown_hermes ;;
          oc)         teardown_oc ;;
        esac
      done

      echo ""
      echo "${GREEN}${BOLD}╔══════════════════════════════════════════╗${NC}"
      echo "${GREEN}${BOLD}║  测试环境已清理！                        ║${NC}"
      echo "${GREEN}${BOLD}╚══════════════════════════════════════════╝${NC}"
      echo ""
      ;;

    status)
      status_all
      ;;
  esac
}

main "$@"
