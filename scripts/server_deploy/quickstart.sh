#!/bin/bash

###########################################
# BiBLE-Atlas 后端服务快速启动向导
#
# 交互式向导，引导用户完成以下步骤：
#   1. 检查并确认 OpenSearch / Redis 连通性
#   2. 确认或指定 bible-atlas.yaml 路径
#   3. 选择 Celery Worker 并发数
#   4. 调用 deploy.sh start 完成启动
###########################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_SH="$SCRIPT_DIR/deploy.sh"

PROJECT_ROOT="${BIBLE_PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

# ── 颜色 ──────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

ask() {
    local prompt=$1
    local default=$2
    local answer
    read -rp "$(echo -e "${CYAN}?${NC} ${prompt} [默认: ${default}]: ")" answer
    echo "${answer:-$default}"
}

ask_yn() {
    local prompt=$1
    local default=${2:-yes}
    local answer
    read -rp "$(echo -e "${CYAN}?${NC} ${prompt} (yes/no) [默认: ${default}]: ")" answer
    answer="${answer:-$default}"
    [ "$answer" = "yes" ] || [ "$answer" = "y" ]
}

check_port_open() {
    local host=$1
    local port=$2
    if command -v nc &>/dev/null; then
        nc -z -w5 "$host" "$port" > /dev/null 2>&1
    else
        (echo > /dev/tcp/"$host"/"$port") 2>/dev/null
    fi
}

clear
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   BiBLE-Atlas 后端服务快速启动向导      ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo "本向导将帮助您完成后端系统的首次启动配置。"
echo ""

# ── 前置：检查 uv ──────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    log_error "未找到 uv，项目使用 uv 管理 Python 环境。"
    echo ""
    echo "  请先安装 uv："
    echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo ""
    exit 1
fi
log_info "uv: $(command -v uv) ✓"
echo ""

# ── 步骤 1：确认项目根目录 ─────────────────────────────────────────────────────
echo -e "${YELLOW}── 步骤 1：确认项目根目录 ──────────────────────────────────${NC}"
echo ""
log_info "检测到项目根目录: $PROJECT_ROOT"

if ! ask_yn "确认使用此目录？"; then
    PROJECT_ROOT=$(ask "请输入项目根目录的绝对路径" "$PROJECT_ROOT")
    if [ ! -d "$PROJECT_ROOT" ]; then
        log_error "目录不存在: $PROJECT_ROOT"
        exit 1
    fi
fi
echo ""

# ── 步骤 2：确认配置文件路径 ───────────────────────────────────────────────────
echo -e "${YELLOW}── 步骤 2：确认 bible-atlas.yaml 路径 ──────────────────────${NC}"
echo ""

DEFAULT_CONFIG="$PROJECT_ROOT/bible-atlas.yaml"
if [ -f "$DEFAULT_CONFIG" ]; then
    log_info "检测到配置文件: $DEFAULT_CONFIG"
    if ask_yn "使用此配置文件？"; then
        CONFIG_PATH="$DEFAULT_CONFIG"
    else
        CONFIG_PATH=$(ask "请输入配置文件的绝对路径" "$DEFAULT_CONFIG")
    fi
else
    log_warn "未找到默认配置文件: $DEFAULT_CONFIG"
    CONFIG_PATH=$(ask "请输入配置文件的绝对路径" "$DEFAULT_CONFIG")
fi

if [ ! -f "$CONFIG_PATH" ]; then
    log_error "配置文件不存在: $CONFIG_PATH"
    exit 1
fi
log_info "配置文件: $CONFIG_PATH ✓"
echo ""

# ── 步骤 3：检查 OpenSearch 连通性 ────────────────────────────────────────────
echo -e "${YELLOW}── 步骤 3：检查 OpenSearch 连通性 ──────────────────────────${NC}"
echo ""

