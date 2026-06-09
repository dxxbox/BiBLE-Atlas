#!/bin/bash

###########################################
# OpenSearch 多用户部署脚本
#
# 功能：
# - 支持多用户独立部署 OpenSearch 实例
# - 自动配置资源分配
# - 自动生成配置文件
# - 支持创建、启动、停止、删除操作
#
# 使用示例：
#   ./deploy.sh create user1 9201 5602 6 20
#   ./deploy.sh start user1
#   ./deploy.sh stop user1
#   ./deploy.sh status
#   ./deploy.sh delete user1
###########################################

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 脚本目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_DIR="$SCRIPT_DIR"

# 基础数据目录（使用脚本所在目录下的 opensearch 子目录）
BASE_DATA_DIR="${OPENSEARCH_BASE_DIR:-$SCRIPT_DIR/opensearch}"

normalize_registry_prefix() {
    local prefix="${BIBLE_DOCKER_REGISTRY_PREFIX:-}"
    if [ -n "$prefix" ]; then
        prefix="${prefix%/}/"
    fi
    echo "$prefix"
}

build_docker_image() {
    local override=$1
    local repository=$2
    local tag=$3

    if [ -n "$override" ]; then
        echo "$override"
    else
        echo "$(normalize_registry_prefix)${repository}:${tag}"
    fi
}

configure_docker_images() {
    export OPENSEARCH_IMAGE
    export OPENSEARCH_DASHBOARDS_IMAGE

    OPENSEARCH_IMAGE="$(build_docker_image \
        "${OPENSEARCH_IMAGE:-}" \
        "opensearchproject/opensearch" \
        "${OPENSEARCH_IMAGE_TAG:-latest}")"
    OPENSEARCH_DASHBOARDS_IMAGE="$(build_docker_image \
        "${OPENSEARCH_DASHBOARDS_IMAGE:-}" \
        "opensearchproject/opensearch-dashboards" \
        "${OPENSEARCH_DASHBOARDS_IMAGE_TAG:-${OPENSEARCH_IMAGE_TAG:-latest}}")"
}

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# 显示使用帮助
show_usage() {
    cat << EOF
${GREEN}OpenSearch 多用户部署脚本${NC}

${YELLOW}使用方法：${NC}
    $0 <命令> [参数]

${YELLOW}命令列表：${NC}
    ${GREEN}create${NC}   <用户名> <HTTP端口> <Dashboard端口> <CPU核心数> <内存GB>
             创建新的 OpenSearch 实例
             示例: $0 create user1 9201 5602 6 20

    ${GREEN}start${NC}    <用户名>
             启动指定用户的 OpenSearch 实例
             示例: $0 start user1

    ${GREEN}stop${NC}     <用户名>
             停止指定用户的 OpenSearch 实例
             示例: $0 stop user1

    ${GREEN}restart${NC}  <用户名>
             重启指定用户的 OpenSearch 实例
             示例: $0 restart user1

    ${GREEN}pull${NC}     [用户名]
             拉取 Docker 镜像
             示例: $0 pull              # 拉取默认镜像
                  $0 pull user1         # 拉取指定实例的镜像

    ${GREEN}delete${NC}   <用户名> [--keep-data]
             删除指定用户的 OpenSearch 实例
             --keep-data: 保留数据目录
             示例: $0 delete user1
                  $0 delete user1 --keep-data

    ${GREEN}status${NC}   [用户名]
             查看 OpenSearch 实例状态
             示例: $0 status           # 查看所有实例
                  $0 status user1      # 查看指定用户实例

    ${GREEN}logs${NC}     <用户名> [行数]
             查看指定用户的日志
             示例: $0 logs user1
                  $0 logs user1 100

    ${GREEN}list${NC}
             列出所有已创建的实例
             示例: $0 list

    ${GREEN}info${NC}     <用户名>
             显示指定用户实例的详细信息
             示例: $0 info user1

${YELLOW}资源配置预设：${NC}
    ${BLUE}小型${NC}  (适合开发测试): 4核  / 12GB  (JVM: 4GB)
    ${BLUE}中型${NC}  (适合小规模应用): 6核  / 20GB  (JVM: 8GB)
    ${BLUE}大型${NC}  (适合生产环境):   12核 / 40GB  (JVM: 16GB)
    ${BLUE}超大${NC}  (高性能需求):     18核 / 66GB  (JVM: 31GB)

${YELLOW}端口规划建议：${NC}
    用户1: HTTP 9201, Dashboard 5602
    用户2: HTTP 9202, Dashboard 5603
    用户3: HTTP 9203, Dashboard 5604
    ...

${YELLOW}环境变量：${NC}
    OPENSEARCH_BASE_DIR: 数据存储基础目录（默认: 脚本目录/opensearch）
    BIBLE_DOCKER_REGISTRY_PREFIX: Docker Hub 镜像前缀/镜像站（例如 docker.m.daocloud.io/）
    OPENSEARCH_IMAGE / OPENSEARCH_DASHBOARDS_IMAGE: 完整镜像名覆盖
    OPENSEARCH_IMAGE_TAG / OPENSEARCH_DASHBOARDS_IMAGE_TAG: 镜像标签覆盖

${YELLOW}示例：${NC}
    # 预先拉取镜像（可选，推荐首次使用前执行）
    $0 pull

    # 使用 Docker Hub 镜像站（适合网络受限地区）
    BIBLE_DOCKER_REGISTRY_PREFIX=docker.m.daocloud.io/ $0 pull

    # 创建用户1的实例（中型配置）
    $0 create user1 9201 5602 6 20

    # 启动实例（会自动检查并拉取镜像）
    $0 start user1

    # 查看状态
    $0 status user1

    # 查看日志
    $0 logs user1

    # 停止实例
    $0 stop user1

    # 删除实例（保留数据）
    $0 delete user1 --keep-data

EOF
}

