#!/usr/bin/env python3
"""
测试翻译服务修复效果的脚本
"""

import asyncio
import logging
from services.translation_service import TranslationService

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_translation_service():
    """测试翻译服务"""
    print("🧪 开始测试翻译服务...")
    
    # 创建翻译服务实例
    translation_service = TranslationService(batch_size=1)
    
    try:
        # 1. 测试连接
        print("\n1️⃣ 测试API连接...")
        is_connected = await translation_service.test_connection()
        if not is_connected:
            print("❌ API连接失败，请检查Ollama服务")
            return False
        print("✅ API连接成功")
        
        # 2. 测试单批次翻译
        print("\n2️⃣ 测试单批次翻译...")
        test_texts = ["Hello, this is a test for translation."]
        try:
            translated_texts = await translation_service.translate_batch(test_texts)
            print(f"原文: {test_texts[0]}")
            print(f"译文: {translated_texts[0]}")
            print("✅ 单批次翻译成功")
        except Exception as e:
            print(f"❌ 单批次翻译失败: {e}")
            return False
        
        # 3. 测试多批次翻译
        print("\n3️⃣ 测试多批次翻译...")
        test_subtitles = [
            {"start": 0, "end": 2, "text": "Hello world."},
            {"start": 2, "end": 4, "text": "This is a test."},
            {"start": 4, "end": 6, "text": "How are you today?"},
        ]
        
        try:
            result = await translation_service.translate_subtitles(
                subtitles=test_subtitles,
                video_name="test_video"
            )
            print(f"✅ 多批次翻译成功，处理了 {len(result)} 条字幕")
            for i, subtitle in enumerate(result[:3]):  # 只显示前3条
                print(f"  {i+1}. 原文: {subtitle.get('original_text', '')}")
                print(f"     译文: {subtitle.get('text', '')}")
        except Exception as e:
            print(f"❌ 多批次翻译失败: {e}")
            return False
        
        print("\n🎉 所有测试通过！翻译服务工作正常。")
        return True
        
    except Exception as e:
        print(f"❌ 测试过程中发生异常: {e}")
        return False
        
    finally:
        # 确保清理资源
        await translation_service.close()

async def main():
    """主函数"""
    print("🦙 翻译服务连接修复测试")
    print("=" * 50)
    
    success = await test_translation_service()
    
    print("\n" + "=" * 50)
    if success:
        print("✅ 测试结果: 翻译服务修复成功！")
        print("\n💡 建议:")
        print("1. 重新启动您的视频翻译服务")
        print("2. 如果问题仍然存在，检查Ollama模型是否正确加载")
    else:
        print("❌ 测试结果: 仍存在问题")
        print("\n🔧 故障排除:")
        print("1. 确保Ollama服务正在运行: curl http://localhost:11434/api/tags")
        print("2. 检查模型是否已下载: ollama list")
        print("3. 检查防火墙设置")

if __name__ == "__main__":
    asyncio.run(main()) 