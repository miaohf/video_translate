#!/usr/bin/env python3
"""
音频修复验证脚本
"""
import os
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def find_latest_subtitle_file():
    """查找最新的字幕文件"""
    temp_dirs = [d for d in os.listdir('temp') if os.path.isdir(os.path.join('temp', d))]
    
    for temp_dir in temp_dirs:
        subtitle_files = []
        dir_path = os.path.join('temp', temp_dir)
        
        for file in os.listdir(dir_path):
            if file.endswith('_subtitles_zh.json'):
                subtitle_files.append(os.path.join(dir_path, file))
        
        if subtitle_files:
            # 返回最新的文件
            latest_file = max(subtitle_files, key=os.path.getctime)
            return latest_file
    
    return None

def check_tts_audio_files(subtitle_file):
    """检查TTS音频文件"""
    logger.info(f"🔍 检查字幕文件: {subtitle_file}")
    
    with open(subtitle_file, 'r', encoding='utf-8') as f:
        subtitles = json.load(f)
    
    valid_count = 0
    total_count = len(subtitles)
    
    for i, subtitle in enumerate(subtitles):
        audio_path = subtitle.get("generated_audio")
        if audio_path and os.path.exists(audio_path):
            try:
                from pydub import AudioSegment
                audio = AudioSegment.from_file(audio_path)
                file_size = os.path.getsize(audio_path)
                
                logger.info(f"✅ 音频 {i+1}: 大小={file_size}字节, "
                           f"时长={audio.duration_seconds:.2f}s, RMS={audio.rms}")
                valid_count += 1
            except:
                logger.error(f"❌ 音频 {i+1}: 文件损坏")
        else:
            logger.warning(f"⚠️ 音频 {i+1}: 文件不存在")
    
    logger.info(f"📊 结果: {valid_count}/{total_count} 个音频文件有效")
    return valid_count > 0

if __name__ == "__main__":
    subtitle_file = find_latest_subtitle_file()
    if subtitle_file:
        logger.info(f"找到字幕文件: {subtitle_file}")
        if check_tts_audio_files(subtitle_file):
            print("✅ TTS音频文件检查通过，可以继续处理")
        else:
            print("❌ TTS音频文件有问题，需要重新生成")
    else:
        print("❌ 未找到字幕文件")
