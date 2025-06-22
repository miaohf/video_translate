#!/usr/bin/env python3
"""
测试不同翻译模式的效果对比脚本
"""

import os
import json
import asyncio
import logging
from services.translation_service import TranslationService
from services.translation_config import TranslationConfig

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_translation_modes():
    """测试批量翻译和整体翻译模式"""
    
    # 使用示例字幕数据
    test_subtitles = [
        {
            "start": 0.0,
            "end": 5.0,
            "text": "Hello everyone, welcome to this tutorial.",
            "speaker": "Unknown"
        },
        {
            "start": 5.0,
            "end": 10.0,
            "text": "Today we will learn about video processing.",
            "speaker": "Unknown"
        },
        {
            "start": 10.0,
            "end": 15.0,
            "text": "First, let's extract the audio from the video file.",
            "speaker": "Unknown"
        },
        {
            "start": 15.0,
            "end": 20.0,
            "text": "Then we will use speech recognition to generate subtitles.",
            "speaker": "Unknown"
        },
        {
            "start": 20.0,
            "end": 25.0,
            "text": "Finally, we'll translate the subtitles to Chinese.",
            "speaker": "Unknown"
        }
    ]
    
    video_name = "translation_test"
    
    # 创建翻译服务实例
    translation_service = TranslationService()
    
    try:
        logger.info("=== 开始翻译模式对比测试 ===")
        
        # 测试批量翻译模式
        logger.info("\n1. 测试批量翻译模式 (batch)")
        batch_subtitles = await translation_service.translate_subtitles_auto(
            test_subtitles.copy(), 
            f"{video_name}_batch",
            translation_mode=TranslationConfig.TRANSLATION_MODE_BATCH
        )
        
        logger.info("批量翻译完成")
        
        # 测试整体翻译模式
        logger.info("\n2. 测试整体翻译模式 (whole)")
        whole_subtitles = await translation_service.translate_subtitles_auto(
            test_subtitles.copy(), 
            f"{video_name}_whole",
            translation_mode=TranslationConfig.TRANSLATION_MODE_WHOLE
        )
        
        logger.info("整体翻译完成")
        
        # 对比结果
        logger.info("\n=== 翻译结果对比 ===")
        
        print("\n原文 vs 批量翻译 vs 整体翻译:")
        print("-" * 120)
        print(f"{'序号':<4} | {'原文':<40} | {'批量翻译':<35} | {'整体翻译':<35}")
        print("-" * 120)
        
        for i, (original, batch, whole) in enumerate(zip(test_subtitles, batch_subtitles, whole_subtitles), 1):
            original_text = original["text"][:37] + "..." if len(original["text"]) > 40 else original["text"]
            batch_text = batch["text"][:32] + "..." if len(batch["text"]) > 35 else batch["text"]
            whole_text = whole["text"][:32] + "..." if len(whole["text"]) > 35 else whole["text"]
            
            print(f"{i:<4} | {original_text:<40} | {batch_text:<35} | {whole_text:<35}")
        
        # 保存对比结果
        comparison_data = {
            "original": test_subtitles,
            "batch_translation": batch_subtitles,
            "whole_translation": whole_subtitles,
            "test_info": {
                "test_date": "2024-06-22",
                "batch_mode": TranslationConfig.TRANSLATION_MODE_BATCH,
                "whole_mode": TranslationConfig.TRANSLATION_MODE_WHOLE
            }
        }
        
        os.makedirs("temp/translation_comparison", exist_ok=True)
        comparison_file = "temp/translation_comparison/mode_comparison.json"
        
        with open(comparison_file, 'w', encoding='utf-8') as f:
            json.dump(comparison_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"\n对比结果已保存到: {comparison_file}")
        
        # 统计翻译质量
        batch_good = sum(1 for sub in batch_subtitles if sub.get("translation_quality") == "good")
        whole_good = sum(1 for sub in whole_subtitles if sub.get("translation_quality") == "good")
        
        logger.info(f"\n翻译质量统计:")
        logger.info(f"  批量翻译 - 成功: {batch_good}/{len(batch_subtitles)} ({batch_good/len(batch_subtitles)*100:.1f}%)")
        logger.info(f"  整体翻译 - 成功: {whole_good}/{len(whole_subtitles)} ({whole_good/len(whole_subtitles)*100:.1f}%)")
        
        logger.info("\n=== 测试完成 ===")
        
    except Exception as e:
        logger.error(f"测试失败: {str(e)}")
        raise
    finally:
        await translation_service.close()

if __name__ == "__main__":
    asyncio.run(test_translation_modes())
