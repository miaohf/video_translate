#!/bin/bash

# 视频翻译API测试脚本
echo "🚀 开始测试视频翻译API..."

# 服务器地址
API_BASE="http://localhost:8001"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 测试函数
test_endpoint() {
    local method=$1
    local endpoint=$2
    local data=$3
    local description=$4
    
    echo -e "\n${BLUE}📋 测试: $description${NC}"
    echo -e "${YELLOW}请求: $method $endpoint${NC}"
    
    if [ -n "$data" ]; then
        echo -e "${YELLOW}数据: $data${NC}"
        response=$(curl -s -w "\n%{http_code}" -X $method "$API_BASE$endpoint" \
            -H "Content-Type: application/json" \
            -d "$data")
    else
        response=$(curl -s -w "\n%{http_code}" -X $method "$API_BASE$endpoint")
    fi
    
    # 分离响应体和状态码
    status_code=$(echo "$response" | tail -n1)
    response_body=$(echo "$response" | head -n -1)
    
    echo -e "${YELLOW}响应状态码: $status_code${NC}"
    echo -e "${YELLOW}响应内容:${NC}"
    echo "$response_body" | python3 -m json.tool 2>/dev/null || echo "$response_body"
    
    if [ "$status_code" -ge 200 ] && [ "$status_code" -lt 300 ]; then
        echo -e "${GREEN}✅ 测试通过${NC}"
        return 0
    else
        echo -e "${RED}❌ 测试失败${NC}"
        return 1
    fi
}

# 1. 健康检查
test_endpoint "GET" "/health" "" "健康检查"

# 2. 查看所有任务
test_endpoint "GET" "/tasks" "" "查看所有任务"

# 3. 启动翻译任务
echo -e "\n${BLUE}🎬 准备启动翻译任务...${NC}"
echo "请确保有测试视频文件，或修改下面的video_file_path路径"

translate_data='{
    "video_id": 123,
    "video_file_path": "videos/sample.mp4",
    "callback_url": "http://localhost:8000/callback",
    "source_language": "en",
    "target_language": "zh",
    "voice_type": "female",
    "voice_speed": 1.0
}'

if test_endpoint "POST" "/translate" "$translate_data" "启动翻译任务"; then
    # 提取task_id (假设返回的JSON中包含task_id)
    task_id=$(echo "$response_body" | python3 -c "import json,sys; data=json.load(sys.stdin); print(data.get('task_id', ''))" 2>/dev/null)
    
    if [ -n "$task_id" ]; then
        echo -e "\n${GREEN}📝 获取到任务ID: $task_id${NC}"
        
        # 4. 查询任务状态
        sleep 2
        test_endpoint "GET" "/tasks/$task_id/status" "" "查询任务状态"
        
        # 5. 取消任务 (可选，取消注释来测试)
        echo -e "\n${YELLOW}⚠️  是否要取消任务？(y/N)${NC}"
        read -t 10 -n 1 cancel_choice
        if [ "$cancel_choice" = "y" ] || [ "$cancel_choice" = "Y" ]; then
            test_endpoint "POST" "/tasks/$task_id/cancel" "" "取消任务"
        else
            echo -e "\n${BLUE}ℹ️  保持任务继续运行...${NC}"
        fi
    else
        echo -e "${RED}❌ 未能获取任务ID${NC}"
    fi
fi

# 6. 再次查看所有任务
echo -e "\n${BLUE}📋 最终任务列表:${NC}"
test_endpoint "GET" "/tasks" "" "查看所有任务"

echo -e "\n${GREEN}🎉 API测试完成！${NC}"

# 额外的测试命令示例
echo -e "\n${BLUE}📚 其他有用的curl命令:${NC}"
echo "1. 测试API文档访问:"
echo "   curl -I http://localhost:8001/docs"
echo ""
echo "2. 下载翻译后的文件 (需要实际的文件名):"
echo "   curl -O http://localhost:8001/files/123_translated_audio.wav"
echo ""
echo "3. 简单的健康检查:"
echo "   curl http://localhost:8001/health"
echo ""
echo "4. 查看特定任务 (替换TASK_ID):"
echo "   curl http://localhost:8001/tasks/TASK_ID/status" 