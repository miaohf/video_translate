import os
import json
import logging
import aiohttp
from typing import List, Dict, Any, Optional
from utils.common import get_file_hash
from config import STT_SERVER_URL

logger = logging.getLogger(__name__)

class SubtitleProcessor:
    def __init__(self, stt_server_url: str = None):
        """
        初始化字幕处理器
        
        参数:
            stt_server_url: 语音识别服务器地址
        """
        self.stt_server_url = stt_server_url or STT_SERVER_URL
        self._session = None
        logger.info("Subtitle processor initialized")
        
    async def get_session(self) -> aiohttp.ClientSession:
        """
        获取或创建 aiohttp session
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
        
    async def close(self):
        """
        关闭 aiohttp session
        """
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        
    async def get_subtitles(self, audio_path: str, video_name: str) -> List[Dict[str, Any]]:
        """
        从音频文件生成字幕
        
        参数:
            audio_path: 音频文件路径
            video_name: 视频文件名（不含扩展名）
            
        返回:
            字幕列表，每个元素为包含 start, end, text, speaker 的字典
        """
        try:
            # 检查缓存
            file_hash = get_file_hash(audio_path)
            
            # 音频路径格式：temp/{video_name}/{file_hash}_audio.wav
            # 缓存文件格式：temp/{video_name}/{file_hash}_subtitles.json
            cache_file = os.path.join("temp", video_name, f"{file_hash}_subtitles.json")
            speaker_cache_file = os.path.join("temp", video_name, f"{file_hash}_speaker_segments.json")
            
            if os.path.exists(cache_file) and os.path.exists(speaker_cache_file):
                logger.info("Using cached subtitles")
                with open(cache_file, 'r', encoding='utf-8') as f:
                    subtitles = json.load(f)
                with open(speaker_cache_file, 'r', encoding='utf-8') as f:
                    speaker_segments = json.load(f)
                    
                # 合并说话人信息
                for subtitle in subtitles:
                    subtitle["speaker"] = "Unknown"
                    for segment in speaker_segments:
                        if (subtitle["start"] >= segment["start"] and 
                            subtitle["end"] <= segment["end"]):
                            subtitle["speaker"] = segment["speaker"]
                            break
                            
                return subtitles
            
            # 生成字幕
            logger.info("Generating subtitles")
            session = await self.get_session()
            
            # 准备音频文件
            with open(audio_path, 'rb') as f:
                audio_data = f.read()
            
            # 发送请求到语音识别服务器
            async with session.post(
                f"{self.stt_server_url}/transcribe",
                data={'file': audio_data}
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"STT API error: {error_text}")
                    
                result = await response.json()
                
            # 转换为字幕格式
            subtitles = []
            for segment in result['segments']:
                subtitle = {
                    "start": segment['start'],
                    "end": segment['end'],
                    "text": segment['text'].strip(),
                    "speaker": "Unknown"  # 默认说话人
                }
                subtitles.append(subtitle)
            
            # 保存字幕
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(subtitles, f, ensure_ascii=False, indent=2)
            
            return subtitles
            
        except Exception as e:
            logger.error(f"Error generating subtitles: {str(e)}")
            raise
        finally:
            # 确保关闭session
            await self.close()
            
    def save_subtitles_to_srt(self, subtitles: List[Dict[str, Any]], output_path: str):
        """
        将字幕保存为SRT格式
        
        参数:
            subtitles: 字幕列表
            output_path: 输出文件路径
        """
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                for i, subtitle in enumerate(subtitles, 1):
                    # 格式化时间
                    start_time = self.format_time(subtitle["start"])
                    end_time = self.format_time(subtitle["end"])
                    
                    # 写入字幕
                    f.write(f"{i}\n")
                    f.write(f"{start_time} --> {end_time}\n")
                    if subtitle["speaker"] != "Unknown":
                        f.write(f"[{subtitle['speaker']}] {subtitle['text']}\n")
                    else:
                        f.write(f"{subtitle['text']}\n")
                    f.write("\n")
                    
            logger.info(f"Subtitles saved to {output_path}")
            
        except Exception as e:
            logger.error(f"Error saving subtitles: {str(e)}")
            raise
            
    def format_time(self, seconds: float) -> str:
        """
        将秒数格式化为SRT时间格式
        
        参数:
            seconds: 秒数
            
        返回:
            格式化的时间字符串 (HH:MM:SS,mmm)
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = seconds % 60
        milliseconds = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{int(seconds):02d},{milliseconds:03d}" 