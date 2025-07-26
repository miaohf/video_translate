#!/usr/bin/env python3
"""
启动翻译API服务器
"""

import uvicorn
import os
import logging
from pathlib import Path
from config import settings

def main():
    """启动API服务器"""
    # 确保必要的目录存在
    Path(settings.TEMP_DIR).mkdir(exist_ok=True)
    Path(settings.OUTPUT_DIR).mkdir(exist_ok=True)
    
    print(f"🚀 启动翻译API服务器...")
    print(f"📡 监听地址: http://{settings.API_HOST}:{settings.API_PORT}")
    print(f"📚 API文档: http://{settings.API_HOST}:{settings.API_PORT}/docs")
    print(f"⚡ 工作进程: {settings.API_WORKERS}")
    print(f"🔧 配置文件: 已加载环境变量配置")
    
    # 启动服务器
    uvicorn.run(
        "app:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        workers=settings.API_WORKERS,
        reload=True,  # 开发模式下自动重载
        access_log=True
    )

if __name__ == "__main__":
    main() 