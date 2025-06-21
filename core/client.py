import logging
import platform
from services.translation_service import TranslationService
from processors.audio_processor import AudioProcessor
from processors.subtitle_processor import SubtitleProcessor
from processors.video_processor import VideoProcessor
from config import settings
from utils.file_manager import FileManager
from .workflow import VideoWorkflow

logger = logging.getLogger(__name__)

class VideoTranslationClient:
    """视频翻译客户端"""
    
    def __init__(self):
        """
        初始化视频翻译客户端
        """      
        # 初始化各个处理器
        self.translation_service = TranslationService()
        self.audio_processor = AudioProcessor(settings.STT_SERVER_URL, settings.TTS_SERVER_URL)
        self.subtitle_processor = SubtitleProcessor(settings.STT_SERVER_URL)
        self.video_processor = VideoProcessor()
        
        # 初始化工作流程编排器
        self.workflow = VideoWorkflow(
            self.translation_service,
            self.audio_processor,
            self.subtitle_processor,
            self.video_processor
        )
        
        # 打印环境信息
        logger.info(f"System Info:")
        logger.info(f"- OS: {platform.system()} {platform.release()}")
        logger.info(f"- Python Version: {platform.python_version()}")
        
        # 确保temp目录存在
        FileManager.ensure_temp_dir()
    
    async def process_video(self, video_path: str, output_path: str = None):
        """
        处理视频
        
        参数:
            video_path: 视频文件路径
            output_path: 输出文件路径，如果为 None 则自动生成
        """
        return await self.workflow.process_video(video_path, output_path) 