#!/home/miaohf/Documents/mycode/video_translate/.venv/bin/python
"""
启动翻译API服务器 - 生产环境版本
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
    
    print(f"🚀 启动翻译API服务器 (生产模式)...")
    print(f"📡 监听地址: http://{settings.API_HOST}:{settings.API_PORT}")
    print(f"📚 API文档: http://{settings.API_HOST}:{settings.API_PORT}/docs")
    print(f"⚡ 工作进程: {settings.API_WORKERS}")
    print(f"🔧 配置文件: 已加载环境变量配置")
    
    # 启动服务器 - 生产模式
    uvicorn.run(
        "api_server:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        workers=settings.API_WORKERS,
        reload=False,  # 生产模式不自动重载
        access_log=True
    )

if __name__ == "__main__":
    main()
