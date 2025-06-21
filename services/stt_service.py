import os
import requests
import logging
from typing import List, Dict, Optional
import json
from pathlib import Path

logger = logging.getLogger(__name__)

class STTService:
    """语音识别服务"""
    
    def __init__(self, stt_server_url: str):
        """
        初始化STT服务
        
        参数:
            stt_server_url: 语音识别服务器地址
        """
        self.stt_server_url = stt_server_url
    
    def transcribe_audio(self, audio_path: str, language: str = "en") -> List[Dict]:
        """
        识别音频文件中的语音
        
        参数:
            audio_path: 音频文件路径
            language: 识别语言
            
        返回:
            识别结果列表
        """
        try:
            logger.info(f"Starting speech recognition for: {audio_path}")
            
            # 检查音频文件是否存在
            if not os.path.exists(audio_path):
                raise FileNotFoundError(f"Audio file not found: {audio_path}")
            
            # 准备文件上传
            with open(audio_path, 'rb') as audio_file:
                files = {'file': audio_file}
                data = {'language': language}
                
                # 发送请求到STT服务器
                response = requests.post(
                    f"{self.stt_server_url}/transcribe",
                    files=files,
                    data=data,
                    timeout=300  # 5分钟超时
                )
            
            if response.status_code != 200:
                error_msg = f"STT request failed: {response.status_code} - {response.text}"
                logger.error(error_msg)
                raise Exception(error_msg)
            
            # 解析响应
            result = response.json()
            segments = result.get('segments', [])
            
            logger.info(f"Speech recognition completed, found {len(segments)} segments")
            
            return segments
            
        except Exception as e:
            logger.error(f"Speech recognition failed: {str(e)}")
            raise
    
    def save_transcription(self, segments: List[Dict], video_name: str, file_hash: str) -> str:
        """
        保存识别结果到文件
        
        参数:
            segments: 识别结果
            video_name: 视频名称
            file_hash: 文件哈希
            
        返回:
            保存的文件路径
        """
        try:
            # 创建输出目录
            temp_dir = os.path.join("temp", video_name)
            os.makedirs(temp_dir, exist_ok=True)
            
            # 保存为JSON文件
            subtitle_path = os.path.join(temp_dir, f"{file_hash}_subtitles.json")
            with open(subtitle_path, 'w', encoding='utf-8') as f:
                json.dump(segments, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Transcription saved to: {subtitle_path}")
            return subtitle_path
            
        except Exception as e:
            logger.error(f"Failed to save transcription: {str(e)}")
            raise
    
    def extract_speakers_from_segments(self, segments: List[Dict]) -> List[str]:
        """
        从识别结果中提取说话人信息
        
        参数:
            segments: 识别结果
            
        返回:
            说话人列表
        """
        speakers = set()
        for segment in segments:
            speaker = segment.get("speaker")
            if speaker:
                speakers.add(speaker)
        
        return list(speakers) 