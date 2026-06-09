#!/bin/bash

###########################################
# Redis + Celery Worker 部署管理脚本
#
# 功能：
#   redis  子命令 — 管理 Docker 化的 Redis 实例（多实例支持）
#   worker 子命令 — 管理 Celery worker 进程（进程管理，配合项目 venv）
#
# 使用示例：
#   ./deploy.sh redis create myredis 6379
#   ./deploy.sh redis start myredis
#   ./deploy.sh worker start myredis          # 为 myredis 实例启动 worker
#   ./deploy.sh worker start myredis --concurrency 4
#   ./deploy.sh status                        # 查看所有 Redis + Worker 状态
###########################################

set -euo pipefail

# ── 颜色 ──────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ── 路径 ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_DIR="$SCRIPT_DIR"

# 数据根目录（可通过环境变量覆盖）
BASE_DATA_DIR="${REDIS_BASE_DIR:-$SCRIPT_DIR/redis}"

# 项目根目录（脚本位于 scripts/redis_celery_deploy/，向上两级）
PROJECT_ROOT="${BIBLE_PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

normalize_registry_prefix() {
    local prefix="${BIBLE_DOCKER_REGISTRY_PREFIX:-}"
    if [ -n "$prefix" ]; then
        prefix="${prefix#http://}"
        prefix="${prefix#https://}"
        prefix="${prefix%/}/"
    fi
    echo "$prefix"
}

normalize_docker_image() {
    local image=$1
    image="${image#http://}"
    image="${image#https://}"
    echo "$image"
}

build_docker_image() {
    local override=$1
    local repository=$2
    local tag=$3

    if [ -n "$override" ]; then
        normalize_docker_image "$override"
    else
        echo "$(normalize_registry_prefix)${repository}:${tag}"
    fi
}

configure_docker_images() {
    export REDIS_IMAGE
    export REDIS_COMMANDER_IMAGE
    export REDIS_COMMANDER_ENABLED="${REDIS_COMMANDER_ENABLED:-true}"

    if [ "$REDIS_COMMANDER_ENABLED" != "true" ]; then
        REDIS_COMMANDER_ENABLED=false
    fi

    REDIS_IMAGE="$(build_docker_image \
        "${REDIS_IMAGE:-}" \
        "redis" \
        "${REDIS_IMAGE_TAG:-7-alpine}")"
    REDIS_COMMANDER_IMAGE="$(build_docker_image \
        "${REDIS_COMMANDER_IMAGE:-}" \
        "rediscommander/redis-commander" \
        "${REDIS_COMMANDER_IMAGE_TAG:-latest}")"
}

# ── 日志函数 ──────────────────────────────────────────────────────────────────
log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "${BLUE}[STEP]${NC} $1"; }

