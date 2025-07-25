# API配置说明

本翻译服务支持两种API提供商：**Ollama** 和 **DeepSeek**。

## 🎯 快速配置

### 1. 复制配置文件
```bash
cp config.env.example config.env
```

### 2. 编辑配置文件
根据您选择的API提供商，编辑 `config.env` 文件中的相应配置。

## 🔧 API配置详解

### Ollama API配置

**适用场景：** 本地部署，免费使用，需要GPU资源

**配置项：**
```env
# 选择Ollama作为翻译提供商
TRANSLATION_PROVIDER=ollama

# Ollama服务器地址
OLLAMA_SERVER_URL=http://localhost:11434

# 使用的模型名称
OLLAMA_MODEL=qwen3:14b

# GPU配置（可选）
OLLAMA_GPU_LAYERS=35
OLLAMA_NUM_GPU=1
```

**使用步骤：**
1. 安装Ollama：https://ollama.ai/
2. 下载模型：`ollama pull qwen3:14b`
3. 启动服务：`ollama serve`
4. 配置环境变量并运行翻译服务

**优势：**
- ✅ 完全免费
- ✅ 本地部署，数据安全
- ✅ 支持流式翻译
- ✅ 可自定义模型参数

**劣势：**
- ❌ 需要GPU资源
- ❌ 需要本地部署
- ❌ 模型质量依赖本地模型

### DeepSeek API配置

**适用场景：** 云端服务，高质量翻译，无需本地资源

**配置项：**
```env
# 选择DeepSeek作为翻译提供商
TRANSLATION_PROVIDER=deepseek

# DeepSeek API地址
DEEPSEEK_API_URL=https://api.deepseek.com

# DeepSeek API密钥
DEEPSEEK_API_KEY=your_deepseek_api_key_here

# 使用的模型名称
DEEPSEEK_MODEL=deepseek-chat
```

**使用步骤：**
1. 注册DeepSeek账号：https://platform.deepseek.com/
2. 获取API密钥
3. 配置环境变量并运行翻译服务

**优势：**
- ✅ 高质量翻译
- ✅ 无需本地资源
- ✅ 云端服务，稳定可靠
- ✅ 支持多种模型

**劣势：**
- ❌ 需要付费
- ❌ 依赖网络连接
- ❌ 数据需要上传到云端

## 🚀 测试配置

运行测试脚本验证配置是否正确：

```bash
python test_api_connection.py
```

测试脚本会：
1. 显示当前配置信息
2. 测试API连接
3. 进行简单翻译测试

## 📊 配置对比

| 特性 | Ollama | DeepSeek |
|------|--------|----------|
| 费用 | 免费 | 按使用量付费 |
| 部署 | 本地 | 云端 |
| 资源需求 | 需要GPU | 无需本地资源 |
| 数据安全 | 完全本地 | 需要上传 |
| 流式翻译 | ✅ 支持 | ⚠️ 降级处理 |
| 模型质量 | 依赖本地模型 | 高质量 |
| 网络依赖 | 无 | 需要稳定网络 |

## 🔄 切换API提供商

要切换API提供商，只需修改 `config.env` 文件中的 `TRANSLATION_PROVIDER` 配置：

```env
# 使用Ollama
TRANSLATION_PROVIDER=ollama

# 或使用DeepSeek
TRANSLATION_PROVIDER=deepseek
```

重启翻译服务后，系统会自动使用新的API提供商。

## 🛠️ 故障排除

### Ollama连接失败
1. 检查Ollama服务是否启动：`ollama serve`
2. 检查模型是否下载：`ollama list`
3. 检查端口是否被占用：`netstat -tlnp | grep 11434`

### DeepSeek连接失败
1. 检查API密钥是否正确
2. 检查网络连接是否正常
3. 检查API配额是否充足

### 通用问题
1. 检查配置文件格式是否正确
2. 检查环境变量是否加载
3. 查看日志获取详细错误信息

## 📝 日志信息

翻译服务启动时会显示以下信息：
```
🚀 单条异步翻译服务已初始化
  API类型: OLLAMA
  模型: qwen3:14b
  API地址: http://localhost:11434
  处理模式: 单条异步
  上下文功能: ✅ 始终启用
  流式处理: ✅ 启用
  三步翻译法: ✅ 启用
  翻译模式: contextual_three_step
```

连接测试时会显示：
```
🔌 测试OLLAMA API连接...
  模型: qwen3:14b
  API地址: http://localhost:11434
✅ OLLAMA API连接测试成功
``` 