# 检查端口是否被占用
check_port() {
    local port=$1
    if command -v netstat &> /dev/null; then
        if netstat -tuln | grep -q ":$port "; then
            return 1
        fi
    elif command -v ss &> /dev/null; then
        if ss -tuln | grep -q ":$port "; then
            return 1
        fi
    else
        log_warn "无法检查端口，netstat 和 ss 命令都不可用"
    fi
    return 0
}

# 检查 Docker CLI 是否实际由 rootless Podman 提供
is_podman_backend() {
    docker version 2>&1 | grep -qi "Podman"
}

# 准备 OpenSearch bind mount 目录权限
prepare_volume_permissions() {
    local user_dir=$1

    chmod 755 "$user_dir"
    chmod 755 "$user_dir/config" 2>/dev/null || true

    if [ "$(id -u)" -eq 0 ]; then
        # root 或真实 Docker 环境：让容器内 opensearch 用户直接拥有数据目录
        chown -R 1000:1000 "$user_dir/data" "$user_dir/logs" "$user_dir/backup"
        chmod -R 755 "$user_dir/data" "$user_dir/logs" "$user_dir/backup"
    elif is_podman_backend; then
        # rootless Podman 会把宿主用户拥有的 bind mount 映射成容器内 root:root。
        # Compose 中使用 user: "1000:0"，这里允许 root 组写入挂载目录。
        chmod 775 "$user_dir/data" "$user_dir/logs" "$user_dir/backup"
    else
        log_warn "非 root 用户，跳过目录所有者设置"
        log_warn "如果容器启动失败，请以 root 权限运行："
        log_warn "  sudo chown -R 1000:1000 $user_dir/data $user_dir/logs $user_dir/backup"
    fi
}

# 计算线程配置
calculate_threads() {
    local cpu_cores=$1

    # 搜索线程：CPU核心数 * 1.5
    local search_threads=$(echo "$cpu_cores * 1.5 / 1" | bc)
    # 写入线程：等于CPU核心数
    local write_threads=$cpu_cores
    # k-NN线程：CPU核心数 * 0.4
    local knn_threads=$(echo "$cpu_cores * 0.4 / 1" | bc)
    if [ "$knn_threads" -lt 1 ]; then
        knn_threads=1
    fi

    echo "$search_threads $write_threads $knn_threads"
}

