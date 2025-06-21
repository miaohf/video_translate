"""
示例配置文件，用于说明配置项
请复制此文件为 config.py 并填入实际的配置值
"""

# API 配置
STT_SERVER_URL = "http://127.0.0.1:8001/api/generate"  # 语音识别服务器地址
TTS_SERVER_URL = "http://127.0.0.1:8000/api/generate"  # 语音合成服务器地址

# 翻译服务配置
TRANSLATION_PROVIDER = "ollama"  # 翻译提供商: "ollama" 或 "deepseek"

# Ollama 配置 (当 TRANSLATION_PROVIDER = "ollama" 时使用)
OLLAMA_SERVER_URL = "http://127.0.0.1:11434"  # Ollama 服务器地址
OLLAMA_MODEL = "qwen3:7b"  # 使用的模型名称

# DeepSeek API 配置 (当 TRANSLATION_PROVIDER = "deepseek" 时使用)
DEEPSEEK_API_URL = "https://api.deepseek.com"  # DeepSeek API 地址
DEEPSEEK_API_KEY = "your-deepseek-api-key-here"  # DeepSeek API 密钥
DEEPSEEK_MODEL = "deepseek-chat"  # DeepSeek 模型名称

# 音频配置
AUDIO_SAMPLE_RATE = 16000  # 音频采样率
AUDIO_CHANNELS = 1  # 音频声道数

# 临时文件配置
TEMP_DIR = "temp"  # 临时文件目录 