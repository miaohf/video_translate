import asyncio
import argparse
import logging
from core.client import VideoTranslationClient

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def create_parser() -> argparse.ArgumentParser:
    """
    创建命令行参数解析器
    
    返回:
        配置好的参数解析器
    """
    parser = argparse.ArgumentParser(description="Video Translation Program")
    parser.add_argument("--input_video", required=True, help="Input Video File Path")
    return parser

async def main():
    """主程序入口"""
    try:
        # 解析命令行参数
        parser = create_parser()
        args = parser.parse_args()
        
        # 创建视频翻译客户端
        client = VideoTranslationClient()
        
        # 处理视频
        await client.process_video(args.input_video)
        
    except Exception as e:
        logger.error(f"程序执行失败: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(main())