#!/usr/bin/env python3
"""
总结功能使用示例
演示如何使用新增的summarize字段来生成视频内容总结
"""

import requests
import json
import time

# 配置
API_BASE_URL = "http://localhost:9000"
TEST_VIDEO_PATH = "/path/to/test/video.mp4"

def example_with_summary():
    """示例：启用总结功能的翻译请求"""
    print("📝 启用总结功能的翻译请求")
    
    url = f"{API_BASE_URL}/translate"
    data = {
        "video_file_path": TEST_VIDEO_PATH,
        "summarize": True,  # 启用总结功能
        "callback_url": "http://localhost:7000/callback"
    }
    
    try:
        response = requests.post(url, json=data)
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ 请求成功: {json.dumps(result, indent=2, ensure_ascii=False)}")
            
            if result.get("success"):
                task_id = result["task_id"]
                print(f"🎯 任务ID: {task_id}")
                
                # 监控任务进度
                monitor_task_progress(task_id)
                
                # 获取总结
                get_task_summary(task_id)
                
        else:
            print(f"❌ HTTP错误: {response.status_code}")
            
    except Exception as e:
        print(f"❌ 请求失败: {str(e)}")

def monitor_task_progress(task_id: str):
    """监控任务进度"""
    print(f"⏳ 监控任务进度: {task_id}")
    
    while True:
        try:
            status_url = f"{API_BASE_URL}/tasks/{task_id}/status"
            response = requests.get(status_url)
            
            if response.status_code == 200:
                task_data = response.json()
                status = task_data["status"]
                progress = task_data["progress"]
                current_step = task_data["current_step"]
                
                print(f"📊 状态: {status} | 进度: {progress}% | 步骤: {current_step}")
                
                # 检查总结信息
                if "summary_url" in task_data and task_data["summary_url"]:
                    print(f"📄 总结URL: {task_data['summary_url']}")
                
                if status == "completed":
                    print(f"✅ 任务完成!")
                    return task_data
                elif status == "failed":
                    print(f"❌ 任务失败: {task_data.get('error_message', 'Unknown error')}")
                    return task_data
                    
        except Exception as e:
            print(f"❌ 查询任务状态时发生错误: {str(e)}")
        
        time.sleep(5)

def get_task_summary(task_id: str):
    """获取任务总结"""
    print(f"📄 获取任务总结: {task_id}")
    
    try:
        summary_url = f"{API_BASE_URL}/tasks/{task_id}/summary"
        response = requests.get(summary_url)
        
        if response.status_code == 200:
            summary_data = response.json()
            print(f"✅ 总结获取成功: {json.dumps(summary_data, indent=2, ensure_ascii=False)}")
        elif response.status_code == 404:
            print(f"⚠️  总结不存在: {response.json()}")
        else:
            print(f"❌ HTTP错误: {response.status_code}")
            
    except Exception as e:
        print(f"❌ 获取总结失败: {str(e)}")

if __name__ == "__main__":
    example_with_summary() 