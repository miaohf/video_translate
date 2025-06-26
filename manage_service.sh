#!/bin/bash

# 视频翻译API服务器 - 服务管理脚本

SERVICE_NAME="video-translate-api"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# 显示使用说明
show_usage() {
    echo "🔧 视频翻译API服务器管理脚本"
    echo ""
    echo "用法: $0 {start|stop|restart|status|logs|install|uninstall|help}"
    echo ""
    echo "命令说明:"
    echo "  start     - 启动服务"
    echo "  stop      - 停止服务"
    echo "  restart   - 重启服务"
    echo "  status    - 查看服务状态"
    echo "  logs      - 查看服务日志 (实时)"
    echo "  logs-all  - 查看所有日志"
    echo "  install   - 安装systemd服务"
    echo "  uninstall - 卸载systemd服务"
    echo "  help      - 显示此帮助信息"
    echo ""
}

# 检查服务是否存在
check_service_exists() {
    if ! systemctl list-unit-files | grep -q "$SERVICE_NAME"; then
        print_error "服务未安装，请先运行 '$0 install'"
        exit 1
    fi
}

# 启动服务
start_service() {
    check_service_exists
    print_info "启动服务..."
    sudo systemctl start "$SERVICE_NAME"
    if [ $? -eq 0 ]; then
        print_success "服务启动成功"
        sleep 2
        sudo systemctl status "$SERVICE_NAME" --no-pager -l
    else
        print_error "服务启动失败"
        exit 1
    fi
}

# 停止服务
stop_service() {
    check_service_exists
    print_info "停止服务..."
    sudo systemctl stop "$SERVICE_NAME"
    if [ $? -eq 0 ]; then
        print_success "服务停止成功"
    else
        print_error "服务停止失败"
        exit 1
    fi
}

# 重启服务
restart_service() {
    check_service_exists
    print_info "重启服务..."
    sudo systemctl restart "$SERVICE_NAME"
    if [ $? -eq 0 ]; then
        print_success "服务重启成功"
        sleep 2
        sudo systemctl status "$SERVICE_NAME" --no-pager -l
    else
        print_error "服务重启失败"
        exit 1
    fi
}

# 查看服务状态
show_status() {
    check_service_exists
    print_info "服务状态:"
    sudo systemctl status "$SERVICE_NAME" --no-pager -l
}

# 查看服务日志
show_logs() {
    check_service_exists
    print_info "查看服务日志 (按 Ctrl+C 退出):"
    sudo journalctl -u "$SERVICE_NAME" -f
}

# 查看所有日志
show_all_logs() {
    check_service_exists
    print_info "所有服务日志:"
    sudo journalctl -u "$SERVICE_NAME" --no-pager
}

# 安装服务
install_service() {
    print_info "安装systemd服务..."
    ./setup_systemd_service.sh
}

# 卸载服务
uninstall_service() {
    print_warning "这将卸载systemd服务"
    read -p "确认卸载? [y/N]: " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_info "停止并禁用服务..."
        sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true
        sudo systemctl disable "$SERVICE_NAME" 2>/dev/null || true
        
        print_info "删除服务文件..."
        sudo rm -f "/etc/systemd/system/$SERVICE_NAME.service"
        
        print_info "重新加载systemd配置..."
        sudo systemctl daemon-reload
        
        print_success "服务卸载完成"
    else
        print_info "取消卸载"
    fi
}

# 主逻辑
case "$1" in
    start)
        start_service
        ;;
    stop)
        stop_service
        ;;
    restart)
        restart_service
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs
        ;;
    logs-all)
        show_all_logs
        ;;
    install)
        install_service
        ;;
    uninstall)
        uninstall_service
        ;;
    help|--help|-h)
        show_usage
        ;;
    *)
        show_usage
        exit 1
        ;;
esac

exit 0 