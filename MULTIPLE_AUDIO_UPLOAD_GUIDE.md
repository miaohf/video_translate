# 多音频文件上传指南

## 🎯 概述

现在API支持同时上传多个音频文件：
1. **主音频文件** - 需要翻译的音频文件
2. **角色音频文件** - 用于语音合成的参考音频文件

## 📋 上传格式

### 1. 使用 multipart/form-data

```bash
curl -X POST "http://localhost:9000/translate" \
  -F "video_id=123" \
  -F "audio_file=@/path/to/main_audio.wav" \
  -F "voice_role_files=@/path/to/speaker1.wav" \
  -F "voice_role_files=@/path/to/speaker2.wav" \
  -F "callback_url=http://localhost:7000/callback"
```

**注意**: 每个角色音频文件都需要使用相同的字段名 `voice_role_files`，FastAPI会自动将它们收集到一个列表中。这是FastAPI的标准行为。

### 2. Python 示例

```python
import requests

def upload_multiple_audio_files():
    url = "http://localhost:9000/translate"
    
    # 准备文件
    files = {
        "audio_file": open("main_audio.wav", "rb"),
    }
    
    # 添加角色音频文件 - 每个文件都需要使用相同的字段名
    for role_file in ["speaker1.wav", "speaker2.wav", "speaker3.wav"]:
        files["voice_role_files"] = open(role_file, "rb")
    
    # 注意：这种方式会覆盖前面的文件，正确的做法是：
    files = {
        "audio_file": open("main_audio.wav", "rb"),
    }
    
    # 方法1：使用列表（推荐）
    role_files = [open("speaker1.wav", "rb"), open("speaker2.wav", "rb")]
    for role_file in role_files:
        files["voice_role_files"] = role_file
    
    # 方法2：使用requests的files参数特性
    files = {
        "audio_file": open("main_audio.wav", "rb"),
        "voice_role_files": [
            open("speaker1.wav", "rb"),
            open("speaker2.wav", "rb"),
            open("speaker3.wav", "rb")
        ]
    }
    
    # 准备表单数据
    data = {
        "video_id": "123",
        "callback_url": "http://localhost:7000/callback"
    }
    
    response = requests.post(url, files=files, data=data)
    return response.json()
```

### 3. JavaScript 示例

```javascript
async function uploadMultipleAudioFiles() {
    const url = "http://localhost:9000/translate";
    
    const formData = new FormData();
    
    // 主音频文件
    const mainAudioFile = document.getElementById('mainAudio').files[0];
    formData.append('audio_file', mainAudioFile);
    
    // 角色音频文件
    const roleFiles = document.getElementById('roleFiles').files;
    for (let i = 0; i < roleFiles.length; i++) {
        formData.append('voice_role_files', roleFiles[i]);
    }
    
    // 其他参数
    formData.append('video_id', '123');
    formData.append('callback_url', 'http://localhost:7000/callback');
    
    const response = await fetch(url, {
        method: 'POST',
        body: formData
    });
    
    return await response.json();
}
```

## 🔧 参数说明

### 必需参数

| 参数名 | 类型 | 说明 |
|--------|------|------|
| `audio_file` | File | 主音频文件（需要翻译的音频） |

### 可选参数

| 参数名 | 类型 | 说明 |
|--------|------|------|
| `voice_role_files` | File[] | 角色音频文件列表（用于语音合成） |
| `video_id` | int | 视频ID（不提供时自动生成） |
| `callback_url` | string | 回调URL |
| `source_language` | string | 源语言（默认: "en"） |
| `target_language` | string | 目标语言（默认: "zh"） |
| `voice_type` | string | 语音类型（默认: "female"） |
| `voice_speed` | float | 语音速度（默认: 1.0） |

## 📁 支持的文件格式

### 主音频文件格式
- MP3 (.mp3)
- WAV (.wav)
- M4A (.m4a)
- AAC (.aac)
- OGG (.ogg)
- FLAC (.flac)

### 角色音频文件格式
- MP3 (.mp3)
- WAV (.wav)
- M4A (.m4a)
- AAC (.aac)
- OGG (.ogg)
- FLAC (.flac)

## 🔄 处理流程

1. **文件上传**: 系统接收主音频文件和角色音频文件
2. **文件保存**: 将文件保存到临时目录
3. **角色映射**: 自动创建语音角色映射
4. **说话人识别**: 分析主音频文件中的说话人
5. **语音合成**: 使用对应的角色音频文件生成中文语音

## 📊 自动映射规则

系统会自动为上传的角色音频文件创建映射：

```json
{
  "voice_mappings": [
    {
      "speaker_id": "SPEAKER_00",
      "voice_role_id": 1,
      "voice_role_name": "voice_role_00",
      "audio_file_path": "temp/voice_roles/123/voice_role_00.wav"
    },
    {
      "speaker_id": "SPEAKER_01", 
      "voice_role_id": 2,
      "voice_role_name": "voice_role_01",
      "audio_file_path": "temp/voice_roles/123/voice_role_01.wav"
    }
  ]
}
```

## ⚠️ 注意事项

### 1. 文件顺序
- 角色音频文件的顺序很重要
- 第一个角色音频文件对应 `SPEAKER_00`
- 第二个角色音频文件对应 `SPEAKER_01`
- 以此类推

### 2. 文件质量
- 角色音频文件应该是清晰的语音样本
- 建议时长在 3-10 秒之间
- 避免包含背景音乐或噪音

### 3. 说话人匹配
- 系统会自动识别主音频中的说话人
- 如果识别出的说话人数量超过角色音频文件数量，多余的说话人将使用默认语音

### 4. 文件大小限制
- 建议单个文件不超过 100MB
- 总上传大小建议不超过 500MB

## 📝 日志示例

成功上传多个文件时的日志：

```
2025-07-27 01:00:51,370 - routes.translation_routes - INFO - Audio file uploaded: temp/uploads/267_20250727_010051.wav (size: 24153678 bytes)
2025-07-27 01:00:51,371 - routes.translation_routes - INFO - Voice role file uploaded: temp/voice_roles/267/voice_role_00.wav (size: 1024000 bytes)
2025-07-27 01:00:51,372 - routes.translation_routes - INFO - Voice role file uploaded: temp/voice_roles/267/voice_role_01.wav (size: 1536000 bytes)
2025-07-27 01:00:51,373 - routes.translation_routes - INFO - Processed 2 voice role files
```

## 🔗 相关文档

- [语音角色映射功能使用指南](./VOICE_MAPPINGS_GUIDE.md)
- [统一API使用指南](./UNIFIED_API_GUIDE.md)
- [错误处理指南](./ERROR_HANDLING.md) 