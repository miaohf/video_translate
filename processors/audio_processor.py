import os
import logging
from typing import List, Dict
from pydub import AudioSegment
import aiohttp
import aiofiles
from config import STT_SERVER_URL, TTS_SERVER_URL
from utils.common import get_file_hash
from services.stt_service import STTService
from services.tts_service import TTSService
from services.audio_mixer_service import AudioMixerService

logger = logging.getLogger(__name__)

class AudioProcessor:
    """音频处理器 - 负责编排各种音频服务，实现完整的音频处理流程"""
    
    def __init__(self, stt_server_url: str = None, tts_server_url: str = None):
        """
        初始化音频处理器
        
        参数:
            stt_server_url: 语音识别服务器地址
            tts_server_url: 语音合成服务器地址
        """
        self.stt_server_url = stt_server_url or STT_SERVER_URL
        self.tts_server_url = tts_server_url or TTS_SERVER_URL
        
        # 初始化服务
        self.stt_service = STTService(self.stt_server_url)
        self.tts_service = TTSService(self.tts_server_url)
        self.audio_mixer_service = AudioMixerService()
        
    def extract_audio(self, video_path: str, video_name: str) -> str:
        """
        从视频中提取音频
        
        参数:
            video_path: 视频文件路径
            video_name: 视频文件名（不含扩展名）
            
        返回:
            音频文件路径
        """
        try:
            # 创建临时目录
            temp_dir = os.path.join("temp", video_name)
            os.makedirs(temp_dir, exist_ok=True)
            
            # 生成音频文件路径
            file_hash = get_file_hash(video_name)
            audio_path = os.path.join(temp_dir, f"{file_hash}_audio.mp3")
            
            # 检查是否已存在
            if os.path.exists(audio_path):
                logger.info("Using existing audio file")
                return audio_path
            
            # 提取音频
            logger.info("Extracting audio from video")
            video = AudioSegment.from_file(video_path)
            
            # 转换为单声道，16kHz采样率
            audio = video.set_channels(1).set_frame_rate(16000)
            
            # 导出为mp3格式
            audio.export(audio_path, format="mp3")
            
            return audio_path
            
        except Exception as e:
            logger.error(f"Error extracting audio: {str(e)}")
            raise
    
    def transcribe_audio(self, audio_path: str, video_name: str) -> List[Dict]:
        """
        识别音频并保存结果
        
        参数:
            audio_path: 音频文件路径
            video_name: 视频名称
            
        返回:
            识别结果列表
        """
        try:
            # 使用STT服务进行识别
            segments = self.stt_service.transcribe_audio(audio_path)
            
            # 保存结果
            file_hash = get_file_hash(video_name)
            subtitle_path = self.stt_service.save_transcription(segments, video_name, file_hash)
            
            logger.info(f"Transcription completed and saved to: {subtitle_path}")
            return segments
            
        except Exception as e:
            logger.error(f"Audio transcription failed: {str(e)}")
            raise
    
    async def generate_tts_audio(self, subtitles: List[Dict], video_name: str, session) -> List[Dict]:
        """
        为字幕生成TTS音频
        
        参数:
            subtitles: 字幕列表
            video_name: 视频名称
            session: HTTP会话对象
            
        返回:
            包含音频信息的更新字幕列表
        """
        try:
            return await self.tts_service.generate_audio_for_subtitles(subtitles, video_name, session)
        except Exception as e:
            logger.error(f"TTS audio generation failed: {str(e)}")
            raise
    
    async def mix_audio_with_background(self, subtitles: List[Dict], background_audio_path: str, output_path: str) -> str:
        """
        将TTS音频与背景音频混合
        
        参数:
            subtitles: 包含generated_audio信息的字幕列表
            background_audio_path: 背景音频文件路径
            output_path: 输出文件路径
            
        返回:
            合成后的音频文件路径
        """
        try:
            return await self.audio_mixer_service.mix_audio_with_background(
                subtitles, background_audio_path, output_path
            )
        except Exception as e:
            logger.error(f"Audio mixing failed: {str(e)}")
            raise
    
    def create_audio_segments(self, audio_path: str, subtitles: List[Dict], video_name: str) -> List[Dict]:
        """
        为字幕创建音频切片作为参考音频
        
        参数:
            audio_path: 原始音频文件路径
            subtitles: 字幕列表，每个字幕包含start和end时间
            video_name: 视频名称，用于创建目录
            
        返回:
            更新后的字幕列表，包含reference_audio字段
        """
        try:
            # 创建音频切片目录
            segments_dir = os.path.join("temp", video_name, "audio_segments")
            os.makedirs(segments_dir, exist_ok=True)
            
            # 加载原始音频
            logger.info(f"Loading audio file: {audio_path}")
            audio = AudioSegment.from_file(audio_path)
            
            # 为每个字幕创建音频切片
            updated_subtitles = []
            for i, subtitle in enumerate(subtitles):
                try:
                    start_time = subtitle["start"] * 1000  # 转换为毫秒
                    end_time = subtitle["end"] * 1000      # 转换为毫秒
                    
                    # 创建音频切片文件名
                    file_hash = get_file_hash(video_name)
                    speaker = subtitle.get("speaker", "UNKNOWN")
                    segment_filename = f"{file_hash}_{i:04d}_{speaker}.mp3"
                    segment_path = os.path.join(segments_dir, segment_filename)
                    
                    # 检查是否已存在
                    if os.path.exists(segment_path):
                        logger.debug(f"Audio segment {i+1} already exists")
                    else:
                        # 提取音频片段
                        segment = audio[start_time:end_time]
                        segment.export(segment_path, format="mp3")
                        logger.debug(f"Created audio segment {i+1}/{len(subtitles)}")
                    
                    # 更新字幕信息
                    updated_subtitle = subtitle.copy()
                    updated_subtitle["reference_audio"] = segment_path
                    updated_subtitles.append(updated_subtitle)
                    
                except Exception as e:
                    logger.error(f"Error creating audio segment {i+1}: {str(e)}")
                    # 即使出错也要保留原始字幕
                    updated_subtitles.append(subtitle.copy())
                    continue
            
            logger.info(f"Created {len(updated_subtitles)} audio segments")
            return updated_subtitles
            
        except Exception as e:
            logger.error(f"Failed to create audio segments: {str(e)}")
            raise
    
    async def upload_reference_audio(self, subtitles: List[Dict]) -> List[Dict]:
        """
        将参考音频文件上传到TTS服务器
        
        参数:
            subtitles: 包含reference_audio字段的字幕列表
            
        返回:
            更新后的字幕列表
        """
        try:
            logger.info("开始上传参考音频文件到TTS服务器...")
            
            # 收集所有需要上传的音频文件
            audio_files_to_upload = []
            for subtitle in subtitles:
                if "reference_audio" in subtitle and os.path.exists(subtitle["reference_audio"]):
                    audio_files_to_upload.append(subtitle["reference_audio"])
            
            # 去重
            unique_audio_files = list(set(audio_files_to_upload))
            logger.info(f"需要上传 {len(unique_audio_files)} 个唯一的音频文件")
            
            # 创建HTTP会话
            async with aiohttp.ClientSession() as session:
                uploaded_count = 0
                for audio_file in unique_audio_files:
                    try:
                        success = await self._upload_single_audio_file(session, audio_file)
                        if success:
                            uploaded_count += 1
                            logger.debug(f"成功上传: {os.path.basename(audio_file)}")
                        else:
                            logger.warning(f"上传失败: {os.path.basename(audio_file)}")
                    except Exception as e:
                        logger.error(f"上传音频文件 {audio_file} 时出错: {str(e)}")
                        continue
                
                logger.info(f"参考音频上传完成: {uploaded_count}/{len(unique_audio_files)} 个文件成功上传")
                
            return subtitles
            
        except Exception as e:
            logger.error(f"上传参考音频失败: {str(e)}")
            # 即使上传失败也返回原始字幕，不影响后续流程
            return subtitles
    
    async def _upload_single_audio_file(self, session: aiohttp.ClientSession, audio_file_path: str) -> bool:
        """
        上传单个音频文件到TTS服务器
        
        参数:
            session: aiohttp会话
            audio_file_path: 音频文件路径
            
        返回:
            是否上传成功
        """
        try:
            filename = os.path.basename(audio_file_path)
            
            # 准备multipart表单数据
            async with aiofiles.open(audio_file_path, 'rb') as f:
                file_content = await f.read()
            
            # 创建form data
            data = aiohttp.FormData()
            data.add_field('file', 
                          file_content,
                          filename=filename,
                          content_type='audio/mpeg' if filename.endswith('.mp3') else 'audio/wav')
            
            # 发送上传请求
            async with session.post(f"{self.tts_server_url}/upload_audio", data=data) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.debug(f"上传成功: {filename} -> {result.get('file_path', 'unknown')}")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"上传音频文件 {filename} 失败: HTTP {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            logger.error(f"上传音频文件 {audio_file_path} 时发生异常: {str(e)}")
            return False

    def log_audio_info(self, final_audio_path: str, video_name: str, final_audio_copy: str = None):
        """
        输出音频文件信息摘要
        
        参数:
            final_audio_path: 最终音频文件路径
            video_name: 视频名称
            final_audio_copy: 音频副本路径
        """
        self.tts_service.log_audio_info(final_audio_path, video_name, final_audio_copy) 