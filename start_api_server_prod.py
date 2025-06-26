#!/home/miaohf/Documents/mycode/video_translate/.venv/bin/python
"""
启动翻译API服务器 - 生产环境版本
"""

import uvicorn
import os
import logging
from pathlib import Path
from config_manager import config

def main():
    """启动API服务器"""
    # 确保必要的目录存在
    Path(config.temp_dir).mkdir(exist_ok=True)
    Path(config.output_dir).mkdir(exist_ok=True)
    
    print(f"🚀 启动翻译API服务器 (生产模式)...")
    print(f"📡 监听地址: http://{config.api_host}:{config.api_port}")
    print(f"📚 API文档: http://{config.api_host}:{config.api_port}/docs")
    print(f"⚡ 工作进程: {config.api_workers}")
    print(f"🔧 配置文件: 已加载环境变量配置")
    
    # 启动服务器 - 生产模式
    uvicorn.run(
        "api_server:app",
        host=config.api_host,
        port=config.api_port,
        workers=config.api_workers,
        reload=False,  # 生产模式不自动重载
        access_log=True
    )

if __name__ == "__main__":
    main()
