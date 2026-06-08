#!/bin/bash

###############################################################################
# OpenSearch 快速配置脚本
# 
# 此脚本提供了一些常用配置的快捷命令
# 根据你的需求选择合适的配置
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_SCRIPT="$SCRIPT_DIR/deploy.sh"

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}OpenSearch 快速配置向导${NC}"
echo "================================"
echo ""

# 显示配置选项
echo -e "${YELLOW}请选择配置方案：${NC}"
echo ""
echo "1. 小型配置（开发/测试）      - 4核 / 12GB"
echo "2. 中型配置（小规模生产）     - 6核 / 20GB"
echo "3. 大型配置（生产环境）       - 12核 / 40GB"
echo "4. 超大配置（高性能需求）     - 18核 / 66GB"
echo "5. 自定义配置"
echo ""
read -p "请输入选项 (1-5): " choice

case $choice in
    1)
        CPU=4
        MEM=12
        CONFIG_NAME="小型"
        ;;
    2)
        CPU=6
        MEM=20
        CONFIG_NAME="中型"
        ;;
    3)
        CPU=12
        MEM=40
        CONFIG_NAME="大型"
        ;;
    4)
        CPU=18
        MEM=66
        CONFIG_NAME="超大"
        ;;
    5)
        read -p "请输入 CPU 核心数: " CPU
        read -p "请输入内存大小(GB): " MEM
        CONFIG_NAME="自定义"
        ;;
    *)
        echo "无效选项"
        exit 1
        ;;
esac

echo ""
echo -e "${YELLOW}配置信息：${NC}"
echo "  方案: $CONFIG_NAME 配置"
echo "  CPU: ${CPU}核"
echo "  内存: ${MEM}GB"
echo ""

# 输入用户名
read -p "请输入用户名（实例名称）: " USERNAME

# 建议端口（从脚本目录下的 opensearch/ 查找现有实例）
BASE_DIR="${OPENSEARCH_BASE_DIR:-$SCRIPT_DIR/opensearch}"
DEFAULT_HTTP=$((9200 + $(ls -1d $BASE_DIR/*/ 2>/dev/null | wc -l) + 1))
DEFAULT_DASH=$((5601 + $(ls -1d $BASE_DIR/*/ 2>/dev/null | wc -l) + 1))

echo ""
echo -e "${YELLOW}端口配置：${NC}"
read -p "HTTP 端口 [默认: $DEFAULT_HTTP]: " HTTP_PORT
HTTP_PORT=${HTTP_PORT:-$DEFAULT_HTTP}

read -p "Dashboard 端口 [默认: $DEFAULT_DASH]: " DASH_PORT
DASH_PORT=${DASH_PORT:-$DEFAULT_DASH}

echo ""
echo -e "${YELLOW}即将创建实例：${NC}"
echo "  用户名: $USERNAME"
echo "  配置: $CONFIG_NAME ($CPU 核 / $MEM GB)"
echo "  HTTP 端口: $HTTP_PORT"
echo "  Dashboard 端口: $DASH_PORT"
echo ""

read -p "确认创建？(yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "取消创建"
    exit 0
fi

echo ""
echo -e "${GREEN}开始创建实例...${NC}"
echo ""

# 创建实例
if ! $DEPLOY_SCRIPT create $USERNAME $HTTP_PORT $DASH_PORT $CPU $MEM; then
    echo ""
    echo -e "${RED}实例创建失败！${NC}"
    echo "请检查错误信息并修复问题后重试。"
    exit 1
fi

# 询问是否立即启动
echo ""
read -p "是否立即启动实例？(yes/no): " start_now
if [ "$start_now" == "yes" ]; then
    echo ""
    $DEPLOY_SCRIPT start $USERNAME
    
    echo ""
    echo -e "${GREEN}实例已启动！${NC}"
    echo ""
    echo -e "${BLUE}访问地址：${NC}"
    echo "  OpenSearch:  http://localhost:$HTTP_PORT"
    echo "  Dashboard:   http://localhost:$DASH_PORT"
    echo ""
    echo -e "${BLUE}常用命令：${NC}"
    echo "  查看状态:    $DEPLOY_SCRIPT status $USERNAME"
    echo "  查看日志:    $DEPLOY_SCRIPT logs $USERNAME"
    echo "  停止实例:    $DEPLOY_SCRIPT stop $USERNAME"
    echo "  删除实例:    $DEPLOY_SCRIPT delete $USERNAME"
fi