# ── 帮助 ──────────────────────────────────────────────────────────────────────
show_usage() {
    cat << EOF
${GREEN}Redis + Celery Worker 部署管理脚本${NC}

${YELLOW}使用方法：${NC}
    $0 <子命令> [参数]

${YELLOW}Redis 子命令（Docker 实例管理）：${NC}
    ${GREEN}redis create${NC}   <实例名> <Redis端口> [内存MB]
             创建并部署新的 Redis Docker 实例（默认内存 512m）
             示例: $0 redis create myredis 6379
                  $0 redis create myredis 6379 1024

    ${GREEN}redis register${NC} <实例名> [Redis端口]
             登记已有的 Redis（不部署 Docker，仅创建元信息供 worker 子命令使用）
             适用场景：端口已被系统 Redis 或其他 Redis 占用，直接复用它
             示例: $0 redis register myredis 6379
                  $0 redis register myredis        # 默认端口 6379

    ${GREEN}redis start${NC}    <实例名>
             启动 Redis 实例
             示例: $0 redis start myredis

    ${GREEN}redis stop${NC}     <实例名>
             停止 Redis 实例
             示例: $0 redis stop myredis

    ${GREEN}redis restart${NC}  <实例名>
             重启 Redis 实例
             示例: $0 redis restart myredis

    ${GREEN}redis delete${NC}   <实例名> [--keep-data]
             删除 Redis 实例（--keep-data 保留数据目录）

    ${GREEN}redis status${NC}   [实例名]
             查看 Redis 实例状态（不传参数则显示所有）

    ${GREEN}redis logs${NC}     <实例名> [行数]
             查看 Redis 容器日志

    ${GREEN}redis list${NC}
             列出所有已创建的 Redis 实例

    ${GREEN}redis info${NC}     <实例名>
             显示 Redis 实例详细信息

    ${GREEN}redis flush${NC}    <实例名> [--db <db编号>]
             清空 Redis 数据（危险操作，需确认）

${YELLOW}Worker 子命令（Celery worker 进程管理）：${NC}
    ${GREEN}worker start${NC}   <实例名> [选项]
             为指定 Redis 实例启动 Celery worker
             选项:
               --concurrency <N>   工作进程数（默认：CPU核心数）
               --queues <queue>    监听的队列（默认：celery）
               --config <path>     bible-atlas.yaml 路径（默认：项目根目录）
               --loglevel <level>  日志级别（默认：info）
             示例: $0 worker start myredis
                  $0 worker start myredis --concurrency 4

    ${GREEN}worker stop${NC}    <实例名>
             停止 Celery worker
             示例: $0 worker stop myredis

    ${GREEN}worker restart${NC} <实例名> [选项]
             重启 Celery worker

    ${GREEN}worker status${NC}  [实例名]
             查看 worker 进程状态

    ${GREEN}worker logs${NC}    <实例名> [行数]
             查看 worker 日志（tail）

${YELLOW}全局命令：${NC}
    ${GREEN}status${NC}
             查看所有 Redis 实例 + Worker 状态总览

    ${GREEN}start-all${NC}  <实例名>
             同时启动 Redis 实例和对应 Worker

    ${GREEN}stop-all${NC}   <实例名>
             同时停止 Worker 和 Redis 实例

    ${GREEN}help${NC}
             显示本帮助信息

${YELLOW}环境变量：${NC}
    REDIS_BASE_DIR       Redis 实例数据根目录（默认: 脚本目录/redis）
    BIBLE_PROJECT_ROOT   项目根目录（默认: 脚本向上两级）
    BIBLE_DOCKER_REGISTRY_PREFIX  Docker Hub 镜像前缀/镜像站（例如 docker.m.daocloud.io/）
    REDIS_IMAGE / REDIS_COMMANDER_IMAGE  完整镜像名覆盖
    REDIS_IMAGE_TAG / REDIS_COMMANDER_IMAGE_TAG  镜像标签覆盖
    REDIS_COMMANDER_ENABLED  是否启动 Redis Commander（仅 true 启用，其它值跳过；默认 true）

${YELLOW}快速开始：${NC}
    # 1. 创建 Redis 实例
    $0 redis create myredis 6379

    # 2. 启动 Redis
    $0 redis start myredis

    # 使用 Docker Hub 镜像站启动（适合网络受限地区）
    BIBLE_DOCKER_REGISTRY_PREFIX=docker.m.daocloud.io/ $0 redis start myredis

    # 3. 启动 Celery Worker
    $0 worker start myredis

    # 或一键启动两者
    $0 start-all myredis

EOF
}

# ══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════════════

check_port() {
    local port=$1
    if command -v ss &>/dev/null; then
        ss -tuln 2>/dev/null | grep -q ":$port " && return 1
    elif command -v netstat &>/dev/null; then
        netstat -tuln 2>/dev/null | grep -q ":$port " && return 1
    fi
    return 0
}

require_instance() {
    local instance_name=$1
    local instance_dir="$BASE_DATA_DIR/$instance_name"
    if [ ! -d "$instance_dir" ] || [ ! -f "$instance_dir/instance.info" ]; then
        log_error "Redis 实例 '${instance_name}' 不存在，请先执行: $0 redis create $instance_name <端口>"
        exit 1
    fi
}

repair_instance_config() {
    local instance_name=$1
    local instance_dir="$BASE_DATA_DIR/$instance_name"
    local compose_file="$instance_dir/docker-compose.yml"

    if [ -f "$compose_file" ] && grep -Eq "image: redis:7-alpine$|image: rediscommander/redis-commander:latest$" "$compose_file"; then
        log_warn "检测到旧版固定镜像配置，自动改为可通过环境变量覆盖: $compose_file"
        local tmp_file="${compose_file}.tmp.$$"
        sed \
            -e 's|image: redis:7-alpine|image: ${REDIS_IMAGE:-redis:7-alpine}|g' \
            -e 's|image: rediscommander/redis-commander:latest|image: ${REDIS_COMMANDER_IMAGE:-rediscommander/redis-commander:latest}|g' \
            "$compose_file" > "$tmp_file"
        mv "$tmp_file" "$compose_file"
    fi
}

load_instance_info() {
    local instance_name=$1
    # shellcheck disable=SC1090
    source "$BASE_DATA_DIR/$instance_name/instance.info"
}

instance_dir_of() {
    echo "$BASE_DATA_DIR/$1"
}

worker_pidfile() {
    echo "$BASE_DATA_DIR/$1/worker/celery.pid"
}

