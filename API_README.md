# 视频翻译API服务

基于FastAPI的视频翻译HTTP服务，支持异步任务处理、状态跟踪和回调通知。

## 🚀 快速开始

### 1. 安装依赖

```bash
# 安装API服务依赖
pip install -r requirements_api.txt

# 安装原有项目依赖（如果还没安装）
pip install -r requirements.txt
```

### 1.5. 配置环境变量

```bash
# 复制配置文件模板
cp config.env .env

# 或者直接编辑配置文件
vim .env
```

配置文件说明：
- **config.env**: 配置文件模板，包含所有可用的配置项
- **.env**: 实际使用的配置文件（优先级最高）
- 如果没有.env文件，系统会使用默认配置

### 2. 启动服务器

```bash
# 方法1: 使用启动脚本（推荐）
python start_api_server.py

# 方法2: 使用shell脚本（包含环境检查）
./run_api.sh

# 方法3: 直接使用uvicorn
uvicorn api_server:app --host 0.0.0.0 --port 8001 --reload
```

服务器启动后，你可以访问：
- **API文档**: http://localhost:8001/docs
- **ReDoc文档**: http://localhost:8001/redoc
- **健康检查**: http://localhost:8001/health

### 3. 使用API

#### 启动翻译任务

```bash
curl -X POST "http://localhost:8001/translate" \
  -H "Content-Type: application/json" \
  -d '{
    "video_id": 123,
    "video_file_path": "videos/sample.mp4",
    "callback_url": "http://localhost:8000/callback",
    "source_language": "en",
    "target_language": "zh",
    "voice_type": "female",
    "voice_speed": 1.0
  }'
```

#### 查询任务状态

```bash
curl -X GET "http://localhost:8001/tasks/{task_id}/status"
```

#### 取消任务

```bash
curl -X POST "http://localhost:8001/tasks/{task_id}/cancel"
```

### 4. 使用测试客户端

```bash
# 启动翻译任务并监控进度
python test_api_client.py 123 videos/sample.mp4

# 启动翻译任务并指定回调URL
python test_api_client.py 123 videos/sample.mp4 http://localhost:8000/callback
```

## 📋 API接口说明

### 1. 启动翻译任务

- **接口**: `POST /translate`
- **说明**: 启动视频翻译任务
- **请求体**:
  ```json
  {
    "video_id": 123,
    "video_file_path": "/path/to/video.mp4",
    "callback_url": "http://localhost:8000/callback",
    "source_language": "en",
    "target_language": "zh",
    "voice_type": "female",
    "voice_speed": 1.0
  }
  ```
- **响应**:
  ```json
  {
    "success": true,
    "task_id": "uuid-task-id",
    "message": "Translation task started",
    "estimated_duration": 1800
  }
  ```

### 2. 查询任务状态

- **接口**: `GET /tasks/{task_id}/status`
- **说明**: 查询翻译任务的当前状态
- **响应**:
  ```json
  {
    "task_id": "uuid-task-id",
    "video_id": 123,
    "status": "translating",
    "progress": 45,
    "current_step": "Generating TTS audio",
    "error_message": null,
    "started_at": "2024-01-01T12:00:00Z",
    "estimated_completion": "2024-01-01T12:30:00Z",
    "translated_video_url": null
  }
  ```

### 3. 取消翻译任务

- **接口**: `POST /tasks/{task_id}/cancel`
- **说明**: 取消正在执行的翻译任务
- **响应**:
  ```json
  {
    "success": true,
    "message": "Task cancelled successfully"
  }
  ```

## 📊 任务状态

| 状态 | 说明 | 进度范围 |
|------|------|----------|
| `started` | 任务已创建 | 0% |
| `extracting` | 提取音频和字幕 | 0-40% |
| `translating` | 翻译字幕 | 40-60% |
| `generating_tts` | 生成TTS语音 | 60-90% |
| `composing` | 合成最终音频 | 90-100% |
| `completed` | 翻译完成 | 100% |
| `failed` | 翻译失败 | - |
| `cancelled` | 任务被取消 | - |

