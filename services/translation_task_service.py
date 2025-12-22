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
    
    def _format_srt_time(self, seconds: float) -> str:
        """格式化时间为SRT格式 (HH:MM:SS,mmm)"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        milliseconds = int((secs - int(secs)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{int(secs):02d},{milliseconds:03d}"
    
    def _get_cache_status(self, cache_dir: str, file_hash: str, video_id: int) -> dict:
        """获取各阶段缓存状态，支持断点续传"""
        temp_dir = os.path.join(settings.TEMP_DIR, cache_dir)
        
        # 定义各阶段文件路径
        paths = {
            "audio": os.path.join(temp_dir, f"{file_hash}_audio.mp3"),
            "subtitles_json": os.path.join(temp_dir, f"{file_hash}_subtitles.json"),
            "subtitles_vtt": os.path.join(temp_dir, f"{file_hash}_subtitles.vtt"),
            "translated_json": os.path.join(temp_dir, f"{file_hash}_subtitles_zh.json"),
            "translated_srt": os.path.join(temp_dir, f"{file_hash}_subtitles_zh.srt"),
            "with_audio_json": os.path.join(temp_dir, f"{file_hash}_subtitles_zh_with_audio.json"),
            "output_subtitle": os.path.join(settings.OUTPUT_DIR, f"{video_id}_{file_hash}_subtitles_zh.json"),
            "output_audio": os.path.join(settings.OUTPUT_DIR, f"{video_id}_{file_hash}_translated_audio.mp3"),
        }
        
        # 检查各阶段完成状态
        audio_extracted = os.path.exists(paths["audio"])
        subtitles_generated = os.path.exists(paths["subtitles_json"])
        translation_done = os.path.exists(paths["translated_json"]) and os.path.exists(paths["translated_srt"])
        audio_segments_done = os.path.exists(paths["with_audio_json"])
        all_complete = os.path.exists(paths["output_audio"]) and os.path.exists(paths["output_subtitle"])
        
        cache_status = {
            "paths": paths,
            "audio_extracted": audio_extracted,
            "subtitles_generated": subtitles_generated,
            "translation_done": translation_done,
            "audio_segments_done": audio_segments_done,
            "all_complete": all_complete,
        }
        
        # 打印缓存状态日志
        logger.info(f"🔍 缓存状态检查: {cache_dir} (hash: {file_hash})")
        logger.info(f"  {'✅' if audio_extracted else '❌'} 音频提取: {os.path.basename(paths['audio'])}")
        logger.info(f"  {'✅' if subtitles_generated else '❌'} 字幕生成: {os.path.basename(paths['subtitles_json'])}")
        logger.info(f"  {'✅' if translation_done else '❌'} 翻译完成: {os.path.basename(paths['translated_json'])}")
        logger.info(f"  {'✅' if audio_segments_done else '❌'} 音频片段: {os.path.basename(paths['with_audio_json'])}")
        logger.info(f"  {'✅' if all_complete else '❌'} 全部完成: {os.path.basename(paths['output_audio'])}")
        
        return cache_status
    
    def _check_cache_files(self, cache_dir: str, file_hash: str, video_id: int) -> Optional[dict]:
        """检查是否全部完成，如果是则返回缓存信息（兼容旧接口）"""
        try:
            cache_status = self._get_cache_status(cache_dir, file_hash, video_id)
            
            if not cache_status["all_complete"]:
                return None
            
            # 全部完成，加载翻译结果
            logger.info(f"🎯 发现完整缓存文件，直接使用缓存结果")
            
            with open(cache_status["paths"]["translated_json"], "r", encoding="utf-8") as f:
                subtitles = json.load(f)
            
            output_audio_url = f"{settings.API_BASE_URL}/files/{video_id}_{file_hash}_translated_audio.mp3"
            
            cache_info = {
                "subtitles": subtitles,
                "translated_audio_url": output_audio_url,
                "cache_status": cache_status
            }
            
            logger.info(f"✅ 缓存检查完成: 找到 {len(subtitles)} 条已翻译字幕")
            return cache_info
            
        except Exception as e:
            logger.warning(f"⚠️ 缓存检查失败: {str(e)}")
            return None
    
    async def process_translation_task(self, task_id: str, video_file_path: str, callback_url: Optional[str] = None, voice_mappings: Optional[list] = None, summarize: Optional[bool] = False):
        """异步处理翻译任务"""
        try:
            task_data = task_manager.get_task(task_id)
            if not task_data:
                logger.error(f"Task {task_id} not found")
                return
                
            video_id = task_data["video_id"]
            
            # 记录总结模式
            if summarize:
                logger.info(f"📝 总结模式已启用，任务 {task_id} 将生成内容总结")
            
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
            
            # 步骤0: 获取缓存状态（支持断点续传）
            cache_status = self._get_cache_status(cache_dir, file_hash, video_id)
            
            # 检查是否全部完成
            if cache_status["all_complete"]:
                logger.info(f"🚀 全部完成，使用缓存结果")
                
                output_audio_url = f"{settings.API_BASE_URL}/files/{video_id}_{file_hash}_translated_audio.mp3"
                
                task_manager.update_task_status(task_id, TaskStatus.COMPLETED, 100, "Translation completed from cache")
                await callback_service.send_callback(callback_url, CallbackData(
                    video_id=video_id,
                    task_id=task_id,
                    status=TaskStatus.COMPLETED,
                    progress=100,
                    current_step="Translation completed from cache",
                    translated_video_url=output_audio_url
                ))
                
                logger.info(f"Translation task {task_id} completed from cache")
                return
            
            # 确定从哪个阶段开始
            if cache_status["audio_segments_done"]:
                start_stage = 5  # 从 TTS 生成开始
                logger.info(f"📍 从阶段 5 (TTS生成) 继续处理...")
            elif cache_status["translation_done"]:
                start_stage = 4  # 从音频片段创建开始
                logger.info(f"📍 从阶段 4 (音频片段创建) 继续处理...")
            elif cache_status["subtitles_generated"]:
                start_stage = 3  # 从翻译开始
                logger.info(f"📍 从阶段 3 (翻译) 继续处理...")
            elif cache_status["audio_extracted"]:
                start_stage = 2  # 从字幕生成开始
                logger.info(f"📍 从阶段 2 (字幕生成) 继续处理...")
            else:
                start_stage = 1  # 从头开始
                logger.info(f"📍 从阶段 1 (音频提取) 开始处理...")
            
            # ==================== 步骤1: 提取音频 ====================
            if start_stage <= 1:
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
                
                audio_path = self.translation_client.audio_processor.extract_audio(video_file_path, cache_dir)
            else:
                audio_path = cache_status["paths"]["audio"]
                logger.info(f"⏭️ 跳过音频提取，使用缓存: {os.path.basename(audio_path)}")
            
            if check_cancelled():
                return
            
            # ==================== 步骤2: 生成字幕 ====================
            if start_stage <= 2:
                task_manager.update_task_status(task_id, TaskStatus.EXTRACTING, 30, "Generating subtitles")
                await callback_service.send_callback(callback_url, CallbackData(
                    video_id=video_id,
                    task_id=task_id,
                    status=TaskStatus.EXTRACTING,
                    progress=30,
                    current_step="Generating subtitles"
                ))
                
                # 检查是否存在已有字幕
                if cache_status["subtitles_generated"]:
                    with open(cache_status["paths"]["subtitles_json"], "r", encoding="utf-8") as f:
                        subtitles = json.load(f)
                    logger.info(f"⏭️ 跳过字幕生成，使用缓存: {len(subtitles)} 条字幕")
                else:
                    from config import ENABLE_VOCAL_SEPARATION
                    subtitles = await self.translation_client.subtitle_processor.get_subtitles(
                        audio_path, cache_dir, video_file_path, 
                        use_vocal_separation=ENABLE_VOCAL_SEPARATION
                    )
            else:
                with open(cache_status["paths"]["subtitles_json"], "r", encoding="utf-8") as f:
                    subtitles = json.load(f)
                logger.info(f"⏭️ 跳过字幕生成，使用缓存: {len(subtitles)} 条字幕")
            
            if check_cancelled():
                return
                
            # ==================== 步骤2.5: 生成内容总结 ====================
            if summarize and start_stage <= 3:
                try:
                    logger.info(f"📝 开始生成内容总结...")
                    task_manager.update_task_status(task_id, TaskStatus.EXTRACTING, 40, "Generating content summary")
                    
                    from services.summarization_service import summarization_service
                    
                    summary_result = await summarization_service.generate_content_summary(
                        subtitles=subtitles,
                        video_name=cache_dir,
                        video_id=video_id
                    )
                    
                    if summary_result["success"]:
                        summary_url = summarization_service.get_summary_file_url(video_id)
                        task_data = task_manager.get_task(task_id)
                        if task_data:
                            task_data["summary_url"] = summary_url
                            task_data["summary_metadata"] = summary_result["metadata"]
                        logger.info(f"✅ 内容总结生成完成: {summary_url}")
                    else:
                        logger.warning(f"⚠️ 内容总结生成失败: {summary_result.get('error', 'Unknown error')}")
                        
                except Exception as e:
                    logger.error(f"❌ 生成内容总结时发生错误: {str(e)}")
                
            # ==================== 步骤3: 翻译字幕 ====================
            if start_stage <= 3:
                if cache_status["translation_done"]:
                    # 翻译已完成，直接加载
                    with open(cache_status["paths"]["translated_json"], "r", encoding="utf-8") as f:
                        subtitles = json.load(f)
                    logger.info(f"⏭️ 跳过翻译，使用缓存: {len(subtitles)} 条已翻译字幕")
                else:
                    task_manager.update_task_status(task_id, TaskStatus.TRANSLATING, 50, "Translating subtitles")
                    await callback_service.send_callback(callback_url, CallbackData(
                        video_id=video_id,
                        task_id=task_id,
                        status=TaskStatus.TRANSLATING,
                        progress=50,
                        current_step="Translating subtitles"
                    ))
                    
                    translation_mode = settings.TRANSLATION_MODE
                    use_whole_translation = (translation_mode == 'whole')
                    
                    subtitles = await self.translation_client.translation_service.translate_subtitles(
                        subtitles=subtitles
                    )
                    
                    logger.info(f"翻译完成，使用模式: {translation_mode} ({'整体翻译' if use_whole_translation else '批量翻译'})")
                    
                    # 保存翻译后的字幕到临时目录
                    temp_subtitle_dir = os.path.join(settings.TEMP_DIR, cache_dir)
                    os.makedirs(temp_subtitle_dir, exist_ok=True)
                    
                    temp_translated_json_path = os.path.join(temp_subtitle_dir, f"{file_hash}_subtitles_zh.json")
                    with open(temp_translated_json_path, "w", encoding="utf-8") as f:
                        json.dump(subtitles, f, ensure_ascii=False, indent=2)
                    logger.info(f"💾 翻译字幕已保存: {temp_translated_json_path}")
                    
                    temp_translated_srt_path = os.path.join(temp_subtitle_dir, f"{file_hash}_subtitles_zh.srt")
                    with open(temp_translated_srt_path, "w", encoding="utf-8") as f:
                        for i, subtitle in enumerate(subtitles, 1):
                            start_time = self._format_srt_time(subtitle.get("start", 0))
                            end_time = self._format_srt_time(subtitle.get("end", 0))
                            text = subtitle.get("text", "")
                            f.write(f"{i}\n{start_time} --> {end_time}\n{text}\n\n")
                    logger.info(f"💾 翻译字幕SRT已保存: {temp_translated_srt_path}")
            else:
                # 从翻译后的阶段恢复
                with open(cache_status["paths"]["translated_json"], "r", encoding="utf-8") as f:
                    subtitles = json.load(f)
                logger.info(f"⏭️ 跳过翻译，使用缓存: {len(subtitles)} 条已翻译字幕")
            
            if check_cancelled():
                return
                
            # ==================== 步骤4: 创建增强参考音频 ====================
            if start_stage <= 4:
                if cache_status["audio_segments_done"]:
                    # 音频片段已创建，直接加载
                    with open(cache_status["paths"]["with_audio_json"], "r", encoding="utf-8") as f:
                        subtitles = json.load(f)
                    logger.info(f"⏭️ 跳过音频片段创建，使用缓存: {len(subtitles)} 条字幕")
                    # 重要：即使使用缓存，也需要重新上传参考音频（TTS服务端可能已清除）
                    logger.info(f"📤 重新上传参考音频到TTS服务端...")
                    subtitles = await self.translation_client.audio_processor.upload_reference_audio(subtitles)
                else:
                    task_manager.update_task_status(task_id, TaskStatus.GENERATING_TTS, 65, "Creating enhanced reference audio segments")
                    from config import ENABLE_VOCAL_SEPARATION
                    subtitles = self.translation_client.audio_processor.create_enhanced_audio_segments(
                        audio_path, subtitles, cache_dir, 
                        use_vocal_separation=ENABLE_VOCAL_SEPARATION
                    )
                    
                    # 上传参考音频
                    subtitles = await self.translation_client.audio_processor.upload_reference_audio(subtitles)
            else:
                # 从音频片段创建后的阶段恢复（阶段5: TTS生成）
                with open(cache_status["paths"]["with_audio_json"], "r", encoding="utf-8") as f:
                    subtitles = json.load(f)
                logger.info(f"⏭️ 跳过音频片段创建，使用缓存: {len(subtitles)} 条字幕")
                # 重要：即使从阶段5恢复，也需要重新上传参考音频（TTS服务端可能已清除）
                logger.info(f"📤 重新上传参考音频到TTS服务端...")
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