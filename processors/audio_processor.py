import os
import requests
import soundfile as sf
import numpy as np
import librosa
from pydub import AudioSegment
import logging
from typing import List, Dict, Any, Optional
import json
from tqdm import tqdm
import subprocess
from pathlib import Path
from config import STT_SERVER_URL, TTS_SERVER_URL, AUDIO_SAMPLE_RATE, AUDIO_CHANNELS
from utils.common import get_file_hash

logger = logging.getLogger(__name__)

class AudioProcessor:
    def __init__(self, stt_server_url: str = None, tts_server_url: str = None):
        """
        初始化音频处理器
        
        参数:
            stt_server_url: 语音识别服务器地址
            tts_server_url: 语音合成服务器地址
        """
        self.stt_server_url = stt_server_url or STT_SERVER_URL
        self.tts_server_url = tts_server_url or TTS_SERVER_URL
        
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
    
    def get_file_hash(self, text: str, length: int = 20) -> str:
        """
        生成文本的短哈希值
        
        参数:
            text: 要哈希的文本
            length: 哈希值长度
            
        返回:
            哈希值字符串
        """
        import hashlib
        return hashlib.md5(text.encode()).hexdigest()[:length]
    
    def generate_chinese_audio(self, subtitles: List[Dict], speaker: str = None) -> str:
        """
        生成中文语音
        
        参数:
            subtitles: 字幕列表
            speaker: 说话人名称
            
        返回:
            生成的音频文件路径
        """
        logger.info("Generating Chinese audio...")
        temp_audio_path = os.path.join("temp", "chinese_audio.wav")
        
        # 检查是否已存在中文音频文件
        if os.path.exists(temp_audio_path):
            logger.info(f"Found existing Chinese audio file: {temp_audio_path}")
            return temp_audio_path
            
        sample_rate = 16000
        
        # 使用 OpenAI TTS API 生成中文语音
        audio_segments = []
        total = len(subtitles)
        
        # 获取所有不同的说话人
        speakers = set(sub["speaker"] for sub in subtitles if sub.get("speaker"))
        logger.info(f"Starting to generate audio for {len(speakers)} different speakers")
        
        # 记录错误信息
        error_count = 0
        max_errors = 3  # 最大允许错误次数
        
        for i, subtitle in enumerate(tqdm(subtitles, desc="Generating Chinese audio")):
            try:
                # 获取当前字幕的说话人
                current_speaker = subtitle.get("speaker")
                
                # 如果没有指定说话人，使用默认说话人
                if not current_speaker:
                    current_speaker = speaker if speaker else "alloy"
                    logger.debug(f"Using default speaker: {current_speaker}")
                else:
                    logger.debug(f"Using speaker: {current_speaker}")
                
                response = requests.post(
                    f"{self.tts_server_url}/tts",
                    json={
                        "text": subtitle["translated_text"],
                        "speaker": current_speaker
                    }
                )
                
                if response.status_code == 200:
                    # 保存临时音频文件
                    temp_segment_path = os.path.join("temp", f"segment_{i}.wav")
                    with open(temp_segment_path, 'wb') as f:
                        f.write(response.content)
                    
                    # 读取音频数据
                    audio_data, _ = librosa.load(temp_segment_path, sr=sample_rate)
                    
                    # 计算静音段
                    silence_duration = int((subtitle["end"] - subtitle["start"]) * sample_rate) - len(audio_data)
                    if silence_duration > 0:
                        silence = np.zeros(silence_duration)
                        audio_data = np.concatenate([audio_data, silence])
                    
                    audio_segments.append(audio_data)
                    os.remove(temp_segment_path)
                    
                    # 定期清理内存
                    if i % 10 == 0:
                        import gc
                        gc.collect()
                else:
                    error_msg = f"Failed to generate audio: {response.text}"
                    logger.error(error_msg)
                    raise Exception(error_msg)
                    
            except Exception as e:
                error_count += 1
                logger.error(f"Error generating audio segment {i+1}: {str(e)}")
                
                if error_count >= max_errors:
                    logger.error(f"Error count exceeded {max_errors}, stopping audio generation")
                    raise Exception(f"Audio generation failed after {error_count} errors")
                
                # 发生错误时，使用静音段
                logger.warning(f"Using silence for segment {i+1}")
                silence_duration = int((subtitle["end"] - subtitle["start"]) * sample_rate)
                audio_segments.append(np.zeros(silence_duration))
        
        # 合并所有音频段
        if audio_segments:
            final_audio = np.concatenate(audio_segments)
            sf.write(temp_audio_path, final_audio, sample_rate)
            return temp_audio_path
        else:
            raise Exception("No audio segments generated")
    
    def mix_audio(self, original_audio_path: str, chinese_audio_path: str, subtitles: List[Dict]) -> str:
        """
        混合原始音频和中文音频
        
        参数:
            original_audio_path: 原始音频文件路径
            chinese_audio_path: 中文音频文件路径
            subtitles: 字幕列表
            
        返回:
            混合后的音频文件路径
        """
        logger.info("Mixing audio...")
        mixed_audio_path = os.path.join("temp", "mixed_audio.wav")
        
        # 检查是否已存在混合音频文件
        if os.path.exists(mixed_audio_path):
            logger.info(f"Found existing mixed audio file: {mixed_audio_path}")
            return mixed_audio_path
        
        try:
            # 准备音频文件
            with open(original_audio_path, 'rb') as f1, open(chinese_audio_path, 'rb') as f2:
                files = {
                    'original_audio': ('original.wav', f1, 'audio/wav'),
                    'chinese_audio': ('chinese.wav', f2, 'audio/wav')
                }
                
                # 准备字幕信息
                data = {
                    'subtitles': json.dumps(subtitles)
                }
                
                # 调用音频混合 API
                response = requests.post(
                    f"{self.tts_server_url}/mix_audio",
                    files=files,
                    data=data
                )
                
                if response.status_code == 200:
                    # 保存混合后的音频
                    with open(mixed_audio_path, 'wb') as f:
                        f.write(response.content)
                    return mixed_audio_path
                else:
                    raise Exception(f"Audio mixing failed: {response.text}")
                    
        except Exception as e:
            logger.error(f"Error mixing audio: {str(e)}")
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
            logger.info(f"加载音频文件: {audio_path}")
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
                    
                    # 如果切片文件已存在，跳过创建
                    if os.path.exists(segment_path):
                        logger.debug(f"音频切片已存在: {segment_filename}")
                    else:
                        # 提取音频片段
                        audio_segment = audio[start_time:end_time]
                        
                        # 确保音频片段长度至少为500ms，避免过短的音频
                        if len(audio_segment) < 500:
                            logger.warning(f"音频片段 {i} 太短({len(audio_segment)}ms)，扩展到500ms")
                            # 向前扩展时间
                            extend_time = 500 - len(audio_segment)
                            new_start = max(0, start_time - extend_time // 2)
                            new_end = min(len(audio), end_time + extend_time // 2)
                            audio_segment = audio[new_start:new_end]
                        
                        # 保存音频切片
                        audio_segment.export(segment_path, format="mp3")
                        logger.debug(f"创建音频切片: {segment_filename}")
                    
                    # 更新字幕，添加reference_audio字段
                    updated_subtitle = subtitle.copy()
                    updated_subtitle["reference_audio"] = segment_path
                    updated_subtitles.append(updated_subtitle)
                    
                except Exception as e:
                    logger.error(f"创建第 {i} 个音频切片失败: {str(e)}")
                    # 即使出错也要保留原字幕
                    updated_subtitles.append(subtitle)
                    continue
            
            logger.info(f"成功创建 {len([s for s in updated_subtitles if 'reference_audio' in s])} 个音频切片")
            return updated_subtitles
            
        except Exception as e:
            logger.error(f"创建音频切片失败: {str(e)}")
            return subtitles  # 返回原始字幕

    async def upload_reference_audio(self, subtitles: List[Dict]) -> List[Dict]:
        """
        将参考音频上传到TTS服务器
        
        参数:
            subtitles: 包含reference_audio字段的字幕列表
            
        返回:
            更新后的字幕列表
        """
        try:
            import aiohttp
            uploaded_files = set()  # 记录已上传的文件，避免重复上传
            
            # 检查TTS服务器是否可用
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{self.tts_server_url}/", timeout=aiohttp.ClientTimeout(total=5)) as response:
                        pass
            except Exception as e:
                logger.warning(f"TTS服务器不可用，跳过音频上传: {str(e)}")
                return subtitles
            
            async with aiohttp.ClientSession() as session:
                for i, subtitle in enumerate(subtitles):
                    reference_audio = subtitle.get("reference_audio")
                    if not reference_audio or not os.path.exists(reference_audio):
                        logger.warning(f"第 {i} 个字幕缺少参考音频文件: {reference_audio}")
                        continue
                    
                    # 检查是否已经上传过这个文件
                    filename = os.path.basename(reference_audio)
                    if filename in uploaded_files:
                        logger.debug(f"音频文件已上传，跳过: {filename}")
                        continue
                    
                    try:
                        # 上传音频文件
                        with open(reference_audio, 'rb') as f:
                            data = aiohttp.FormData()
                            data.add_field('file', f, filename=filename, content_type='audio/mpeg')
                            
                            async with session.post(
                                f"{self.tts_server_url}/upload_audio",
                                data=data,
                                timeout=aiohttp.ClientTimeout(total=30)
                            ) as response:
                                if response.status == 200:
                                    try:
                                        result = await response.json()
                                        logger.info(f"成功上传音频文件: {filename}")
                                    except:
                                        logger.info(f"成功上传音频文件: {filename}")
                                    uploaded_files.add(filename)
                                else:
                                    error_text = await response.text()
                                    logger.error(f"上传音频文件失败 {filename}: HTTP {response.status} - {error_text}")
                    
                    except Exception as e:
                        logger.error(f"上传第 {i} 个音频文件失败: {str(e)}")
                        continue
            
            logger.info(f"共上传了 {len(uploaded_files)} 个参考音频文件")
            return subtitles
            
        except Exception as e:
            logger.error(f"上传参考音频失败: {str(e)}")
            return subtitles 