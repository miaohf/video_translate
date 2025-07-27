# Voice Mappings 使用指南

## 🎯 概述

`voice_mappings` 字段用于将说话人ID映射到特定的语音角色和音频文件，实现个性化的语音合成。

## 📋 字段结构

### VoiceRoleMapping 模型

```python
class VoiceRoleMapping(BaseModel):
    speaker_id: str          # 说话人ID，如 "SPEAKER_00"
    voice_role_id: int       # 语音角色ID
    voice_role_name: str     # 语音角色名称
    audio_file_path: str     # 参考音频文件路径
```

## 🔄 优先级逻辑

系统按以下优先级处理参考音频：

### 1. 🎯 Voice Mappings（最高优先级）
如果提供了 `voice_mappings` 且找到匹配的 `speaker_id`：
- 使用 `voice_mapping` 中的 `audio_file_path` 作为参考音频
- 日志：`🎯 使用voice_mapping: SPEAKER_00 -> zhaozhongxiang -> downloads/voice_roles/xxx.mp3`

### 2. 🎵 音频切片（中等优先级）
如果没有 `voice_mappings` 或未找到匹配：
- 使用人声分离后的音频切片作为参考音频
- 日志：`🎵 使用音频切片作为参考音频: temp/voice_roles/267/voice_role_00.mp3`

### 3. 🔊 默认Speaker（最低优先级）
如果以上都没有：
- 使用默认的speaker设置
- 日志：`🔊 使用默认speaker: Unknown`

## 📝 使用示例

### 1. JSON请求体方式

```json
{
  "video_id": 267,
  "video_file_path": "/path/to/video.mp4",
  "voice_mappings": [
    {
      "speaker_id": "SPEAKER_00",
      "voice_role_id": 1,
      "voice_role_name": "zhaozhongxiang",
      "audio_file_path": "downloads/voice_roles/cc48bc22-a61e-4c29-a6da-1b4ff23d8287.mp3"
    },
    {
      "speaker_id": "SPEAKER_01", 
      "voice_role_id": 2,
      "voice_role_name": "female_voice",
      "audio_file_path": "downloads/voice_roles/female_sample.mp3"
    }
  ]
}
```

### 2. 文件上传方式

```bash
curl -X POST "http://localhost:9000/translate" \
  -F "video_id=267" \
  -F "audio_file=@main_audio.wav" \
  -F "voice_role_files=@speaker1.wav" \
  -F "voice_role_files=@speaker2.wav"
```

系统会自动创建 `voice_mappings`：
```json
[
  {
    "speaker_id": "SPEAKER_00",
    "voice_role_id": 1,
    "voice_role_name": "voice_role_00",
    "audio_file_path": "temp/voice_roles/267/voice_role_00.mp3"
  },
  {
    "speaker_id": "SPEAKER_01",
    "voice_role_id": 2,
    "voice_role_name": "voice_role_01", 
    "audio_file_path": "temp/voice_roles/267/voice_role_01.mp3"
  }
]
```

## 🔧 技术实现

### 说话人匹配逻辑

```python
# 从字幕的speaker字段提取说话人ID
speaker_match = re.search(r'SPEAKER_\d+', speaker)
if speaker_match:
    detected_speaker_id = speaker_match.group(0)  # 如 "SPEAKER_00"
    
    # 查找匹配的voice_mapping
    for mapping in voice_mappings:
        if mapping["speaker_id"] == detected_speaker_id:
            # 确保角色音频文件已上传到TTS服务器
            role_audio_path = mapping["audio_file_path"]
            if os.path.exists(role_audio_path):
                await self._upload_role_audio_to_tts(role_audio_path, tts_server_url)
            
            # 使用voice_mapping中的音频文件
            data["prompt_speech_path"] = role_audio_path
            break
```

### 角色音频文件上传

系统会自动将 `voice_mappings` 中的角色音频文件上传到TTS服务器：

1. **自动上传**：当找到匹配的 `voice_mapping` 时，系统会自动上传对应的音频文件
2. **避免重复**：使用缓存机制避免重复上传同一个文件
3. **错误处理**：如果上传失败，会记录警告但继续处理

### 字幕更新

当找到匹配的 `voice_mapping` 时，系统会更新字幕的 `reference_audio` 字段：

```python
# 更新字幕的reference_audio字段
updated_subtitle["reference_audio"] = mapping["audio_file_path"]
```

## 📊 日志示例

### 成功匹配voice_mapping
```
🎯 使用voice_mapping: SPEAKER_00 -> zhaozhongxiang -> downloads/voice_roles/cc48bc22-a61e-4c29-a6da-1b4ff23d8287.mp3
```

### 使用音频切片
```
🎵 使用音频切片作为参考音频: temp/voice_roles/267/voice_role_00.mp3
```

### 使用默认speaker
```
🔊 使用默认speaker: Unknown
```

## ⚠️ 注意事项

1. **文件路径验证**：确保 `audio_file_path` 指向的文件存在且可访问
2. **说话人ID格式**：`speaker_id` 必须与字幕中的格式匹配（如 `SPEAKER_00`）
3. **音频格式**：参考音频文件支持 MP3、WAV 等常见格式
4. **优先级**：Voice Mappings > 音频切片 > 默认Speaker

## 🎉 最佳实践

1. **提供高质量的参考音频**：确保参考音频清晰、无噪音
2. **合理命名**：使用有意义的 `voice_role_name`
3. **测试验证**：上传后检查日志确认匹配成功
4. **文件管理**：定期清理不需要的参考音频文件 