# 计算JVM堆大小
calculate_jvm_heap() {
    local memory_gb=$1

    # JVM堆大小为总内存的40%，但不超过31GB
    local jvm_heap=$(echo "$memory_gb * 0.4 / 1" | bc)

    if [ $jvm_heap -gt 31 ]; then
        jvm_heap=31
    fi

    echo "${jvm_heap}g"
}

# 创建实例
create_instance() {
    local user_name=$1
    local http_port=$2
    local dashboard_port=$3
    local cpu_cores=$4
    local memory_gb=$5

    # 参数验证
    if [ -z "$user_name" ] || [ -z "$http_port" ] || [ -z "$dashboard_port" ] || [ -z "$cpu_cores" ] || [ -z "$memory_gb" ]; then
        log_error "参数不完整"
        show_usage
        exit 1
    fi

    log_step "开始创建用户 ${user_name} 的 OpenSearch 实例..."

    # 检查用户目录是否已存在
    local user_dir="$BASE_DATA_DIR/$user_name"
    if [ -d "$user_dir" ]; then
        log_error "用户 ${user_name} 的实例已存在：$user_dir"
        log_info "如果要重新创建，请先删除：$0 delete $user_name"
        exit 1
    fi

    # 检查端口是否被占用
    log_step "检查端口可用性..."
    local perf_port=$((http_port + 400))

    if ! check_port $http_port; then
        log_error "HTTP 端口 $http_port 已被占用"
        exit 1
    fi

    if ! check_port $perf_port; then
        log_error "性能监控端口 $perf_port 已被占用"
        exit 1
    fi

    if ! check_port $dashboard_port; then
        log_error "Dashboard 端口 $dashboard_port 已被占用"
        exit 1
    fi

    log_info "端口检查通过：HTTP=$http_port, Perf=$perf_port, Dashboard=$dashboard_port"

    # 计算资源配置
    log_step "计算资源配置..."
    read -r search_threads write_threads knn_threads <<< $(calculate_threads $cpu_cores)
    local jvm_heap=$(calculate_jvm_heap $memory_gb)
    local cpu_reserve=$(echo "$cpu_cores / 2" | bc)
    local mem_reserve=$(echo "$memory_gb / 2" | bc)

    log_info "资源配置："
    log_info "  - CPU: ${cpu_cores}核 (预留: ${cpu_reserve}核)"
    log_info "  - 内存: ${memory_gb}GB (预留: ${mem_reserve}GB)"
    log_info "  - JVM堆: ${jvm_heap}"
    log_info "  - 搜索线程: ${search_threads}"
    log_info "  - 写入线程: ${write_threads}"
    log_info "  - k-NN线程: ${knn_threads}"

    # 创建目录结构
    log_step "创建目录结构..."
    if ! mkdir -p "$user_dir"/{data,logs,backup,config}; then
        log_error "创建目录失败：$user_dir"
        log_error "请检查权限或使用环境变量指定目录：OPENSEARCH_BASE_DIR=/your/path $0 create ..."
        exit 1
    fi
    log_info "目录创建成功：$user_dir"

    # 生成配置文件
    log_step "生成配置文件..."

    # 生成 docker-compose.yml
    cat "$TEMPLATE_DIR/docker-compose.template.yml" | \
        sed "s/\${USER_NAME}/$user_name/g" | \
        sed "s/\${HTTP_PORT}/$http_port/g" | \
        sed "s/\${PERF_PORT}/$perf_port/g" | \
        sed "s/\${DASHBOARD_PORT}/$dashboard_port/g" | \
        sed "s/\${DATA_DIR}/$(echo $user_dir | sed 's/\//\\\//g')/g" | \
        sed "s/\${JVM_HEAP_SIZE}/$jvm_heap/g" | \
        sed "s/\${SEARCH_THREAD_SIZE}/$search_threads/g" | \
        sed "s/\${WRITE_THREAD_SIZE}/$write_threads/g" | \
        sed "s/\${KNN_THREAD_SIZE}/$knn_threads/g" | \
        sed "s/\${CPU_LIMIT}/$cpu_cores/g" | \
        sed "s/\${MEM_LIMIT}/${memory_gb}G/g" | \
        sed "s/\${CPU_RESERVE}/$cpu_reserve/g" | \
        sed "s/\${MEM_RESERVE}/${mem_reserve}G/g" | \
        sed "s/\${SECURITY_DISABLED}/true/g" | \
        sed "s/\${ADMIN_PASSWORD}/MyStr0ng!Pass#2024/g" \
        > "$user_dir/docker-compose.yml"

    # 生成 OpenSearch 配置文件（可选）
    cat "$TEMPLATE_DIR/opensearch.yml" | \
        sed "s/\${CLUSTER_NAME}/opensearch-$user_name-cluster/g" | \
        sed "s/\${NODE_NAME}/opensearch-$user_name-node1/g" | \
        sed "s/\${SEARCH_THREAD_SIZE}/$search_threads/g" | \
        sed "s/\${WRITE_THREAD_SIZE}/$write_threads/g" | \
        sed "s/\${KNN_THREAD_SIZE}/$knn_threads/g" | \
        sed "s/\${SECURITY_DISABLED}/true/g" \
        > "$user_dir/config/opensearch.yml"

    # 生成实例信息文件
    cat > "$user_dir/instance.info" << EOF
# OpenSearch 实例信息
USER_NAME=$user_name
HTTP_PORT=$http_port
PERF_PORT=$perf_port
DASHBOARD_PORT=$dashboard_port
CPU_CORES=$cpu_cores
MEMORY_GB=$memory_gb
JVM_HEAP=$jvm_heap
SEARCH_THREADS=$search_threads
WRITE_THREADS=$write_threads
KNN_THREADS=$knn_threads
CREATED_AT=$(date '+%Y-%m-%d %H:%M:%S')
DATA_DIR=$user_dir
EOF

    # 设置目录权限
    log_step "设置目录权限..."
    chmod -R 755 "$user_dir"
    prepare_volume_permissions "$user_dir"

    log_info "${GREEN}实例创建成功！${NC}"
    log_info ""
    log_info "实例信息："
    log_info "  - 用户名: $user_name"
    log_info "  - 数据目录: $user_dir"
    log_info "  - HTTP 端口: $http_port"
    log_info "  - Dashboard 端口: $dashboard_port"
    log_info "  - 配置文件: $user_dir/docker-compose.yml"
    log_info ""
    log_info "启动实例："
    log_info "  $0 start $user_name"
    log_info ""
    log_info "访问地址："
    log_info "  - OpenSearch: http://localhost:$http_port"
    log_info "  - Dashboard:  http://localhost:$dashboard_port"
}

