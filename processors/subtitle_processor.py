import os
import json
import requests
import logging
from typing import List, Dict

logger = logging.getLogger("video-translation-client")

class SubtitleProcessor:
    def __init__(self, stt_server_url: str):
        """
        初始化字幕处理器
        
        参数:
            stt_server_url: 语音识别服务器地址
        """
        self.stt_server_url = stt_server_url
    
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
    
    def get_subtitles(self, audio_path: str) -> List[Dict]:
        """
        获取音频的字幕
        
        参数:
            audio_path: 音频文件路径
            
        返回:
            字幕列表
        """
        try:
            # 计算文件哈希值
            file_hash = self.get_file_hash(audio_path)
            
            # 从音频路径中获取视频目录名
            # 音频路径格式：temp/{video_name}/{file_hash}_audio.wav
            video_name = os.path.basename(os.path.dirname(audio_path))
            
            cache_file = os.path.join("temp", video_name, f"{file_hash}_subtitles.json")
            speaker_cache_file = os.path.join("temp", video_name, f"{file_hash}_speaker_segments.json")
            
            # 检查缓存
            if os.path.exists(cache_file):
                logger.info(f"Using cached subtitle file: {cache_file}")
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            
            # 检查说话人识别缓存
            speaker_segments = []
            if os.path.exists(speaker_cache_file):
                logger.info(f"Using cached speaker recognition results: {speaker_cache_file}")
                with open(speaker_cache_file, 'r', encoding='utf-8') as f:
                    speaker_segments = json.load(f)
            else:
                # 进行说话人识别
                logger.info("Starting speaker recognition...")
                with open(audio_path, 'rb') as f:
                    diarization_response = requests.post(
                        f"{self.stt_server_url}/diarize/",
                        files={"file": f},
                        timeout=600  # 延长超时时间到10分钟
                    )
                
                if diarization_response.status_code != 200:
                    logger.warning(f"Speaker recognition failed: {diarization_response.text}")
                    logger.info("Continuing with default speaker")
                    speaker_segments = []
                else:
                    speaker_segments = diarization_response.json().get("segments", [])
                    logger.info(f"Identified {len(speaker_segments)} speaker segments")
                    
                    # 保存说话人识别结果到缓存
                    with open(speaker_cache_file, 'w', encoding='utf-8') as f:
                        json.dump(speaker_segments, f, ensure_ascii=False, indent=2)
                    logger.info(f"Speaker recognition results saved to: {speaker_cache_file}")
            
            # 进行音频转录
            logger.info("Starting audio transcription...")
            with open(audio_path, 'rb') as f:
                response = requests.post(
                    f"{self.stt_server_url}/transcribe/",
                    files={"file": f},
                    timeout=600  # 延长超时时间到10分钟
                )
            
            if response.status_code != 200:
                raise Exception(f"Transcription failed: {response.text}")
            
            # 处理转录结果
            result = response.json()
            segments = result.get("segments", [])
            
            # 合并说话人信息
            if speaker_segments:
                logger.info("Merging speaker information...")
                for segment in segments:
                    # 找到对应的说话人
                    segment_start = segment["start"]
                    segment_end = segment["end"]
                    
                    # 查找重叠的说话人片段
                    for speaker_segment in speaker_segments:
                        if (segment_start >= speaker_segment["start"] and 
                            segment_end <= speaker_segment["end"]):
                            segment["speaker"] = speaker_segment["speaker"]
                            break
                    else:
                        # 如果没有找到对应的说话人，使用默认值
                        segment["speaker"] = "SPEAKER_0"
            
            # 保存到缓存
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(segments, f, ensure_ascii=False, indent=2)
            logger.info(f"Subtitles saved to: {cache_file}")
            
            return segments
            
        except Exception as e:
            logger.error(f"Failed to get subtitles: {str(e)}")
            raise
    
    def save_subtitles_to_srt(self, subtitles: List[Dict], output_path: str):
        """
        将字幕保存为 SRT 格式
        
        参数:
            subtitles: 字幕列表
            output_path: 输出文件路径
        """
        try:
            logger.info(f"Saving SRT file: {output_path}")
            with open(output_path, 'w', encoding='utf-8') as f:
                for i, subtitle in enumerate(subtitles, 1):
                    # 写入序号
                    f.write(f"{i}\n")
                    
                    # 写入时间戳
                    start_time = self.format_time(subtitle["start"])
                    end_time = self.format_time(subtitle["end"])
                    f.write(f"{start_time} --> {end_time}\n")
                    
                    # 写入说话人信息和文本
                    speaker = subtitle.get("speaker", "SPEAKER_0")
                    text = subtitle["text"]
                    f.write(f"[{speaker}] {text}\n\n")
            
            logger.info(f"SRT file saved: {output_path}")
            
        except Exception as e:
            logger.error(f"Failed to save SRT file: {str(e)}")
            raise
    
    def format_time(self, seconds: float) -> str:
        """
        将秒数格式化为SRT时间格式
        
        参数:
            seconds: 秒数
            
        返回:
            格式化的时间字符串
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = seconds % 60
        milliseconds = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{int(seconds):02d},{milliseconds:03d}" 