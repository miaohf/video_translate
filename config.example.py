"""
示例配置文件，用于说明配置项
请复制此文件为 config.py 并填入实际的配置值
"""

# API 配置
STT_SERVER_URL = "http://127.0.0.1:8001/api/generate"  # 语音识别服务器地址
TTS_SERVER_URL = "http://127.0.0.1:8000/api/generate"  # 语音合成服务器地址

# 模型配置
MODEL_NAME = "qwen3:8b"  # 使用的模型名称

# 音频配置
AUDIO_SAMPLE_RATE = 16000  # 音频采样率
AUDIO_CHANNELS = 1  # 音频声道数

# 临时文件配置
TEMP_DIR = "temp"  # 临时文件目录 