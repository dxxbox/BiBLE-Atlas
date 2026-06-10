#!/bin/bash

###########################################
# BiBLE-Atlas 后端服务部署管理脚本
#
# 管理对象：
#   server  — FastAPI 应用进程（uvicorn，通过 python -m bible.main 启动）
#   worker  — Celery Worker 进程（bible.features.async_task.worker）
#
# 前提条件：
#   - OpenSearch 实例已启动（见 scripts/opensearch_deploy/）
#   - Redis 实例已启动（见 scripts/redis_celery_deploy/）
#   - python 虚拟环境已创建（.venv/）并已安装依赖
#   - bible-atlas.yaml 中的 OpenSearch / Redis 地址已正确配置
#
# 使用示例：
#   ./deploy.sh start
#   ./deploy.sh start --config /path/to/bible-atlas.yaml --concurrency 4
#   ./deploy.sh stop
#   ./deploy.sh restart
#   ./deploy.sh status
#   ./deploy.sh logs server
#   ./deploy.sh logs worker 100
#   ./deploy.sh health
###########################################

set -euo pipefail

# ── 颜色 ──────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── 路径 ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 项目根目录（脚本位于 scripts/server_deploy/，向上两级）
PROJECT_ROOT="${BIBLE_PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

# 运行时文件目录（PID 文件、日志）
BASE_RUNS_DIR="$SCRIPT_DIR/runs"
RUNS_DIR="$BASE_RUNS_DIR"
SERVICE_PROFILE="${BIBLE_SERVICE_PROFILE:-prod}"

# 默认配置文件路径
DEFAULT_CONFIG="$PROJECT_ROOT/bible-atlas.yaml"
DEFAULT_TEST_CONFIG="$PROJECT_ROOT/bible-atlas.entity-test.yaml"

# ── 日志函数 ──────────────────────────────────────────────────────────────────
log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "${BLUE}[STEP]${NC} $1"; }

# ── 帮助 ──────────────────────────────────────────────────────────────────────
show_usage() {
    cat << EOF
${GREEN}BiBLE-Atlas 后端服务管理脚本${NC}

${YELLOW}使用方法：${NC}
    $0 <命令> [选项]

${YELLOW}命令：${NC}
    ${GREEN}start${NC}   [选项]
             启动 FastAPI Server 和 Celery Worker
             选项：
               --profile <prod|test>  服务配置档（默认：prod）
               --config <path>       bible-atlas.yaml 路径（默认：项目根目录）
               --concurrency <N>     Celery Worker 并发数（默认：CPU 核心数）
               --loglevel <level>    日志级别（默认：info）
               --host <addr>         FastAPI 监听地址（默认：0.0.0.0，允许外部访问）
               --port <N>            FastAPI 监听端口（默认：5555）
             示例：$0 start
                  $0 start --profile test
                  $0 start --config /path/to/bible-atlas.yaml --concurrency 4
                  $0 start --host 127.0.0.1 --port 8080

    ${GREEN}stop${NC}
             优雅停止 Celery Worker 和 FastAPI Server
             选项：--profile <prod|test>

    ${GREEN}restart${NC} [选项]
             重启两个进程（传入的选项同 start）

    ${GREEN}status${NC}
             查看 Server 和 Worker 运行状态
             选项：--profile <prod|test>

    ${GREEN}logs${NC}    [server|worker] [行数]
             查看日志（默认显示两者各 50 行）
             示例：$0 logs server 100
                  $0 logs worker

    ${GREEN}health${NC}
             对 FastAPI /health 接口发起探活请求
             选项：--profile <prod|test> [--port <N>]

    ${GREEN}api-test${NC} [选项]
             运行 tests/server/entity_test/ 下的 live API 测试（默认 profile=test）
             选项透传给 pytest，例如：
               -q
               tests/server/entity_test/test_info.py::test_info -q
             可通过 BIBLE_API_BASE_URL 指定后端地址

    ${GREEN}help${NC}
             显示本帮助信息

${YELLOW}环境变量：${NC}
    BIBLE_PROJECT_ROOT        项目根目录（默认：脚本向上两级）
    BIBLE_ATLAS_CONFIG_PATH   配置文件路径（优先级低于 --config 参数）
    BIBLE_SERVER_HOST         FastAPI 监听地址（默认：0.0.0.0，允许外部访问）
    BIBLE_SERVER_PORT         FastAPI 监听端口（默认：5555）
    BIBLE_SERVICE_PROFILE     服务配置档（prod|test，默认：prod）

${YELLOW}快速开始：${NC}
    # 确保 OpenSearch 和 Redis 已启动，然后：
    $0 start

    # 查看运行状态
    $0 status

    # 查看服务健康
    $0 health

    # 运行 API 响应测试
    $0 api-test

EOF
}

