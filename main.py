import os
import argparse
import logging
import platform
import asyncio
from typing import Dict, Optional, List
from pathlib import Path

from services.translation_service import TranslationService
from processors.audio_processor import AudioProcessor
from processors.subtitle_processor import SubtitleProcessor
from processors.video_processor import VideoProcessor
from utils.common import get_file_hash

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class VideoTranslationClient:
    def __init__(self, stt_server_url: str, tts_server_url: str, speaker: str = None, speaker_mapping: Dict[str, str] = None):
        """
        初始化视频翻译客户端
        
        参数:
            stt_server_url: 语音识别服务器地址
            tts_server_url: 语音合成服务器地址
            speaker: 默认说话人
            speaker_mapping: 说话人映射配置
        """
        self.stt_server_url = stt_server_url
        self.tts_server_url = tts_server_url
        self.speaker = speaker
        self.speaker_mapping = speaker_mapping or {}  # 说话人映射配置
        
        # 初始化各个处理器
        self.translation_service = TranslationService()
        self.audio_processor = AudioProcessor(stt_server_url, tts_server_url)
        self.subtitle_processor = SubtitleProcessor(stt_server_url)
        self.video_processor = VideoProcessor()
        
        # 打印环境信息
        logger.info(f"System Info:")
        logger.info(f"- OS: {platform.system()} {platform.release()}")
        logger.info(f"- Python Version: {platform.python_version()}")
        
        # 确保temp目录存在
        os.makedirs("temp", exist_ok=True)
        
        # 打印说话人映射配置
        if self.speaker_mapping:
            logger.info("Speaker Mapping:")
            for original_speaker, target_speaker in self.speaker_mapping.items():
                logger.info(f"- {original_speaker} -> {target_speaker}")
    
    def _get_temp_dir(self, video_path: str) -> str:
        """
        获取临时文件目录
        
        参数:
            video_path: 视频文件路径
            
        返回:
            临时文件目录路径
        """
        # 使用输入视频的文件名作为目录名
        video_name = Path(video_path).stem
        temp_dir = os.path.join("temp", video_name)
        os.makedirs(temp_dir, exist_ok=True)
        return temp_dir
    
    async def process_video(self, video_path: str, output_path: str = None):
        """
        处理视频
        
        参数:
            video_path: 视频文件路径
            output_path: 输出文件路径，如果为 None 则自动生成
        """
        try:
            # 获取视频文件名（不含扩展名）
            video_name = Path(video_path).stem
            
            # 检查翻译后的字幕文件是否存在
            file_hash = get_file_hash(video_name)
            translated_subtitle_path = os.path.join("temp", video_name, f"{file_hash}_subtitles_zh.srt")
            if os.path.exists(translated_subtitle_path):
                logger.info(f"发现已存在的翻译字幕文件: {translated_subtitle_path}")
                # 读取已存在的字幕文件
                with open(translated_subtitle_path, 'r', encoding='utf-8') as f:
                    srt_content = f.read()
                    # 解析 SRT 格式字幕
                    subtitles = []
                    for block in srt_content.strip().split('\n\n'):
                        lines = block.split('\n')
                        if len(lines) >= 3:
                            # 解析时间戳
                            time_line = lines[1]
                            start_time, end_time = time_line.split(' --> ')
                            # 转换时间格式为秒
                            start_seconds = self._srt_time_to_seconds(start_time)
                            end_seconds = self._srt_time_to_seconds(end_time)
                            # 获取文本内容
                            text = '\n'.join(lines[2:])
                            subtitles.append({
                                "start": start_seconds,
                                "end": end_seconds,
                                "text": text,
                                "translated_text": text  # 因为已经是翻译后的字幕，所以直接使用
                            })
                logger.info(f"已加载 {len(subtitles)} 条字幕")
            else:
                # 处理说话人分离
                logger.info("\n1. Extracting Audio...")
                audio_path = self.audio_processor.extract_audio(video_path, video_name)
                # subtitles = await self.subtitle_processor.process_speaker_diarization(video_path, video_name, file_hash)
                # logger.info(f"说话人分离完成，共识别出 {len(subtitles)} 条字幕")
                
                # 获取字幕
                logger.info("\n2. Generating Subtitles...")
                subtitles = await self.subtitle_processor.get_subtitles(audio_path, video_name)

                # 翻译字幕
                logger.info("\n3. Translating Subtitles...")
                subtitles = await self.translation_service.translate_batch_subtitles(subtitles, video_name)
                logger.info("字幕翻译完成")
            
            # 生成 TTS 音频
            logger.info("开始生成 TTS 音频...")
            tts_audio_path = await self._generate_tts_audio(subtitles, video_name)
            logger.info("TTS 音频生成完成")
            
            # 保存翻译后的字幕
            if output_path is None:
                # 使用文件哈希值生成输出路径
                file_hash = get_file_hash(video_path)
                output_path = os.path.join("temp", video_name, f"{file_hash}_subtitles_zh.srt")
            
            self.subtitle_processor.save_subtitles_to_srt(subtitles, output_path)
            logger.info(f"\nTranslation completed, output saved to {output_path}")
            
            return tts_audio_path
            
        except Exception as e:
            logger.error(f"处理视频失败: {str(e)}")
            raise
            
    def _srt_time_to_seconds(self, time_str: str) -> float:
        """
        将 SRT 时间格式转换为秒
        
        参数:
            time_str: SRT 格式的时间字符串 (HH:MM:SS,mmm)
            
        返回:
            秒数
        """
        hours, minutes, seconds = time_str.replace(',', '.').split(':')
        return float(hours) * 3600 + float(minutes) * 60 + float(seconds)

    async def _generate_tts_audio(self, subtitles: List[Dict], video_name: str) -> str:
        """
        生成 TTS 音频
        
        参数:
            subtitles: 字幕列表
            video_name: 视频名称
            
        返回:
            生成的音频文件路径
        """
        try:
            # 检查最终音频文件是否已存在
            final_audio_path = os.path.join("temp", video_name, "final_audio.wav")
            if os.path.exists(final_audio_path):
                logger.info(f"发现已存在的音频文件: {final_audio_path}")
                return final_audio_path
            
            # 创建临时目录
            temp_dir = os.path.join("temp", video_name, "tts_segments")
            os.makedirs(temp_dir, exist_ok=True)
            
            # 获取 TTS 服务器地址
            tts_server_url = os.getenv("TTS_SERVER_URL", "http://localhost:8000")
            
            # 生成每个字幕的音频
            audio_segments = []
            for i, subtitle in enumerate(subtitles):
                try:
                    # 检查音频片段是否已存在
                    segment_path = os.path.join(temp_dir, f"segment_{i:04d}.wav")
                    if os.path.exists(segment_path):
                        logger.info(f"发现已存在的音频片段: {segment_path}")
                        audio_segments.append({
                            "path": segment_path,
                            "start": subtitle["start"],
                            "end": subtitle["end"]
                        })
                        continue
                    
                    # 获取要转换的文本
                    text_to_convert = subtitle.get("translated_text") or subtitle.get("text")
                    if not text_to_convert:
                        logger.warning(f"第 {i+1} 个字幕没有文本内容，跳过")
                        continue
                    
                    # 准备请求数据
                    data = {
                        "text": text_to_convert,
                        "speaker": subtitle.get("speaker", "Unknown"),
                        "temperature": 0.8,
                        "top_k": 50,  # 确保是整数
                        "top_p": 0.95,
                        "seed": 421 + i  # 为每个片段使用不同的种子
                    }
                    
                    # 发送请求到 TTS 服务器
                    session = await self.subtitle_processor.get_session()
                    async with session.post(f"{tts_server_url}/tts", json=data) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            logger.error(f"生成 TTS 音频失败: {error_text}")
                            continue
                        
                        # 保存音频片段
                        with open(segment_path, "wb") as f:
                            f.write(await response.read())
                        
                        # 记录音频片段信息
                        audio_segments.append({
                            "path": segment_path,
                            "start": subtitle["start"],
                            "end": subtitle["end"]
                        })
                        
                        logger.info(f"已生成第 {i+1}/{len(subtitles)} 个音频片段")
                        
                except Exception as e:
                    logger.error(f"处理第 {i+1} 个音频片段时出错: {str(e)}")
                    continue
            
            # 如果所有音频片段都已存在，直接合并
            if len(audio_segments) == len(subtitles):
                logger.info("所有音频片段已存在，开始合并...")
            else:
                logger.info("正在合并音频片段...")
            
            # 使用 pydub 合并音频
            from pydub import AudioSegment
            final_audio = AudioSegment.silent(duration=0)
            
            for segment in audio_segments:
                # 加载音频片段
                audio = AudioSegment.from_file(segment["path"])
                
                # 计算需要添加的静音时长
                silence_duration = int((segment["start"] - final_audio.duration_seconds) * 1000)
                if silence_duration > 0:
                    silence = AudioSegment.silent(duration=silence_duration)
                    final_audio += silence
                
                # 添加音频片段
                final_audio += audio
            
            # 导出最终音频
            final_audio.export(final_audio_path, format="wav")
            logger.info(f"音频生成完成: {final_audio_path}")
            
            # 清理临时文件
            for segment in audio_segments:
                try:
                    os.remove(segment["path"])
                except:
                    pass
            
            return final_audio_path
            
        except Exception as e:
            logger.error(f"生成 TTS 音频失败: {str(e)}")
            raise