# 拉取镜像
pull_images() {
    local user_name=$1
    configure_docker_images

    if [ -n "$user_name" ]; then
        # 拉取指定用户实例的镜像
        local user_dir="$BASE_DATA_DIR/$user_name"

        if [ ! -d "$user_dir" ]; then
            log_error "用户 ${user_name} 的实例不存在"
            exit 1
        fi

        log_step "拉取用户 ${user_name} 的 Docker 镜像..."
        repair_instance_config "$user_name"
        cd "$user_dir"
        docker-compose pull
    else
        # 拉取默认镜像
        log_step "拉取 OpenSearch Docker 镜像..."
        log_info "OpenSearch 镜像: $OPENSEARCH_IMAGE"
        log_info "Dashboards 镜像: $OPENSEARCH_DASHBOARDS_IMAGE"
        docker pull "$OPENSEARCH_IMAGE"
        docker pull "$OPENSEARCH_DASHBOARDS_IMAGE"
    fi

    log_info "${GREEN}镜像拉取完成！${NC}"
}

# 启动实例
start_instance() {
    local user_name=$1
    local user_dir="$BASE_DATA_DIR/$user_name"

    if [ ! -d "$user_dir" ]; then
        log_error "用户 ${user_name} 的实例不存在"
        exit 1
    fi

    log_step "启动用户 ${user_name} 的 OpenSearch 实例..."
    configure_docker_images
    repair_instance_config "$user_name"
    prepare_volume_permissions "$user_dir"

    cd "$user_dir"

    # 检查镜像是否存在，如果不存在则拉取
    if ! docker images --format "{{.Repository}}:{{.Tag}}" | grep -Fxq "$OPENSEARCH_IMAGE"; then
        log_info "本地未找到 OpenSearch 镜像 ${OPENSEARCH_IMAGE}，开始拉取..."
        docker-compose pull opensearch
    fi

    if ! docker images --format "{{.Repository}}:{{.Tag}}" | grep -Fxq "$OPENSEARCH_DASHBOARDS_IMAGE"; then
        log_info "本地未找到 OpenSearch Dashboards 镜像 ${OPENSEARCH_DASHBOARDS_IMAGE}，开始拉取..."
        docker-compose pull opensearch-dashboards
    fi

    docker-compose up -d

    log_info "${GREEN}实例启动成功！${NC}"
    log_info ""
    log_info "等待服务就绪（约 30-60 秒）..."
    log_info "查看启动日志："
    log_info "  $0 logs $user_name"
    log_info ""
    log_info "查看状态："
    log_info "  $0 status $user_name"
}

