# 翻译服务提供商配置说明

本项目支持多种翻译服务提供商，您可以根据需要选择合适的服务。

## 支持的提供商

### 1. Ollama (本地部署)
- **适用场景**: 需要本地部署、数据隐私要求高
- **优点**: 完全本地化、免费使用、数据不出本地
- **缺点**: 需要较高的硬件配置、模型质量取决于本地模型

### 2. DeepSeek (云端API)
- **适用场景**: 追求翻译质量、不想本地部署
- **优点**: 翻译质量高、无需本地GPU、响应速度快
- **缺点**: 需要付费、数据需上传到云端

## 配置方法

### 使用 Ollama

1. 确保 Ollama 服务正在运行
2. 在配置文件中设置：
```python
TRANSLATION_PROVIDER = "ollama"
OLLAMA_SERVER_URL = "http://127.0.0.1:11434"
MODEL_NAME = "qwen3:8b"  # 或其他支持的模型
```

### 使用 DeepSeek

1. 前往 [DeepSeek 平台](https://platform.deepseek.com/api_keys) 获取 API 密钥
2. 在配置文件中设置：
```python
TRANSLATION_PROVIDER = "deepseek"
DEEPSEEK_API_URL = "https://api.deepseek.com"
DEEPSEEK_API_KEY = "your-api-key-here"
DEEPSEEK_MODEL = "deepseek-chat"
```

## 环境变量配置

您也可以通过环境变量进行配置：

```bash
# 通用配置
export TRANSLATION_PROVIDER="deepseek"  # 或 "ollama"

# Ollama 配置
export OLLAMA_SERVER_URL="http://127.0.0.1:11434"
export MODEL_NAME="qwen3:8b"

# DeepSeek 配置
export DEEPSEEK_API_URL="https://api.deepseek.com"
export DEEPSEEK_API_KEY="your-api-key-here"
export DEEPSEEK_MODEL="deepseek-chat"
```

## 模型选择

### Ollama 推荐模型
- `qwen3:8b` - 平衡性能与质量
- `qwen3:14b` - 更好的翻译质量
- `llama3:8b` - 另一个选择

### DeepSeek 模型
- `deepseek-chat` - 通用聊天模型，适合翻译任务
- `deepseek-reasoner` - 推理模型，适合复杂翻译

## 成本比较

| 提供商 | 成本 | 翻译质量 | 延迟 | 隐私性 |
|-------|------|----------|------|--------|
| Ollama | 免费 | 中等 | 中等 | 最高 |
| DeepSeek | 付费 | 高 | 低 | 中等 |

## 使用建议

1. **开发测试阶段**: 建议使用 Ollama，无需担心API费用
2. **生产环境**: 如果对翻译质量要求高，建议使用 DeepSeek
3. **隐私敏感**: 必须使用 Ollama 本地部署
4. **批量翻译**: DeepSeek 的并发性能更好

## 故障排除

### Ollama 相关问题
- 确保 Ollama 服务启动: `ollama serve`
- 确保模型已下载: `ollama pull qwen3:8b`
- 检查端口是否被占用

### DeepSeek 相关问题
- 检查 API 密钥是否正确
- 确认账户余额充足
- 检查网络连接是否正常

## 切换提供商

要切换翻译提供商，只需修改配置文件中的 `TRANSLATION_PROVIDER` 值：

```python
# 切换到 DeepSeek
TRANSLATION_PROVIDER = "deepseek"

# 切换到 Ollama
TRANSLATION_PROVIDER = "ollama"
```

然后重启应用程序即可。 