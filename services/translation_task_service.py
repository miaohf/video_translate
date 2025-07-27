import os
import json
import logging
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from main import VideoTranslationClient
from utils.common import get_file_hash
from config import settings
from models.api_models import TaskStatus, CallbackData
from services.task_manager import task_manager
from services.callback_service import callback_service

logger = logging.getLogger(__name__)

class TranslationTaskService:
    """翻译任务处理服务"""
    
    def __init__(self):
        self.translation_client = VideoTranslationClient()
    
    def _check_cache_files(self, video_name: str, file_hash: str, video_id: int) -> Optional[dict]:
        """检查缓存文件是否存在，如果存在则返回缓存信息"""
        try:
            # 使用video_id作为缓存目录名，而不是带时间戳的文件名
            cache_dir = str(video_id)
            
            # 检查所有必要的缓存文件
            cache_files = {
                "subtitle_json": os.path.join(settings.TEMP_DIR, cache_dir, f"{file_hash}_subtitles.json"),
                "translated_subtitle_json": os.path.join(settings.TEMP_DIR, cache_dir, f"{file_hash}_subtitles_zh.json"),
                "translated_subtitle_srt": os.path.join(settings.TEMP_DIR, cache_dir, f"{file_hash}_subtitles_zh.srt"),
                "output_subtitle_json": os.path.join(settings.OUTPUT_DIR, f"{video_id}_{file_hash}_subtitles_zh.json"),
                "output_audio": os.path.join(settings.OUTPUT_DIR, f"{video_id}_{file_hash}_translated_audio.mp3")
            }
            
            # 检查所有缓存文件是否存在
            missing_files = []
            for name, path in cache_files.items():
                if not os.path.exists(path):
                    missing_files.append(name)
            
            if missing_files:
                logger.info(f"📋 缓存文件检查: 缺少 {len(missing_files)} 个文件: {', '.join(missing_files)}")
                return None
            
            # 所有缓存文件都存在，加载翻译结果
            logger.info(f"🎯 发现完整缓存文件，直接使用缓存结果")
            
            # 加载翻译后的字幕
            with open(cache_files["translated_subtitle_json"], "r", encoding="utf-8") as f:
                subtitles = json.load(f)
            
            # 检查输出文件
            output_audio_url = f"{settings.API_BASE_URL}/files/{video_id}_{file_hash}_translated_audio.mp3"
            
            cache_info = {
                "subtitles": subtitles,
                "translated_audio_url": output_audio_url,
                "cache_files": cache_files
            }
            
            logger.info(f"✅ 缓存检查完成: 找到 {len(subtitles)} 条已翻译字幕")
            return cache_info
            
        except Exception as e:
            logger.warning(f"⚠️ 缓存检查失败: {str(e)}")
            return None
    
    async def process_translation_task(self, task_id: str, video_file_path: str, callback_url: Optional[str] = None, voice_mappings: Optional[list] = None):
        """异步处理翻译任务"""
        try:
            task_data = task_manager.get_task(task_id)
            if not task_data:
                logger.error(f"Task {task_id} not found")
                return
                
            video_id = task_data["video_id"]
            
            # 检查任务是否被取消
            def check_cancelled():
                return task_manager.is_task_cancelled(task_id)
            
            # 获取视频文件名和哈希
            # 对于上传的文件，使用video_id作为缓存目录名
            if "uploads" in video_file_path:
                # 上传的文件，使用video_id作为缓存目录
                cache_dir = str(video_id)
                file_hash = get_file_hash(str(video_id))
            else:
                # 本地文件，使用原始文件名
                video_name = Path(video_file_path).stem
                cache_dir = video_name
                file_hash = get_file_hash(video_name)
            
            # 步骤0: 检查缓存文件
            logger.info(f"🔍 检查缓存文件: {cache_dir} (hash: {file_hash})")
            cache_info = self._check_cache_files(cache_dir, file_hash, video_id)
            
            if cache_info:
                # 缓存存在，直接返回结果
                logger.info(f"🚀 使用缓存结果，跳过翻译流程")
                
                # 更新任务状态为完成
                task_manager.update_task_status(task_id, TaskStatus.COMPLETED, 100, "Translation completed from cache")
                
                # 发送完成回调
                await callback_service.send_callback(callback_url, CallbackData(
                    video_id=video_id,
                    task_id=task_id,
                    status=TaskStatus.COMPLETED,
                    progress=100,
                    current_step="Translation completed from cache",
                    translated_video_url=cache_info["translated_audio_url"]
                ))
                
                logger.info(f"Translation task {task_id} completed from cache")
                return
            
            # 缓存不存在，开始正常流程
            logger.info(f"🔄 缓存不存在，开始完整翻译流程")
            
            # 步骤1: 提取音频
            if check_cancelled():
                return
                
            task_manager.update_task_status(task_id, TaskStatus.EXTRACTING, 10, "Extracting audio from video")
            await callback_service.send_callback(callback_url, CallbackData(
                video_id=video_id,
                task_id=task_id,
                status=TaskStatus.EXTRACTING,
                progress=10,
                current_step="Extracting audio from video"
            ))
            
            # 提取音频
            audio_path = self.translation_client.audio_processor.extract_audio(video_file_path, cache_dir)
            
            if check_cancelled():
                return
                
            # 步骤2: 生成字幕
            task_manager.update_task_status(task_id, TaskStatus.EXTRACTING, 30, "Generating subtitles")
            await callback_service.send_callback(callback_url, CallbackData(
                video_id=video_id,
                task_id=task_id,
                status=TaskStatus.EXTRACTING,
                progress=30,
                current_step="Generating subtitles"
            ))
            
            # 检查是否存在已有字幕
            subtitle_json_path = os.path.join(settings.TEMP_DIR, cache_dir, f"{file_hash}_subtitles.json")
            if os.path.exists(subtitle_json_path):
                with open(subtitle_json_path, "r", encoding="utf-8") as f:
                    subtitles = json.load(f)
            else:
                from config import ENABLE_VOCAL_SEPARATION
                subtitles = await self.translation_client.subtitle_processor.get_subtitles(
                    audio_path, cache_dir, video_file_path, 
                    use_vocal_separation=ENABLE_VOCAL_SEPARATION
                )
            
            if check_cancelled():
                return
                
            # 步骤3: 翻译字幕
            task_manager.update_task_status(task_id, TaskStatus.TRANSLATING, 50, "Translating subtitles")
            await callback_service.send_callback(callback_url, CallbackData(
                video_id=video_id,
                task_id=task_id,
                status=TaskStatus.TRANSLATING,
                progress=50,
                current_step="Translating subtitles"
            ))
            
            # 使用配置的翻译模式
            translation_mode = settings.TRANSLATION_MODE
            use_whole_translation = (translation_mode == 'whole')
            
            if use_whole_translation:
                subtitles = await self.translation_client.translation_service.translate_whole_subtitles(
                    subtitles=subtitles,
                    video_name=cache_dir
                )
            else:
                subtitles = await self.translation_client.translation_service.translate_subtitles(
                    subtitles=subtitles,
                    video_name=cache_dir
                )
            
            logger.info(f"翻译完成，使用模式: {translation_mode} ({'整体翻译' if use_whole_translation else '批量翻译'})")
            
            if check_cancelled():
                return
                
            # 步骤4: 创建增强参考音频
            task_manager.update_task_status(task_id, TaskStatus.GENERATING_TTS, 65, "Creating enhanced reference audio segments")
            from config import ENABLE_VOCAL_SEPARATION
            subtitles = self.translation_client.audio_processor.create_enhanced_audio_segments(
                audio_path, subtitles, cache_dir, 
                use_vocal_separation=ENABLE_VOCAL_SEPARATION
            )
            
            # 上传参考音频
            subtitles = await self.translation_client.audio_processor.upload_reference_audio(subtitles)
            
            if check_cancelled():
                return
                
            # 步骤5: 生成TTS音频
            task_manager.update_task_status(task_id, TaskStatus.GENERATING_TTS, 80, "Generating TTS audio")
            await callback_service.send_callback(callback_url, CallbackData(
                video_id=video_id,
                task_id=task_id,
                status=TaskStatus.GENERATING_TTS,
                progress=80,
                current_step="Generating TTS audio"
            ))
            
            tts_audio_path = await self.translation_client._generate_tts_audio(subtitles, cache_dir, voice_mappings)
            
            if check_cancelled():
                return
                
            # 步骤6: 保存结果文件
            task_manager.update_task_status(task_id, TaskStatus.COMPOSING, 95, "Saving translation results")
            
            # 保存翻译后的字幕
            output_subtitle_path = os.path.join(settings.OUTPUT_DIR, f"{video_id}_{file_hash}_subtitles_zh.json")
            os.makedirs(os.path.dirname(output_subtitle_path), exist_ok=True)
            self.translation_client.subtitle_processor.save_subtitles_to_json(subtitles, output_subtitle_path)
            
            # 复制音频文件到输出目录 - 支持MP3格式
            output_audio_path = os.path.join(settings.OUTPUT_DIR, f"{video_id}_{file_hash}_translated_audio.mp3")
            if tts_audio_path and os.path.exists(tts_audio_path):
                shutil.copy2(tts_audio_path, output_audio_path)
            
            # 生成文件访问URL - 支持MP3格式
            translated_audio_url = f"{settings.API_BASE_URL}/files/{video_id}_{file_hash}_translated_audio.mp3"
            
            # 更新任务为完成状态
            task_manager.update_task_status(task_id, TaskStatus.COMPLETED, 100, "Translation completed")
            task_data = task_manager.get_task(task_id)
            if task_data:
                task_data["translated_video_url"] = translated_audio_url
            
            # 发送完成回调
            await callback_service.send_callback(callback_url, CallbackData(
                video_id=video_id,
                task_id=task_id,
                status=TaskStatus.COMPLETED,
                progress=100,
                current_step="Translation completed",
                translated_video_url=translated_audio_url
            ))
            
            logger.info(f"Translation task {task_id} completed successfully")
            
        except Exception as e:
            error_message = str(e)
            logger.error(f"Translation task {task_id} failed: {error_message}")
            
            task_manager.update_task_status(task_id, TaskStatus.FAILED, 0, "Translation failed", error_message)
            
            # 发送失败回调
            if callback_url:
                await callback_service.send_callback(callback_url, CallbackData(
                    video_id=task_data["video_id"],
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    progress=0,
                    current_step="Translation failed",
                    error_message=error_message
                ))

# 全局翻译任务服务实例
translation_task_service = TranslationTaskService() 