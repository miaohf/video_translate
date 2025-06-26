#!/bin/bash

# 视频翻译API服务器 - systemd服务安装脚本

set -e

SERVICE_NAME="video-translate-api"
SERVICE_FILE="${SERVICE_NAME}.service"
SYSTEMD_DIR="/etc/systemd/system"

echo "🔧 安装视频翻译API服务..."

# 检查服务文件是否存在
if [ ! -f "$SERVICE_FILE" ]; then
    echo "❌ 错误: $SERVICE_FILE 文件不存在"
    echo "请确保你在项目根目录下运行此脚本"
    exit 1
fi

# 复制服务文件到systemd目录
echo "📂 复制服务文件到 $SYSTEMD_DIR..."
sudo cp "$SERVICE_FILE" "$SYSTEMD_DIR/"

# 重新加载systemd配置
echo "🔄 重新加载systemd配置..."
sudo systemctl daemon-reload

# 启用服务
echo "✅ 启用服务..."
sudo systemctl enable "$SERVICE_NAME"

echo ""
echo "🎉 服务安装完成!"
echo ""
echo "📋 常用命令:"
echo "  启动服务: sudo systemctl start $SERVICE_NAME"
echo "  停止服务: sudo systemctl stop $SERVICE_NAME"
echo "  重启服务: sudo systemctl restart $SERVICE_NAME"
echo "  查看状态: sudo systemctl status $SERVICE_NAME"
echo "  查看日志: sudo journalctl -u $SERVICE_NAME -f"
echo ""

# 询问是否立即启动服务
read -p "🚀 是否立即启动服务? [y/N]: " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "启动服务..."
    sudo systemctl start "$SERVICE_NAME"
    echo "✅ 服务已启动"
    
    # 等待一下然后显示状态
    sleep 2
    echo ""
    echo "📊 服务状态:"
    sudo systemctl status "$SERVICE_NAME" --no-pager -l
fi

echo ""
echo "🔗 访问地址: http://localhost:9000"
echo "📚 API文档: http://localhost:9000/docs" 