# 视频翻译程序

## 🎬 项目简介

英文访谈视频自动翻译系统，支持语音识别、智能翻译、语音合成和音频混合。

## ✨ 主要功能

- 🎵 自动生成英文字幕 (STT)
- 🌍 智能翻译成中文 (支持 Ollama 和 DeepSeek)
- 🎤 说话人识别和角色分离
- 🗣️ 中文语音合成 (TTS)
- 🔊 智能音频混合

## 🚀 快速开始

### 安装依赖

```bash
# 安装系统依赖
sudo apt-get install ffmpeg

# 安装Python依赖
pip install -r requirements.txt
```

### 配置环境

复制配置文件并修改：
```bash
cp config.example.py config.py
```

配置服务器地址：
- STT服务器: `STT_SERVER_URL`
- TTS服务器: `TTS_SERVER_URL`
- 翻译服务: 支持 Ollama 和 DeepSeek，详见 [翻译服务配置说明](TRANSLATION_PROVIDERS.md)

### 使用方法

```bash
python main.py --input_video path/to/video.mp4
```

## 📁 项目结构

```
video_translate/
├── main.py              # 程序入口
├── core/                # 核心业务逻辑
├── audio/               # 音频处理
├── utils/               # 工具模块
├── processors/          # 处理器
├── services/            # 服务接口
├── server/              # 服务器端
└── config.py            # 配置文件
```

## 🛠️ 技术栈

- **Python 3.12+**: 主要开发语言
- **Whisper**: 语音识别
- **Ollama/DeepSeek**: 大语言模型翻译
- **TTS**: 语音合成
- **FFmpeg**: 音视频处理

## 📋 系统要求

- Python 3.12+
- FFmpeg
- 4GB+ 内存
- GPU (推荐)

## 🔧 服务器配置

### STT服务器
```bash
python server/stt_server.py
```

### TTS服务器
```bash
python server/indextts_server.py
```

### Ollama服务
确保Ollama服务运行在11434端口

## �� 许可证

MIT License 