# 修复旧实例中的非法配置。
# 早期小规格实例可能生成 knn.algo_param.index_thread_qty=0，
# OpenSearch k-NN 插件要求该值必须位于 1..32，否则节点启动后立即退出。
repair_instance_config() {
    local user_name=$1
    local user_dir="$BASE_DATA_DIR/$user_name"
    local compose_file="$user_dir/docker-compose.yml"
    local info_file="$user_dir/instance.info"

    if [ -f "$compose_file" ] && grep -Eq "image: opensearchproject/opensearch(:latest)?$|image: opensearchproject/opensearch-dashboards(:latest)?$" "$compose_file"; then
        log_warn "检测到旧版固定镜像配置，自动改为可通过环境变量覆盖: $compose_file"
        local tmp_file="${compose_file}.tmp.$$"
        sed \
            -e 's|^\([[:space:]]*image: \)opensearchproject/opensearch$|\1${OPENSEARCH_IMAGE:-opensearchproject/opensearch:latest}|g' \
            -e 's|image: opensearchproject/opensearch:latest|image: ${OPENSEARCH_IMAGE:-opensearchproject/opensearch:latest}|g' \
            -e 's|^\([[:space:]]*image: \)opensearchproject/opensearch-dashboards$|\1${OPENSEARCH_DASHBOARDS_IMAGE:-opensearchproject/opensearch-dashboards:latest}|g' \
            -e 's|image: opensearchproject/opensearch-dashboards:latest|image: ${OPENSEARCH_DASHBOARDS_IMAGE:-opensearchproject/opensearch-dashboards:latest}|g' \
            "$compose_file" > "$tmp_file"
        mv "$tmp_file" "$compose_file"
    fi

    if [ -f "$compose_file" ] && grep -q "knn.algo_param.index_thread_qty=0" "$compose_file"; then
        log_warn "检测到非法 k-NN 线程配置，自动修复为 1: $compose_file"
        sed -i 's/knn\.algo_param\.index_thread_qty=0/knn.algo_param.index_thread_qty=1/g' "$compose_file"
    fi

    if [ -f "$info_file" ] && grep -q "^KNN_THREADS=0$" "$info_file"; then
        sed -i 's/^KNN_THREADS=0$/KNN_THREADS=1/g' "$info_file"
    fi
}

# 停止实例
stop_instance() {
    local user_name=$1
    local user_dir="$BASE_DATA_DIR/$user_name"

    if [ ! -d "$user_dir" ]; then
        log_error "用户 ${user_name} 的实例不存在"
        exit 1
    fi

    log_step "停止用户 ${user_name} 的 OpenSearch 实例..."

    cd "$user_dir"
    docker-compose down

    log_info "${GREEN}实例已停止${NC}"
}

