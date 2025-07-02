#!/usr/bin/env python3
"""
音频叠加调试工具
用于诊断和验证TTS音频文件以及音频叠加过程中的问题
"""

import os
import json
import logging
from pydub import AudioSegment
import numpy as np
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_tts_files(subtitles_file: str):
    """检查TTS音频文件的有效性"""
    
    logger.info(f"🔍 开始检查TTS音频文件...")
    
    if not os.path.exists(subtitles_file):
        logger.error(f"❌ 字幕文件不存在: {subtitles_file}")
        return
    
    with open(subtitles_file, 'r', encoding='utf-8') as f:
        subtitles = json.load(f)
    
    valid_count = 0
    total_count = len(subtitles)
    
    for i, subtitle in enumerate(subtitles):
        audio_path = subtitle.get("generated_audio")
        if not audio_path:
            logger.warning(f"⚠️ 字幕 {i+1} 缺少generated_audio字段")
            continue
            
        if not os.path.exists(audio_path):
            logger.error(f"❌ 字幕 {i+1} 音频文件不存在: {audio_path}")
            continue
        
        try:
            audio = AudioSegment.from_file(audio_path)
            file_size = os.path.getsize(audio_path)
            
            logger.info(f"✅ 字幕 {i+1}: 文件大小={file_size}字节, "
                       f"时长={audio.duration_seconds:.2f}s, "
                       f"RMS={audio.rms}, "
                       f"采样率={audio.frame_rate}Hz, "
                       f"声道={audio.channels}")
            
            # 检查是否有问题
            issues = []
            if file_size < 512:
                issues.append("文件过小")
            if audio.duration_seconds < 0.05:
                issues.append("时长过短")
            if audio.rms < 10:
                issues.append("可能静音")
            
            if issues:
                logger.warning(f"⚠️ 字幕 {i+1} 问题: {', '.join(issues)}")
            else:
                valid_count += 1
            
        except Exception as e:
            logger.error(f"❌ 字幕 {i+1} 音频文件无法加载: {e}")
    
    logger.info(f"📊 检查完成: {valid_count}/{total_count} 个音频文件有效")
    return valid_count, total_count

def test_audio_overlay(background_path: str, tts_path: str, position_ms: int = 5000):
    """测试音频叠加功能"""
    
    logger.info(f"🧪 测试音频叠加功能...")
    
    try:
        # 加载音频
        background = AudioSegment.from_file(background_path)
        tts_audio = AudioSegment.from_file(tts_path)
        
        logger.info(f"背景音频: 时长={background.duration_seconds:.2f}s, RMS={background.rms}")
        logger.info(f"TTS音频: 时长={tts_audio.duration_seconds:.2f}s, RMS={tts_audio.rms}")
        
        # 增强TTS音频
        enhanced_tts = tts_audio + 6  # 增加6dB
        logger.info(f"增强后TTS音频: RMS={enhanced_tts.rms}")
        
        # 确保格式匹配
        if enhanced_tts.frame_rate != background.frame_rate:
            enhanced_tts = enhanced_tts.set_frame_rate(background.frame_rate)
        if enhanced_tts.channels != background.channels:
            enhanced_tts = enhanced_tts.set_channels(background.channels)
        
        # 测试叠加
        original_rms = background.rms
        overlay_result = background.overlay(enhanced_tts, position=position_ms)
        final_rms = overlay_result.rms
        
        rms_change = final_rms - original_rms
        
        logger.info(f"叠加结果: RMS变化={rms_change:+.1f}")
        
        if abs(rms_change) > 1:
            logger.info("✅ 音频叠加成功！")
            
            # 保存测试结果
            test_output = "test_overlay_result.wav"
            overlay_result.export(test_output, format="wav")
            logger.info(f"📁 测试结果已保存到: {test_output}")
            
            return True
        else:
            logger.error("❌ 音频叠加失败，RMS没有明显变化")
            return False
            
    except Exception as e:
        logger.error(f"❌ 音频叠加测试失败: {e}")
        return False

def force_overlay_test(background_path: str, tts_path: str, position_ms: int = 5000):
    """强制叠加测试"""
    
    logger.info(f"🔧 测试强制叠加方法...")
    
    try:
        background = AudioSegment.from_file(background_path)
        tts_audio = AudioSegment.from_file(tts_path)
        
        # 增强TTS音频
        enhanced_tts = tts_audio + 6
        
        # 确保格式匹配
        if enhanced_tts.frame_rate != background.frame_rate:
            enhanced_tts = enhanced_tts.set_frame_rate(background.frame_rate)
        if enhanced_tts.channels != background.channels:
            enhanced_tts = enhanced_tts.set_channels(background.channels)
        
        # 强制叠加方法：分段替换
        before_segment = background[:position_ms] if position_ms > 0 else AudioSegment.empty()
        
        # 计算要替换的段落
        segment_end = min(position_ms + len(enhanced_tts), len(background))
        background_segment = background[position_ms:segment_end]
        
        after_segment = background[segment_end:] if segment_end < len(background) else AudioSegment.empty()
        
        # 降低背景音音量
        reduced_bg = background_segment - 12
        
        # 混合
        if len(enhanced_tts) > len(background_segment):
            enhanced_tts = enhanced_tts[:len(background_segment)]
        
        mixed_segment = reduced_bg.overlay(enhanced_tts)
        
        # 重新组合
        result = before_segment + mixed_segment + after_segment
        
        # 验证
        rms_change = result.rms - background.rms
        
        logger.info(f"强制叠加结果: RMS变化={rms_change:+.1f}")
        
        if abs(rms_change) > 0.5:
            logger.info("✅ 强制叠加成功！")
            
            # 保存测试结果
            test_output = "test_force_overlay_result.wav"
            result.export(test_output, format="wav")
            logger.info(f"📁 强制叠加结果已保存到: {test_output}")
            
            return True
        else:
            logger.error("❌ 强制叠加失败")
            return False
            
    except Exception as e:
        logger.error(f"❌ 强制叠加测试失败: {e}")
        return False

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("使用方法:")
        print("  python audio_debug.py check <字幕文件.json>")
        print("  python audio_debug.py test <背景音频> <TTS音频> [位置ms]")
        print("  python audio_debug.py force <背景音频> <TTS音频> [位置ms]")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "check" and len(sys.argv) >= 3:
        subtitles_file = sys.argv[2]
        check_tts_files(subtitles_file)
        
    elif command == "test" and len(sys.argv) >= 4:
        background_path = sys.argv[2]
        tts_path = sys.argv[3]
        position_ms = int(sys.argv[4]) if len(sys.argv) > 4 else 5000
        
        if test_audio_overlay(background_path, tts_path, position_ms):
            print("✅ 标准叠加测试通过")
        else:
            print("❌ 标准叠加测试失败")
            
    elif command == "force" and len(sys.argv) >= 4:
        background_path = sys.argv[2]
        tts_path = sys.argv[3]
        position_ms = int(sys.argv[4]) if len(sys.argv) > 4 else 5000
        
        if force_overlay_test(background_path, tts_path, position_ms):
            print("✅ 强制叠加测试通过")
        else:
            print("❌ 强制叠加测试失败")
            
    else:
        print("❌ 无效的命令或参数不足")
        sys.exit(1) 