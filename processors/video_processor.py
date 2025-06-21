import os
import subprocess
import logging
from typing import List, Dict
from utils.common import format_time

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
        try:
            logger.info("开始生成最终视频...")
            
            # 检查输入文件
            if not os.path.exists(video_path):
                raise FileNotFoundError(f"原始视频文件不存在: {video_path}")
            if not os.path.exists(audio_path):
                raise FileNotFoundError(f"音频文件不存在: {audio_path}")
            
            # 创建字幕文件
            # video_name = os.path.splitext(os.path.basename(video_path))[0]
            # temp_dir = os.path.dirname(output_path)
            # srt_path = os.path.join(temp_dir, f"{video_name}_zh.srt")
            
            # logger.info(f"创建字幕文件: {srt_path}")
            # with open(srt_path, "w", encoding="utf-8") as f:
            #     for i, subtitle in enumerate(subtitles, 1):
            #         start_time = format_time(subtitle["start"])
            #         end_time = format_time(subtitle["end"])
            #         f.write(f"{i}\n")
            #         f.write(f"{start_time} --> {end_time}\n")
                    
            #         # 使用翻译后的文本
            #         text = subtitle.get("text", subtitle.get("translated_text", ""))
            #         speaker = subtitle.get("speaker", "")
            #         if speaker and speaker != "Unknown":
            #             f.write(f"[{speaker}] {text}\n\n")
            #         else:
            #             f.write(f"{text}\n\n")
            
            # 使用ffmpeg合并视频和音频，并嵌入字幕
            logger.info("使用FFmpeg合成视频...")
            
            # 构建ffmpeg命令 - 只替换音频，不重新编码视频
            ffmpeg_cmd = [
                'ffmpeg',
                '-i', video_path,      # 输入视频
                '-i', audio_path,      # 输入音频
                '-c:v', 'copy',        # 复制视频流，不重新编码
                '-c:a', 'aac',         # 音频编码器
                '-map', '0:v:0',       # 使用第一个输入的视频流
                '-map', '1:a:0',       # 使用第二个输入的音频流
                '-y',                  # 覆盖输出文件
                output_path
            ]
            
            logger.info(f"执行FFmpeg命令: {' '.join(ffmpeg_cmd)}")
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=300)  # 5分钟超时
            
            if result.returncode != 0:
                logger.error(f"FFmpeg stderr: {result.stderr}")
                logger.error(f"FFmpeg stdout: {result.stdout}")
                raise RuntimeError(f"视频合成失败: {result.stderr}")
            
            # 检查输出文件
            if not os.path.exists(output_path):
                raise RuntimeError(f"视频合成失败: 输出文件不存在 {output_path}")
            
            file_size = os.path.getsize(output_path) / (1024 * 1024)  # MB
            logger.info(f"视频合成成功: {output_path} ({file_size:.2f} MB)")
            
            return output_path
            
        except subprocess.TimeoutExpired:
            logger.error("视频合成超时")
            raise RuntimeError("视频合成超时，请检查输入文件或减少视频长度")
        except Exception as e:
            logger.error(f"创建最终视频失败: {str(e)}")
            raise 