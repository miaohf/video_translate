import asyncio
import logging
import aiohttp
from models.api_models import CallbackData

logger = logging.getLogger(__name__)

class CallbackService:
    """回调服务"""
    
    @staticmethod
    async def send_callback(callback_url: str, data: CallbackData, max_retries: int = 3):
        """发送回调通知"""
        if not callback_url:
            return
        
        for attempt in range(max_retries):
            try:
                timeout = aiohttp.ClientTimeout(total=30)  # 30秒超时
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        callback_url, 
                        json=data.dict(),
                        headers={"Content-Type": "application/json"}
                    ) as response:
                        response_text = await response.text()
                        
                        if response.status == 200:
                            logger.info(f"✅ Callback sent successfully to {callback_url}")
                            return
                        else:
                            logger.warning(f"⚠️ Callback failed with status {response.status}, response: {response_text}")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2 ** attempt)  # 指数退避
                            
            except asyncio.TimeoutError:
                logger.error(f"⏰ Callback timeout to {callback_url} (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
            except Exception as e:
                logger.error(f"❌ Failed to send callback to {callback_url} (attempt {attempt + 1}/{max_retries}): {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
        
        logger.error(f"💥 All callback attempts failed for {callback_url}")

# 全局回调服务实例
callback_service = CallbackService() 