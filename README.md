# 视频翻译程序

这个程序实现了英文访谈视频的自动翻译功能，包括以下特性：

1. 使用 STT (Speech-to-Text) 生成英文字幕
2. 通过 Ollama 将字幕翻译成中文
3. 识别语音角色并分析视频中的说话者数量
4. 使用 STT zero-shot + 语音角色提示音 + 字幕文本生成角色的中文语音
5. 根据字幕时间戳合成对应的中文访谈语音
6. 智能音频混合：在播放中文语音时降低原音频音量，中文语音静音时恢复原音频音量

## 系统架构

程序分为服务器端和客户端两个部分：

- 服务器端（GPU 主机）：
  - 运行 STT 服务（Whisper）
  - 运行翻译服务（Ollama）
  - 运行 TTS 服务（OpenAI）

- 客户端：
  - 处理视频文件
  - 调用服务器端 API
  - 处理音频混合和视频合成

## 安装依赖

### 服务器端（GPU 主机）

```bash
# 安装系统依赖
sudo apt-get update
sudo apt-get install ffmpeg

# 安装 Python 依赖
pip install -r requirements.txt
```

### 客户端

```bash
# 安装系统依赖
sudo apt-get update
sudo apt-get install ffmpeg

# 安装 Python 依赖
pip install -r requirements.txt
```

## 使用方法

### 1. 启动服务器

在 GPU 主机（192.168.31.80）上运行：

```bash
python server.py
```

服务器将在 5000 端口启动。

### 2. 运行客户端

在本地机器上运行：

```bash
python client.py --input_video path/to/your/video.mp4 --output_video path/to/output/video.mp4
```

## 配置说明

1. 服务器端配置：
   - 在服务器端创建 `.env` 文件，添加 OpenAI API 密钥：
     ```
     OPENAI_API_KEY=your_api_key_here
     ```
   - 确保 Ollama 服务已启动并运行在默认端口（11434）

2. 客户端配置：
   - 默认连接到 `http://192.168.31.80:5000`
   - 可以通过 `--server_url` 参数修改服务器地址

## 注意事项

- 确保输入视频文件格式为 MP4
- 程序需要足够的磁盘空间用于临时文件存储
- 服务器端需要 GPU 支持
- 确保网络连接稳定，因为需要传输音频文件 