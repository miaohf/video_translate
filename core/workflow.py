import os
import json
import logging
import glob
from typing import Dict, Optional, List
from pathlib import Path
from utils.common import get_file_hash
from utils.file_manager import FileManager
from services.tts_service import TTSService
from services.audio_mixer_service import AudioMixerService

logger = logging.getLogger(__name__)

class VideoWorkflow:
    """视频翻译工作流程编排器"""
    
    def __init__(self, translation_service, audio_processor, subtitle_processor, video_processor):
        """
        初始化工作流程编排器
        
        参数:
            translation_service: 翻译服务
            audio_processor: 音频处理器
            subtitle_processor: 字幕处理器
            video_processor: 视频处理器
        """
        self.translation_service = translation_service
        self.audio_processor = audio_processor
        self.subtitle_processor = subtitle_processor
        self.video_processor = video_processor
        
        # 初始化TTS服务
        self.tts_service = TTSService(
            tts_server_url=os.getenv("TTS_SERVER_URL", "http://localhost:8000")
        )
    
    async def process_video(self, video_path: str, output_path: str = None):
        """
        处理视频的主要工作流程
        
        参数:
            video_path: 视频文件路径
            output_path: 输出文件路径，如果为 None 则自动生成
        """
        try:
            # 获取视频文件名（不含扩展名）
            video_name = Path(video_path).stem
            file_hash = get_file_hash(video_name)
            
            # 检查翻译后的字幕文件是否存在
            translated_subtitle_path = FileManager.get_subtitle_path(video_name, file_hash, translated=True)
            
            if os.path.exists(translated_subtitle_path):
                logger.info(f"发现已存在的翻译字幕文件: {translated_subtitle_path}")
                subtitles = await self._load_existing_subtitles(translated_subtitle_path, video_name, file_hash)
            else:
                subtitles = await self._process_new_video(video_path, video_name, file_hash)
            
            # 生成 TTS 音频
            logger.info("\n6. 开始生成 TTS 音频...")
            session = await self.subtitle_processor.get_session()
            updated_subtitles = await self.tts_service.generate_audio_for_subtitles(subtitles, video_name, session)
            logger.info("TTS 音频生成完成")
            
            # 关闭subtitle_processor的session
            await self.subtitle_processor.close()
            
            # 合成最终音频
            tts_audio_path = await self._synthesize_final_audio(updated_subtitles, video_name, file_hash)
            
            # 合成最终视频
            logger.info("\n7. 开始合成最终视频...")
            high_resolution_version_video_path = FileManager.get_high_resolution_version_video_path(video_path)
            final_video_path = await self._synthesize_final_video(high_resolution_version_video_path, tts_audio_path, updated_subtitles, video_name, file_hash, output_path)
            
            # 保存翻译后的字幕
            subtitle_output_path = FileManager.get_subtitle_path(video_name, file_hash, translated=True)
            self.subtitle_processor.save_subtitles_to_json(updated_subtitles, subtitle_output_path)
            logger.info(f"\nSubtitle translation completed, output saved to {subtitle_output_path}")
            
            # 输出处理完成的文件总结
            self._log_completion_summary(subtitle_output_path, tts_audio_path, video_name, final_video_path)
            
            return final_video_path
            
        except Exception as e:
            logger.error(f"处理视频失败: {str(e)}")
            raise
        finally:
            # 确保所有连接都已关闭
            await self._cleanup_connections()
    
    async def _load_existing_subtitles(self, translated_subtitle_path: str, video_name: str, file_hash: str) -> List[Dict]:
        """
        加载已存在的翻译字幕文件
        
        参数:
            translated_subtitle_path: 翻译字幕文件路径
            video_name: 视频名称
            file_hash: 文件哈希值
            
        返回:
            字幕列表
        """
        # 读取已存在的字幕文件
        with open(translated_subtitle_path, 'r', encoding='utf-8') as f:
            subtitles = json.load(f)
        logger.info(f"已加载 {len(subtitles)} 条字幕")
        
        # 检查是否需要创建音频切片
        audio_path = FileManager.get_audio_path(video_name, file_hash)
        if os.path.exists(audio_path):
            # 检查字幕是否已包含reference_audio字段
            if not any('reference_audio' in subtitle for subtitle in subtitles):
                logger.info("为已有字幕创建参考音频切片...")
                subtitles = self.audio_processor.create_audio_segments(audio_path, subtitles, video_name)
                logger.info("参考音频切片创建完成")
                
                # 上传参考音频到TTS服务器
                logger.info("上传参考音频...")
                subtitles = await self.audio_processor.upload_reference_audio(subtitles)
                logger.info("参考音频上传完成")
                
                # 保存更新后的字幕文件
                with open(translated_subtitle_path, 'w', encoding='utf-8') as f:
                    json.dump(subtitles, f, ensure_ascii=False, indent=2)
                logger.info("已更新字幕文件，添加参考音频信息")
        
        return subtitles
    
    async def _process_new_video(self, video_path: str, video_name: str, file_hash: str) -> List[Dict]:
        """
        处理新的视频文件
        
        参数:
            video_path: 视频文件路径
            video_name: 视频名称
            file_hash: 文件哈希值
            
        返回:
            处理后的字幕列表
        """
        # 处理音频提取
        logger.info("\n1. Extracting Audio...")
        audio_path = self.audio_processor.extract_audio(video_path, video_name)
        
        # 获取字幕
        logger.info("\n2. Generating Subtitles...")
        subtitle_json_path = FileManager.get_subtitle_path(video_name, file_hash, translated=False)
        
        if os.path.exists(subtitle_json_path):
            logger.info(f"使用已存在的字幕文件: {subtitle_json_path}")
            with open(subtitle_json_path, "r", encoding="utf-8") as f:
                subtitles = json.load(f)
        else:
            # 生成字幕
            subtitles = await self.subtitle_processor.get_subtitles(audio_path, video_name)

        # 翻译字幕
        logger.info("\n3. Translating Subtitles...")
        subtitles = await self.translation_service.translate_batch_subtitles(subtitles, video_name)
        logger.info("字幕翻译完成")

        # 创建音频切片作为参考音频
        logger.info("\n4. Creating Reference Audio Segments...")
        subtitles = self.audio_processor.create_audio_segments(audio_path, subtitles, video_name)
        logger.info("参考音频切片创建完成")

        # 上传参考音频到TTS服务器
        logger.info("\n5. Uploading Reference Audio...")
        subtitles = await self.audio_processor.upload_reference_audio(subtitles)
        logger.info("参考音频上传完成")
        
        return subtitles
    
    async def _synthesize_final_audio(self, subtitles: List[Dict], video_name: str, file_hash: str) -> str:
        """
        合成最终音频
        
        参数:
            subtitles: 字幕列表
            video_name: 视频名称
            file_hash: 文件哈希值
            
        返回:
            最终音频文件路径
        """
        logger.info("开始合成最终音频...")
        
        # 获取原始音频文件路径
        original_audio_path = FileManager.get_audio_path(video_name, file_hash)
        final_audio_path = os.path.join("temp", video_name, f"{file_hash}_final_audio.mp3")
        
        # 调用音频混合方法
        final_audio_path = await AudioMixerService.mix_audio_with_background(
            subtitles, 
            original_audio_path, 
            final_audio_path
        )
        
        logger.info(f"音频合成完成: {final_audio_path}")
        
        # 保存最终合成音频的副本到项目根目录
        final_audio_copy = FileManager.create_final_audio_copy(final_audio_path, video_name)
        
        # 输出文件信息摘要
        self.tts_service.log_audio_info(final_audio_path, video_name, final_audio_copy)
        
        return final_audio_path
    
    async def _synthesize_final_video(self, video_path: str, audio_path: str, subtitles: List[Dict], 
                                     video_name: str, file_hash: str, output_path: str = None) -> str:
        """
        合成最终视频
        
        参数:
            video_path: 原始视频文件路径
            audio_path: 合成音频文件路径
            subtitles: 字幕列表
            video_name: 视频名称
            file_hash: 文件哈希值
            output_path: 输出视频路径，如果为 None 则自动生成
            
        返回:
            最终视频文件路径
        """
        try:
            # 生成输出视频路径
            if output_path is None:
                output_path = os.path.join("temp", video_name, f"{file_hash}_final_video.mp4")
            
            # 确保输出目录存在
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # 使用video_processor合成视频
            final_video_path = self.video_processor.create_final_video(
                video_path, audio_path, subtitles, output_path
            )
            
            logger.info(f"最终视频合成完成: {final_video_path}")
            
            # 创建视频副本到项目根目录
            video_copy_path = FileManager.create_final_video_copy(final_video_path, video_name)
            
            return final_video_path
            
        except Exception as e:
            logger.error(f"视频合成失败: {str(e)}")
            raise
    
    async def _cleanup_connections(self):
        """
        清理所有的连接和会话
        """
        try:
            # 关闭translation_service的连接
            await self.translation_service.close()
            
            # 关闭subtitle_processor的连接
            await self.subtitle_processor.close()
            
            logger.debug("所有连接已清理完成")
        except Exception as e:
            logger.warning(f"清理连接时出现警告: {str(e)}")
    
    def _log_completion_summary(self, subtitle_path: str, audio_path: str, video_name: str, video_path: str = None):
        """
        输出处理完成的文件总结
        
        参数:
            subtitle_path: 字幕文件路径
            audio_path: 音频文件路径
            video_name: 视频名称
            video_path: 视频文件路径
        """
        logger.info(f"\n🎉 视频翻译处理完成！")
        logger.info(f"📁 输出文件列表:")
        logger.info(f"   翻译字幕: {subtitle_path}")
        
        if audio_path and os.path.exists(audio_path):
            logger.info(f"   合成音频: {audio_path}")
            # 检查是否有副本（查找最新的副本文件）
            pattern = f"*{video_name}*_final_audio_*.wav"
            audio_copies = glob.glob(pattern)
            if audio_copies:
                # 获取最新的副本文件
                latest_copy = max(audio_copies, key=os.path.getctime)
                logger.info(f"   音频副本: {latest_copy}")
        
        if video_path and os.path.exists(video_path):
            logger.info(f"   最终视频: {video_path}")
            # 检查是否有视频副本
            pattern = f"*{video_name}*_final_video_*.mp4"
            video_copies = glob.glob(pattern)
            if video_copies:
                latest_copy = max(video_copies, key=os.path.getctime)
                logger.info(f"   视频副本: {latest_copy}") 