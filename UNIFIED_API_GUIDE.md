# 统一API使用指南

## 🎯 概述

现在 `POST /translate` 端点支持两种方式处理文件：

1. **JSON请求体** - 指定本地视频文件路径
2. **音频文件上传** - 直接上传音频文件

## 🚀 使用方式

### 方式1：JSON请求体（本地视频文件路径）

**Content-Type**: `application/json`

**请求体**:
```json
{
  "video_id": 123,
  "video_file_path": "/path/to/video.mp4",
  "callback_url": "http://your-server.com/callback",
  "source_language": "en",
  "target_language": "zh",
  "voice_type": "female",
  "voice_speed": 1.0
}
```

**简化请求体**（所有可选参数都有默认值）:
```json
{
  "video_file_path": "/path/to/video.mp4"
}
```

**curl示例**:
```bash
# 完整参数
curl -X POST "http://localhost:9000/translate" \
  -H "Content-Type: application/json" \
  -d '{
    "video_id": 123,
    "video_file_path": "/home/user/videos/sample.mp4",
    "callback_url": "http://localhost:7000/translation/callback/123"
  }'

# 简化参数
curl -X POST "http://localhost:9000/translate" \
  -H "Content-Type: application/json" \
  -d '{
    "video_file_path": "/home/user/videos/sample.mp4"
  }'
```

**Python示例**:
```python
import requests

def translate_local_file():
    url = "http://localhost:9000/translate"
    
    # 完整参数
    data = {
        "video_id": 123,
        "video_file_path": "/home/user/videos/sample.mp4",
        "callback_url": "http://localhost:7000/callback"
    }
    
    # 简化参数
    data_simple = {
        "video_file_path": "/home/user/videos/sample.mp4"
    }
    
    response = requests.post(url, json=data_simple)
    return response.json()
```

### 方式2：音频文件上传

**Content-Type**: `multipart/form-data`

**参数**:
- `video_id` (int, optional): 视频ID（不提供时自动生成）
- `audio_file` (file, required): 音频文件
- `callback_url` (string, optional): 回调URL
- `source_language` (string, default: "en"): 源语言
- `target_language` (string, default: "zh"): 目标语言
- `voice_type` (string, optional, default: "female"): 语音类型
- `voice_speed` (float, optional, default: 1.0): 语音速度

**curl示例**:
```bash
# 完整参数
curl -X POST "http://localhost:9000/translate" \
  -F "video_id=123" \
  -F "audio_file=@/path/to/local/audio.mp3" \
  -F "callback_url=http://localhost:7000/translation/callback/123"

# 简化参数（只上传音频文件）
curl -X POST "http://localhost:9000/translate" \
  -F "audio_file=@/path/to/local/audio.mp3"
```

**Python示例**:
```python
import requests

def translate_upload_audio():
    url = "http://localhost:9000/translate"
    
    # 完整参数
    files = {"audio_file": open("sample.mp3", "rb")}
    data = {
        "video_id": 123,
        "callback_url": "http://localhost:7000/callback"
    }
    
    # 简化参数
    files_simple = {"audio_file": open("sample.mp3", "rb")}
    
    response = requests.post(url, files=files_simple)
    return response.json()
```

## 📁 支持的文件格式

### 视频文件格式（本地路径方式）
- MP4 (.mp4)
- AVI (.avi)
- MOV (.mov)
- MKV (.mkv)
- WMV (.wmv)
- FLV (.flv)

### 音频文件格式（上传方式）
- MP3 (.mp3)
- WAV (.wav)
- M4A (.m4a)
- AAC (.aac)
- OGG (.ogg)
- FLAC (.flac)

## 🔧 参数说明

### 必需参数
- **JSON方式**: `video_file_path` - 视频文件路径
- **上传方式**: `audio_file` - 音频文件

### 可选参数
- `video_id` - 视频ID（不提供时自动生成时间戳ID）
- `callback_url` - 回调URL
- `source_language` - 源语言（默认: "en"）
- `target_language` - 目标语言（默认: "zh"）
- `voice_type` - 语音类型（默认: "female"）
- `voice_speed` - 语音速度（默认: 1.0）

## 📊 对比分析

| 特性 | JSON方式（视频） | 音频上传方式 |
|------|------------------|--------------|
| **适用场景** | 服务器已有视频文件 | 客户端上传音频文件 |
| **请求复杂度** | 简单 | 中等 |
| **文件大小限制** | 无（服务器文件） | 受HTTP限制 |
| **网络传输** | 只传路径 | 传输整个音频文件 |
| **处理流程** | 提取音频→转录→翻译 | 直接转录→翻译 |
| **批量处理** | 适合 | 适合 |

## 🎯 推荐使用场景

### 使用JSON方式当：
- ✅ 视频文件已存在于服务器
- ✅ 需要从视频中提取音频
- ✅ 批量处理多个视频
- ✅ 自动化脚本调用
- ✅ 文件路径已知且稳定

### 使用音频上传方式当：
- ✅ 客户端直接上传音频文件
- ✅ 已有音频文件，无需视频
- ✅ 单次处理
- ✅ Web界面集成
- ✅ 音频文件不在服务器上

## 🔧 技术实现细节

### 自动检测机制

API会根据 `Content-Type` 头部自动检测请求类型：

1. **`application/json`** → 处理本地视频文件路径
2. **`multipart/form-data`** → 处理音频文件上传
3. **混合模式** → 优先使用上传的音频文件

### 处理流程差异

**JSON方式（视频文件）**:
```
视频文件 → 提取音频 → 语音转录 → 翻译 → TTS → 合成
```

**音频上传方式**:
```
音频文件 → 语音转录 → 翻译 → TTS → 合成
```

### 自动ID生成

当不提供 `video_id` 时，系统会自动生成一个基于时间戳的ID：
```python
video_id = int(datetime.now().timestamp())
```

### 错误处理

- **文件不存在**: 返回 `FILE_NOT_FOUND` 错误
- **文件类型不支持**: 返回 `INVALID_FILE_TYPE` 错误
- **请求格式错误**: 返回 `INVALID_REQUEST` 错误

### 文件存储

上传的音频文件会保存在 `{TEMP_DIR}/uploads/` 目录下，文件名格式为：
```
{video_id}_{timestamp}{extension}
```

## 🚀 优势总结

### 统一端点的优势：
1. **API简洁**: 只有一个端点，减少学习成本
2. **向后兼容**: 现有JSON调用无需修改
3. **灵活选择**: 客户端可根据需要选择合适方式
4. **统一响应**: 两种方式返回相同的响应格式
5. **易于维护**: 减少重复代码

### 支持音频上传的优势：
- ✅ 减少视频处理开销
- ✅ 支持更多音频格式
- ✅ 更快的处理速度
- ✅ 更小的文件传输

### 可选参数的优势：
- ✅ 简化API调用
- ✅ 灵活的配置选项
- ✅ 自动ID生成
- ✅ 合理的默认值

## 📝 最佳实践

1. **选择合适的方式**: 
   - 有视频文件 → 使用JSON方式
   - 只有音频文件 → 使用音频上传方式

2. **参数使用**: 
   - 必需参数：`video_file_path` 或 `audio_file`
   - 可选参数：根据需要提供，有合理的默认值

3. **音频文件质量**: 
   - 使用高质量音频文件（16kHz+采样率）
   - 避免压缩过度的音频格式

4. **错误处理**: 
   - 正确处理各种错误情况
   - 检查文件格式是否支持

5. **文件管理**: 
   - 定期清理临时上传文件
   - 监控文件上传和处理的日志信息

现在您可以在同一个端点中使用两种方式，享受统一的API体验！🎉 