import os
import subprocess
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

class VideoProcessor:
    def create_final_video(self, video_path: str, audio_path: str, subtitles: List[Dict], output_path: str) -> str:
        """
        创建最终视频
        
        参数:
            video_path: 原始视频路径
            audio_path: 音频文件路径
            subtitles: 字幕列表
            output_path: 输出视频路径
            
        返回:
            输出视频路径
        """
        logger.info("Generating final video...")
        
        # 创建字幕文件
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        srt_path = os.path.join("temp", f"{base_name}.srt")
        
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, subtitle in enumerate(subtitles, 1):
                start_time = self.format_time(subtitle["start"])
                end_time = self.format_time(subtitle["end"])
                f.write(f"{i}\n")
                f.write(f"{start_time} --> {end_time}\n")
                speaker_text = f"[{subtitle['speaker']}] " if subtitle['speaker'] else ""
                f.write(f"{speaker_text}{subtitle['translated_text']}\n\n")
        
        # 使用ffmpeg合并视频和音频
        ffmpeg_cmd = f'ffmpeg -i {video_path} -i {audio_path} -c:v copy -c:a aac -map 0:v:0 -map 1:a:0 {output_path}'
        result = subprocess.run(ffmpeg_cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg processing failed: {result.stderr}")
        
        return output_path
    
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