## 🔄 回调通知

当任务状态发生重要变化时，系统会自动调用指定的回调URL：

```json
{
  "video_id": 123,
  "task_id": "uuid-task-id",
  "status": "completed",
  "progress": 100,
  "current_step": "Translation completed",
  "error_message": null,
  "translated_video_url": "http://localhost:8001/files/123_hash_translated_audio.wav"
}
```

## 📁 文件管理

- **输入文件**: 通过`video_file_path`参数指定
- **输出文件**: 保存在`output/`目录下
- **访问方式**: 通过`/files/`路径访问，如：`http://localhost:8001/files/filename.wav`
- **临时文件**: 保存在`temp/`目录下，用于处理过程中的中间文件

## ⚙️ 配置参数

配置参数通过环境变量文件(.env)管理，主要包含以下配置项：

### 服务器配置
```bash
API_HOST=0.0.0.0                    # 监听地址
API_PORT=8001                       # 监听端口
API_WORKERS=1                       # 工作进程数
API_BASE_URL=http://localhost:8001  # 基础URL（用于生成文件下载链接）
```

### 翻译服务配置
```bash
STT_SERVER_URL=http://localhost:9000  # 语音识别服务地址
TTS_SERVER_URL=http://localhost:8000  # 语音合成服务地址
```

### 任务配置
```bash
DEFAULT_ESTIMATED_DURATION=1800      # 默认估计处理时间（秒）
TASK_CHECK_INTERVAL=10               # 任务状态检查间隔（秒）
```

### 文件路径配置
```bash
TEMP_DIR=temp                        # 临时文件目录
OUTPUT_DIR=output                    # 输出文件目录
```

### 日志配置
```bash
LOG_LEVEL=INFO                       # 日志级别
LOG_FORMAT=%(asctime)s - %(name)s - %(levelname)s - %(message)s
```

### 音频处理配置
```bash
FADE_DURATION=150                    # 音频渐变时长（毫秒）
BACKGROUND_MIN_VOLUME=0.05           # 背景音最低音量
```

### TTS配置
```bash
TTS_TEMPERATURE=0.8                  # TTS温度参数
TTS_TOP_K=50                         # TTS Top-K参数
TTS_TOP_P=0.95                       # TTS Top-P参数
TTS_SEED_BASE=421                    # TTS种子基数
```

## 🛠️ 开发说明

### 项目结构

```
├── api_server.py           # FastAPI服务器主文件
├── start_api_server.py     # 服务器启动脚本
├── test_api_client.py      # 测试客户端
├── requirements_api.txt    # API依赖
├── main.py                 # 原始翻译逻辑
├── temp/                   # 临时文件目录
└── output/                 # 输出文件目录
```

### 扩展功能

1. **认证**: 可以添加API Key或Bearer Token认证
2. **限流**: 使用slowapi等库实现请求限流
3. **数据库**: 使用Redis或SQLite存储任务状态
4. **监控**: 集成Prometheus监控
5. **日志**: 配置结构化日志输出

## 🐛 故障排除

### 常见问题

1. **端口占用**: 修改`API_PORT`环境变量或使用不同端口
2. **依赖缺失**: 确保安装了所有必要的Python包
3. **文件权限**: 确保有`temp/`和`output/`目录的读写权限
4. **STT/TTS服务**: 确保语音服务正常运行

### 调试方法

1. 查看服务器日志输出
2. 访问`/health`检查服务状态
3. 使用`/tasks`接口查看所有任务
4. 检查`temp/`和`output/`目录的文件

## 📞 技术支持

如果遇到问题，请检查：
1. 服务器日志
2. API文档：http://localhost:8001/docs
3. 原始翻译程序是否正常工作 