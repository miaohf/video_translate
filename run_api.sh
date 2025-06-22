#!/bin/bash

# 视频翻译API服务器启动脚本

echo "🚀 启动视频翻译API服务器..."

# 检查Python环境
if ! command -v python &> /dev/null; then
    echo "❌ Python未安装，请先安装Python"
    exit 1
fi

# 检查依赖
echo "📦 检查依赖..."
if [ ! -f "requirements_api.txt" ]; then
    echo "❌ 找不到requirements_api.txt文件"
    exit 1
fi

# 安装依赖（如果需要）
echo "📦 安装API依赖..."
pip install -r requirements_api.txt

# 检查配置文件
if [ ! -f ".env" ] && [ -f "config.env" ]; then
    echo "📄 复制配置文件..."
    cp config.env .env
fi

if [ ! -f ".env" ]; then
    echo "⚠️  未找到 .env 配置文件，使用默认配置"
else
    echo "✅ 找到配置文件: .env"
fi

# 创建必要的目录
mkdir -p temp
mkdir -p output

echo "📡 服务器配置: 使用配置文件中的设置"

# 启动服务器
echo "🔥 启动服务器..."
python start_api_server.py 