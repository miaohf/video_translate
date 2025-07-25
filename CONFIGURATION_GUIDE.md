# 配置管理指南

## 概述

本项目采用统一的配置管理方式：
- **`.env` 文件**：存储用户自定义的核心配置项
- **`config.py` 文件**：统一管理所有配置，从 `.env` 读取核心配置，其他配置使用合理的默认值

## 配置文件结构

### 1. `.env` 文件（用户自定义配置）

`.env` 文件包含需要用户自定义的核心配置项：

```env
# ========== API密钥配置 ==========
HF_TOKEN=your_huggingface_token_here

# ========== API提供商配置 ==========
# 翻译服务提供商选择: ollama 或 deepseek
TRANSLATION_PROVIDER=deepseek

# ========== Ollama API 配置 ==========
# 当 TRANSLATION_PROVIDER=ollama 时使用
OLLAMA_SERVER_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b

# ========== DeepSeek API 配置 ==========
# 当 TRANSLATION_PROVIDER=deepseek 时使用
DEEPSEEK_API_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=sk-39edbcf2781f4010af834fd9226ab92e
DEEPSEEK_MODEL=deepseek-chat

# ========== 服务器配置 ==========
API_HOST=0.0.0.0
API_PORT=9000
API_WORKERS=1

# ========== 翻译服务配置 ==========
STT_SERVER_URL=http://localhost:8001
TTS_SERVER_URL=http://localhost:8002

# ========== 翻译模式配置 ==========
# 翻译模式: batch (批量翻译) 或 whole (整体翻译)
TRANSLATION_MODE=batch

# ========== 文件路径配置 ==========
TEMP_DIR=temp
OUTPUT_DIR=output

# ========== 日志配置 ==========
LOG_LEVEL=INFO
```

### 2. `config.py` 文件（统一配置管理）

`config.py` 文件负责：
- 从 `.env` 文件读取核心配置
- 为其他配置项提供合理的默认值
- 提供向后兼容的配置变量

## 配置项说明

### API提供商配置

| 配置项 | 说明 | 默认值 | 可选值 |
|--------|------|--------|--------|
| `TRANSLATION_PROVIDER` | 翻译服务提供商 | `ollama` | `ollama`, `deepseek` |

### Ollama API 配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `OLLAMA_SERVER_URL` | Ollama服务器地址 | `http://localhost:11434` |
| `OLLAMA_MODEL` | 使用的模型名称 | `qwen3:7b` |

### DeepSeek API 配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `DEEPSEEK_API_URL` | DeepSeek API地址 | `https://api.deepseek.com` |
| `DEEPSEEK_API_KEY` | DeepSeek API密钥 | `""` |
| `DEEPSEEK_MODEL` | 使用的模型名称 | `deepseek-chat` |

### 服务器配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `API_HOST` | API服务器主机 | `0.0.0.0` |
| `API_PORT` | API服务器端口 | `9000` |
| `API_WORKERS` | API工作进程数 | `1` |

### 翻译服务配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `STT_SERVER_URL` | 语音识别服务器地址 | `http://localhost:8001` |
| `TTS_SERVER_URL` | 语音合成服务器地址 | `http://localhost:8002` |
| `TRANSLATION_MODE` | 翻译模式 | `batch` |

### 文件路径配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `TEMP_DIR` | 临时文件目录 | `temp` |
| `OUTPUT_DIR` | 输出文件目录 | `output` |

### 日志配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `LOG_LEVEL` | 日志级别 | `INFO` |

## 使用方法

### 1. 基本配置

1. 复制 `.env` 文件（如果不存在）
2. 根据需要修改配置项
3. 重启应用程序

### 2. 切换API提供商

要使用 Ollama API：
```env
TRANSLATION_PROVIDER=ollama
OLLAMA_MODEL=qwen3:8b
```

要使用 DeepSeek API：
```env
TRANSLATION_PROVIDER=deepseek
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_MODEL=deepseek-chat
```

### 3. 在代码中使用配置

```python
from config import settings

# 使用统一配置
print(f"翻译提供商: {settings.TRANSLATION_PROVIDER}")
print(f"API端口: {settings.API_PORT}")

# 使用向后兼容的配置变量
from config import TRANSLATION_PROVIDER, API_PORT
print(f"翻译提供商: {TRANSLATION_PROVIDER}")
print(f"API端口: {API_PORT}")
```

## 配置优先级

1. **`.env` 文件中的配置**（最高优先级）
2. **`config.py` 中的默认值**（最低优先级）

## 注意事项

1. **敏感信息**：API密钥等敏感信息应存储在 `.env` 文件中，不要提交到版本控制
2. **默认值**：大多数配置项都有合理的默认值，用户只需要配置必要的项目
3. **向后兼容**：保留了旧的配置变量名称，确保现有代码正常工作
4. **类型安全**：配置项会自动转换为正确的数据类型（整数、浮点数、布尔值等）

## 测试配置

使用以下命令测试配置是否正确：

```bash
python test_api_connection.py
```

这将测试API连接和翻译功能是否正常工作。