OS_HOST=$(grep -A3 "opensearch:" "$CONFIG_PATH" 2>/dev/null | grep -e '- "' | head -1 | tr -d ' "-' || true)
if [ -n "$OS_HOST" ]; then
    OS_H="${OS_HOST%:*}"
    OS_P="${OS_HOST#*:}"
    log_info "配置中的 OpenSearch 地址: ${OS_H}:${OS_P}"
    if check_port_open "$OS_H" "$OS_P"; then
        log_info "${GREEN}OpenSearch 连通性正常 ✓${NC}"
    else
        log_warn "${YELLOW}OpenSearch 不可达 (${OS_H}:${OS_P})${NC}"
        echo ""
        OPENSEARCH_DEPLOY="$PROJECT_ROOT/scripts/opensearch_deploy/deploy.sh"
        if [ -x "$OPENSEARCH_DEPLOY" ] && ask_yn "是否通过 opensearch_deploy 脚本启动 OpenSearch 实例？"; then
            OS_INSTANCE=$(ask "请输入 OpenSearch 实例名称" "opensearch1")
            log_step "尝试启动 OpenSearch 实例 '$OS_INSTANCE'..."
            if bash "$OPENSEARCH_DEPLOY" start "$OS_INSTANCE"; then
                log_info "等待 OpenSearch 就绪..."
                sleep 8
                if check_port_open "$OS_H" "$OS_P"; then
                    log_info "${GREEN}OpenSearch 已启动 ✓${NC}"
                else
                    log_warn "OpenSearch 启动中，可能需要更多时间，继续向下执行..."
                fi
            else
                log_error "启动 OpenSearch 失败，请手动检查。"
                if ! ask_yn "仍要继续？" "no"; then exit 0; fi
            fi
        else
            echo "  请手动启动 OpenSearch，参考："
            echo "    scripts/opensearch_deploy/deploy.sh start <实例名>"
            echo ""
            if ! ask_yn "OpenSearch 未就绪，仍要继续启动后端？" "no"; then
                log_info "已取消。"
                exit 0
            fi
        fi
    fi
else
    log_warn "无法从配置文件中解析 OpenSearch 地址，跳过检查。"
fi
echo ""

# ── 步骤 4：检查 Redis 连通性 ─────────────────────────────────────────────────
echo -e "${YELLOW}── 步骤 4：检查 Redis 连通性 ────────────────────────────────${NC}"
echo ""

REDIS_URL=$(grep "broker_url:" "$CONFIG_PATH" 2>/dev/null | head -1 | sed 's/.*broker_url: *"*//;s/".*//;s/ *$//' || true)
if [ -n "$REDIS_URL" ]; then
    REDIS_H=$(echo "$REDIS_URL" | sed 's|redis://||;s|/.*||;s|:.*||')
    REDIS_P=$(echo "$REDIS_URL" | sed 's|redis://||;s|/.*||;s|.*:||')
    REDIS_H="${REDIS_H:-localhost}"
    REDIS_P="${REDIS_P:-6379}"
    log_info "配置中的 Redis 地址: ${REDIS_H}:${REDIS_P}"
    if check_port_open "$REDIS_H" "$REDIS_P"; then
        log_info "${GREEN}Redis 连通性正常 ✓${NC}"
    else
        log_warn "${YELLOW}Redis 不可达 (${REDIS_H}:${REDIS_P})${NC}"
        echo ""
        REDIS_DEPLOY="$PROJECT_ROOT/scripts/redis_celery_deploy/deploy.sh"
        if [ -x "$REDIS_DEPLOY" ] && ask_yn "是否通过 redis_celery_deploy 脚本启动 Redis 实例？"; then
            REDIS_INSTANCE=$(ask "请输入 Redis 实例名称" "redis1")
            log_step "尝试启动 Redis 实例 '$REDIS_INSTANCE'..."
            if bash "$REDIS_DEPLOY" redis start "$REDIS_INSTANCE"; then
                sleep 3
                if check_port_open "$REDIS_H" "$REDIS_P"; then
                    log_info "${GREEN}Redis 已启动 ✓${NC}"
                else
                    log_warn "Redis 启动中，可能需要更多时间，继续向下执行..."
                fi
            else
                log_error "启动 Redis 失败，请手动检查。"
                if ! ask_yn "仍要继续？" "no"; then exit 0; fi
            fi
        else
            echo "  请手动启动 Redis，参考："
            echo "    scripts/redis_celery_deploy/deploy.sh redis start <实例名>"
            echo ""
            if ! ask_yn "Redis 未就绪，仍要继续启动后端？" "no"; then
                log_info "已取消。"
                exit 0
            fi
        fi
    fi
