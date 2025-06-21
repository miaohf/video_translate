import os
import logging
from pathlib import Path
from utils.common import get_file_hash

logger = logging.getLogger(__name__)

class FileManager:
    """文件和目录管理工具类"""
    
    @staticmethod
    def get_temp_dir(video_path: str) -> str:
        """
        获取临时文件目录
        
        参数:
            video_path: 视频文件路径
            
        返回:
            临时文件目录路径
        """
        # 使用输入视频的文件名作为目录名
        video_name = Path(video_path).stem
        temp_dir = os.path.join("temp", video_name)
        os.makedirs(temp_dir, exist_ok=True)
        return temp_dir
    
    @staticmethod
    def ensure_temp_dir():
        """确保temp目录存在"""
        os.makedirs("temp", exist_ok=True)
    
    @staticmethod
    def get_subtitle_path(video_name: str, file_hash: str, translated: bool = False) -> str:
        """
        获取字幕文件路径
        
        参数:
            video_name: 视频名称
            file_hash: 文件哈希值
            translated: 是否为翻译后的字幕
            
        返回:
            字幕文件路径
        """
        suffix = "_subtitles_zh.json" if translated else "_subtitles.json"
        return os.path.join("temp", video_name, f"{file_hash}{suffix}")
    
    @staticmethod
    def get_audio_path(video_name: str, file_hash: str) -> str:
        """
        获取音频文件路径
        
        参数:
            video_name: 视频名称
            file_hash: 文件哈希值
            
        返回:
            音频文件路径
        """
        return os.path.join("temp", video_name, f"{file_hash}_audio.mp3")
    
    @staticmethod
    def create_final_audio_copy(final_audio_path: str, video_name: str) -> str:
        """
        创建最终音频文件的副本
        
        参数:
            final_audio_path: 最终音频文件路径
            video_name: 视频名称
            
        返回:
            副本文件路径
        """
        import shutil
        from datetime import datetime
        
        # 创建带时间戳的文件名，避免覆盖
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_video_name = "".join(c for c in video_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        final_audio_copy = f"{safe_video_name}_final_audio_{timestamp}.wav"
        
        try:
            shutil.copy2(final_audio_path, final_audio_copy)
            logger.info(f"最终音频已保存到: {final_audio_copy}")
            return final_audio_copy
        except Exception as e:
            logger.warning(f"保存最终音频副本失败: {str(e)}")
            return None
    
    @staticmethod
    def create_final_video_copy(final_video_path: str, video_name: str) -> str:
        """
        创建最终视频文件的副本
        
        参数:
            final_video_path: 最终视频文件路径
            video_name: 视频名称
            
        返回:
            副本文件路径
        """
        import shutil
        from datetime import datetime
        
        # 创建带时间戳的文件名，避免覆盖
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_video_name = "".join(c for c in video_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        final_video_copy = f"{safe_video_name}_final_video_{timestamp}.mp4"
        
        try:
            shutil.copy2(final_video_path, final_video_copy)
            logger.info(f"最终视频已保存到: {final_video_copy}")
            return final_video_copy
        except Exception as e:
            logger.warning(f"保存最终视频副本失败: {str(e)}")
            return None

    @staticmethod
    def get_high_resolution_version_video_path(video_path: str) -> str:
        """
        获取视频的高清版本路径，并标准化文件名
        
        参数:
            video_path: 原始视频文件路径
            
        返回:
            高清版本视频路径，如果不存在则返回标准化后的原始路径
        """
        try:
            # 获取视频文件名和目录
            video_dir = os.path.dirname(video_path)
            original_name = os.path.splitext(os.path.basename(video_path))[0]
            extension = os.path.splitext(os.path.basename(video_path))[1]
            
            # 标准化文件名：转小写，空格和特殊字符替换为下划线
            normalized_name = FileManager._normalize_filename(original_name)
            
            # 如果文件名需要标准化，先重命名原文件
            if normalized_name != original_name:
                old_path = video_path
                new_path = os.path.join(video_dir, f"{normalized_name}{extension}")
                
                if os.path.exists(old_path) and not os.path.exists(new_path):
                    os.rename(old_path, new_path)
                    logger.info(f"文件名已标准化: {old_path} -> {new_path}")
                    video_path = new_path
                elif os.path.exists(new_path):
                    logger.info(f"标准化文件名已存在，使用: {new_path}")
                    video_path = new_path
            
            # 构建高清版本路径
            high_res_path = os.path.join(video_dir, f"{normalized_name}_1080p.mp4")
            
            # 检查高清版本是否存在
            if os.path.exists(high_res_path):
                logger.info(f"使用高清版本视频: {high_res_path}")
                return high_res_path
            else:
                logger.info(f"高清版本视频不存在，使用标准化视频: {video_path}")
                return video_path
                
        except Exception as e:
            logger.warning(f"获取高清版本视频路径失败: {str(e)}")
            return video_path
    
    @staticmethod
    def _normalize_filename(filename: str) -> str:
        """
        标准化文件名：转小写，空格和特殊字符替换为下划线
        
        参数:
            filename: 原始文件名（不包含扩展名）
            
        返回:
            标准化后的文件名
        """
        import re
        
        # 转小写
        normalized = filename.lower()
        
        # 替换空格、反斜杠和其他特殊字符为下划线
        normalized = re.sub(r'[\\\/\s\-\.\(\)\[\]]+', '_', normalized)
        
        # 移除开头和结尾的下划线
        normalized = normalized.strip('_')
        
        # 合并多个连续的下划线
        normalized = re.sub(r'_+', '_', normalized)
        
        return normalized 