if __name__ == "__main__":
    # 创建命令行参数解析器
    parser = argparse.ArgumentParser(description="Video Translation Program")
    parser.add_argument("--input_video", required=True, help="Input Video File Path")
    parser.add_argument("--output_video", required=True, help="Output Video File Path")
    parser.add_argument("--stt_server", default="http://localhost:8001", help="STT Server Address")
    parser.add_argument("--tts_server", default="http://localhost:8000", help="TTS Server Address")
    parser.add_argument("--speaker", help="Default TTS Speaker Name")
    parser.add_argument("--speaker_mapping", help="Speaker Mapping Configuration, Format: 'speaker1:voice1,speaker2:voice2'")
    
    args = parser.parse_args()
    
    # 解析说话人映射配置
    speaker_mapping = {}
    if args.speaker_mapping:
        try:
            mappings = args.speaker_mapping.split(',')
            for mapping in mappings:
                original, target = mapping.split(':')
                speaker_mapping[original.strip()] = target.strip()
        except Exception as e:
            logger.error(f"Failed to Parse Speaker Mapping Configuration: {str(e)}")
            raise ValueError("Speaker Mapping Configuration Format Error, Please Use 'speaker1:voice1,speaker2:voice2' Format")
    
    video_translation_client = VideoTranslationClient(
        stt_server_url=args.stt_server,
        tts_server_url=args.tts_server,
        speaker=args.speaker,
        speaker_mapping=speaker_mapping
    )
    
    asyncio.run(video_translation_client.process_video(args.input_video, args.output_video))