# ── 工具函数 ──────────────────────────────────────────────────────────────────

server_pidfile() { echo "$RUNS_DIR/server.pid"; }
server_logfile() { echo "$RUNS_DIR/server.log"; }
worker_pidfile() { echo "$RUNS_DIR/worker.pid"; }
worker_logfile() { echo "$RUNS_DIR/worker.log"; }

set_service_profile() {
    local profile=${1:-prod}
    case "$profile" in
        prod|"")
            SERVICE_PROFILE="prod"
            RUNS_DIR="$BASE_RUNS_DIR"
            ;;
        test)
            SERVICE_PROFILE="test"
            RUNS_DIR="$BASE_RUNS_DIR/test"
            ;;
        *)
            log_error "未知 profile: $profile（允许：prod, test）"
            exit 1
            ;;
    esac
}

default_config_for_profile() {
    if [ "$SERVICE_PROFILE" = "test" ]; then
        echo "$DEFAULT_TEST_CONFIG"
    else
        echo "$DEFAULT_CONFIG"
    fi
}

default_host_for_profile() {
    if [ "$SERVICE_PROFILE" = "test" ]; then
        echo "127.0.0.1"
    else
        echo "0.0.0.0"
    fi
}

default_port_for_profile() {
    if [ "$SERVICE_PROFILE" = "test" ]; then
        echo "15555"
    else
        echo "5555"
    fi
}

process_is_running() {
    local pidfile=$1
    [ -s "$pidfile" ] || return 1

    local pid
    # PID file may be created/removed concurrently by detached workers.
    pid=$(cat "$pidfile" 2>/dev/null || true)
    [[ "$pid" =~ ^[0-9]+$ ]] || return 1

    if kill -0 "$pid" 2>/dev/null; then
        return 0
    fi
    return 1
}

server_is_running() { process_is_running "$(server_pidfile)"; }
worker_is_running() { process_is_running "$(worker_pidfile)"; }

worker_process_is_starting() {
    local pidfile
    pidfile="$(worker_pidfile)"

    ps -eo pid=,args= | awk -v pidfile="$pidfile" '
        index($0, "bible.features.async_task.worker") && index($0, pidfile) {
            found = 1
        }
        END { exit(found ? 0 : 1) }
    '
}

worker_log_has_ready_since() {
    local logfile=$1
    local start_line=$2

    [ -f "$logfile" ] || return 1
    awk -v start_line="$start_line" '
        NR > start_line && /celery@.* ready\./ {
            found = 1
        }
        END { exit(found ? 0 : 1) }
    ' "$logfile"
}

find_uv() {
    command -v uv 2>/dev/null || echo ""
}

check_tcp() {
    local h=$1 p=$2
    if command -v nc &>/dev/null; then
        nc -z -w5 "$h" "$p" > /dev/null 2>&1
    else
        (echo > /dev/tcp/"$h"/"$p") 2>/dev/null
    fi
}

# ── 前置检查 ──────────────────────────────────────────────────────────────────

