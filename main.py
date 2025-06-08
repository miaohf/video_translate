import os
import argparse
import logging
import platform
import asyncio
from typing import Dict
from pathlib import Path

from services.translation_service import TranslationService
from processors.audio_processor import AudioProcessor
from processors.subtitle_processor import SubtitleProcessor
from processors.video_processor import VideoProcessor

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("video-translation-client")

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
    
    async def process_video(self, video_path: str, output_path: str, speaker_name: str = None):
        """
        异步处理视频文件
        
        参数:
            video_path: 输入视频路径
            output_path: 输出视频路径
            speaker_name: 说话人名称
        """
        # 获取视频文件名（不含扩展名）
        video_name = Path(video_path).stem
        
        # 获取临时文件目录
        temp_dir = self._get_temp_dir(video_path)
        
        # 计算文件哈希值
        file_hash = self.audio_processor.get_file_hash(video_path)
        
        # 初始化临时文件路径变量
        audio_path = os.path.join(temp_dir, f"{file_hash}_audio.wav")
        chinese_audio_path = os.path.join(temp_dir, "chinese_audio.wav")
        mixed_audio_path = os.path.join(temp_dir, "mixed_audio.wav")
        
        try:
            logger.info("\nProcessing Video...")
            logger.info(f"Input Video: {video_path}")
            logger.info(f"Output Video: {output_path}")
            logger.info(f"Temp Directory: {temp_dir}")
            
            # 检查输入文件是否存在
            if not os.path.exists(video_path):
                raise FileNotFoundError(f"Input Video File Not Found: {video_path}")
            
            # 检查输出目录是否可写
            output_dir = os.path.dirname(output_path)
            if output_dir and not os.access(output_dir, os.W_OK):
                raise PermissionError(f"Output Directory Not Writable: {output_dir}")
            
            # 1. 提取音频
            logger.info("\n1. Extracting Audio...")
            audio_path = self.audio_processor.extract_audio(video_path, audio_path)
            
            # 2. 生成字幕
            logger.info("\n2. Generating Subtitles...")
            subtitles = self.subtitle_processor.get_subtitles(audio_path)
            
            # 3. 翻译字幕
            logger.info("\n3. Translating Subtitles...")
            translated_subtitles = await self.translation_service.translate_batch(subtitles, video_name)
            
            # 更新字幕
            for subtitle, translated_subtitle in zip(subtitles, translated_subtitles):
                subtitle["translated_text"] = translated_subtitle["text"]
            
            # # 4. 生成中文语音
            # logger.info("\n4. Generating Chinese Audio...")
            # chinese_audio_path = self.audio_processor.generate_chinese_audio(subtitles, self.speaker)
            
            # # 5. 混合音频
            # logger.info("\n5. Mixing Audio...")
            # mixed_audio_path = self.audio_processor.mix_audio(audio_path, chinese_audio_path, subtitles)
            
            # # 6. 生成最终视频
            # logger.info("\n6. Generating Final Video...")
            # self.video_processor.create_final_video(video_path, mixed_audio_path, subtitles, output_path)
            
            # 清理临时文件
            logger.info("\nCleaning Up Temporary Files...")
            for temp_file in [audio_path, chinese_audio_path, mixed_audio_path]:
                try:
                    if temp_file and os.path.exists(temp_file):
                        os.remove(temp_file)
                except Exception as e:
                    logger.warning(f"Error Cleaning Up Temporary File {temp_file}: {str(e)}")
            
            logger.info("\nProcessing Completed!")
            logger.info(f"Output Video Saved to: {output_path}")
            
            return {
                "status": "success",
                "output_video": output_path,
                "speaker_count": len(set(sub["speaker"] for sub in subtitles if sub["speaker"])),
                "subtitle_count": len(subtitles)
            }
            
        except Exception as e:
            logger.error(f"\nError During Processing: {str(e)}")
            # 确保清理所有临时文件
            for temp_file in [audio_path, chinese_audio_path, mixed_audio_path]:
                try:
                    if temp_file and os.path.exists(temp_file):
                        os.remove(temp_file)
                except:
                    pass
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
    
    client = VideoTranslationClient(
        stt_server_url=args.stt_server,
        tts_server_url=args.tts_server,
        speaker=args.speaker,
        speaker_mapping=speaker_mapping
    )
    
    asyncio.run(client.process_video(args.input_video, args.output_video))