worker_logfile() {
    echo "$BASE_DATA_DIR/$1/worker/celery.log"
}

worker_is_running() {
    local pidfile
    pidfile="$(worker_pidfile "$1")"
    if [ -f "$pidfile" ]; then
        local pid
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

find_venv_python() {
    # Prefer project venv, fall back to system python3
    local venv_python="$PROJECT_ROOT/.venv/bin/python"
    if [ -x "$venv_python" ]; then
        echo "$venv_python"
    else
        command -v python3
    fi
}

find_venv_celery() {
    local venv_celery="$PROJECT_ROOT/.venv/bin/celery"
    if [ -x "$venv_celery" ]; then
        echo "$venv_celery"
    elif command -v celery &>/dev/null; then
        command -v celery
    else
        echo ""
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
# Redis 子命令
# ══════════════════════════════════════════════════════════════════════════════

redis_create() {
    local instance_name=$1
    local redis_port=${2:-6379}
    local mem_mb=${3:-512}

    if [ -z "$instance_name" ]; then
        log_error "缺少实例名参数"
        echo "用法: $0 redis create <实例名> [Redis端口] [内存MB]"
        exit 1
    fi

    local instance_dir
    instance_dir="$(instance_dir_of "$instance_name")"

    if [ -d "$instance_dir" ]; then
        log_error "实例 '${instance_name}' 已存在：$instance_dir"
        log_info "如需重建，请先执行: $0 redis delete $instance_name"
        exit 1
    fi

    log_step "检查端口可用性..."
    local commander_port=$((redis_port + 1000))
    if ! check_port "$redis_port"; then
        # 找下一个可用端口给出提示
        local next_port=$((redis_port + 1))
        while ! check_port "$next_port" && [ $next_port -lt $((redis_port + 20)) ]; do
            next_port=$((next_port + 1))
        done
        log_error "端口 $redis_port 已被占用"
        log_info ""
        log_info "可选方案："
        log_info "  1. 使用其他端口部署新实例："
        log_info "     $0 redis create $instance_name $next_port"
        log_info ""
        log_info "  2. 如果该端口已有 Redis 在运行，直接登记它（不部署 Docker）："
        log_info "     $0 redis register $instance_name $redis_port"
        log_info "     之后直接启动 Worker 即可："
        log_info "     $0 worker start $instance_name"
        exit 1
    fi
    if ! check_port "$commander_port"; then
        log_warn "Redis Commander 端口 $commander_port 已被占用，将跳过 Commander 部署"
        commander_port=0
    fi
    log_info "端口检查通过：Redis=$redis_port, Commander=${commander_port:-跳过}"

    log_step "创建目录结构..."
    mkdir -p "$instance_dir"/{data,logs,config,worker}
    log_info "目录创建完成：$instance_dir"

    log_step "生成 Redis 配置..."
    local max_memory="${mem_mb}mb"
    sed \
        -e "s/\${INSTANCE_NAME}/$instance_name/g" \
        -e "s/\${REDIS_PORT}/$redis_port/g" \
        -e "s/\${MAX_MEMORY}/$max_memory/g" \
        "$TEMPLATE_DIR/redis.conf.template" \
        > "$instance_dir/config/redis.conf"

    log_step "生成 docker-compose.yml..."
    local mem_reserve_mb=$(( mem_mb / 2 ))
    sed \
        -e "s/\${INSTANCE_NAME}/$instance_name/g" \
        -e "s/\${REDIS_PORT}/$redis_port/g" \
        -e "s|\${DATA_DIR}|$instance_dir|g" \
        -e "s/\${MEM_LIMIT}/${mem_mb}M/g" \
        -e "s/\${MEM_RESERVE}/${mem_reserve_mb}M/g" \
        -e "s/\${COMMANDER_PORT}/${commander_port}/g" \
        -e "s/\${COMMANDER_USER}/admin/g" \
        -e "s/\${COMMANDER_PASSWORD}/admin/g" \
        "$TEMPLATE_DIR/docker-compose.template.yml" \
        > "$instance_dir/docker-compose.yml"

    # 如果 Commander 端口冲突则移除该服务段
    if [ "$commander_port" -eq 0 ]; then
        # 简单方案：保留文件但记录跳过
        log_warn "Redis Commander 未配置（端口冲突），可手动编辑 $instance_dir/docker-compose.yml"
    fi

    # 实例元信息
    cat > "$instance_dir/instance.info" << EOF
# Redis 实例信息（由 deploy.sh 自动生成）
INSTANCE_NAME=$instance_name
REDIS_PORT=$redis_port
COMMANDER_PORT=$commander_port
MEM_MB=$mem_mb
CREATED_AT="$(date '+%Y-%m-%d %H:%M:%S')"
DATA_DIR=$instance_dir
BROKER_URL=redis://localhost:${redis_port}/0
RESULT_BACKEND=redis://localhost:${redis_port}/1
EOF

    chmod -R 755 "$instance_dir"

    log_info ""
    log_info "${GREEN}Redis 实例 '${instance_name}' 创建成功！${NC}"
    log_info ""
    log_info "  数据目录:   $instance_dir"
    log_info "  Redis 端口: $redis_port"
    log_info "  Commander:  http://localhost:$commander_port  (admin/admin)"
    log_info ""
    log_info "下一步："
    log_info "  启动 Redis:         $0 redis start $instance_name"
    log_info "  启动 Celery Worker: $0 worker start $instance_name"
    log_info "  一键启动两者:       $0 start-all $instance_name"
}

# 登记已有 Redis（不部署 Docker，只创建 instance.info 供 worker 子命令使用）
redis_register() {
    local instance_name=$1
    local redis_port=${2:-6379}

    if [ -z "$instance_name" ]; then
        log_error "缺少实例名参数"
        echo "用法: $0 redis register <实例名> [Redis端口]"
        exit 1
    fi

    local instance_dir
    instance_dir="$(instance_dir_of "$instance_name")"

    if [ -d "$instance_dir" ] && [ -f "$instance_dir/instance.info" ]; then
        log_error "实例 '${instance_name}' 已存在：$instance_dir"
        log_info "如需更新端口，请先执行: $0 redis delete $instance_name --keep-data"
        exit 1
    fi

    log_step "登记已有 Redis 实例（端口 ${redis_port}）..."

    # 尝试验证 Redis 连通性
    if command -v redis-cli &>/dev/null; then
        if redis-cli -p "$redis_port" ping 2>/dev/null | grep -q "PONG"; then
            log_info "连通性验证通过（redis-cli -p $redis_port ping → PONG）"
        else
            log_warn "redis-cli ping 失败，请确认 Redis 确实在 localhost:$redis_port 运行"
        fi
    else
        log_warn "redis-cli 未安装，跳过连通性验证"
    fi

    mkdir -p "$instance_dir/worker"

    cat > "$instance_dir/instance.info" << EOF
# Redis 实例信息（外部实例，由 redis register 登记，非本脚本 Docker 部署）
INSTANCE_NAME=$instance_name
REDIS_PORT=$redis_port
COMMANDER_PORT=0
MEM_MB=0
CREATED_AT="$(date '+%Y-%m-%d %H:%M:%S')"
DATA_DIR=$instance_dir
BROKER_URL=redis://localhost:${redis_port}/0
RESULT_BACKEND=redis://localhost:${redis_port}/1
EXTERNAL=true
EOF

    log_info ""
    log_info "${GREEN}Redis 实例 '${instance_name}' 登记成功！${NC}"
    log_info ""
    log_info "  Redis 端口:     $redis_port"
    log_info "  broker_url:     redis://localhost:${redis_port}/0"
    log_info "  result_backend: redis://localhost:${redis_port}/1"
    log_info ""
    log_info "请确认 bible-atlas.yaml 中的 celery 配置与上述端口一致，然后："
    log_info "  $0 worker start $instance_name"
}

redis_start() {
    local instance_name=$1
    require_instance "$instance_name"
    configure_docker_images
    repair_instance_config "$instance_name"
    load_instance_info "$instance_name"
    local instance_dir
    instance_dir="$(instance_dir_of "$instance_name")"

    log_step "启动 Redis 实例 '${instance_name}'..."

    cd "$instance_dir"

    # docker images outputs REPOSITORY and TAG in separate columns; use --format
    # to get "repo:tag" strings so the grep works correctly.
    if ! docker images --format "{{.Repository}}:{{.Tag}}" | grep -Fxq "$REDIS_IMAGE"; then
        log_info "本地未找到 Redis 镜像 ${REDIS_IMAGE}，开始拉取..."
        docker-compose pull redis
    fi

    docker-compose up -d redis

    local commander_started=false
    if [ "${REDIS_COMMANDER_ENABLED:-true}" = "false" ]; then
        log_warn "Redis Commander 已按配置跳过"
    elif [ "${COMMANDER_PORT:-0}" -gt 0 ] 2>/dev/null; then
        if docker-compose up -d redis-commander; then
            commander_started=true
        else
            log_warn "Redis Commander 启动失败，已跳过。Redis 实例仍可正常使用。"
            log_warn "如需 Commander，请设置 REDIS_COMMANDER_IMAGE 为可访问的完整镜像名后重试。"
        fi
    else
        log_warn "Redis Commander 未配置，跳过启动"
    fi

    log_info "${GREEN}Redis 已启动${NC}"
    log_info ""
    log_info "  连接地址: redis://localhost:${REDIS_PORT}"
    if [ "$commander_started" = true ]; then
        log_info "  Commander: http://localhost:${COMMANDER_PORT}  (admin/admin)"
    else
        log_info "  Commander: 跳过"
    fi
    log_info ""
    log_info "验证连接: redis-cli -p ${REDIS_PORT} ping"
}

redis_stop() {
    local instance_name=$1
    require_instance "$instance_name"
    local instance_dir
    instance_dir="$(instance_dir_of "$instance_name")"

    log_step "停止 Redis 实例 '${instance_name}'..."
    cd "$instance_dir"
    docker-compose down
    log_info "${GREEN}Redis 已停止${NC}"
}

redis_restart() {
    local instance_name=$1
    log_step "重启 Redis 实例 '${instance_name}'..."
    redis_stop "$instance_name"
    sleep 2
    redis_start "$instance_name"
}

redis_delete() {
    local instance_name=$1
    local keep_data=${2:-}
    require_instance "$instance_name"
    local instance_dir
    instance_dir="$(instance_dir_of "$instance_name")"

    log_warn "即将删除 Redis 实例 '${instance_name}'"
    log_warn "数据目录: $instance_dir"
    read -rp "确认删除？(yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        log_info "取消删除"
        exit 0
    fi

    # 先停止 worker
    if worker_is_running "$instance_name"; then
        log_step "停止关联的 Celery Worker..."
        worker_stop "$instance_name"
    fi

    log_step "停止并删除 Docker 容器..."
    cd "$instance_dir"
    docker-compose down -v

    if [ "$keep_data" = "--keep-data" ]; then
        log_info "保留数据目录，仅删除配置文件..."
        rm -f "$instance_dir/docker-compose.yml" "$instance_dir/instance.info"
        rm -rf "$instance_dir/config"
    else
        cd "$BASE_DATA_DIR"
        rm -rf "$instance_dir"
        log_info "${GREEN}实例已完全删除${NC}"
    fi
}

redis_status() {
    local instance_name=${1:-}

    if [ -n "$instance_name" ]; then
        require_instance "$instance_name"
        local instance_dir
        instance_dir="$(instance_dir_of "$instance_name")"

        log_info "Redis 实例 '${instance_name}' 状态："
        cd "$instance_dir"
        docker-compose ps

        load_instance_info "$instance_name"
        log_info ""
        log_info "配置：Redis端口=${REDIS_PORT}  内存=${MEM_MB}MB  创建时间=${CREATED_AT}"

        if docker ps --format '{{.Names}}' | grep -q "^redis-${instance_name}$"; then
            log_info ""
            log_info "连通性测试："
            if redis-cli -p "$REDIS_PORT" ping 2>/dev/null | grep -q "PONG"; then
                log_info "  ${GREEN}redis-cli ping → PONG${NC}"
                log_info "  内存使用: $(redis-cli -p "$REDIS_PORT" info memory 2>/dev/null | grep used_memory_human | cut -d: -f2 | tr -d '[:space:]')"
            else
                log_warn "  redis-cli 不可用（redis-cli 未安装或端口不通）"
            fi
        fi
    else
        log_info "所有 Redis 实例状态："
        echo ""
        docker ps --filter "name=redis-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || true
        echo ""
        log_info "使用 '$0 redis status <实例名>' 查看单实例详情"
    fi
}

redis_logs() {
    local instance_name=$1
    local lines=${2:-50}
    require_instance "$instance_name"
    local instance_dir
    instance_dir="$(instance_dir_of "$instance_name")"

    log_info "Redis '${instance_name}' 日志（最近 ${lines} 行）："
    cd "$instance_dir"
    docker-compose logs --tail="$lines" -f redis
}

redis_list() {
    log_info "已创建的 Redis 实例："
    echo ""

    if [ ! -d "$BASE_DATA_DIR" ]; then
        log_warn "数据目录不存在: $BASE_DATA_DIR"
        return
    fi

    printf "%-18s %-10s %-12s %-12s %-10s %-22s\n" \
        "实例名" "状态" "Redis端口" "Commander端口" "内存" "创建时间"
    echo "────────────────────────────────────────────────────────────────────────────────────"

    for dir in "$BASE_DATA_DIR"/*/; do
        [ -f "$dir/instance.info" ] || continue
        # shellcheck disable=SC1090
        source "$dir/instance.info"
        if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^redis-${INSTANCE_NAME}$"; then
            status="${GREEN}运行中${NC}"
        elif docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^redis-${INSTANCE_NAME}$"; then
            status="${YELLOW}已停止${NC}"
        else
            status="${RED}未启动${NC}"
        fi
        printf "%-18s %-18b %-12s %-12s %-10s %-22s\n" \
            "$INSTANCE_NAME" "$status" "$REDIS_PORT" "$COMMANDER_PORT" \
            "${MEM_MB}MB" "$CREATED_AT"
    done
    echo ""
    log_info "使用 '$0 redis info <实例名>' 查看详情"
}

redis_info() {
    local instance_name=$1
    require_instance "$instance_name"
    load_instance_info "$instance_name"

    log_info "Redis 实例 '${instance_name}' 详细信息："
    echo ""
    log_info "${BLUE}基本信息：${NC}"
    log_info "  实例名:       $INSTANCE_NAME"
    log_info "  数据目录:     $DATA_DIR"
    log_info "  创建时间:     $CREATED_AT"
    echo ""
    log_info "${BLUE}网络配置：${NC}"
    log_info "  Redis 端口:   $REDIS_PORT"
    log_info "  Commander 端口: $COMMANDER_PORT"
    echo ""
    log_info "${BLUE}资源配置：${NC}"
    log_info "  最大内存:     ${MEM_MB}MB"
    echo ""
    log_info "${BLUE}Celery 配置（供 bible-atlas.yaml 使用）：${NC}"
    log_info "  broker_url:      $BROKER_URL"
    log_info "  result_backend:  $RESULT_BACKEND"
    echo ""
    log_info "${BLUE}访问地址：${NC}"
    log_info "  Redis:       redis://localhost:$REDIS_PORT"
    log_info "  Commander:   http://localhost:$COMMANDER_PORT  (admin/admin)"
    echo ""
    log_info "${BLUE}Worker 状态：${NC}"
    if worker_is_running "$instance_name"; then
        local pid
        pid=$(cat "$(worker_pidfile "$instance_name")")
        log_info "  ${GREEN}运行中 (PID=$pid)${NC}"
    else
        log_info "  ${YELLOW}未运行${NC}"
    fi
    echo ""
    log_info "${BLUE}常用命令：${NC}"
    log_info "  启动 Redis:    $0 redis start $instance_name"
    log_info "  停止 Redis:    $0 redis stop $instance_name"
    log_info "  启动 Worker:   $0 worker start $instance_name"
    log_info "  一键启动:      $0 start-all $instance_name"
}

redis_flush() {
    local instance_name=$1
    local db_flag=${2:-}
    local db_num=${3:-}
    require_instance "$instance_name"
    load_instance_info "$instance_name"

    local target="所有数据库"
    local flushcmd="FLUSHALL"
    if [ "$db_flag" = "--db" ] && [ -n "$db_num" ]; then
        target="数据库 $db_num"
        flushcmd="SELECT $db_num; FLUSHDB"
    fi

    log_warn "即将清空 Redis 实例 '${instance_name}' 的 ${target}！"
    read -rp "确认清空？(yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        log_info "取消操作"
        exit 0
    fi

    redis-cli -p "$REDIS_PORT" $flushcmd
    log_info "${GREEN}清空完成${NC}"
}

# ══════════════════════════════════════════════════════════════════════════════
# Worker 子命令（Celery worker 进程管理）
# ══════════════════════════════════════════════════════════════════════════════

worker_start() {
    local instance_name=$1
    shift
    require_instance "$instance_name"
    load_instance_info "$instance_name"

    local instance_dir
    instance_dir="$(instance_dir_of "$instance_name")"
    local pidfile
    pidfile="$(worker_pidfile "$instance_name")"
    local logfile
    logfile="$(worker_logfile "$instance_name")"
    local worker_dir="$instance_dir/worker"

    if worker_is_running "$instance_name"; then
        local pid
        pid=$(cat "$pidfile")
        log_warn "Celery Worker '${instance_name}' 已在运行 (PID=$pid)"
        return 0
    fi

    # 解析额外参数
    local concurrency=""
    local queues="celery"
    local loglevel="info"
    local config_path="$PROJECT_ROOT/bible-atlas.yaml"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --concurrency) concurrency="$2"; shift 2 ;;
            --queues)      queues="$2";      shift 2 ;;
            --loglevel)    loglevel="$2";    shift 2 ;;
            --config)      config_path="$2"; shift 2 ;;
            *) log_warn "未知参数: $1"; shift ;;
        esac
    done

    local celery_bin
    celery_bin="$(find_venv_celery)"
    if [ -z "$celery_bin" ]; then
        log_error "未找到 celery 可执行文件。请确认项目 venv 已激活或 celery 已安装。"
        log_error "安装方式: cd $PROJECT_ROOT && .venv/bin/pip install celery"
        exit 1
    fi

    if [ ! -f "$config_path" ]; then
        log_error "配置文件不存在: $config_path"
        log_error "请使用 --config 参数指定正确路径"
        exit 1
    fi

    mkdir -p "$worker_dir"

    # If concurrency not given on CLI, read worker_concurrency from bible-atlas.yaml.
    # A value of 0 or empty means "use Celery default (CPU count)".
    if [ -z "$concurrency" ] && [ -f "$config_path" ]; then
        local yaml_concurrency
        yaml_concurrency=$(grep -E '^\s*worker_concurrency\s*:' "$config_path" \
            | head -1 | sed 's/.*:\s*\([0-9]*\).*/\1/')
        if [ -n "$yaml_concurrency" ] && [ "$yaml_concurrency" -gt 0 ] 2>/dev/null; then
            concurrency="$yaml_concurrency"
        fi
    fi

    local concurrency_arg=""
    if [ -n "$concurrency" ]; then
        concurrency_arg="--concurrency $concurrency"
    fi

    log_step "启动 Celery Worker（连接 Redis 实例 '${instance_name}'，端口 ${REDIS_PORT}）..."
    log_info "  Celery:     $celery_bin"
    log_info "  项目根目录: $PROJECT_ROOT"
    log_info "  配置文件:   $config_path"
    log_info "  日志文件:   $logfile"
    log_info "  PID 文件:   $pidfile"
    log_info "  队列:       $queues"
    log_info "  日志级别:   $loglevel"
    if [ -n "$concurrency" ]; then
        log_info "  并发数:     $concurrency (from bible-atlas.yaml)"
    else
        log_info "  并发数:     (CPU 核心数，Celery 默认)"
    fi

    # 切换到项目根目录，确保 bible-atlas.yaml 里的相对路径（如 ./workspace/memory/import_work）
    # 以项目根为基准解析，而不是以调用者的工作目录为基准。
    # 将配置文件路径通过环境变量传给 worker（bible 项目读取 BIBLE_ATLAS_CONFIG_PATH）
    ( cd "$PROJECT_ROOT" && \
      BIBLE_ATLAS_CONFIG_PATH="$config_path" \
      PYTHONPATH="$PROJECT_ROOT" \
          "$celery_bin" \
          -A bible.features.async_task.worker \
          worker \
          --loglevel="$loglevel" \
          --queues="$queues" \
          $concurrency_arg \
          --logfile="$logfile" \
          --pidfile="$pidfile" \
          --detach \
    )

    # 等待 PID 文件写入（最多 15 秒）
    local waited=0
    # worker_init 包含同步向量模型预加载（每个大模型约 10-15s），
    # 所有模型加载完毕后才写 PID 文件，需要足够的等待时间。
    while [ ! -f "$pidfile" ] && [ $waited -lt 120 ]; do
        sleep 1
        waited=$((waited + 1))
    done

    if worker_is_running "$instance_name"; then
        local pid
        pid=$(cat "$pidfile")
        log_info "${GREEN}Celery Worker 已启动 (PID=$pid)${NC}"
        log_info ""
        log_info "查看日志:  $0 worker logs $instance_name"
        log_info "检查状态:  $0 worker status $instance_name"
        log_info "停止:      $0 worker stop $instance_name"
        log_info "重启:      $0 worker restart $instance_name"
        log_info "再次启动:  $0 worker start $instance_name"
    else
        log_error "Worker 启动失败，请查看日志: $logfile"
        exit 1
    fi
}

worker_stop() {
    local instance_name=$1
    local pidfile
    pidfile="$(worker_pidfile "$instance_name")"

    if ! worker_is_running "$instance_name"; then
        log_warn "Celery Worker '${instance_name}' 未在运行"
        return 0
    fi

    local pid
    pid=$(cat "$pidfile")
    log_step "停止 Celery Worker '${instance_name}' (PID=$pid)..."

    # 发送 SIGTERM，等待优雅退出（最多 30 秒）
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

worker_restart() {
    local instance_name=$1
    shift
    log_step "重启 Celery Worker '${instance_name}'..."
    worker_stop "$instance_name"
    sleep 2
    worker_start "$instance_name" "$@"
}

worker_status() {
    local instance_name=${1:-}

    if [ -n "$instance_name" ]; then
        require_instance "$instance_name"
        if worker_is_running "$instance_name"; then
            local pid
            pid=$(cat "$(worker_pidfile "$instance_name")")
            log_info "${GREEN}Celery Worker '${instance_name}' 运行中 (PID=$pid)${NC}"
            # 显示进程资源
            if command -v ps &>/dev/null; then
                echo ""
                ps -p "$pid" -o pid,ppid,%cpu,%mem,etime,cmd 2>/dev/null || true
            fi
        else
            log_info "${YELLOW}Celery Worker '${instance_name}' 未运行${NC}"
        fi
    else
        log_info "所有 Celery Worker 状态："
        echo ""
        [ ! -d "$BASE_DATA_DIR" ] && log_warn "数据目录不存在: $BASE_DATA_DIR" && return
        for dir in "$BASE_DATA_DIR"/*/; do
            [ -f "$dir/instance.info" ] || continue
            # shellcheck disable=SC1090
            source "$dir/instance.info"
            if worker_is_running "$INSTANCE_NAME"; then
                local pid
                pid=$(cat "$(worker_pidfile "$INSTANCE_NAME")")
                log_info "  ${GREEN}●${NC} $INSTANCE_NAME  (PID=$pid)"
            else
                log_info "  ${RED}○${NC} $INSTANCE_NAME  (未运行)"
            fi
        done
    fi
}

worker_logs() {
    local instance_name=$1
    local lines=${2:-100}
    require_instance "$instance_name"
    local logfile
    logfile="$(worker_logfile "$instance_name")"

    if [ ! -f "$logfile" ]; then
        log_warn "日志文件不存在: $logfile"
        log_info "Worker 可能尚未启动，或日志路径不同"
        return
    fi

    log_info "Celery Worker '${instance_name}' 日志（最近 ${lines} 行）："
    tail -n "$lines" -f "$logfile"
}

# ══════════════════════════════════════════════════════════════════════════════
# 全局命令
# ══════════════════════════════════════════════════════════════════════════════

show_all_status() {
    log_info "══════════════════ Redis 实例 ══════════════════"
    redis_list
    echo ""
    log_info "══════════════════ Celery Worker ══════════════════"
    worker_status
}

start_all() {
    local instance_name=$1
    if [ -z "$instance_name" ]; then
        log_error "缺少实例名参数"
        echo "用法: $0 start-all <实例名>"
        exit 1
    fi
    redis_start "$instance_name"
    echo ""
    log_info "等待 Redis 就绪（3 秒）..."
    sleep 3
    worker_start "$instance_name"
}

stop_all() {
    local instance_name=$1
    if [ -z "$instance_name" ]; then
        log_error "缺少实例名参数"
        echo "用法: $0 stop-all <实例名>"
        exit 1
    fi
    worker_stop "$instance_name"
    echo ""
    redis_stop "$instance_name"
}

# ══════════════════════════════════════════════════════════════════════════════
# 主函数
# ══════════════════════════════════════════════════════════════════════════════

main() {
    local command=${1:-}

    case "$command" in
        redis)
            local sub=${2:-}
            case "$sub" in
                create)   redis_create    "$3" "${4:-}" "${5:-}" ;;
                register) redis_register  "$3" "${4:-}" ;;
                start)    redis_start     "$3" ;;
                stop)     redis_stop      "$3" ;;
                restart)  redis_restart   "$3" ;;
                delete)   redis_delete    "$3" "${4:-}" ;;
                status)   redis_status    "${3:-}" ;;
                logs)     redis_logs      "$3" "${4:-}" ;;
                list)     redis_list ;;
                info)     redis_info      "$3" ;;
                flush)    redis_flush     "$3" "${4:-}" "${5:-}" ;;
                *)
                    log_error "未知 redis 子命令: $sub"
                    show_usage; exit 1 ;;
            esac
            ;;
        worker)
            local sub=${2:-}
            case "$sub" in
                start)   worker_start   "$3" "${@:4}" ;;
                stop)    worker_stop    "$3" ;;
                restart) worker_restart "$3" "${@:4}" ;;
                status)  worker_status  "${3:-}" ;;
                logs)    worker_logs    "$3" "${4:-}" ;;
                *)
                    log_error "未知 worker 子命令: $sub"
                    show_usage; exit 1 ;;
            esac
            ;;
        status)    show_all_status ;;
        start-all) start_all "$2" ;;
        stop-all)  stop_all  "$2" ;;
        help|--help|-h|"")
            show_usage ;;
        *)
            log_error "未知命令: $command"
            show_usage; exit 1 ;;
    esac
}

main "$@"
