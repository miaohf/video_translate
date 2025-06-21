#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
from pathlib import Path

def generate_videos_json():
    """
    扫描videos文件夹中的视频文件，生成videos.json配置文件
    """
    # 视频文件夹路径
    videos_dir = Path('./videos')
    
    # 支持的视频格式
    video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.wmv', '.m4v'}
    
    # 检查videos文件夹是否存在
    if not videos_dir.exists():
        print(f"错误：videos文件夹不存在 ({videos_dir.absolute()})")
        return
    
    # 扫描视频文件
    video_files = []
    for file_path in videos_dir.iterdir():
        if file_path.is_file() and file_path.suffix.lower() in video_extensions:
            # 生成相对路径
            relative_path = f"./videos/{file_path.name}"
            video_files.append({"videoUrl": relative_path})
    
    # 按文件名排序
    video_files.sort(key=lambda x: x['videoUrl'])
    
    # 生成JSON
    json_output = json.dumps(video_files, ensure_ascii=False, indent=2)
       
    # 写入JSON文件
    output_file = './videos.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(json_output)
    
    print(f"✅ 成功生成 {output_file}")
    print(f"📺 找到 {len(video_files)} 个视频文件:")
    for video in video_files:
        print(f"   - {video['videoUrl']}")

if __name__ == "__main__":
    generate_videos_json() 