else
    log_warn "无法从配置文件中解析 Redis 地址，跳过检查。"
fi
echo ""

# ── 步骤 5：选择 Celery Worker 并发数 ────────────────────────────────────────
echo -e "${YELLOW}── 步骤 5：选择 Celery Worker 并发数 ───────────────────────${NC}"
echo ""

CPU_COUNT=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo "4")
echo -e "  当前主机 CPU 核心数: ${CYAN}${CPU_COUNT}${NC}"
echo ""
echo "  并发数建议："
echo -e "  ${BLUE}1.${NC} 自动（Celery 默认，= CPU 核心数 ${CPU_COUNT}）"
echo -e "  ${BLUE}2.${NC} 轻量（2 个 worker）        - 开发/调试"
echo -e "  ${BLUE}3.${NC} 标准（4 个 worker）        - 日常使用"
echo -e "  ${BLUE}4.${NC} 高并发（8 个 worker）      - 大批量导入"
echo -e "  ${BLUE}5.${NC} 自定义"
echo ""
read -rp "$(echo -e "${CYAN}?${NC} 请选择并发方案 [默认: 1]: ")" concurrency_choice
concurrency_choice="${concurrency_choice:-1}"

case "$concurrency_choice" in
    1) CONCURRENCY="" ;;
    2) CONCURRENCY="2" ;;
    3) CONCURRENCY="4" ;;
    4) CONCURRENCY="8" ;;
    5) CONCURRENCY=$(ask "请输入并发数" "$CPU_COUNT") ;;
    *) log_warn "无效选项，使用默认值（自动）"; CONCURRENCY="" ;;
esac

if [ -n "$CONCURRENCY" ]; then
    log_info "Celery Worker 并发数: $CONCURRENCY"
else
    log_info "Celery Worker 并发数: 自动（Celery 默认）"
fi
echo ""

# ── 步骤 6：选择日志级别 ──────────────────────────────────────────────────────
echo -e "${YELLOW}── 步骤 6：选择日志级别 ─────────────────────────────────────${NC}"
echo ""
echo -e "  ${BLUE}1.${NC} INFO  （推荐，只输出关键信息）"
echo -e "  ${BLUE}2.${NC} DEBUG （输出详细调试信息）"
echo -e "  ${BLUE}3.${NC} WARNING（只输出警告和错误）"
echo ""
read -rp "$(echo -e "${CYAN}?${NC} 请选择日志级别 [默认: 1]: ")" log_choice
log_choice="${log_choice:-1}"

case "$log_choice" in
    1) LOG_LEVEL="info" ;;
    2) LOG_LEVEL="debug" ;;
    3) LOG_LEVEL="warning" ;;
    *) log_warn "无效选项，使用 info"; LOG_LEVEL="info" ;;
esac
log_info "日志级别: $LOG_LEVEL"
echo ""

# ── 确认并启动 ────────────────────────────────────────────────────────────────
echo -e "${YELLOW}── 启动确认 ─────────────────────────────────────────────────${NC}"
echo ""
echo "  项目根目录:   $PROJECT_ROOT"
echo "  配置文件:     $CONFIG_PATH"
if [ -n "$CONCURRENCY" ]; then
    echo "  Worker 并发数: $CONCURRENCY"
else
    echo "  Worker 并发数: 自动"
fi
echo "  日志级别:     $LOG_LEVEL"
echo ""

if ! ask_yn "确认以上配置并启动后端服务？"; then
    log_info "已取消启动。"
    exit 0
fi

echo ""

# 构建启动参数
START_ARGS="--config $CONFIG_PATH --loglevel $LOG_LEVEL"
if [ -n "$CONCURRENCY" ]; then
    START_ARGS="$START_ARGS --concurrency $CONCURRENCY"
fi

BIBLE_PROJECT_ROOT="$PROJECT_ROOT" bash "$DEPLOY_SH" start $START_ARGS
