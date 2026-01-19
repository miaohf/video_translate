#!/usr/bin/env python3
"""
测试批量翻译功能（使用实际的 TranslationService）
"""

import asyncio
import logging
import time
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.DEBUG,  # 使用 DEBUG 级别查看详细日志
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 设置第三方库日志级别
logging.getLogger("httpx").setLevel(logging.WARNING)  # 减少 httpx 噪音
logging.getLogger("httpcore").setLevel(logging.WARNING)


# 测试字幕数据
TEST_SUBTITLES = [
    {"id": 1, "start": 0.0, "end": 3.0, "text": "Hello, welcome to our documentary about artificial intelligence."},
    {"id": 2, "start": 3.5, "end": 6.5, "text": "Machine learning is transforming our world in many ways."},
    {"id": 3, "start": 7.0, "end": 10.0, "text": "Deep neural networks can process complex patterns."},
    {"id": 4, "start": 10.5, "end": 14.0, "text": "Artificial intelligence has many applications in healthcare."},
    {"id": 5, "start": 14.5, "end": 18.0, "text": "Self-driving cars rely on computer vision and AI."},
    {"id": 6, "start": 18.5, "end": 22.0, "text": "Natural language processing helps computers understand human speech."},
    {"id": 7, "start": 22.5, "end": 26.0, "text": "AI is being used to solve climate change problems."},
    {"id": 8, "start": 26.5, "end": 30.0, "text": "Robotics and AI are revolutionizing manufacturing."},
    {"id": 9, "start": 30.5, "end": 34.0, "text": "The future of AI is both exciting and challenging."},
    {"id": 10, "start": 34.5, "end": 38.0, "text": "We must ensure AI is developed responsibly and ethically."},
]


async def progress_callback(progress: int, message: str):
    """进度回调"""
    logger.info(f"  进度: {progress}% - {message}")


async def test_batch_mode():
    """测试批量翻译模式"""
    from services.translation_service import TranslationService
    
    logger.info("=" * 60)
    logger.info("🚀 测试批量翻译模式")
    logger.info("=" * 60)
    
    service = TranslationService()
    
    try:
        # 复制测试数据
        subtitles = [s.copy() for s in TEST_SUBTITLES]
        
        start_time = time.time()
        
        # 使用批量模式翻译
        result = await service.translate_subtitles(
            subtitles,
            progress_callback=progress_callback,
            use_batch_mode=True
        )
        
        elapsed = time.time() - start_time
        
        logger.info(f"\n📊 批量翻译完成，耗时: {elapsed:.2f}s")
        logger.info(f"平均: {elapsed/len(subtitles):.2f}s/条")
        
        # 显示结果
        success_count = 0
        logger.info("\n翻译结果:")
        for sub in result:
            original = sub.get('original_text', sub.get('text', ''))[:40]
            translated = sub.get('text', '')[:40]
            failed = sub.get('translation_failed', False)
            status = "❌" if failed else "✅"
            logger.info(f"  {status} [{sub['id']}] {original}... → {translated}...")
            if not failed:
                success_count += 1
        
        logger.info(f"\n成功率: {success_count}/{len(result)} ({success_count/len(result)*100:.1f}%)")
        
        return elapsed, success_count
        
    finally:
        await service.close()


async def test_sequential_mode():
    """测试逐条翻译模式（对照组）"""
    from services.translation_service import TranslationService
    
    logger.info("=" * 60)
    logger.info("🚀 测试逐条翻译模式（对照组）")
    logger.info("=" * 60)
    
    service = TranslationService()
    
    try:
        # 复制测试数据
        subtitles = [s.copy() for s in TEST_SUBTITLES]
        
        start_time = time.time()
        
        # 使用逐条模式翻译
        result = await service.translate_subtitles(
            subtitles,
            progress_callback=progress_callback,
            use_batch_mode=False
        )
        
        elapsed = time.time() - start_time
        
        logger.info(f"\n📊 逐条翻译完成，耗时: {elapsed:.2f}s")
        logger.info(f"平均: {elapsed/len(subtitles):.2f}s/条")
        
        # 显示结果
        success_count = 0
        logger.info("\n翻译结果:")
        for sub in result:
            original = sub.get('original_text', sub.get('text', ''))[:40]
            translated = sub.get('text', '')[:40]
            failed = sub.get('translation_failed', False)
            status = "❌" if failed else "✅"
            logger.info(f"  {status} [{sub['id']}] {original}... → {translated}...")
            if not failed:
                success_count += 1
        
        logger.info(f"\n成功率: {success_count}/{len(result)} ({success_count/len(result)*100:.1f}%)")
        
        return elapsed, success_count
        
    finally:
        await service.close()


async def main():
    """主函数"""
    logger.info("🎯 开始测试翻译服务")
    logger.info(f"测试字幕数: {len(TEST_SUBTITLES)} 条\n")
    
    # 测试批量模式
    batch_time, batch_success = await test_batch_mode()
    
    logger.info("\n" + "=" * 60)
    
    # 测试逐条模式
    seq_time, seq_success = await test_sequential_mode()
    
    # 对比
    logger.info("\n" + "=" * 60)
    logger.info("📈 对比结果")
    logger.info("=" * 60)
    logger.info(f"批量模式: {batch_time:.2f}s ({batch_success}/{len(TEST_SUBTITLES)} 成功)")
    logger.info(f"逐条模式: {seq_time:.2f}s ({seq_success}/{len(TEST_SUBTITLES)} 成功)")
    
    if batch_time < seq_time:
        speedup = seq_time / batch_time
        logger.info(f"🚀 批量模式加速比: {speedup:.2f}x")
    else:
        logger.info(f"⚠️ 批量模式未能加速")


if __name__ == "__main__":
    asyncio.run(main())

