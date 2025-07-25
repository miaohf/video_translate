#!/usr/bin/env python3
"""
测试API连接脚本
用于验证Ollama和DeepSeek API连接功能
"""

import asyncio
import logging
from services.translation_service import TranslationService
from config import settings

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_api_connection():
    """测试API连接"""
    logger.info("🚀 开始API连接测试")
    
    # 打印当前配置
    logger.info(f"📋 当前配置:")
    logger.info(f"  翻译提供商: {settings.TRANSLATION_PROVIDER}")
    logger.info(f"  Ollama模型: {settings.OLLAMA_MODEL}")
    logger.info(f"  Ollama API: {settings.OLLAMA_API_URL}")
    logger.info(f"  DeepSeek模型: {settings.DEEPSEEK_MODEL}")
    logger.info(f"  DeepSeek API: {settings.DEEPSEEK_API_URL}")
    logger.info(f"  DeepSeek密钥: {'已配置' if settings.DEEPSEEK_API_KEY else '未配置'}")
    
    try:
        # 初始化翻译服务
        translator = TranslationService()
        
        # 测试连接
        logger.info("\n🔌 开始连接测试...")
        success = await translator.test_connection()
        
        if success:
            logger.info("✅ API连接测试成功!")
            
            # 测试简单翻译
            logger.info("\n🌍 开始简单翻译测试...")
            test_text = "Hello, how are you today?"
            translated = await translator.translate_single_subtitle(test_text)
            logger.info(f"原文: {test_text}")
            logger.info(f"译文: {translated}")
            
        else:
            logger.error("❌ API连接测试失败!")
            
    except Exception as e:
        logger.error(f"❌ 测试过程中发生错误: {str(e)}")
    
    finally:
        # 关闭连接
        await translator.close()

if __name__ == "__main__":
    asyncio.run(test_api_connection()) 