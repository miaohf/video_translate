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
try:
    from config_manager import config as app_config
except ImportError:
    app_config = None

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
        temp_base_dir = app_config.temp_dir if app_config else "temp"
        os.makedirs(temp_base_dir, exist_ok=True)
    
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
        temp_base_dir = app_config.temp_dir if app_config else "temp"
        temp_dir = os.path.join(temp_base_dir, video_name)
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
                    # 生成字幕（传递video_path参数）
                    subtitles = await self.subtitle_processor.get_subtitles(audio_path, video_name, video_path)

                # 翻译字幕
                logger.info("\n3. Translating Subtitles...")
                # 翻译字幕  
                logger.info("开始翻译字幕...")
                translation_service = TranslationService()
                
                # 从配置读取翻译模式
                translation_mode = settings.TRANSLATION_MODE
                use_whole_translation = (translation_mode == 'whole')  # whole=整体翻译，batch=批量翻译
                logger.info(f"使用翻译模式: {translation_mode} ({'整体翻译' if use_whole_translation else '批量翻译'})")
                
                if use_whole_translation:
                    print("使用整体翻译")
                    translated_subtitles = await translation_service.translate_whole_subtitles(
                        subtitles=subtitles,
                        video_name=video_name,
                        output_path=translated_subtitle_path,
                        original_path=subtitle_json_path
                    )
                else:
                    print("使用批量翻译")
                    translated_subtitles = await translation_service.translate_batch_subtitles(
                        subtitles=subtitles,
                        video_name=video_name,
                        output_path=translated_subtitle_path,
                        original_path=subtitle_json_path
                    )
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
            
            # 输出处理完成的文件总结
            logger.info(f"\n🎉 视频翻译处理完成！")
            logger.info(f"📁 输出文件列表:")
            logger.info(f"   翻译字幕: {output_path}")
            if tts_audio_path and os.path.exists(tts_audio_path):
                logger.info(f"   合成音频: {tts_audio_path}")
                # 检查是否有副本（查找最新的副本文件）
                import glob
                pattern = f"*{video_name}*_final_audio_*.wav"
                audio_copies = glob.glob(pattern)
                if audio_copies:
                    # 获取最新的副本文件
                    latest_copy = max(audio_copies, key=os.path.getctime)
                    logger.info(f"   音频副本: {latest_copy}")
            
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
            tts_server_url = os.getenv("TTS_SERVER_URL", "http://localhost:8002")
            
            # 生成每个字幕的音频并保存文件信息
            updated_subtitles = []
            for i, subtitle in enumerate(subtitles):
                try:
                    # 检查音频片段是否已存在
                    segment_path = os.path.join(temp_dir, f"segment_{i:04d}.wav")
                    
                    # 复制字幕信息
                    updated_subtitle = subtitle.copy()
                    
                    if os.path.exists(segment_path):
                        logger.info(f"发现已存在的音频片段: {segment_path}")
                        # 获取音频文件时长
                        from pydub import AudioSegment
                        audio = AudioSegment.from_file(segment_path)
                        duration = audio.duration_seconds
                        
                        # 保存音频文件信息到字幕数据
                        updated_subtitle["generated_audio"] = segment_path
                        updated_subtitle["generated_duration"] = duration
                        updated_subtitles.append(updated_subtitle)
                        continue
                    
                    # 获取要转换的文本
                    text_to_convert = subtitle.get("translated_text") or subtitle.get("text")
                    if not text_to_convert:
                        logger.warning(f"第 {i+1} 个字幕没有文本内容，跳过")
                        updated_subtitles.append(updated_subtitle)
                        continue
                    
                    # 从reference_audio字段中提取说话人信息
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
                            updated_subtitles.append(updated_subtitle)
                            continue
                        
                        # 保存音频片段
                        with open(segment_path, "wb") as f:
                            f.write(await response.read())
                        
                        # 获取生成音频的时长
                        from pydub import AudioSegment
                        audio = AudioSegment.from_file(segment_path)
                        duration = audio.duration_seconds
                        
                        # 保存音频文件信息到字幕数据
                        updated_subtitle["generated_audio"] = segment_path
                        updated_subtitle["generated_duration"] = duration
                        updated_subtitles.append(updated_subtitle)
                        
                        logger.info(f"已生成第 {i+1}/{len(subtitles)} 个音频片段，时长: {duration:.2f}s")
                        
                except Exception as e:
                    logger.error(f"处理第 {i+1} 个音频片段时出错: {str(e)}")
                    updated_subtitles.append(subtitle.copy())
                    continue
            
            # 使用新的音频合成方法
            logger.info("开始合成最终音频...")
            
            # 获取原始音频文件路径
            file_hash = get_file_hash(video_name)
            original_audio_path = os.path.join("temp", video_name, f"{file_hash}_audio.mp3")
            
            # 调用新的音频合成方法
            final_audio_path = await self._mix_audio_with_background(
                updated_subtitles, 
                original_audio_path, 
                final_audio_path
            )
            
            logger.info(f"音频合成完成: {final_audio_path}")
            
            # 保存最终合成音频的副本到项目根目录（便于查找和使用）
            import shutil
            from datetime import datetime
            
            # 创建带时间戳的文件名，避免覆盖
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_video_name = "".join(c for c in video_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
            final_audio_copy = f"{safe_video_name}_final_audio_{timestamp}.wav"
            
            try:
                shutil.copy2(final_audio_path, final_audio_copy)
                logger.info(f"最终音频已保存到: {final_audio_copy}")
            except Exception as e:
                logger.warning(f"保存最终音频副本失败: {str(e)}")
                final_audio_copy = None
            
            # 保存更新后的字幕文件（包含generated_audio信息）
            updated_subtitle_path = os.path.join("temp", video_name, f"{file_hash}_subtitles_zh_with_audio.json")
            with open(updated_subtitle_path, 'w', encoding='utf-8') as f:
                json.dump(updated_subtitles, f, ensure_ascii=False, indent=2)
            logger.info(f"已保存包含音频信息的字幕文件: {updated_subtitle_path}")
            
            # 输出文件信息摘要
            if os.path.exists(final_audio_path):
                from pydub import AudioSegment
                audio_info = AudioSegment.from_file(final_audio_path)
                file_size = os.path.getsize(final_audio_path) / (1024 * 1024)  # MB
                logger.info(f"\n📄 最终音频文件信息:")
                logger.info(f"   文件路径: {final_audio_path}")
                logger.info(f"   文件大小: {file_size:.2f} MB")
                logger.info(f"   音频时长: {audio_info.duration_seconds:.2f} 秒")
                logger.info(f"   采样率: {audio_info.frame_rate} Hz")
                logger.info(f"   声道数: {audio_info.channels}")
                if final_audio_copy and os.path.exists(final_audio_copy):
                    logger.info(f"   副本位置: {final_audio_copy}")
            
            return final_audio_path
            
        except Exception as e:
            logger.error(f"生成 TTS 音频失败: {str(e)}")
            raise

    async def _mix_audio_with_background(self, subtitles: List[Dict], background_audio_path: str, output_path: str) -> str:
        """
        将TTS音频与背景音频混合，使用音量控制和渐变
        
        参数:
            subtitles: 包含generated_audio信息的字幕列表
            background_audio_path: 背景音频文件路径
            output_path: 输出文件路径
            
        返回:
            合成后的音频文件路径
        """
        try:
            from pydub import AudioSegment
            import numpy as np
            
            # 配置参数
            fade_duration = 150  # 渐变时间（毫秒）
            background_min_volume = 0.05  # 背景音最低音量（5%）
            
            logger.info("加载背景音频...")
            background = AudioSegment.from_file(background_audio_path)
            
            # 获取背景音频的采样点数（不是毫秒数）
            background_samples = np.array(background.get_array_of_samples())
            
            # 计算实际的采样点数
            if background.channels == 2:
                # 立体声：采样点数 = 数组长度 / 2
                total_samples = len(background_samples) // 2
            else:
                # 单声道：采样点数 = 数组长度
                total_samples = len(background_samples)
            
            # 创建音量包络数组（用于控制背景音音量）
            volume_envelope = np.ones(total_samples)  # 默认音量为1.0
            
            logger.info("处理TTS音频插入和音量控制...")
            
            # 用于存储要叠加的TTS音频
            overlays = []
            
            for i, subtitle in enumerate(subtitles):
                generated_audio_path = subtitle.get("generated_audio")
                if not generated_audio_path or not os.path.exists(generated_audio_path):
                    logger.warning(f"第 {i+1} 个字幕缺少生成的音频文件")
                    continue
                
                start_time_ms = subtitle["start"] * 1000  # 转换为毫秒
                generated_duration_ms = subtitle.get("generated_duration", 0) * 1000  # 转换为毫秒
                
                # 转换为采样点位置
                start_sample = int((start_time_ms / 1000.0) * background.frame_rate)
                generated_duration_samples = int((generated_duration_ms / 1000.0) * background.frame_rate)
                
                if start_sample >= total_samples:
                    logger.warning(f"第 {i+1} 个字幕开始时间超出背景音频长度")
                    continue
                
                # 计算音量控制的关键采样点（以采样点为单位）
                fade_duration_samples = int((fade_duration / 1000.0) * background.frame_rate)
                fade_out_start = max(0, start_sample - fade_duration_samples // 2)
                fade_out_end = min(total_samples, start_sample + fade_duration_samples // 2)
                fade_in_start = max(0, start_sample + generated_duration_samples - fade_duration_samples // 2)
                fade_in_end = min(total_samples, start_sample + generated_duration_samples + fade_duration_samples // 2)
                
                # 设置音量包络
                # 淡出阶段
                if fade_out_start < fade_out_end:
                    fade_out_samples = np.linspace(1.0, background_min_volume, fade_out_end - fade_out_start)
                    volume_envelope[fade_out_start:fade_out_end] = np.minimum(
                        volume_envelope[fade_out_start:fade_out_end], fade_out_samples
                    )
                
                # 低音量阶段
                low_volume_start = fade_out_end
                low_volume_end = min(total_samples, fade_in_start)
                if low_volume_start < low_volume_end:
                    volume_envelope[low_volume_start:low_volume_end] = np.minimum(
                        volume_envelope[low_volume_start:low_volume_end], background_min_volume
                    )
                
                # 淡入阶段
                if fade_in_start < fade_in_end:
                    fade_in_samples = np.linspace(background_min_volume, 1.0, fade_in_end - fade_in_start)
                    volume_envelope[fade_in_start:fade_in_end] = fade_in_samples
                
                # 记录要叠加的TTS音频
                overlays.append({
                    "audio_path": generated_audio_path,
                    "start_time": int(start_time_ms),
                    "subtitle_index": i + 1
                })
                
                logger.debug(f"处理第 {i+1} 个TTS音频: {start_time_ms/1000:.2f}s, 时长: {generated_duration_ms/1000:.2f}s")
            
            logger.info("应用音量包络到背景音频...")
            
            # 将音量包络应用到背景音频
            if background.channels == 2:
                # 立体声处理
                background_samples_reshaped = background_samples.reshape((-1, 2))
                # 扩展音量包络以匹配立体声
                volume_envelope_stereo = np.column_stack([volume_envelope, volume_envelope])
                background_samples_processed = (background_samples_reshaped * volume_envelope_stereo).astype(np.int16)
                background_samples_final = background_samples_processed.flatten()
            else:
                # 单声道处理
                background_samples_final = (background_samples * volume_envelope).astype(np.int16)
            
            # 重建AudioSegment
            modified_background = background._spawn(background_samples_final.tobytes())
            
            logger.info("叠加TTS音频...")
            
            # 叠加所有TTS音频
            final_audio = modified_background
            for overlay in overlays:
                try:
                    tts_audio = AudioSegment.from_file(overlay["audio_path"])
                    
                    # 确保采样率和声道数匹配
                    if tts_audio.frame_rate != final_audio.frame_rate:
                        tts_audio = tts_audio.set_frame_rate(final_audio.frame_rate)
                    if tts_audio.channels != final_audio.channels:
                        if final_audio.channels == 2 and tts_audio.channels == 1:
                            tts_audio = tts_audio.set_channels(2)
                        elif final_audio.channels == 1 and tts_audio.channels == 2:
                            tts_audio = tts_audio.set_channels(1)
                    
                    # 在指定位置叠加TTS音频
                    final_audio = final_audio.overlay(tts_audio, position=overlay["start_time"])
                    
                    logger.debug(f"已叠加第 {overlay['subtitle_index']} 个TTS音频")
                    
                except Exception as e:
                    logger.error(f"叠加第 {overlay['subtitle_index']} 个TTS音频失败: {str(e)}")
                    continue
            
            logger.info("导出最终音频...")
            final_audio.export(output_path, format="wav")
            
            logger.info(f"音频混合完成，最终时长: {final_audio.duration_seconds:.2f}s")
            return output_path
            
        except Exception as e:
            logger.error(f"音频混合失败: {str(e)}")
            raise

if __name__ == "__main__":
    # 创建命令行参数解析器
    parser = argparse.ArgumentParser(description="Video Translation Program")
    parser.add_argument("--input_video", required=True, help="Input Video File Path")   
    args = parser.parse_args()
    
    video_translation_client = VideoTranslationClient()
    asyncio.run(video_translation_client.process_video(args.input_video))