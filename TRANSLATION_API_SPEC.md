# 翻译项目API接口规范

## 概述

本文档定义了 `translation_project` 需要实现的API接口，用于与视频下载管理系统对接。

## 基础信息

- **基础URL**: `http://localhost:8001` (可配置)
- **认证方式**: Bearer Token 或 API Secret
- **数据格式**: JSON
- **字符编码**: UTF-8

## 接口规范

### 1. 启动翻译任务

**接口**: `POST /translate`

**请求头**:
```
Content-Type: application/json
Authorization: Bearer {api_key}
# 或者
X-API-Secret: {api_secret}
```

**请求参数**:
```json
{
  "video_id": 123,
  "video_file_path": "/path/to/video.mp4",
  "callback_url": "http://localhost:7000/translation/callback/123",
  "source_language": "en",
  "target_language": "zh", 
  "voice_type": "female",
  "voice_speed": 1.0
}
```

**响应**:
```json
{
  "success": true,
  "task_id": "uuid-task-id",
  "message": "Translation task started",
  "estimated_duration": 1800
}
```

### 2. 查询任务状态

**接口**: `GET /tasks/{task_id}/status`

**响应**:
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

**状态值说明**:
- `started`: 任务已开始
- `extracting`: 提取字幕中
- `translating`: 翻译字幕中
- `generating_tts`: 生成TTS语音中
- `composing`: 合成视频中
- `completed`: 翻译完成
- `failed`: 翻译失败

### 3. 取消翻译任务

**接口**: `POST /tasks/{task_id}/cancel`

**响应**:
```json
{
  "success": true,
  "message": "Task cancelled successfully"
}
```

### 4. 回调通知

当任务状态发生重要变化时，translation_project应该主动调用视频管理系统的回调接口：

**接口**: `POST {callback_url}`

**请求参数**:
```json
{
  "video_id": 123,
  "task_id": "uuid-task-id",
  "status": "completed",
  "progress": 100,
  "current_step": "Translation completed",
  "error_message": null,
  "translated_video_url": "http://localhost:8001/files/translated/123.mp4"
}
```

## 工作流程

### 完整翻译流程

1. **提取字幕** (`extracting`)
   - 从视频文件中提取音频
   - 使用语音识别生成字幕文件
   - 进度: 0-20%

2. **翻译字幕** (`translating`)
   - 调用翻译API翻译字幕内容
   - 保持时间轴同步
   - 进度: 20-50%

3. **生成TTS语音** (`generating_tts`)
   - 根据翻译后的文本生成语音
   - 匹配原始语音的节奏和停顿
   - 进度: 50-80%

4. **合成视频** (`composing`)
   - 将新语音与原视频合成
   - 可选择保留原始音轨作为背景
   - 进度: 80-100%

5. **完成** (`completed`)
   - 上传翻译后的视频文件
   - 通过回调通知完成

## 错误处理

### 常见错误码

- `400`: 请求参数错误
- `401`: 认证失败
- `404`: 任务不存在
- `429`: 请求频率过高
- `500`: 服务器内部错误

### 错误响应格式

```json
{
  "success": false,
  "error_code": "INVALID_VIDEO_FORMAT",
  "message": "Unsupported video format",
  "details": "Only MP4, AVI, MOV formats are supported"
}
```

## 文件管理

### 输入文件
- translation_project需要能够访问video_file_path指定的视频文件
- 建议通过共享存储或HTTP下载方式获取

### 输出文件
- 翻译后的视频文件应该可以通过HTTP访问
- 文件URL在任务完成时通过translated_video_url返回
- 建议保留文件至少24小时供下载

## 配置参数

### 语言支持
- `source_language`: 源语言代码 (如: en, zh, ja, ko)
- `target_language`: 目标语言代码

### 语音配置
- `voice_type`: 语音类型 (male, female, child)
- `voice_speed`: 语音速度 (0.5-2.0)

### 质量配置
- 视频质量应保持与原始文件一致
- 音频质量建议不低于128kbps
- 支持常见视频格式: MP4, AVI, MOV, MKV

## 部署建议

### 资源要求
- CPU: 建议多核处理器，支持并发处理
- 内存: 建议8GB以上
- 存储: 建议SSD，预留足够临时空间
- GPU: 可选，用于加速TTS和视频处理

### 扩展性
- 支持水平扩展以处理更多并发任务
- 实现任务队列机制
- 支持任务优先级设置

## 示例实现

### Python Flask示例

```python
from flask import Flask, request, jsonify
import uuid

app = Flask(__name__)

@app.route('/translate', methods=['POST'])
def start_translation():
    data = request.json
    task_id = str(uuid.uuid4())
    
    # 启动异步翻译任务
    start_async_translation(task_id, data)
    
    return jsonify({
        'success': True,
        'task_id': task_id,
        'message': 'Translation task started'
    })

@app.route('/tasks/<task_id>/status', methods=['GET'])
def get_task_status(task_id):
    status = get_translation_status(task_id)
    return jsonify(status)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8001)
```

## 测试用例

### 基本功能测试
1. 启动翻译任务
2. 查询任务状态
3. 接收状态更新
4. 下载翻译后的视频

### 异常情况测试
1. 无效视频文件
2. 不支持的语言
3. 网络中断恢复
4. 任务取消

## 监控和日志

### 建议记录的信息
- 任务开始/结束时间
- 处理进度和耗时
- 错误信息和堆栈
- 资源使用情况

### 性能指标
- 平均处理时间
- 成功率
- 并发处理能力
- 资源利用率 