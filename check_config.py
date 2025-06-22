#!/usr/bin/env python3
"""
配置检查脚本
"""

import os
import sys
import requests
from pathlib import Path

def check_config():
    """检查当前配置"""
    print("🔍 当前配置检查")
    print("=" * 50)
    
    # 检查环境变量文件
    print("\n📁 环境变量文件:")
    config_files = ['.env', 'config.env']
    for file in config_files:
        if Path(file).exists():
            print(f"  ✅ {file} 存在")
        else:
            print(f"  ❌ {file} 不存在")
    
    # 加载配置
    try:
        from config_manager import config
        print("\n⚙️ 配置管理器加载状态:")
        print(f"  ✅ config_manager 加载成功")
        
        print(f"\n🌐 服务器地址配置:")
        print(f"  - 翻译API: {config.api_base_url} (端口: {config.api_port})")
        print(f"  - STT服务器: {config.stt_server_url}")
        print(f"  - TTS服务器: {config.tts_server_url}")
        
    except Exception as e:
        print(f"  ❌ 配置管理器加载失败: {e}")
    
    # 检查旧配置文件
    try:
        from config import settings
        print(f"\n🔧 传统配置文件:")
        print(f"  - STT服务器: {settings.STT_SERVER_URL}")
        print(f"  - TTS服务器: {settings.TTS_SERVER_URL}")
        print(f"  - OLLAMA模型: {settings.OLLAMA_MODEL}")
        print(f"  - OLLAMA API: {settings.OLLAMA_API_URL}")
        
    except Exception as e:
        print(f"  ❌ 传统配置加载失败: {e}")
    
    # 检查环境变量
    print(f"\n🌍 关键环境变量:")
    env_vars = [
        'STT_SERVER_URL', 'TTS_SERVER_URL', 'OLLAMA_MODEL', 
        'API_PORT', 'API_BASE_URL'
    ]
    for var in env_vars:
        value = os.getenv(var)
        if value:
            print(f"  - {var}: {value}")
        else:
            print(f"  - {var}: 未设置")
    
    # 检查服务器连通性
    print(f"\n🔗 服务器连通性检查:")
    
    # 检查翻译API
    try:
        api_url = os.getenv('API_BASE_URL', 'http://localhost:9000')
        response = requests.get(f"{api_url}/health", timeout=5)
        if response.status_code == 200:
            print(f"  ✅ 翻译API ({api_url}) - 运行正常")
        else:
            print(f"  ⚠️ 翻译API ({api_url}) - 状态码: {response.status_code}")
    except Exception as e:
        print(f"  ❌ 翻译API ({api_url}) - 连接失败: {e}")
    
    # 检查STT服务器
    try:
        stt_url = os.getenv('STT_SERVER_URL', 'http://localhost:8001')
        response = requests.get(f"{stt_url}/", timeout=5)
        print(f"  ✅ STT服务器 ({stt_url}) - 可访问")
    except Exception as e:
        print(f"  ❌ STT服务器 ({stt_url}) - 连接失败: {e}")
    
    # 检查TTS服务器
    try:
        tts_url = os.getenv('TTS_SERVER_URL', 'http://localhost:8002')
        response = requests.get(f"{tts_url}/", timeout=5)
        print(f"  ✅ TTS服务器 ({tts_url}) - 可访问")
    except Exception as e:
        print(f"  ❌ TTS服务器 ({tts_url}) - 连接失败: {e}")
    
    # 检查OLLAMA服务器
    try:
        ollama_url = os.getenv('OLLAMA_SERVER_URL', 'http://localhost:11434')
        response = requests.get(f"{ollama_url}/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json()
            model_names = [m['name'] for m in models.get('models', [])]
            print(f"  ✅ OLLAMA服务器 ({ollama_url}) - 运行正常")
            print(f"    可用模型: {', '.join(model_names) if model_names else '无'}")
            
            # 检查配置的模型是否存在
            configured_model = os.getenv('OLLAMA_MODEL', 'qwen3:7b')
            if configured_model in model_names:
                print(f"    ✅ 配置模型 '{configured_model}' 存在")
            else:
                print(f"    ❌ 配置模型 '{configured_model}' 不存在")
                if model_names:
                    print(f"    💡 建议使用: {model_names[0]}")
        else:
            print(f"  ⚠️ OLLAMA服务器 ({ollama_url}) - 状态码: {response.status_code}")
    except Exception as e:
        print(f"  ❌ OLLAMA服务器 ({ollama_url}) - 连接失败: {e}")
    
    print(f"\n✨ 配置检查完成")

if __name__ == "__main__":
    check_config() 