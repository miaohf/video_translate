# 回调功能故障排除指南

## 问题描述
当翻译API尝试发送回调通知时，出现 `Callback failed with status 404` 错误。

## 常见原因和解决方案

### 1. 回调服务器未启动
**问题**: 回调URL指向的服务器没有运行
**解决方案**: 
- 启动回调测试服务器：`python callback_test_server.py`
- 或者确保您的应用程序回调端点正在运行

### 2. 回调URL错误
**问题**: 提供的回调URL不正确或端点不存在
**解决方案**:
- 检查回调URL格式是否正确
- 确认端点路径存在，例如：`http://localhost:8000/callback`
- 使用浏览器或curl测试URL是否可访问

### 3. 网络连接问题
**问题**: 翻译服务器无法连接到回调服务器
**解决方案**:
- 检查防火墙设置
- 确保端口未被占用
- 如果是跨机器调用，检查网络连通性

### 4. 回调端点HTTP方法不匹配
**问题**: 回调端点只支持GET，但API发送的是POST请求
**解决方案**:
- 确保回调端点支持POST方法
- 检查路由配置

## 测试回调功能

### 方法1：使用提供的测试工具
```bash
# 1. 启动回调测试服务器
python callback_test_server.py

# 2. 在另一个终端中启动翻译API
python start_api_server.py

# 3. 在第三个终端中运行完整测试
python test_callback.py
```

### 方法2：手动测试
```bash
# 1. 启动回调服务器
python callback_test_server.py

# 2. 测试回调端点是否可访问
curl -X POST http://localhost:8000/callback \
  -H "Content-Type: application/json" \
  -d '{"test": "data"}'

# 3. 使用带回调URL的翻译请求
python test_api_client.py 999 videos/sample.mp4 http://localhost:8000/callback
```

### 方法3：检查回调历史
```bash
# 查看所有回调记录
curl http://localhost:8000/callbacks

# 查看最新回调
curl http://localhost:8000/callbacks/latest

# 清空回调历史
curl -X DELETE http://localhost:8000/callbacks
```

## 调试技巧

### 1. 检查日志
翻译API日志会显示回调发送的详细信息：
```
✅ Callback sent successfully to http://localhost:8000/callback
⚠️ Callback failed with status 404, response: Not Found
❌ Failed to send callback to http://localhost:8000/callback: Connection refused
```

### 2. 验证回调数据格式
回调数据应该包含以下字段：
```json
{
  "video_id": 123,
  "task_id": "uuid-task-id",
  "status": "completed",
  "progress": 100,
  "current_step": "Translation completed",
  "error_message": null,
  "translated_video_url": "http://localhost:9000/files/result.wav"
}
```

### 3. 网络连通性测试
```bash
# 测试端口是否开放
telnet localhost 8000

# 测试HTTP连接
curl -v http://localhost:8000/health
```

## 常见错误码

| 状态码 | 含义 | 解决方案 |
|--------|------|----------|
| 404 | 端点不存在 | 检查URL路径和端点配置 |
| 405 | 方法不允许 | 确保端点支持POST方法 |
| 500 | 服务器内部错误 | 检查回调服务器日志 |
| 连接超时 | 网络问题 | 检查网络连接和防火墙 |

## 配置示例

### Flask回调服务器示例
```python
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/callback', methods=['POST'])
def receive_callback():
    data = request.get_json()
    print(f"收到回调: {data}")
    return jsonify({"status": "success"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
```

### FastAPI回调服务器示例
```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class CallbackData(BaseModel):
    video_id: int
    task_id: str
    status: str
    progress: int
    current_step: str

@app.post("/callback")
async def receive_callback(data: CallbackData):
    print(f"收到回调: {data}")
    return {"status": "success"}
```

## 生产环境建议

1. **使用HTTPS**: 生产环境中应该使用HTTPS协议
2. **认证验证**: 添加API密钥或签名验证
3. **重试机制**: 已实现3次重试，失败后记录日志
4. **监控告警**: 设置回调失败的监控和告警
5. **日志记录**: 详细记录回调发送情况用于故障排除

## 联系支持

如果以上解决方案都不能解决问题，请提供以下信息：
- 翻译API日志
- 回调服务器日志  
- 网络环境描述
- 复现步骤 