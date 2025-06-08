import os
import requests
import soundfile as sf
import numpy as np
import librosa
from pydub import AudioSegment
import logging
from typing import List, Dict, Any
import json
from tqdm import tqdm
import subprocess
from pathlib import Path
from config import STT_SERVER_URL, TTS_SERVER_URL, AUDIO_SAMPLE_RATE, AUDIO_CHANNELS

logger = logging.getLogger("video-translation-client")

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
        
    def extract_audio(self, video_path: str, output_path: str = None) -> str:
        """
        从视频中提取音频
        
        参数:
            video_path: 视频文件路径
            output_path: 输出音频文件路径，如果为 None 则自动生成
            
        返回:
            音频文件路径
        """
        try:
            if output_path is None:
                # 生成默认输出路径
                video_name = os.path.splitext(os.path.basename(video_path))[0]
                output_path = os.path.join("temp", video_name, "audio.wav")
            
            # 确保输出目录存在
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # 使用 ffmpeg 提取音频
            command = [
                "ffmpeg",
                "-i", video_path,
                "-vn",  # 不处理视频
                "-acodec", "pcm_s16le",  # 音频编码
                "-ar", str(AUDIO_SAMPLE_RATE),  # 采样率
                "-ac", str(AUDIO_CHANNELS),  # 声道数
                "-y",  # 覆盖已存在的文件
                output_path
            ]
            
            subprocess.run(command, check=True, capture_output=True)
            logger.info(f"Audio extracted to: {output_path}")
            
            return output_path
            
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