# 重启实例
restart_instance() {
    local user_name=$1

    log_step "重启用户 ${user_name} 的 OpenSearch 实例..."
    stop_instance "$user_name"
    sleep 3
    start_instance "$user_name"
}

# 删除实例
delete_instance() {
    local user_name=$1
    local keep_data=$2
    local user_dir="$BASE_DATA_DIR/$user_name"

    if [ ! -d "$user_dir" ]; then
        log_error "用户 ${user_name} 的实例不存在"
        exit 1
    fi

    log_warn "即将删除用户 ${user_name} 的 OpenSearch 实例"
    log_warn "数据目录: $user_dir"

    read -p "确认删除？(yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        log_info "取消删除"
        exit 0
    fi

    log_step "停止并删除容器..."
    cd "$user_dir"
    docker-compose down -v

    if [ "$keep_data" == "--keep-data" ]; then
        log_info "保留数据目录: $user_dir"
        log_info "只删除配置文件..."
        rm -f "$user_dir/docker-compose.yml"
        rm -f "$user_dir/instance.info"
        rm -rf "$user_dir/config"
    else
        log_step "删除数据目录..."
        cd "$BASE_DATA_DIR"
        if ! rm -rf "$user_dir" 2>/dev/null; then
            log_warn "普通删除失败（容器数据文件由 uid 1000 拥有），尝试 sudo rm -rf ..."
            sudo rm -rf "$user_dir"
        fi
        log_info "${GREEN}实例已完全删除${NC}"
    fi
}

# 查看状态
show_status() {
    local user_name=$1

    if [ -n "$user_name" ]; then
        # 显示指定用户的状态
        local user_dir="$BASE_DATA_DIR/$user_name"

        if [ ! -d "$user_dir" ]; then
            log_error "用户 ${user_name} 的实例不存在"
            exit 1
        fi

        log_info "用户 ${user_name} 的实例状态："
        log_info ""

        cd "$user_dir"
        docker-compose ps

        # 显示详细信息
        if [ -f "$user_dir/instance.info" ]; then
            log_info ""
            log_info "实例配置："
            cat "$user_dir/instance.info" | grep -E "HTTP_PORT|DASHBOARD_PORT|CPU_CORES|MEMORY_GB|JVM_HEAP|CREATED_AT" | sed 's/^/  /'
        fi

        # 尝试获取集群健康状态
        if docker ps | grep -q "opensearch-$user_name"; then
            log_info ""
            log_info "集群健康状态："

            source "$user_dir/instance.info"
            sleep 2
            curl -s "http://localhost:$HTTP_PORT/_cluster/health?pretty" 2>/dev/null || log_warn "  无法连接到 OpenSearch"
        fi
    else
        # 显示所有实例的状态
        log_info "所有 OpenSearch 实例状态："
        log_info ""

        docker ps --filter "name=opensearch-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | head -n 20

        log_info ""
        log_info "使用 '$0 status <用户名>' 查看详细信息"
    fi
}

# 查看日志
show_logs() {
    local user_name=$1
    local lines=${2:-50}
    local user_dir="$BASE_DATA_DIR/$user_name"

    if [ ! -d "$user_dir" ]; then
        log_error "用户 ${user_name} 的实例不存在"
        exit 1
    fi

    log_info "查看用户 ${user_name} 的日志（最近 ${lines} 行）："
    log_info ""

    cd "$user_dir"
    docker-compose logs --tail=$lines -f opensearch
}

