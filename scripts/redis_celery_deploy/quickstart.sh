#!/bin/bash

###########################################
# Redis + Celery 快速配置向导
#
# 面向新手的交互式向导，自动完成：
#   1. 选择 Redis 配置方案
#   2. 输入实例名称和端口
#   3. 创建并启动 Redis 实例
#   4. 可选：同时启动 Celery Worker
###########################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_SH="$SCRIPT_DIR/deploy.sh"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 询问函数（带默认值）
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

# 检查端口是否可用
check_port_free() {
    local port=$1
    if command -v ss &>/dev/null; then
        ! ss -tuln 2>/dev/null | grep -q ":$port "
    elif command -v netstat &>/dev/null; then
        ! netstat -tuln 2>/dev/null | grep -q ":$port "
    else
        return 0
    fi
}

find_free_port() {
    local start=$1
    local port=$start
    while ! check_port_free "$port"; do
        port=$((port + 1))
        [ $port -gt $((start + 100)) ] && echo "$start" && return
    done
    echo "$port"
}

clear
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Redis + Celery Worker 快速配置向导    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""

# ── 步骤 1：选择配置方案 ──────────────────────────────────────────────────────
echo -e "${YELLOW}请选择 Redis 配置方案：${NC}"
echo ""
echo -e "  ${BLUE}1. 轻量配置${NC}（开发/单机测试）     - 512MB 内存"
echo -e "  ${BLUE}2. 标准配置${NC}（小规模生产）         - 1024MB 内存"
echo -e "  ${BLUE}3. 大型配置${NC}（高并发任务队列）     - 2048MB 内存"
echo -e "  ${BLUE}4. 自定义配置${NC}"
echo ""

read -rp "$(echo -e "${CYAN}?${NC} 请输入选项 (1-4): ")" preset_choice
preset_choice="${preset_choice:-1}"

case "$preset_choice" in
    1) preset_mem=512;  preset_desc="轻量 (512MB)" ;;
    2) preset_mem=1024; preset_desc="标准 (1024MB)" ;;
    3) preset_mem=2048; preset_desc="大型 (2048MB)" ;;
    4)
        preset_mem=$(ask "请输入内存大小 (MB)" "512")
        preset_desc="自定义 (${preset_mem}MB)"
        ;;
    *)
        log_error "无效选项: $preset_choice"
        exit 1
        ;;
esac

echo ""

# ── 步骤 2：实例名称 ──────────────────────────────────────────────────────────
instance_name=$(ask "请输入实例名称（字母/数字/中划线）" "myredis")

# 简单校验
if ! echo "$instance_name" | grep -qE '^[a-zA-Z0-9_-]+$'; then
    log_error "实例名称只能包含字母、数字、下划线、中划线"
    exit 1
fi

# ── 步骤 3：端口 ──────────────────────────────────────────────────────────────
recommended_redis_port=$(find_free_port 6379)
recommended_commander_port=$(find_free_port $((recommended_redis_port + 1000)))

redis_port=$(ask "Redis 端口" "$recommended_redis_port")
# Commander 端口自动推导，不询问（计算在 create 时完成）

echo ""

# ── 确认信息 ──────────────────────────────────────────────────────────────────
echo -e "${YELLOW}即将创建实例：${NC}"
echo ""
echo -e "  实例名称:   ${GREEN}${instance_name}${NC}"
echo -e "  配置方案:   ${GREEN}${preset_desc}${NC}"
echo -e "  Redis 端口: ${GREEN}${redis_port}${NC}"
echo -e "  Commander:  ${GREEN}http://localhost:$((redis_port + 1000))${NC}  (admin/admin)"
echo ""

if ! ask_yn "确认创建？"; then
    log_info "已取消"
    exit 0
fi

echo ""
log_info "开始创建实例..."
echo ""

"$DEPLOY_SH" redis create "$instance_name" "$redis_port" "$preset_mem"

echo ""

# ── 步骤 4：是否立即启动 Redis ────────────────────────────────────────────────
if ask_yn "是否立即启动 Redis 实例？"; then
    echo ""
    "$DEPLOY_SH" redis start "$instance_name"
    echo ""

    # ── 步骤 5：是否启动 Celery Worker ───────────────────────────────────────
    if ask_yn "是否同时启动 Celery Worker？"; then
        echo ""
        concurrency=$(ask "Worker 并发进程数（0=自动）" "0")
        echo ""

        if [ "$concurrency" = "0" ] || [ -z "$concurrency" ]; then
            "$DEPLOY_SH" worker start "$instance_name"
        else
            "$DEPLOY_SH" worker start "$instance_name" --concurrency "$concurrency"
        fi
    fi
fi

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           配置完成！                    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Redis 连接:  ${CYAN}redis://localhost:${redis_port}${NC}"
echo -e "  Commander:   ${CYAN}http://localhost:$((redis_port + 1000))${NC}  (admin/admin)"
echo ""
echo -e "${YELLOW}将以下配置写入 bible-atlas.yaml：${NC}"
echo ""
echo -e "  ${BLUE}celery:${NC}"
echo -e "  ${BLUE}  broker_url: \"redis://localhost:${redis_port}/0\"${NC}"
echo -e "  ${BLUE}  result_backend: \"redis://localhost:${redis_port}/1\"${NC}"
echo ""
echo -e "${YELLOW}常用命令：${NC}"
echo -e "  查看状态:    ${CYAN}./deploy.sh status${NC}"
echo -e "  查看 Redis:  ${CYAN}./deploy.sh redis status ${instance_name}${NC}"
echo -e "  查看 Worker: ${CYAN}./deploy.sh worker status ${instance_name}${NC}"
echo -e "  Worker 日志: ${CYAN}./deploy.sh worker logs ${instance_name}${NC}"
echo -e "  停止所有:    ${CYAN}./deploy.sh stop-all ${instance_name}${NC}"
echo ""