check_prerequisites() {
    local config_path=$1
    local all_ok=true

    log_step "检查前置条件..."

    # 检查配置文件
    if [ ! -f "$config_path" ]; then
        log_error "配置文件不存在: $config_path"
        all_ok=false
    else
        log_info "  配置文件:  ${config_path} ✓"
    fi

    # 检查 uv
    local uv_bin
    uv_bin="$(find_uv)"
    if [ -z "$uv_bin" ]; then
        log_error "未找到 uv。请先安装："
        log_error "  curl -LsSf https://astral.sh/uv/install.sh | sh"
        all_ok=false
    else
        log_info "  uv:        ${uv_bin} ✓"
    fi

    # 检查 OpenSearch 连通性（从配置中读取端口）
    local os_host
    os_host=$(grep -A3 "opensearch:" "$config_path" 2>/dev/null | grep -e '- "' | head -1 | tr -d ' "-' || true)
    if [ -n "$os_host" ]; then
        local os_h os_p
        os_h="${os_host%:*}"
        os_p="${os_host#*:}"
        if check_tcp "$os_h" "$os_p"; then
            log_info "  OpenSearch: ${os_h}:${os_p} ✓"
        else
            log_error "  OpenSearch: ${os_h}:${os_p} 不可达"
            log_error "  请先启动：scripts/opensearch_deploy/deploy.sh start <实例名>"
            all_ok=false
        fi
    else
        log_warn "  OpenSearch: 无法从配置文件解析地址，跳过检查"
    fi

    # 检查 Redis 连通性（从配置中读取 broker_url）
    local redis_url
    redis_url=$(grep "broker_url:" "$config_path" 2>/dev/null | head -1 | sed 's/.*broker_url: *"*//;s/".*//;s/ *$//' || true)
    if [ -n "$redis_url" ]; then
        local redis_host redis_port
        redis_host=$(echo "$redis_url" | sed 's|redis://||;s|/.*||;s|:.*||')
        redis_port=$(echo "$redis_url" | sed 's|redis://||;s|/.*||;s|.*:||')
        redis_host="${redis_host:-localhost}"
        redis_port="${redis_port:-6379}"
        if check_tcp "$redis_host" "$redis_port"; then
            log_info "  Redis:     ${redis_host}:${redis_port} ✓"
        else
            log_error "  Redis:     ${redis_host}:${redis_port} 不可达"
            log_error "  请先启动：scripts/redis_celery_deploy/deploy.sh redis start <实例名>"
            all_ok=false
        fi
    else
        log_warn "  Redis:     无法从配置文件解析地址，跳过检查"
    fi

    if [ "$all_ok" = false ]; then
        log_error "前置条件检查未通过，请修复后重试。"
        exit 1
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
# server 子命令
# ══════════════════════════════════════════════════════════════════════════════

server_start() {
    local config_path=$1
    local server_host=${2:-0.0.0.0}
    local server_port=${3:-5555}

    local pidfile logfile
    pidfile="$(server_pidfile)"
    logfile="$(server_logfile)"

    if server_is_running; then
        local pid
        pid=$(cat "$pidfile")
        log_warn "FastAPI Server 已在运行 (PID=$pid)"
        return 0
    fi

    mkdir -p "$RUNS_DIR"

    log_step "启动 FastAPI Server..."
    log_info "  监听地址:   ${server_host}:${server_port}"
    log_info "  项目根目录: $PROJECT_ROOT"
    log_info "  配置文件:   $config_path"
    log_info "  日志文件:   $logfile"
    log_info "  PID 文件:   $pidfile"

    (
        cd "$PROJECT_ROOT"
        BIBLE_ATLAS_CONFIG_PATH="$config_path" \
        BIBLE_SERVER_HOST="$server_host" \
        BIBLE_SERVER_PORT="$server_port" \
            nohup uv run python -m bible.main >> "$logfile" 2>&1 &
        echo $! > "$pidfile"
    )

    # 等待进程确认存活（最多 15 秒）
    local waited=0
    while [ $waited -lt 15 ]; do
        if server_is_running; then
            break
        fi
        sleep 1
        waited=$((waited + 1))
    done

    if server_is_running; then
        local pid
        pid=$(cat "$pidfile")
        log_info "${GREEN}FastAPI Server 已启动 (PID=$pid)${NC}"
    else
        log_error "FastAPI Server 启动失败，请查看日志: $logfile"
        exit 1
    fi
}

server_stop() {
    local pidfile
    pidfile="$(server_pidfile)"

    if ! server_is_running; then
        log_warn "FastAPI Server 未在运行"
        return 0
    fi

    local pid
    pid=$(cat "$pidfile")
    log_step "停止 FastAPI Server (PID=$pid)..."

    kill -TERM "$pid" 2>/dev/null || true

    local waited=0
    while kill -0 "$pid" 2>/dev/null && [ $waited -lt 15 ]; do
        sleep 1
        waited=$((waited + 1))
    done

    if kill -0 "$pid" 2>/dev/null; then
        log_warn "Server 未在 15 秒内退出，强制终止..."
        kill -KILL "$pid" 2>/dev/null || true
    fi

    rm -f "$pidfile"
    log_info "${GREEN}FastAPI Server 已停止${NC}"
}

# ══════════════════════════════════════════════════════════════════════════════
# worker 子命令
# ══════════════════════════════════════════════════════════════════════════════

worker_start() {
    local config_path=$1
    local concurrency=$2
    local loglevel=$3

    local pidfile logfile
    pidfile="$(worker_pidfile)"
    logfile="$(worker_logfile)"

    if worker_is_running; then
        local pid
        pid=$(cat "$pidfile")
        log_warn "Celery Worker 已在运行 (PID=$pid)"
        return 0
    fi

    mkdir -p "$RUNS_DIR"

    # Remove a stale PID file left by a previously dead worker.  If the file
    # still exists here the process is no longer running (checked above), so it
    # is safe to delete.  Without this removal the wait-loop below would see the
    # file as already present and skip waiting entirely, causing a false failure.
    rm -f "$pidfile"

    local concurrency_arg=""
    if [ -n "$concurrency" ]; then
        concurrency_arg="--concurrency $concurrency"
    fi

    log_step "启动 Celery Worker..."
    log_info "  项目根目录: $PROJECT_ROOT"
    log_info "  配置文件:   $config_path"
    log_info "  日志文件:   $logfile"
    log_info "  PID 文件:   $pidfile"
    log_info "  日志级别:   $loglevel"
    [ -n "$concurrency" ] && log_info "  并发数:     $concurrency"

    local worker_log_start_line=0
    if [ -f "$logfile" ]; then
        worker_log_start_line=$(wc -l < "$logfile")
    fi

    (
        cd "$PROJECT_ROOT"
        BIBLE_ATLAS_CONFIG_PATH="$config_path" \
            uv run celery \
            -A bible.features.async_task.worker \
            worker \
            --loglevel="$loglevel" \
            --logfile="$logfile" \
            --pidfile="$pidfile" \
            $concurrency_arg \
            --detach
    )

    # 等待 Worker 真正进入存活状态（而不是只等启动命令返回）。
    # 注意：worker_init 包含同步模型预加载；Celery 主进程可能已经存在，
    # 但在预加载完成前还不会写 pidfile / fork pool worker。
    local worker_start_timeout=180
    local waited=0
    while [ $waited -lt "$worker_start_timeout" ]; do
        if worker_is_running && worker_log_has_ready_since "$logfile" "$worker_log_start_line"; then
            break
        fi
        sleep 1
        waited=$((waited + 1))
        if (( waited % 10 == 0 )); then
            if worker_process_is_starting; then
                log_info "  等待 Worker 就绪... (${waited}/${worker_start_timeout}s，模型预加载中，等待 pidfile)"
            else
                log_info "  等待 Worker 进程启动... (${waited}/${worker_start_timeout}s)"
            fi
        fi
    done

    if worker_is_running && worker_log_has_ready_since "$logfile" "$worker_log_start_line"; then
        local pid
        pid=$(cat "$pidfile")
        log_info "${GREEN}Celery Worker 已就绪 (PID=$pid)${NC}"
    else
        # Extra diagnostics for race/timeout analysis.
        local pid_text=""
        if [ -f "$pidfile" ]; then
            pid_text=$(cat "$pidfile" 2>/dev/null || true)
        fi

        log_error "Celery Worker 启动失败，请查看日志: $logfile"
        log_error "诊断信息: waited=${waited}s, pidfile_exists=$([ -f "$pidfile" ] && echo yes || echo no), pidfile_size=$([ -f "$pidfile" ] && wc -c < "$pidfile" || echo 0), pid='${pid_text}'"
        if [[ "$pid_text" =~ ^[0-9]+$ ]]; then
            if kill -0 "$pid_text" 2>/dev/null; then
                log_error "诊断信息: PID ${pid_text} 存活，但 worker_is_running 判定失败（请检查 pidfile 读取竞态）"
            else
                log_error "诊断信息: PID ${pid_text} 不存活（worker 可能启动后立即退出）"
            fi
        fi
        if [ -f "$logfile" ]; then
            log_error "Worker 日志最后 80 行："
            tail -n 80 "$logfile"
        fi
        exit 1
    fi
}

worker_stop() {
    local pidfile
    pidfile="$(worker_pidfile)"

    if ! worker_is_running; then
        log_warn "Celery Worker 未在运行"
        return 0
    fi

    local pid
    pid=$(cat "$pidfile")
    log_step "停止 Celery Worker (PID=$pid)..."

    kill -TERM "$pid" 2>/dev/null || true

    local waited=0
    while kill -0 "$pid" 2>/dev/null && [ $waited -lt 30 ]; do
        sleep 1
        waited=$((waited + 1))
    done

    if kill -0 "$pid" 2>/dev/null; then
        log_warn "Worker 未在 30 秒内退出，强制终止..."
        kill -KILL "$pid" 2>/dev/null || true
    fi

    rm -f "$pidfile"
    log_info "${GREEN}Celery Worker 已停止${NC}"
}

# ══════════════════════════════════════════════════════════════════════════════
# 顶层命令
# ══════════════════════════════════════════════════════════════════════════════

cmd_start() {
    # 解析参数
    local profile="${BIBLE_SERVICE_PROFILE:-prod}"
    local config_path="${BIBLE_ATLAS_CONFIG_PATH:-}"
    local concurrency=""
    local loglevel="info"
    local server_host="${BIBLE_SERVER_HOST:-}"
    local server_port="${BIBLE_SERVER_PORT:-}"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --profile)     profile="$2";      shift 2 ;;
            --config)      config_path="$2";  shift 2 ;;
            --concurrency) concurrency="$2";  shift 2 ;;
            --loglevel)    loglevel="$2";     shift 2 ;;
            --host)        server_host="$2";  shift 2 ;;
            --port)        server_port="$2";  shift 2 ;;
            *) log_warn "未知参数: $1"; shift ;;
        esac
    done

    set_service_profile "$profile"
    config_path="${config_path:-$(default_config_for_profile)}"
    server_host="${server_host:-$(default_host_for_profile)}"
    server_port="${server_port:-$(default_port_for_profile)}"

    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  启动 BiBLE-Atlas 后端服务           ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"
    echo ""
    log_info "  Profile:    $SERVICE_PROFILE"
    log_info "  运行目录:   $RUNS_DIR"

    check_prerequisites "$config_path"
    echo ""

    server_start "$config_path" "$server_host" "$server_port"
    echo ""

    worker_start "$config_path" "$concurrency" "$loglevel"
    echo ""

    log_info "${GREEN}所有服务已启动！${NC}"
    echo ""
    log_info "  查看状态:  $0 status --profile $SERVICE_PROFILE"
    log_info "  健康检查:  $0 health --profile $SERVICE_PROFILE"
    log_info "  查看日志:  $0 logs --profile $SERVICE_PROFILE"
    log_info "  停止服务:  $0 stop --profile $SERVICE_PROFILE"
    echo ""
}

