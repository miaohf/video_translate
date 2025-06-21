import os
import json
import logging
from typing import List, Dict
from pathlib import Path
from pydub import AudioSegment
from utils.common import get_file_hash

logger = logging.getLogger(__name__)

class TTSService:
    """语音合成服务"""
    
    def __init__(self, tts_server_url: str):
        """
        初始化TTS服务
        
        参数:
            tts_server_url: TTS服务器地址
        """
        self.tts_server_url = tts_server_url
    
    async def generate_audio_for_subtitles(self, subtitles: List[Dict], video_name: str, session) -> List[Dict]:
        """
        为字幕列表生成TTS音频
        
        参数:
            subtitles: 字幕列表
            video_name: 视频名称
            session: HTTP会话对象
            
        返回:
            包含音频信息的更新字幕列表
        """
        try:
            # 检查最终音频文件是否已存在
            final_audio_path = os.path.join("temp", video_name, "final_audio.mp3")
            if os.path.exists(final_audio_path):
                logger.info(f"Found existing audio file: {final_audio_path}")
                return subtitles
            
            # 创建临时目录
            temp_dir = os.path.join("temp", video_name, "tts_segments")
            os.makedirs(temp_dir, exist_ok=True)
            
            # 生成每个字幕的音频并保存文件信息
            updated_subtitles = []
            for i, subtitle in enumerate(subtitles):
                try:
                    # 检查音频片段是否已存在
                    segment_path = os.path.join(temp_dir, f"segment_{i:04d}.wav")
                    
                    # 复制字幕信息
                    updated_subtitle = subtitle.copy()
                    
                    if os.path.exists(segment_path):
                        logger.info(f"Found existing audio segment: {segment_path}")
                        # 获取音频文件时长
                        audio = AudioSegment.from_file(segment_path)
                        duration = audio.duration_seconds
                        
                        # 保存音频文件信息到字幕数据
                        updated_subtitle["generated_audio"] = segment_path
                        updated_subtitle["generated_duration"] = duration
                        updated_subtitles.append(updated_subtitle)
                        continue
                    
                    # 获取要转换的文本
                    text_to_convert = subtitle.get("translated_text") or subtitle.get("text")
                    if not text_to_convert:
                        logger.warning(f"Subtitle {i+1} has no text content, skipping")
                        updated_subtitles.append(updated_subtitle)
                        continue
                    
                    # 从reference_audio字段中提取说话人信息
                    reference_audio = subtitle.get("reference_audio", "")
                    if reference_audio:
                        # 从文件路径中提取说话人信息，格式为：file_hash_index_SPEAKER_XX.mp3
                        speaker = Path(reference_audio).stem
                    else:
                        speaker = "Unknown"
                    
                    # 生成音频
                    audio_path = await self._generate_single_audio(
                        text_to_convert, speaker, segment_path, session, i
                    )
                    
                    if audio_path:
                        # 获取生成音频的时长
                        audio = AudioSegment.from_file(audio_path)
                        duration = audio.duration_seconds
                        
                        # 保存音频文件信息到字幕数据
                        updated_subtitle["generated_audio"] = audio_path
                        updated_subtitle["generated_duration"] = duration
                        
                        logger.info(f"Generated audio segment {i+1}/{len(subtitles)}, duration: {duration:.2f}s")
                    
                    updated_subtitles.append(updated_subtitle)
                        
                except Exception as e:
                    logger.error(f"Error processing audio segment {i+1}: {str(e)}")
                    updated_subtitles.append(subtitle.copy())
                    continue
            
            # 保存更新后的字幕文件（包含generated_audio信息）
            await self._save_subtitles_with_audio_info(updated_subtitles, video_name)
            
            return updated_subtitles
            
        except Exception as e:
            logger.error(f"Failed to generate TTS audio: {str(e)}")
            raise
    
    async def _generate_single_audio(self, text: str, speaker: str, output_path: str, session, index: int) -> str:
        """
        生成单个音频片段
        
        参数:
            text: 要转换的文本
            speaker: 说话人信息
            output_path: 输出文件路径
            session: HTTP会话对象
            index: 片段索引
            
        返回:
            生成的音频文件路径，失败时返回None
        """
        try:
            # 准备请求数据
            data = {
                "text": text,
                "speaker": speaker,
                "temperature": 0.8,
                "top_k": 50,
                "top_p": 0.95,
                "seed": 421 + index  # 为每个片段使用不同的种子
            }
            
            # 发送请求到 TTS 服务器
            async with session.post(f"{self.tts_server_url}/tts", json=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Failed to generate TTS audio: {error_text}")
                    return None
                
                # 保存音频片段
                with open(output_path, "wb") as f:
                    f.write(await response.read())
                
                return output_path
                
        except Exception as e:
            logger.error(f"Error generating single audio: {str(e)}")
            return None
    
    async def _save_subtitles_with_audio_info(self, subtitles: List[Dict], video_name: str):
        """
        保存包含音频信息的字幕文件
        
        参数:
            subtitles: 包含音频信息的字幕列表
            video_name: 视频名称
        """
        try:
            file_hash = get_file_hash(video_name)
            updated_subtitle_path = os.path.join("temp", video_name, f"{file_hash}_subtitles_zh_with_audio.json")
            with open(updated_subtitle_path, 'w', encoding='utf-8') as f:
                json.dump(subtitles, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved subtitles with audio info: {updated_subtitle_path}")
        except Exception as e:
            logger.error(f"Failed to save subtitles with audio info: {str(e)}")
    
    def log_audio_info(self, final_audio_path: str, video_name: str, final_audio_copy: str = None):
        """
        输出音频文件信息摘要
        
        参数:
            final_audio_path: 最终音频文件路径
            video_name: 视频名称
            final_audio_copy: 音频副本路径
        """
        if os.path.exists(final_audio_path):
            audio_info = AudioSegment.from_file(final_audio_path)
            file_size = os.path.getsize(final_audio_path) / (1024 * 1024)  # MB
            logger.info(f"\n📄 Final audio file info:")
            logger.info(f"   File path: {final_audio_path}")
            logger.info(f"   File size: {file_size:.2f} MB")
            logger.info(f"   Duration: {audio_info.duration_seconds:.2f} seconds")
            logger.info(f"   Sample rate: {audio_info.frame_rate} Hz")
            logger.info(f"   Channels: {audio_info.channels}")
            if final_audio_copy and os.path.exists(final_audio_copy):
                logger.info(f"   Copy location: {final_audio_copy}") 