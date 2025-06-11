#!/usr/bin/env python3
"""
测试背景音频混合功能的脚本
"""

import os
import json
import asyncio
import logging
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_background_mixing():
    """测试背景音频混合功能"""
    try:
        # 导入主程序
        from main import VideoTranslationClient
        
        # 测试参数
        video_name = "Mass Protests in Taipei"
        subtitle_path = "temp/Mass Protests in Taipei/backup/4f8e94df15a501a6c912_subtitles_zh.json"
        background_audio_path = "temp/Mass Protests in Taipei/4f8e94df15a501a6c912_audio.mp3"
        
        # 检查文件是否存在
        if not os.path.exists(subtitle_path):
            logger.error(f"字幕文件不存在: {subtitle_path}")
            return
            
        if not os.path.exists(background_audio_path):
            logger.error(f"背景音频文件不存在: {background_audio_path}")
            return
        
        # 读取字幕文件
        logger.info("读取字幕文件...")
        with open(subtitle_path, 'r', encoding='utf-8') as f:
            subtitles = json.load(f)
        
        logger.info(f"加载了 {len(subtitles)} 条字幕")
        
        # 检查字幕是否包含reference_audio字段
        has_reference_audio = any('reference_audio' in subtitle for subtitle in subtitles)
        logger.info(f"字幕包含参考音频: {has_reference_audio}")
        
        # 只取前3条字幕进行测试（模拟generated_audio）
        test_subtitles = subtitles[:3]
        
        # 为测试字幕添加模拟的generated_audio信息
        temp_dir = os.path.join("temp", video_name, "test_tts_segments")
        os.makedirs(temp_dir, exist_ok=True)
        
        for i, subtitle in enumerate(test_subtitles):
            # 创建模拟的TTS音频文件路径
            mock_audio_path = os.path.join(temp_dir, f"mock_segment_{i:04d}.wav")
            
            # 如果模拟文件不存在，创建一个短的静音文件作为测试
            if not os.path.exists(mock_audio_path):
                from pydub import AudioSegment
                # 创建2秒的静音作为模拟TTS音频
                mock_audio = AudioSegment.silent(duration=2000)  # 2秒
                mock_audio.export(mock_audio_path, format="wav")
                logger.info(f"创建模拟TTS音频: {mock_audio_path}")
            
            # 添加generated_audio信息
            subtitle["generated_audio"] = mock_audio_path
            subtitle["generated_duration"] = 2.0  # 2秒
        
        logger.info(f"准备测试前 {len(test_subtitles)} 条字幕")
        
        # 显示测试字幕信息
        for i, subtitle in enumerate(test_subtitles):
            logger.info(f"字幕 {i}: {subtitle['start']:.2f}s - {subtitle['end']:.2f}s")
            logger.info(f"  原文: {subtitle['text'][:50]}...")
            if 'translated_text' in subtitle:
                logger.info(f"  译文: {subtitle['translated_text'][:50]}...")
            logger.info(f"  TTS文件: {subtitle.get('generated_audio', 'None')}")
        
        # 初始化视频翻译客户端
        client = VideoTranslationClient()
        
        # 测试音频混合
        output_path = os.path.join("temp", video_name, "test_mixed_audio.wav")
        logger.info("开始测试音频混合...")
        
        result_path = await client._mix_audio_with_background(
            test_subtitles,
            background_audio_path,
            output_path
        )
        
        if os.path.exists(result_path):
            # 获取输出文件信息
            from pydub import AudioSegment
            output_audio = AudioSegment.from_file(result_path)
            file_size = os.path.getsize(result_path) / (1024 * 1024)  # MB
            
            logger.info(f"✅ 测试成功！")
            logger.info(f"输出文件: {result_path}")
            logger.info(f"文件大小: {file_size:.2f} MB")
            logger.info(f"音频时长: {output_audio.duration_seconds:.2f} 秒")
            logger.info(f"采样率: {output_audio.frame_rate} Hz")
            logger.info(f"声道数: {output_audio.channels}")
        else:
            logger.error("❌ 测试失败：输出文件不存在")
        
    except Exception as e:
        logger.error(f"测试失败: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_background_mixing()) 