cmd_stop() {
    local profile="${BIBLE_SERVICE_PROFILE:-prod}"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --profile) profile="$2"; shift 2 ;;
            *) log_warn "未知参数: $1"; shift ;;
        esac
    done
    set_service_profile "$profile"

    echo ""
    log_step "停止 BiBLE-Atlas 后端服务（profile=$SERVICE_PROFILE）..."
    echo ""

    # 先停 Worker（避免 Worker 向已关闭的 FastAPI 发请求），再停 Server
    worker_stop
    echo ""
    server_stop
    echo ""

    log_info "${GREEN}所有服务已停止${NC}"
}

cmd_restart() {
    log_step "重启 BiBLE-Atlas 后端服务..."
    local args=("$@")
    local profile="${BIBLE_SERVICE_PROFILE:-prod}"
    local idx=0
    while [ $idx -lt ${#args[@]} ]; do
        if [ "${args[$idx]}" = "--profile" ] && [ $((idx + 1)) -lt ${#args[@]} ]; then
            profile="${args[$((idx + 1))]}"
            break
        fi
        idx=$((idx + 1))
    done
    cmd_stop --profile "$profile"
    echo ""
    sleep 2
    cmd_start "${args[@]}"
}

cmd_status() {
    local profile="${BIBLE_SERVICE_PROFILE:-prod}"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --profile) profile="$2"; shift 2 ;;
            *) log_warn "未知参数: $1"; shift ;;
        esac
    done
    set_service_profile "$profile"

    echo ""
    echo -e "${CYAN}BiBLE-Atlas 服务状态（profile=$SERVICE_PROFILE）${NC}"
    echo "────────────────────────────────────────"

    # FastAPI Server
    if server_is_running; then
        local pid
        pid=$(cat "$(server_pidfile)")
        echo -e "  FastAPI Server:  ${GREEN}运行中 (PID=$pid)${NC}"
        if command -v ps &>/dev/null; then
            local mem cpu
            mem=$(ps -p "$pid" -o rss= 2>/dev/null | awk '{printf "%.1f MB", $1/1024}' || echo "N/A")
            cpu=$(ps -p "$pid" -o %cpu= 2>/dev/null | tr -d ' ' || echo "N/A")
            echo -e "                   CPU=${cpu}%  MEM=${mem}"
        fi
    else
        echo -e "  FastAPI Server:  ${YELLOW}未运行${NC}"
    fi

    echo ""

    # Celery Worker
    if worker_is_running; then
        local pid
        pid=$(cat "$(worker_pidfile)")
        echo -e "  Celery Worker:   ${GREEN}运行中 (PID=$pid)${NC}"
        if command -v ps &>/dev/null; then
            local mem cpu
            mem=$(ps -p "$pid" -o rss= 2>/dev/null | awk '{printf "%.1f MB", $1/1024}' || echo "N/A")
            cpu=$(ps -p "$pid" -o %cpu= 2>/dev/null | tr -d ' ' || echo "N/A")
            echo -e "                   CPU=${cpu}%  MEM=${mem}"
        fi
    else
        echo -e "  Celery Worker:   ${YELLOW}未运行${NC}"
    fi

    echo ""
    echo -e "  日志目录: $RUNS_DIR"
    echo ""
}

cmd_logs() {
    local profile="${BIBLE_SERVICE_PROFILE:-prod}"
    local target=${1:-both}
    local lines=${2:-50}

    if [ "${1:-}" = "--profile" ]; then
        profile="$2"
        target=${3:-both}
        lines=${4:-50}
    elif [ "${2:-}" = "--profile" ]; then
        profile="$3"
        lines=${4:-50}
    elif [ "${3:-}" = "--profile" ]; then
        profile="$4"
    fi
    set_service_profile "$profile"

    case "$target" in
        server)
            local logfile
            logfile="$(server_logfile)"
            if [ -f "$logfile" ]; then
                log_info "FastAPI Server 日志（最近 ${lines} 行）："
                echo ""
                tail -n "$lines" -f "$logfile"
            else
                log_warn "日志文件不存在: $logfile"
            fi
            ;;
        worker)
            local logfile
            logfile="$(worker_logfile)"
            if [ -f "$logfile" ]; then
                log_info "Celery Worker 日志（最近 ${lines} 行）："
                echo ""
                tail -n "$lines" -f "$logfile"
            else
                log_warn "日志文件不存在: $logfile"
            fi
            ;;
        both|*)
            local server_log worker_log
            server_log="$(server_logfile)"
            worker_log="$(worker_logfile)"
            if [ -f "$server_log" ]; then
                log_info "FastAPI Server 日志（最近 ${lines} 行）："
                echo ""
                tail -n "$lines" "$server_log"
                echo ""
            else
                log_warn "Server 日志文件不存在: $server_log"
            fi
            if [ -f "$worker_log" ]; then
                log_info "Celery Worker 日志（最近 ${lines} 行）："
                echo ""
                tail -n "$lines" "$worker_log"
            else
                log_warn "Worker 日志文件不存在: $worker_log"
            fi
            ;;
    esac
}

