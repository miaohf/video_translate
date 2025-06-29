#!/bin/bash

# Ollama API 测试脚本
echo "🦙 开始测试 Ollama API..."

# 服务器地址
OLLAMA_BASE="http://localhost:11434"
MODEL_NAME="qwen3:14b"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 测试函数
test_ollama_endpoint() {
    local method=$1
    local endpoint=$2
    local data=$3
    local description=$4
    local timeout=${5:-30}
    
    echo -e "\n${BLUE}🔍 测试: $description${NC}"
    echo -e "${YELLOW}请求: $method $endpoint${NC}"
    
    if [ -n "$data" ]; then
        echo -e "${YELLOW}数据: $data${NC}"
        response=$(timeout ${timeout}s curl -s -w "\n%{http_code}" -X $method "$OLLAMA_BASE$endpoint" \
            -H "Content-Type: application/json" \
            -d "$data" 2>/dev/null)
    else
        response=$(timeout ${timeout}s curl -s -w "\n%{http_code}" -X $method "$OLLAMA_BASE$endpoint" 2>/dev/null)
    fi
    
    if [ $? -eq 124 ]; then
        echo -e "${RED}⏰ 请求超时 (${timeout}s)${NC}"
        return 1
    fi
    
    # 分离响应体和状态码
    status_code=$(echo "$response" | tail -n1)
    response_body=$(echo "$response" | head -n -1)
    
    echo -e "${YELLOW}响应状态码: $status_code${NC}"
    echo -e "${YELLOW}响应内容:${NC}"
    
    # 尝试格式化JSON，如果失败就直接输出
    echo "$response_body" | python3 -m json.tool 2>/dev/null || echo "$response_body"
    
    if [ "$status_code" -ge 200 ] && [ "$status_code" -lt 300 ]; then
        echo -e "${GREEN}✅ 测试通过${NC}"
        return 0
    else
        echo -e "${RED}❌ 测试失败${NC}"
        return 1
    fi
}

# 1. 检查Ollama服务是否运行
echo -e "${BLUE}🚀 检查 Ollama 服务状态...${NC}"
test_ollama_endpoint "GET" "/" "" "Ollama 服务健康检查"

# 2. 列出所有可用模型
test_ollama_endpoint "GET" "/api/tags" "" "列出所有可用模型"

# 3. 显示特定模型信息
show_data="{\"name\": \"$MODEL_NAME\"}"
test_ollama_endpoint "POST" "/api/show" "$show_data" "显示模型 $MODEL_NAME 信息"

# 4. 测试文本生成 (简单测试)
echo -e "\n${BLUE}📝 测试文本生成功能...${NC}"
generate_data="{
    \"model\": \"$MODEL_NAME\",
    \"prompt\": \"你好，请用中文回答：什么是人工智能？\",
    \"stream\": false,
    \"options\": {
        \"temperature\": 0.8,
        \"top_k\": 50,
        \"top_p\": 0.95
    }
}"

test_ollama_endpoint "POST" "/api/generate" "$generate_data" "生成文本回答" 60

# 5. 测试聊天对话
echo -e "\n${BLUE}💬 测试聊天对话功能...${NC}"
chat_data="{
    \"model\": \"$MODEL_NAME\",
    \"messages\": [
        {
            \"role\": \"user\",
            \"content\": \"请简单介绍一下你自己，用中文回答。\"
        }
    ],
    \"stream\": false,
    \"options\": {
        \"temperature\": 0.8
    }
}"

test_ollama_endpoint "POST" "/api/chat" "$chat_data" "聊天对话测试" 60

# 6. 测试翻译功能（模拟项目中的使用场景）
echo -e "\n${BLUE}🌐 测试翻译功能...${NC}"
translation_prompt="请将以下英文文本翻译成中文，只返回翻译结果，不要包含其他解释：

Hello, this is a test for translation. How are you today?"

translation_data="{
    \"model\": \"$MODEL_NAME\",
    \"prompt\": \"$translation_prompt\",
    \"stream\": false,
    \"options\": {
        \"temperature\": 0.3,
        \"top_k\": 40,
        \"top_p\": 0.9
    }
}"

test_ollama_endpoint "POST" "/api/generate" "$translation_data" "英译中翻译测试" 60

# 7. 检查模型是否需要下载
echo -e "\n${BLUE}📥 检查模型状态...${NC}"
echo "如果模型不存在，可以使用以下命令下载："
echo "curl -X POST $OLLAMA_BASE/api/pull -d '{\"name\": \"$MODEL_NAME\"}'"

# 8. 测试流式响应（可选）
echo -e "\n${BLUE}🌊 测试流式响应...${NC}"
stream_data="{
    \"model\": \"$MODEL_NAME\",
    \"prompt\": \"请数数1到5，每个数字占一行。\",
    \"stream\": true
}"

echo "流式响应测试（前10行）:"
curl -s -X POST "$OLLAMA_BASE/api/generate" \
    -H "Content-Type: application/json" \
    -d "$stream_data" | head -10

echo -e "\n${GREEN}🎉 Ollama API 测试完成！${NC}"

# 显示额外的有用命令
echo -e "\n${BLUE}📚 其他有用的 Ollama 命令:${NC}"
echo ""
echo "1. 下载新模型:"
echo "   curl -X POST $OLLAMA_BASE/api/pull -d '{\"name\": \"llama2\"}'"
echo ""
echo "2. 删除模型:"
echo "   curl -X DELETE $OLLAMA_BASE/api/delete -d '{\"name\": \"model_name\"}'"
echo ""
echo "3. 复制模型:"
echo "   curl -X POST $OLLAMA_BASE/api/copy -d '{\"source\": \"llama2\", \"destination\": \"my-llama2\"}'"
echo ""
echo "4. 检查特定模型信息:"
echo "   curl -X POST $OLLAMA_BASE/api/show -d '{\"name\": \"$MODEL_NAME\"}' | jq ."
echo ""
echo "5. 流式聊天:"
echo "   curl -X POST $OLLAMA_BASE/api/chat -d '{\"model\":\"$MODEL_NAME\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}],\"stream\":true}'"
echo ""
echo "6. 获取模型嵌入向量:"
echo "   curl -X POST $OLLAMA_BASE/api/embeddings -d '{\"model\":\"$MODEL_NAME\",\"prompt\":\"Hello world\"}'"

# 显示项目配置检查
echo -e "\n${BLUE}🔧 项目配置检查:${NC}"
echo "运行以下命令检查项目中的ollama配置："
echo "python check_config.py" 