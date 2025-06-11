# 音频切片参考音频功能 + 背景音频混合

## 功能概述

这个功能为视频翻译系统添加了音频切片、参考音频上传和智能背景音频混合功能，用于提高TTS（文本转语音）的质量并保持原音频的时间轴和节奏感。

## 主要特性

### 1. 音频切片生成
- 为每个字幕段落自动创建对应的音频切片
- 音频切片保存在 `temp/{video_name}/audio_segments/` 目录
- 文件命名格式：`{file_hash}_{index:04d}_{speaker}.mp3`
- 自动处理过短音频片段（少于500ms时会扩展）

### 2. 参考音频上传
- 自动将音频切片上传到TTS服务器的 `/upload_audio` 接口
- 支持重复上传检测，避免重复上传相同文件
- 包含超时处理和错误恢复机制

### 3. TTS请求优化
- 在TTS请求中使用参考音频文件名作为speaker参数
- Speaker参数格式：`{file_hash}_{index:04d}_{speaker}`
- 支持向后兼容，如果没有参考音频则使用默认设置

### 4. 智能背景音频混合 ⭐ **核心创新**
- **原音频作为背景**：保持完整的原始音频作为背景音轨
- **精确时间插入**：TTS音频在原始字幕时间点精确插入
- **动态音量控制**：背景音在TTS播放期间自动降低到5%音量
- **平滑渐变效果**：150ms的淡入淡出确保自然过渡
- **时长完全匹配**：最终音频时长与原视频完全一致
- **保留环境音**：保持原音频中的背景音乐、环境声等元素

## 代码修改

### 1. `processors/audio_processor.py`

#### 新增方法：`create_audio_segments()`
```python
def create_audio_segments(self, audio_path: str, subtitles: List[Dict], video_name: str) -> List[Dict]:
    """
    为字幕创建音频切片作为参考音频
    
    参数:
        audio_path: 原始音频文件路径
        subtitles: 字幕列表，每个字幕包含start和end时间
        video_name: 视频名称，用于创建目录
        
    返回:
        更新后的字幕列表，包含reference_audio字段
    """
```

#### 新增方法：`upload_reference_audio()`
```python
async def upload_reference_audio(self, subtitles: List[Dict]) -> List[Dict]:
    """
    将参考音频上传到TTS服务器
    
    参数:
        subtitles: 包含reference_audio字段的字幕列表
        
    返回:
        更新后的字幕列表
    """
```

### 2. `main.py`

#### 修改主处理流程
在字幕翻译完成后添加了两个新步骤：
1. 创建音频切片作为参考音频
2. 上传参考音频到TTS服务器

#### 支持已有字幕文件
如果发现已存在的翻译字幕文件，会检查是否包含参考音频信息，如果没有则自动创建和上传。

### 3. TTS请求改进
修改了 `_generate_tts_audio()` 方法，现在会：
- 从 `reference_audio` 字段提取speaker信息
- 使用音频文件名（去除扩展名）作为speaker参数
- 向后兼容没有参考音频的情况

## 使用方法

### 自动使用（推荐）
正常运行视频翻译程序，系统会自动创建音频切片和上传参考音频：
```bash
python main.py --input_video your_video.mp4
```

### 测试功能
运行测试脚本验证功能：
```bash
# 测试背景音频混合功能（推荐）
python test_background_mixing.py

# 测试音频切片功能
python test_audio_segments_simple.py
```

## 文件结构

处理后的项目目录结构：
```
temp/
└── {video_name}/
    ├── {hash}_audio.mp3              # 原始音频
    ├── {hash}_subtitles.json         # 原始字幕
    ├── {hash}_subtitles_zh.json      # 翻译后字幕（包含reference_audio字段）
    └── audio_segments/               # 音频切片目录
        ├── {hash}_0000_SPEAKER_01.mp3
        ├── {hash}_0001_SPEAKER_01.mp3
        └── ...
```

## 字幕JSON格式更新

新的字幕JSON格式包含多个音频相关字段：
```json
[
  {
    "start": 0.27,
    "end": 30.95,
    "text": "原始英文文本",
    "translated_text": "翻译后的中文文本",
    "speaker": "SPEAKER_01",
    "reference_audio": "temp/video_name/audio_segments/hash_0000_SPEAKER_01.mp3",
    "generated_audio": "temp/video_name/tts_segments/segment_0000.wav",
    "generated_duration": 2.8
  }
]
```

**字段说明：**
- `reference_audio`: 原音频切片路径（用于TTS参考）
- `generated_audio`: 生成的TTS音频文件路径
- `generated_duration`: TTS音频实际时长（秒）

## TTS服务器要求

TTS服务器需要支持以下接口：

### 1. `/upload_audio` (POST)
用于上传参考音频文件：
```python
@app.post("/upload_audio")
async def upload_audio(file: UploadFile = File(...)):
    # 处理上传的音频文件
    return {"status": "success", "message": "音频文件上传成功", "file_path": save_path}
```

### 2. `/tts` (POST)
TTS生成接口，支持speaker参数：
```python
{
    "text": "要转换的文本",
    "speaker": "hash_0000_SPEAKER_01",  # 参考音频文件名（无扩展名）
    "temperature": 0.8,
    "top_k": 50,
    "top_p": 0.95,
    "seed": 421
}
```

## 配置要求

确保配置文件中包含正确的TTS服务器地址：
```python
TTS_SERVER_URL = "http://localhost:8000"  # 或其他TTS服务器地址
```

## 依赖包

确保安装了以下依赖包：
- `pydub`: 音频处理
- `aiohttp`: 异步HTTP客户端
- `pathlib`: 路径处理

这些依赖已包含在 `requirements.txt` 中。

## 错误处理

系统包含完善的错误处理机制：
- 音频切片创建失败时会保留原字幕
- 上传失败时会记录错误但不中断处理
- TTS服务器不可用时会跳过上传步骤
- 支持部分失败的恢复处理

## 性能优化

- 重复文件检测避免不必要的上传
- 支持断点续传（如果切片已存在则跳过）
- 异步上传提高效率
- 内存优化，及时释放音频数据 