cmd_health() {
    local profile="${BIBLE_SERVICE_PROFILE:-prod}"
    local server_port="${BIBLE_SERVER_PORT:-}"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --profile) profile="$2"; shift 2 ;;
            --port)    server_port="$2"; shift 2 ;;
            *) log_warn "未知参数: $1"; shift ;;
        esac
    done
    set_service_profile "$profile"
    server_port="${server_port:-$(default_port_for_profile)}"

    echo ""
    log_step "BiBLE-Atlas 健康检查（profile=$SERVICE_PROFILE）..."
    echo ""

    if ! server_is_running; then
        log_error "FastAPI Server 未运行，无法进行健康检查"
        exit 1
    fi

    if ! command -v curl &>/dev/null; then
        log_error "curl 未安装，无法进行 HTTP 健康检查"
        exit 1
    fi

    local url="http://127.0.0.1:${server_port}/health"
    log_info "请求: GET $url"

    local http_code response
    response=$(curl -sf --connect-timeout 5 -w "\n%{http_code}" "$url" 2>&1) || true
    http_code=$(echo "$response" | tail -1)
    local body
    body=$(echo "$response" | head -n -1)

    if [ "$http_code" = "200" ]; then
        log_info "${GREEN}健康检查通过 (HTTP $http_code)${NC}"
        log_info "响应: $body"
    else
        log_error "健康检查失败 (HTTP ${http_code:-连接超时})"
        log_error "响应: $body"
        exit 1
    fi
    echo ""
}

