import os
import argparse
import logging
import platform
import asyncio
from typing import Dict, Optional, List
from pathlib import Path
import json

from services.translation_service import TranslationService
from processors.audio_processor import AudioProcessor
from processors.subtitle_processor import SubtitleProcessor
from processors.video_processor import VideoProcessor
from utils.common import get_file_hash
from config import settings

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class VideoTranslationClient:
    def __init__(self):
        """
        初始化视频翻译客户端
        
        """      
        # 初始化各个处理器
        self.translation_service = TranslationService()
        self.audio_processor = AudioProcessor(settings.STT_SERVER_URL, settings.TTS_SERVER_URL)
        self.subtitle_processor = SubtitleProcessor(settings.STT_SERVER_URL)
        self.video_processor = VideoProcessor()
        
        # 打印环境信息
        logger.info(f"System Info:")
        logger.info(f"- OS: {platform.system()} {platform.release()}")
        logger.info(f"- Python Version: {platform.python_version()}")
        
        # 确保temp目录存在
        os.makedirs("temp", exist_ok=True)
    
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
            translated_subtitle_path = os.path.join("temp", video_name, f"{file_hash}_subtitles_zh.json")
            if os.path.exists(translated_subtitle_path):
                logger.info(f"发现已存在的翻译字幕文件: {translated_subtitle_path}")
                # 读取已存在的字幕文件
                with open(translated_subtitle_path, 'r', encoding='utf-8') as f:
                    subtitles = json.load(f)
                logger.info(f"已加载 {len(subtitles)} 条字幕")
                
                # 检查是否需要创建音频切片
                audio_path = os.path.join("temp", video_name, f"{file_hash}_audio.mp3")
                if os.path.exists(audio_path):
                    # 检查字幕是否已包含reference_audio字段
                    if not any('reference_audio' in subtitle for subtitle in subtitles):
                        logger.info("为已有字幕创建参考音频切片...")
                        subtitles = self.audio_processor.create_audio_segments(audio_path, subtitles, video_name)
                        logger.info("参考音频切片创建完成")
                        
                        # 上传参考音频到TTS服务器
                        logger.info("上传参考音频...")
                        subtitles = await self.audio_processor.upload_reference_audio(subtitles)
                        logger.info("参考音频上传完成")
                        
                        # 保存更新后的字幕文件
                        with open(translated_subtitle_path, 'w', encoding='utf-8') as f:
                            json.dump(subtitles, f, ensure_ascii=False, indent=2)
                        logger.info("已更新字幕文件，添加参考音频信息")
            else:
                # 处理说话人分离
                logger.info("\n1. Extracting Audio...")
                audio_path = self.audio_processor.extract_audio(video_path, video_name)
                # subtitles = await self.subtitle_processor.process_speaker_diarization(video_path, video_name, file_hash)
                # logger.info(f"说话人分离完成，共识别出 {len(subtitles)} 条字幕")
                
                # 获取字幕
                logger.info("\n2. Generating Subtitles...")
                # 检查是否存在翻译后的字幕文件
                subtitle_json_path = os.path.join("temp", video_name, f"{file_hash}_subtitles.json")
                if os.path.exists(subtitle_json_path):
                    logger.info(f"使用已存在的翻译字幕文件: {subtitle_json_path}")
                    with open(subtitle_json_path, "r", encoding="utf-8") as f:
                        subtitles = json.load(f)
                else:
                    # 生成字幕
                    subtitles = await self.subtitle_processor.get_subtitles(audio_path, video_name)

                # 翻译字幕
                logger.info("\n3. Translating Subtitles...")
                subtitles = await self.translation_service.translate_batch_subtitles(subtitles, video_name)
                logger.info("字幕翻译完成")

                # 创建音频切片作为参考音频
                logger.info("\n4. Creating Reference Audio Segments...")
                subtitles = self.audio_processor.create_audio_segments(audio_path, subtitles, video_name)
                logger.info("参考音频切片创建完成")

                # 上传参考音频到TTS服务器
                logger.info("\n5. Uploading Reference Audio...")
                subtitles = await self.audio_processor.upload_reference_audio(subtitles)
                logger.info("参考音频上传完成")
            
            # 生成 TTS 音频
            logger.info("\n6. 开始生成 TTS 音频...")
            tts_audio_path = await self._generate_tts_audio(subtitles, video_name)
            logger.info("TTS 音频生成完成")
            
            # 保存翻译后的字幕
            if output_path is None:
                # 使用文件哈希值生成输出路径
                file_hash = get_file_hash(video_path)
                output_path = os.path.join("temp", video_name, f"{file_hash}_subtitles_zh.json")
            
            self.subtitle_processor.save_subtitles_to_json(subtitles, output_path)
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
            final_audio_path = os.path.join("temp", video_name, "final_audio.mp3")
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
                    
                    # 从reference_audio字段中提取说话人信息
                    # logger.info(f"subtitle: {subtitle}")
                    reference_audio = subtitle.get("reference_audio", "")
                    if reference_audio:
                        # 从文件路径中提取说话人信息，格式为：file_hash_index_SPEAKER_XX.mp3
                        speaker = Path(reference_audio).stem
                    else:
                        speaker = "Unknown"
                    
                    # 准备请求数据
                    data = {
                        "text": text_to_convert,
                        "speaker": speaker,
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
    args = parser.parse_args()
    
    video_translation_client = VideoTranslationClient()
    asyncio.run(video_translation_client.process_video(args.input_video))