# 列出所有实例
list_instances() {
    log_info "已创建的 OpenSearch 实例："
    log_info ""

    if [ ! -d "$BASE_DATA_DIR" ]; then
        log_warn "数据目录不存在: $BASE_DATA_DIR"
        return
    fi

    printf "%-15s %-10s %-15s %-15s %-10s %-10s %-20s\n" "用户名" "状态" "HTTP端口" "Dashboard端口" "CPU" "内存" "创建时间"
    echo "--------------------------------------------------------------------------------------------------------"

    for user_dir in "$BASE_DATA_DIR"/*/; do
        if [ -f "$user_dir/instance.info" ]; then
            source "$user_dir/instance.info"

            # 检查容器状态
            if docker ps | grep -q "opensearch-$USER_NAME"; then
                status="${GREEN}运行中${NC}"
            elif docker ps -a | grep -q "opensearch-$USER_NAME"; then
                status="${YELLOW}已停止${NC}"
            else
                status="${RED}未启动${NC}"
            fi

            printf "%-15s %-18b %-15s %-15s %-10s %-10s %-20s\n" \
                "$USER_NAME" "$status" "$HTTP_PORT" "$DASHBOARD_PORT" \
                "${CPU_CORES}核" "${MEMORY_GB}GB" "$CREATED_AT"
        fi
    done

    log_info ""
    log_info "使用 '$0 info <用户名>' 查看详细信息"
}

# 显示实例详细信息
show_info() {
    local user_name=$1
    local user_dir="$BASE_DATA_DIR/$user_name"

    if [ ! -d "$user_dir" ]; then
        log_error "用户 ${user_name} 的实例不存在"
        exit 1
    fi

    if [ ! -f "$user_dir/instance.info" ]; then
        log_error "实例信息文件不存在"
        exit 1
    fi

    source "$user_dir/instance.info"

    log_info "用户 ${user_name} 的实例详细信息："
    log_info ""
    log_info "${BLUE}基本信息：${NC}"
    log_info "  用户名:         $USER_NAME"
    log_info "  数据目录:       $DATA_DIR"
    log_info "  创建时间:       $CREATED_AT"
    log_info ""
    log_info "${BLUE}网络配置：${NC}"
    log_info "  HTTP 端口:      $HTTP_PORT"
    log_info "  性能监控端口:   $PERF_PORT"
    log_info "  Dashboard 端口: $DASHBOARD_PORT"
    log_info ""
    log_info "${BLUE}资源配置：${NC}"
    log_info "  CPU 核心数:     ${CPU_CORES}核"
    log_info "  内存大小:       ${MEMORY_GB}GB"
    log_info "  JVM 堆大小:     $JVM_HEAP"
    log_info ""
    log_info "${BLUE}线程池配置：${NC}"
    log_info "  搜索线程:       $SEARCH_THREADS"
    log_info "  写入线程:       $WRITE_THREADS"
    log_info "  k-NN 线程:      $KNN_THREADS"
    log_info ""
    log_info "${BLUE}访问地址：${NC}"
    log_info "  OpenSearch:     http://localhost:$HTTP_PORT"
    log_info "  Dashboard:      http://localhost:$DASHBOARD_PORT"
    log_info "  健康检查:       curl http://localhost:$HTTP_PORT/_cluster/health"
    log_info ""
    log_info "${BLUE}常用命令：${NC}"
    log_info "  启动:           $0 start $user_name"
    log_info "  停止:           $0 stop $user_name"
    log_info "  重启:           $0 restart $user_name"
    log_info "  查看日志:       $0 logs $user_name"
    log_info "  查看状态:       $0 status $user_name"
}

# 主函数
main() {
    local command=$1

    case "$command" in
        create)
            create_instance "$2" "$3" "$4" "$5" "$6"
            ;;
        start)
            start_instance "$2"
            ;;
        stop)
            stop_instance "$2"
            ;;
        restart)
            restart_instance "$2"
            ;;
        pull)
            pull_images "$2"
            ;;
        delete)
            delete_instance "$2" "$3"
            ;;
        status)
            show_status "$2"
            ;;
        logs)
            show_logs "$2" "$3"
            ;;
        list)
            list_instances
            ;;
        info)
            show_info "$2"
            ;;
        help|--help|-h|"")
            show_usage
            ;;
        *)
            log_error "未知命令: $command"
            show_usage
            exit 1
            ;;
    esac
}

# 执行主函数
main "$@"