cmd_api_test() {
    echo ""
    log_step "运行 tests/server/entity_test live API 测试..."
    echo ""

    local profile="${BIBLE_SERVICE_PROFILE:-test}"
    local config_path="${BIBLE_ATLAS_CONFIG_PATH:-}"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --profile) profile="$2"; shift 2 ;;
            --config) config_path="$2"; shift 2 ;;
            *) break ;;
        esac
    done

    set_service_profile "$profile"
    config_path="${config_path:-$(default_config_for_profile)}"
    local default_base_url="http://127.0.0.1:${BIBLE_SERVER_PORT:-$(default_port_for_profile)}"

    if ! command -v uv &>/dev/null; then
        log_error "未找到 uv，无法运行 API 测试脚本"
        exit 1
    fi

    (
        cd "$PROJECT_ROOT"
        local has_test_target=false
        for arg in "$@"; do
            case "$arg" in
                tests/server/entity_test*|*/tests/server/entity_test*|*.py|*::*)
                    has_test_target=true
                    ;;
            esac
        done
        if [ "$has_test_target" = false ]; then
            set -- tests/server/entity_test "$@"
        fi
        BIBLE_API_BASE_URL="${BIBLE_API_BASE_URL:-$default_base_url}" \
        BIBLE_ATLAS_CONFIG_PATH="$config_path" \
            uv run python -m pytest "$@"
    )
}

# ══════════════════════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════════════════════

main() {
    if [ $# -eq 0 ]; then
        show_usage
        exit 0
    fi

    local cmd=$1
    shift

    case "$cmd" in
        start)   cmd_start "$@" ;;
        start-test) cmd_start --profile test "$@" ;;
        stop)    cmd_stop "$@" ;;
        stop-test) cmd_stop --profile test "$@" ;;
        restart) cmd_restart "$@" ;;
        restart-test) cmd_restart --profile test "$@" ;;
        status)  cmd_status "$@" ;;
        status-test) cmd_status --profile test "$@" ;;
        logs)    cmd_logs "$@" ;;
        logs-test) cmd_logs --profile test "$@" ;;
        health)  cmd_health "$@" ;;
        health-test) cmd_health --profile test "$@" ;;
        api-test) cmd_api_test "$@" ;;
        help|--help|-h) show_usage ;;
        *)
            log_error "未知命令: $cmd"
            show_usage
            exit 1
            ;;
    esac
}

main "$@"
