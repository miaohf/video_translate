#!/usr/bin/env python3
"""
测试多文件上传功能
"""

import requests
import os

def test_multiple_file_upload():
    """测试多文件上传"""
    url = "http://localhost:9000/translate"
    
    # 创建测试文件
    test_files = {
        "audio_file": ("test_audio.wav", b"fake audio data", "audio/wav"),
        "voice_role_files": [
            ("voice_role_1.wav", b"fake voice role 1", "audio/wav"),
            ("voice_role_2.wav", b"fake voice role 2", "audio/wav")
        ]
    }
    
    # 准备表单数据
    data = {
        "video_id": "999",
        "callback_url": "http://localhost:7000/callback"
    }
    
    # 准备文件数据 - 正确的方式
    files = {
        "audio_file": test_files["audio_file"]
    }
    
    # 添加多个角色音频文件 - 每个文件都需要使用相同的字段名
    for role_file in test_files["voice_role_files"]:
        files["voice_role_files"] = role_file
    
    print(f"准备上传 {len(test_files['voice_role_files'])} 个角色音频文件")
    print(f"文件列表: {list(files.keys())}")
    
    try:
        response = requests.post(url, files=files, data=data)
        print(f"响应状态码: {response.status_code}")
        print(f"响应内容: {response.json()}")
    except Exception as e:
        print(f"请求失败: {e}")

def test_single_voice_role_file():
    """测试单个角色音频文件上传"""
    url = "http://localhost:9000/translate"
    
    # 准备表单数据
    data = {
        "video_id": "998",
        "callback_url": "http://localhost:7000/callback"
    }
    
    # 准备文件数据 - 单个文件也使用voice_role_files字段
    files = {
        "audio_file": ("test_audio.wav", b"fake audio data", "audio/wav"),
        "voice_role_files": ("voice_role_1.wav", b"fake voice role 1", "audio/wav")  # 单个文件
    }
    
    print("准备上传单个角色音频文件")
    print(f"文件列表: {list(files.keys())}")
    
    try:
        response = requests.post(url, files=files, data=data)
        print(f"响应状态码: {response.status_code}")
        print(f"响应内容: {response.json()}")
    except Exception as e:
        print(f"请求失败: {e}")

def test_correct_multiple_upload():
    """测试正确的多文件上传方式"""
    url = "http://localhost:9000/translate"
    
    # 准备表单数据
    data = {
        "video_id": "997",
        "callback_url": "http://localhost:7000/callback"
    }
    
    # 正确的方式：使用列表
    files = {
        "audio_file": ("test_audio.wav", b"fake audio data", "audio/wav"),
    }
    
    # 添加多个角色音频文件
    for role_file in [
        ("voice_role_1.wav", b"fake voice role 1", "audio/wav"),
        ("voice_role_2.wav", b"fake voice role 2", "audio/wav")
    ]:
        files["voice_role_files"] = role_file
    
    print("准备上传多个角色音频文件（正确方式）")
    print(f"文件列表: {list(files.keys())}")
    
    try:
        response = requests.post(url, files=files, data=data)
        print(f"响应状态码: {response.status_code}")
        print(f"响应内容: {response.json()}")
    except Exception as e:
        print(f"请求失败: {e}")

if __name__ == "__main__":
    print("=== 测试多文件上传（循环方式） ===")
    test_multiple_file_upload()
    print("\n=== 测试单个文件上传 ===")
    test_single_voice_role_file()
    print("\n=== 测试多文件上传（列表方式） ===")
    test_correct_multiple_upload() 