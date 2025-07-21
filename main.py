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
                        logger.info("为已有字幕创建增强参考音频切片...")
                        from config import ENABLE_VOCAL_SEPARATION
                        subtitles = self.audio_processor.create_enhanced_audio_segments(
                            audio_path, subtitles, video_name, 
                            use_vocal_separation=ENABLE_VOCAL_SEPARATION
                        )
                        logger.info("增强参考音频切片创建完成")
                        
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
                    translated_subtitles = await translation_service.translate_subtitles(
                        subtitles=subtitles,
                        video_name=video_name,
                        output_path=translated_subtitle_path,
                        original_path=subtitle_json_path
                    )
                logger.info("字幕翻译完成")

                # 创建音频切片作为参考音频（支持人声分离）
                logger.info("\n4. Creating Enhanced Reference Audio Segments...")
                from config import ENABLE_VOCAL_SEPARATION
                subtitles = self.audio_processor.create_enhanced_audio_segments(
                    audio_path, subtitles, video_name, 
                    use_vocal_separation=ENABLE_VOCAL_SEPARATION
                )
                logger.info("增强参考音频切片创建完成")

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

    def _check_tts_audio_quality(self, audio_path: str, subtitle_index: int) -> Dict:
        """
        检查TTS音频文件的质量
        
        参数:
            audio_path: 音频文件路径
            subtitle_index: 字幕索引（用于日志）
            
        返回:
            包含音频质量信息的字典
        """
        from pydub import AudioSegment
        
        quality_info = {
            "is_valid": False,
            "file_exists": False,
            "file_size": 0,
            "duration": 0.0,
            "rms": 0,
            "channels": 0,
            "frame_rate": 0,
            "issues": []
        }
        
        try:
            # 检查文件是否存在
            if not os.path.exists(audio_path):
                quality_info["issues"].append("文件不存在")
                return quality_info
            
            quality_info["file_exists"] = True
            quality_info["file_size"] = os.path.getsize(audio_path)
            
            # 检查文件大小 - 降低最小文件大小要求
            if quality_info["file_size"] < 512:  # 从1024降到512字节
                quality_info["issues"].append(f"文件过小({quality_info['file_size']}字节)")
                return quality_info
            
            # 加载音频文件
            audio = AudioSegment.from_file(audio_path)
            quality_info["duration"] = audio.duration_seconds
            quality_info["rms"] = audio.rms
            quality_info["channels"] = audio.channels
            quality_info["frame_rate"] = audio.frame_rate
            
            # 检查时长 - 放宽时长要求
            if quality_info["duration"] < 0.05:  # 从0.1降到0.05秒
                quality_info["issues"].append(f"音频过短({quality_info['duration']:.3f}s)")
            elif quality_info["duration"] > 60.0:  # 从30提高到60秒
                quality_info["issues"].append(f"音频过长({quality_info['duration']:.1f}s)")
            
            # 检查是否静音 - 大幅降低RMS阈值，使检查更宽松
            if quality_info["rms"] < 10:  # 从50降到10，更宽松的静音检测
                quality_info["issues"].append(f"可能是静音(RMS={quality_info['rms']})")
            elif quality_info["rms"] > 20000:  # 从10000提高到20000
                quality_info["issues"].append(f"音量可能过大(RMS={quality_info['rms']})")
            
            # 检查采样率 - 放宽采样率要求
            if quality_info["frame_rate"] < 4000:  # 从8000降到4000
                quality_info["issues"].append(f"采样率过低({quality_info['frame_rate']}Hz)")
            elif quality_info["frame_rate"] > 96000:  # 从48000提高到96000
                quality_info["issues"].append(f"采样率过高({quality_info['frame_rate']}Hz)")
            
            # 检查声道数
            if quality_info["channels"] < 1 or quality_info["channels"] > 2:
                quality_info["issues"].append(f"异常声道数({quality_info['channels']})")
            
            # 更宽松的有效性判断：只有关键问题才标记为无效
            critical_issues = [issue for issue in quality_info["issues"] 
                             if any(keyword in issue for keyword in ["不存在", "过小", "过短"])]
            # 移除"静音"作为关键问题，因为很多TTS音频RMS较低但仍然有效
            quality_info["is_valid"] = len(critical_issues) == 0
            
            # 输出诊断信息
            if quality_info["is_valid"]:
                logger.debug(f"✅ TTS音频 {subtitle_index} 质量检查通过: "
                           f"时长={quality_info['duration']:.2f}s, RMS={quality_info['rms']}, "
                           f"采样率={quality_info['frame_rate']}Hz")
            else:
                logger.warning(f"⚠️ TTS音频 {subtitle_index} 质量问题: {', '.join(quality_info['issues'])}")
                
            if len(quality_info["issues"]) > 0 and quality_info["is_valid"]:
                logger.info(f"ℹ️ TTS音频 {subtitle_index} 非关键问题: {', '.join(quality_info['issues'])}")
            
        except Exception as e:
            quality_info["issues"].append(f"加载失败: {str(e)}")
            logger.error(f"❌ TTS音频 {subtitle_index} 质量检查失败: {str(e)}")
        
        return quality_info
    
    def _diagnose_audio_mixing_issue(self, subtitles: List[Dict], background_audio_path: str) -> Dict:
        """
        诊断音频混合问题
        
        参数:
            subtitles: 字幕列表
            background_audio_path: 背景音频路径
            
        返回:
            诊断信息字典
        """
        from pydub import AudioSegment
        
        diagnosis = {
            "background_audio": {"exists": False, "valid": False, "info": {}},
            "tts_audios": [],
            "total_issues": 0,
            "critical_issues": 0,
            "recommendations": []
        }
        
        # 检查背景音频
        logger.info("🔍 开始音频混合问题诊断...")
        
        try:
            if os.path.exists(background_audio_path):
                diagnosis["background_audio"]["exists"] = True
                bg_audio = AudioSegment.from_file(background_audio_path)
                diagnosis["background_audio"]["info"] = {
                    "duration": bg_audio.duration_seconds,
                    "frame_rate": bg_audio.frame_rate,
                    "channels": bg_audio.channels,
                    "rms": bg_audio.rms,
                    "file_size": os.path.getsize(background_audio_path)
                }
                diagnosis["background_audio"]["valid"] = True
                logger.info(f"✅ 背景音频正常: {bg_audio.duration_seconds:.2f}s, {bg_audio.frame_rate}Hz, {bg_audio.channels}声道")
            else:
                diagnosis["total_issues"] += 1
                diagnosis["critical_issues"] += 1
                diagnosis["recommendations"].append("背景音频文件不存在，请检查文件路径")
                logger.error(f"❌ 背景音频文件不存在: {background_audio_path}")
        except Exception as e:
            diagnosis["total_issues"] += 1
            diagnosis["critical_issues"] += 1
            diagnosis["recommendations"].append(f"背景音频文件损坏: {str(e)}")
            logger.error(f"❌ 背景音频文件无法加载: {str(e)}")
        
        # 检查TTS音频
        valid_tts_count = 0
        for i, subtitle in enumerate(subtitles):
            tts_info = {"index": i+1, "issues": [], "valid": False}
            
            generated_audio_path = subtitle.get("generated_audio")
            if not generated_audio_path:
                tts_info["issues"].append("缺少generated_audio字段")
                diagnosis["total_issues"] += 1
            else:
                quality_info = self._check_tts_audio_quality(generated_audio_path, i+1)
                tts_info["quality"] = quality_info
                tts_info["valid"] = quality_info["is_valid"]
                tts_info["issues"] = quality_info["issues"]
                
                if quality_info["is_valid"]:
                    valid_tts_count += 1
                else:
                    diagnosis["total_issues"] += len(quality_info["issues"])
                    if any(keyword in str(quality_info["issues"]) for keyword in ["不存在", "过小", "过短", "静音"]):
                        diagnosis["critical_issues"] += 1
            
            diagnosis["tts_audios"].append(tts_info)
        
        # 生成建议
        if valid_tts_count == 0:
            diagnosis["recommendations"].append("没有任何有效的TTS音频文件，请检查TTS生成过程")
            diagnosis["critical_issues"] += 1
        elif valid_tts_count < len(subtitles) * 0.5:  # 少于50%的音频有效
            diagnosis["recommendations"].append(f"只有 {valid_tts_count}/{len(subtitles)} 个TTS音频有效，建议重新生成TTS音频")
        
        if diagnosis["background_audio"]["valid"] and valid_tts_count > 0:
            # 检查格式兼容性
            bg_info = diagnosis["background_audio"]["info"]
            sample_tts = next((tts for tts in diagnosis["tts_audios"] if tts["valid"]), None)
            
            if sample_tts:
                tts_quality = sample_tts["quality"]
                if bg_info["frame_rate"] != tts_quality["frame_rate"]:
                    diagnosis["recommendations"].append(f"采样率不匹配 (背景:{bg_info['frame_rate']}Hz vs TTS:{tts_quality['frame_rate']}Hz)")
                if bg_info["channels"] != tts_quality["channels"]:
                    diagnosis["recommendations"].append(f"声道数不匹配 (背景:{bg_info['channels']} vs TTS:{tts_quality['channels']})")
        
        # 输出诊断结果
        logger.info(f"📊 音频混合诊断结果:")
        logger.info(f"   背景音频: {'✅正常' if diagnosis['background_audio']['valid'] else '❌异常'}")
        logger.info(f"   有效TTS音频: {valid_tts_count}/{len(subtitles)} 个")
        logger.info(f"   总问题数: {diagnosis['total_issues']} 个")
        logger.info(f"   关键问题数: {diagnosis['critical_issues']} 个")
        
        if diagnosis["recommendations"]:
            logger.info("💡 修复建议:")
            for rec in diagnosis["recommendations"]:
                logger.info(f"   - {rec}")
        
        return diagnosis

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
                        
                        # 立即检查TTS音频质量
                        quality_info = self._check_tts_audio_quality(segment_path, i+1)
                        
                        # 强制处理策略：只有真正关键的问题才跳过，其他情况都尝试处理
                        if not quality_info["file_exists"]:
                            logger.error(f"❌ 第 {i+1} 个TTS音频文件不存在，跳过")
                            updated_subtitles.append(subtitle.copy())
                            continue
                        elif quality_info["file_size"] < 512:
                            logger.error(f"❌ 第 {i+1} 个TTS音频文件过小，跳过")
                            updated_subtitles.append(subtitle.copy())
                            continue
                        elif quality_info["duration"] < 0.05:
                            logger.error(f"❌ 第 {i+1} 个TTS音频过短，跳过")
                            updated_subtitles.append(subtitle.copy())
                            continue
                        else:
                            # 即使有非关键问题，也继续处理
                            if not quality_info["is_valid"]:
                                logger.warning(f"⚠️ 第 {i+1} 个TTS音频有非关键问题，但继续处理: {', '.join(quality_info['issues'])}")
                            else:
                                logger.info(f"✅ 第 {i+1} 个TTS音频质量良好")
                        
                        # 使用质量检查的结果
                        duration = quality_info["duration"]
                        
                        # 保存音频文件信息到字幕数据（包含质量信息）
                        updated_subtitle["generated_audio"] = segment_path
                        updated_subtitle["generated_duration"] = duration
                        updated_subtitle["audio_quality"] = quality_info
                        updated_subtitles.append(updated_subtitle)
                        
                        logger.info(f"✅ 已生成第 {i+1}/{len(subtitles)} 个高质量音频片段，时长: {duration:.2f}s")
                        
                except Exception as e:
                    logger.error(f"处理第 {i+1} 个音频片段时出错: {str(e)}")
                    updated_subtitles.append(subtitle.copy())
                    continue
            
            # 使用新的音频合成方法
            logger.info("开始合成最终音频...")
            
            # 获取原始音频文件路径
            file_hash = get_file_hash(video_name)
            original_audio_path = os.path.join("temp", video_name, f"{file_hash}_audio.mp3")
            
            # 使用简化的音频合成方法
            logger.info("📦 使用简化的音频合成方法")
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
        将TTS音频与背景音频混合，使用简化的时长对齐策略
        
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
            background_min_volume = 0.15  # 背景音最低音量
            tts_boost_db = 3  # TTS音频增益（分贝）
            
            logger.info("加载背景音频...")
            background = AudioSegment.from_file(background_audio_path)
            logger.info(f"背景音频信息: 时长={background.duration_seconds:.2f}s, 采样率={background.frame_rate}Hz, 声道={background.channels}")
            
            # 获取背景音频的采样点数
            background_samples = np.array(background.get_array_of_samples())
            
            if background.channels == 2:
                total_samples = len(background_samples) // 2
            else:
                total_samples = len(background_samples)
            
            # 创建音量包络数组（用于控制背景音音量）
            volume_envelope = np.ones(total_samples)
            
            logger.info("处理TTS音频时长对齐...")
            
            # 用于存储要叠加的TTS音频
            overlays = []
            valid_tts_count = 0
            
            for i, subtitle in enumerate(subtitles):
                try:
                    generated_audio_path = subtitle.get("generated_audio")
                    if not generated_audio_path or not os.path.exists(generated_audio_path):
                        logger.warning(f"第 {i+1} 个字幕缺少生成的音频文件: {generated_audio_path}")
                        continue
                    
                    # 检查TTS音频文件
                    tts_audio = AudioSegment.from_file(generated_audio_path)
                    
                    # 检查音频是否为空或过短
                    if tts_audio.duration_seconds < 0.01:
                        logger.warning(f"第 {i+1} 个TTS音频过短 ({tts_audio.duration_seconds:.3f}s)，跳过")
                        continue
                        
                    valid_tts_count += 1
                    
                    # 获取原字幕时长和TTS音频时长
                    subtitle_duration_s = subtitle["end"] - subtitle["start"]
                    tts_duration_s = tts_audio.duration_seconds
                    start_time_ms = subtitle["start"] * 1000
                    
                    logger.info(f"字幕{i+1}: 原时长={subtitle_duration_s:.2f}s, TTS时长={tts_duration_s:.2f}s")
                    
                    # 简化的时长对齐策略
                    if tts_duration_s > subtitle_duration_s:
                        # 如果TTS音频时长大于字幕时长，加速到与字幕时长一致
                        speedup_ratio = tts_duration_s / subtitle_duration_s
                        tts_audio = tts_audio.speedup(playback_speed=speedup_ratio)
                        logger.info(f"✅ 字幕{i+1} 加速{speedup_ratio:.2f}x: {tts_duration_s:.2f}s → {tts_audio.duration_seconds:.2f}s")
                    else:
                        # 如果TTS音频时长小于等于字幕时长，保持不变
                        logger.info(f"✅ 字幕{i+1} 时长合适，保持不变: {tts_duration_s:.2f}s")
                    
                    # 增强TTS音频音量
                    tts_audio = tts_audio + tts_boost_db
                    
                    # 计算音量包络控制区域
                    start_sample = int((start_time_ms / 1000.0) * background.frame_rate)
                    duration_samples = int((tts_audio.duration_seconds) * background.frame_rate)
                    
                    if start_sample < total_samples:
                        # 计算淡入淡出位置
                        fade_duration_samples = int((fade_duration / 1000.0) * background.frame_rate)
                        fade_out_start = max(0, start_sample - fade_duration_samples // 2)
                        fade_out_end = min(total_samples, start_sample + fade_duration_samples // 2)
                        fade_in_start = max(0, start_sample + duration_samples - fade_duration_samples // 2)
                        fade_in_end = min(total_samples, start_sample + duration_samples + fade_duration_samples // 2)
                        
                        # 应用音量包络
                        if fade_out_start < fade_out_end:
                            fade_out_samples = np.linspace(1.0, background_min_volume, fade_out_end - fade_out_start)
                            volume_envelope[fade_out_start:fade_out_end] = np.minimum(
                                volume_envelope[fade_out_start:fade_out_end], fade_out_samples
                            )
                        
                        low_volume_start = fade_out_end
                        low_volume_end = min(total_samples, fade_in_start)
                        if low_volume_start < low_volume_end:
                            volume_envelope[low_volume_start:low_volume_end] = np.minimum(
                                volume_envelope[low_volume_start:low_volume_end], background_min_volume
                            )
                        
                        if fade_in_start < fade_in_end:
                            fade_in_samples = np.linspace(background_min_volume, 1.0, fade_in_end - fade_in_start)
                            volume_envelope[fade_in_start:fade_in_end] = fade_in_samples
                    
                    # 记录要叠加的TTS音频
                    overlays.append({
                        "audio": tts_audio,
                        "start_time": int(start_time_ms),
                        "subtitle_index": i + 1,
                        "duration": len(tts_audio)
                    })
                    
                except Exception as e:
                    logger.error(f"处理第 {i+1} 个音频片段时出错: {str(e)}")
                    continue
            
            logger.info(f"发现 {valid_tts_count} 个有效的TTS音频文件，准备叠加 {len(overlays)} 个")
            
            if len(overlays) == 0:
                logger.error("❌ 没有任何有效的TTS音频可以叠加！")
                # 直接复制背景音频到输出路径
                background.export(output_path, format="wav")
                return output_path
            
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
            successful_overlays = 0
            
            for overlay in overlays:
                try:
                    tts_audio = overlay["audio"]
                    
                    # 确保采样率和声道数匹配
                    if tts_audio.frame_rate != final_audio.frame_rate:
                        logger.debug(f"调整TTS音频 {overlay['subtitle_index']} 采样率: {tts_audio.frame_rate} -> {final_audio.frame_rate}")
                        tts_audio = tts_audio.set_frame_rate(final_audio.frame_rate)
                    if tts_audio.channels != final_audio.channels:
                        if final_audio.channels == 2 and tts_audio.channels == 1:
                            logger.debug(f"将TTS音频 {overlay['subtitle_index']} 转换为立体声")
                            tts_audio = tts_audio.set_channels(2)
                        elif final_audio.channels == 1 and tts_audio.channels == 2:
                            logger.debug(f"将TTS音频 {overlay['subtitle_index']} 转换为单声道")
                            tts_audio = tts_audio.set_channels(1)
                    
                    # 检查叠加位置是否合理
                    overlay_start = overlay["start_time"]
                    overlay_end = overlay_start + len(tts_audio)
                    if overlay_end > len(final_audio):
                        logger.warning(f"⚠️ TTS音频 {overlay['subtitle_index']} 超出背景音频范围，进行截断")
                        available_duration = len(final_audio) - overlay_start
                        if available_duration > 0:
                            tts_audio = tts_audio[:available_duration]
                        else:
                            logger.warning(f"❌ TTS音频 {overlay['subtitle_index']} 开始位置超出范围，跳过")
                            continue
                    
                    logger.info(f"🎵 叠加TTS音频 {overlay['subtitle_index']}: 位置={overlay_start/1000:.2f}s, 时长={len(tts_audio)/1000:.2f}s")
                    
                    # 叠加音频
                    final_audio = final_audio.overlay(tts_audio, position=overlay_start)
                    successful_overlays += 1
                    logger.info(f"✅ 成功叠加第 {overlay['subtitle_index']} 个TTS音频")
                    
                except Exception as e:
                    logger.error(f"❌ 叠加第 {overlay['subtitle_index']} 个TTS音频失败: {str(e)}")
                    continue
            
            logger.info(f"🎵 音频叠加完成: {successful_overlays}/{len(overlays)} 个TTS音频成功叠加")
            
            if successful_overlays == 0:
                logger.error("❌ 没有任何TTS音频成功叠加！")
                # 返回原始背景音频
                background.export(output_path, format="wav")
                return output_path
            
            # 检查最终音频质量
            logger.info(f"最终音频信息: 时长={final_audio.duration_seconds:.2f}s, 采样率={final_audio.frame_rate}Hz, 声道={final_audio.channels}, RMS={final_audio.rms}")
            
            logger.info("导出最终音频...")
            final_audio.export(output_path, format="wav")
            
            # 验证输出文件
            if os.path.exists(output_path):
                output_size = os.path.getsize(output_path)
                logger.info(f"✅ 音频混合完成，输出文件大小: {output_size/1024/1024:.2f}MB")
                
                # 快速验证输出音频
                try:
                    verify_audio = AudioSegment.from_file(output_path)
                    logger.info(f"✅ 输出音频验证: 时长={verify_audio.duration_seconds:.2f}s, RMS={verify_audio.rms}")
                except Exception as e:
                    logger.error(f"❌ 输出音频验证失败: {str(e)}")
            else:
                logger.error("❌ 输出文件未生成")
            
            return output_path
            
        except Exception as e:
            logger.error(f"音频混合失败: {str(e)}")
            raise

    async def _mix_audio_with_background_v2(self, subtitles: List[Dict], background_audio_path: str, output_path: str) -> str:
        """
        分阶段自适应音频混合方法，采用三阶段处理策略 + 严格时长控制
        
        特点：
        - 三阶段处理：预分析 → 智能处理 → 对齐优化
        - 严格时长控制：确保最终音频时长与原音频完全一致
        - 全局压缩机制：当总时长超出时自动计算并应用全局压缩
        - 最终验证：通过截断或填充确保时长精确匹配
        
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
            
            # 从配置文件加载参数
            from config import (AUDIO_FADE_DURATION, BACKGROUND_MIN_VOLUME, 
                               MIN_GAP_BETWEEN_SPEECH, MAX_SPEEDUP_RATIO,
                               BOUNDARY_EXTENSION_LIMIT, LAST_SEGMENT_PROTECTION,
                               ALIGNMENT_TOLERANCE, GLOBAL_TIME_BUFFER,
                               ENABLE_BOUNDARY_EXTENSION, ENABLE_SMART_ALIGNMENT,
                               PREFER_COMPLETENESS, ENABLE_ADAPTIVE_PROCESSING,
                               STRICT_DURATION_CONTROL)
            
            fade_duration = AUDIO_FADE_DURATION
            background_min_volume = BACKGROUND_MIN_VOLUME
            min_gap_between_speech = MIN_GAP_BETWEEN_SPEECH
            max_speedup_ratio = MAX_SPEEDUP_RATIO
            
            logger.info("加载背景音频...")
            background = AudioSegment.from_file(background_audio_path)
            
            # 获取背景音频的采样点数
            background_samples = np.array(background.get_array_of_samples())
            
            if background.channels == 2:
                total_samples = len(background_samples) // 2
            else:
                total_samples = len(background_samples)
            
            # 创建音量包络数组
            volume_envelope = np.ones(total_samples)
            
            # ===== 阶段1: 预分析阶段 =====
            logger.info("🔍 阶段1: 预分析阶段 - 全局时长评估...")
            
            # 准备TTS音频信息
            tts_segments = []
            total_original_duration = 0
            total_tts_duration = 0
            
            for i, subtitle in enumerate(subtitles):
                generated_audio_path = subtitle.get("generated_audio")
                if not generated_audio_path or not os.path.exists(generated_audio_path):
                    logger.warning(f"第 {i+1} 个字幕缺少生成的音频文件")
                    continue
                
                start_time_ms = subtitle["start"] * 1000
                subtitle_duration_ms = (subtitle["end"] - subtitle["start"]) * 1000
                generated_duration_ms = subtitle.get("generated_duration", 0) * 1000
                
                total_original_duration += subtitle_duration_ms
                total_tts_duration += generated_duration_ms
                
                tts_segments.append({
                    "index": i,
                    "subtitle_index": i + 1,
                    "audio_path": generated_audio_path,
                    "subtitle_start": start_time_ms,
                    "subtitle_end": subtitle["end"] * 1000,
                    "subtitle_duration": subtitle_duration_ms,
                    "original_tts_duration": generated_duration_ms,
                    "adjusted_tts_duration": generated_duration_ms,  # 将被调整
                    "final_start": start_time_ms,  # 最终播放开始时间
                    "final_end": start_time_ms + generated_duration_ms,  # 最终播放结束时间
                    "processing_stage": "initial"  # 处理阶段标记
                })
            
            # 按开始时间排序
            tts_segments.sort(key=lambda x: x["subtitle_start"])

            # 获取背景音频总时长（毫秒）
            background_duration_ms = len(background)
            
            # 全局时长评估
            time_difference = total_tts_duration - total_original_duration
            time_overflow = max(0, tts_segments[-1]["final_end"] - background_duration_ms) if tts_segments else 0
            global_time_buffer_ms = GLOBAL_TIME_BUFFER * 1000
            
            logger.info(f"📊 全局时长分析:")
            logger.info(f"   背景音频时长: {background_duration_ms/1000:.2f}s")
            logger.info(f"   原字幕总时长: {total_original_duration/1000:.2f}s")
            logger.info(f"   TTS音频总时长: {total_tts_duration/1000:.2f}s")
            logger.info(f"   时长差异: {time_difference/1000:.2f}s")
            logger.info(f"   末尾超出: {time_overflow/1000:.2f}s")
            
            # 严格时长控制：计算全局压缩比例
            global_compression_ratio = 1.0
            needs_global_compression = False
            
            if STRICT_DURATION_CONTROL and time_overflow > 0:
                # 计算需要的全局压缩比例
                available_total_time = background_duration_ms
                required_total_time = tts_segments[-1]["final_end"] if tts_segments else 0
                
                if required_total_time > available_total_time:
                    global_compression_ratio = available_total_time / required_total_time
                    needs_global_compression = True
                    logger.warning(f"⚠️ 启用严格时长控制：全局压缩比例 {global_compression_ratio:.3f}")
                    logger.info(f"🎯 目标：确保最终音频时长 = {background_duration_ms/1000:.2f}s")
                    
                    # 应用全局压缩到所有片段
                    for segment in tts_segments:
                        # 压缩TTS音频时长
                        segment["adjusted_tts_duration"] = segment["original_tts_duration"] * global_compression_ratio
                        
                        # 调整时间线：保持开始时间，压缩持续时间
                        compressed_duration = segment["adjusted_tts_duration"]
                        segment["final_end"] = segment["final_start"] + compressed_duration
                        
                        # 标记需要压缩
                        segment["needs_global_compression"] = True
                        segment["global_compression_ratio"] = global_compression_ratio
                    
                    logger.info(f"✅ 已应用全局时间压缩到 {len(tts_segments)} 个片段")
            
            # 分阶段片段识别
            total_segments = len(tts_segments)
            protection_threshold = int(total_segments * (1 - LAST_SEGMENT_PROTECTION))
            
            logger.info(f"📌 片段分组策略:")
            logger.info(f"   总片段数: {total_segments}")
            logger.info(f"   前80%片段 (标准处理): {protection_threshold} 个")
            logger.info(f"   后20%片段 (保护处理): {total_segments - protection_threshold} 个")
            
            # 风险片段识别
            risk_segments = []
            for segment in tts_segments:
                if segment["original_tts_duration"] > segment["subtitle_duration"] * max_speedup_ratio:
                    risk_segments.append(segment["subtitle_index"])
            
            if risk_segments:
                logger.warning(f"⚠️  识别到高风险片段 (无法通过1.3x加速解决): {risk_segments}")
            
            # 动态边界计算
            if STRICT_DURATION_CONTROL:
                # 严格模式：不允许任何边界扩展
                effective_boundary_ms = background_duration_ms
                logger.info(f"🔒 严格时长控制模式：边界固定为 {effective_boundary_ms/1000:.2f}s")
            elif ENABLE_BOUNDARY_EXTENSION and time_overflow > 0:
                allowed_extension = min(BOUNDARY_EXTENSION_LIMIT * 1000, time_overflow + global_time_buffer_ms)
                effective_boundary_ms = background_duration_ms + allowed_extension
                logger.info(f"🎯 动态边界扩展: +{allowed_extension/1000:.2f}s (新边界: {effective_boundary_ms/1000:.2f}s)")
            else:
                effective_boundary_ms = background_duration_ms
                logger.info(f"🎯 使用原始边界: {effective_boundary_ms/1000:.2f}s")
            
            # ===== 阶段2: 智能处理阶段 =====
            logger.info("🛠️ 阶段2: 智能处理阶段 - 分段处理策略...")
            
            for i in range(len(tts_segments)):
                current = tts_segments[i]
                is_protected_segment = i >= protection_threshold
                is_last_segment = i == len(tts_segments) - 1
                
                # 标记处理阶段
                if is_last_segment:
                    current["processing_stage"] = "last_segment"
                elif is_protected_segment:
                    current["processing_stage"] = "protected"
                else:
                    current["processing_stage"] = "standard"
                
                logger.debug(f"处理片段 {current['subtitle_index']} (阶段: {current['processing_stage']})")
                
                # 1. 边界检查 (根据阶段使用不同的边界)
                boundary_to_use = effective_boundary_ms if is_protected_segment else background_duration_ms
                
                if current["final_end"] > boundary_to_use:
                    excess_time = current["final_end"] - boundary_to_use
                    logger.warning(f"字幕{current['subtitle_index']} 超出边界 {excess_time/1000:.2f}s (阶段: {current['processing_stage']})")
                    
                    # 保护段和最后一段的特殊处理
                    if is_protected_segment:
                        if is_last_segment and PREFER_COMPLETENESS:
                            # 最后一段：优先保证完整性
                            if current["final_end"] <= effective_boundary_ms:
                                logger.info(f"✅ 最后片段 {current['subtitle_index']} 在扩展边界内，保持完整")
                                continue
                            else:
                                # 即使在扩展边界外，也尝试温和处理
                                available_time = effective_boundary_ms - current["final_start"]
                                if available_time > current["original_tts_duration"] * 0.7:  # 至少保留70%
                                    compression_ratio = available_time / current["original_tts_duration"]
                                    current["adjusted_tts_duration"] = available_time
                                    current["final_end"] = current["final_start"] + available_time
                                    current["needs_speedup"] = True
                                    current["speedup_ratio"] = 1.0 / compression_ratio
                                    logger.info(f"🎵 最后片段 {current['subtitle_index']} 温和加速 {current['speedup_ratio']:.2f}x")
                                else:
                                    logger.warning(f"⚠️  最后片段 {current['subtitle_index']} 仍需截断，但已最大化保留")
                        else:
                            # 保护段：使用宽松的加速限制
                            available_time = boundary_to_use - current["final_start"]
                            if available_time > 0:
                                compression_ratio = available_time / current["original_tts_duration"]
                                if compression_ratio >= (1.0 / (max_speedup_ratio * 1.2)):  # 宽松20%
                                    current["adjusted_tts_duration"] = available_time
                                    current["final_end"] = current["final_start"] + available_time
                                    current["needs_speedup"] = True
                                    current["speedup_ratio"] = 1.0 / compression_ratio
                                    logger.info(f"🛡️ 保护片段 {current['subtitle_index']} 宽松加速 {current['speedup_ratio']:.2f}x")
                                else:
                                    # 允许适度截断，但记录
                                    current["adjusted_tts_duration"] = available_time
                                    current["final_end"] = boundary_to_use
                                    current["is_truncated"] = True
                                    current["truncation_severity"] = "moderate"
                                    logger.warning(f"✂️  保护片段 {current['subtitle_index']} 适度截断")
                    else:
                        # 标准段：使用原有逻辑
                        available_time = boundary_to_use - current["final_start"]
                        if available_time > 0:
                            compression_ratio = available_time / current["original_tts_duration"]
                            if compression_ratio >= (1.0 / max_speedup_ratio):
                                current["adjusted_tts_duration"] = available_time
                                current["final_end"] = current["final_start"] + available_time
                                current["needs_speedup"] = True
                                current["speedup_ratio"] = 1.0 / compression_ratio
                                logger.info(f"⚡ 标准片段 {current['subtitle_index']} 加速 {current['speedup_ratio']:.2f}x")
                            else:
                                current["adjusted_tts_duration"] = available_time
                                current["final_end"] = boundary_to_use
                                current["is_truncated"] = True
                                current["truncation_severity"] = "standard"
                                logger.warning(f"✂️  标准片段 {current['subtitle_index']} 标准截断")
                        else:
                            current["skip"] = True
                            logger.error(f"❌ 片段 {current['subtitle_index']} 开始时间超出边界，跳过")
                            continue
                
                # 2. 重叠检查和处理
                if i < len(tts_segments) - 1:
                    next_segment = tts_segments[i + 1]
                    current_end = current["final_end"]
                    next_start = next_segment["subtitle_start"]
                    overlap = current_end - next_start + min_gap_between_speech
                    
                    if overlap > 0:
                        next_is_protected = (i + 1) >= protection_threshold
                        logger.debug(f"重叠检测: {current['subtitle_index']} vs {next_segment['subtitle_index']}, 重叠{overlap/1000:.2f}s")
                        
                        # 根据段落类型选择解决策略
                        if is_protected_segment and next_is_protected:
                            # 两个都是保护段：优先延迟
                            delay = overlap
                            next_segment["final_start"] = next_segment["subtitle_start"] + delay
                            next_segment["final_end"] = next_segment["final_start"] + next_segment["original_tts_duration"]
                            next_segment["is_delayed"] = True
                            logger.info(f"⏰ 保护段重叠：延迟下一段 {next_segment['subtitle_index']} {delay/1000:.2f}s")
                        else:
                            # 标准处理：先尝试加速，再延迟
                            available_time = next_start - current["final_start"] - min_gap_between_speech
                            if available_time > 0:
                                compression_ratio = available_time / current["original_tts_duration"]
                                if compression_ratio >= (1.0 / max_speedup_ratio):
                                    current["adjusted_tts_duration"] = available_time
                                    current["final_end"] = current["final_start"] + available_time
                                    current["needs_speedup"] = True
                                    current["speedup_ratio"] = 1.0 / compression_ratio
                                    logger.info(f"⚡ 重叠解决：加速当前段 {current['subtitle_index']} {current['speedup_ratio']:.2f}x")
                                else:
                                    delay = overlap
                                    next_segment["final_start"] = next_segment["subtitle_start"] + delay
                                    next_segment["final_end"] = next_segment["final_start"] + next_segment["original_tts_duration"]
                                    next_segment["is_delayed"] = True
                                    logger.info(f"⏰ 重叠解决：延迟下一段 {next_segment['subtitle_index']} {delay/1000:.2f}s")
            
            # ===== 阶段3: 对齐优化阶段 =====
            logger.info("🎯 阶段3: 对齐优化阶段 - 智能对齐处理...")
            
            if ENABLE_SMART_ALIGNMENT:
                for segment in tts_segments:
                    if segment.get("skip"):
                        continue
                        
                    # 短音频对齐处理
                    if segment["adjusted_tts_duration"] < segment["subtitle_duration"] * 0.8:  # 短于原时长80%
                        # 在原时间窗口内居中对齐或尾部对齐
                        time_gap = segment["subtitle_duration"] - segment["adjusted_tts_duration"]
                        if time_gap > ALIGNMENT_TOLERANCE * 1000:
                            # 选择对齐策略：居中或尾部对齐
                            segment["alignment_offset"] = time_gap * 0.7  # 70%偏向尾部对齐
                            segment["final_start"] = segment["subtitle_start"] + segment["alignment_offset"]
                            logger.debug(f"🎯 片段 {segment['subtitle_index']} 尾部对齐，偏移 {segment['alignment_offset']/1000:.2f}s")
            
            # 最终统计和边界检查
            processing_stats = {
                "speedup_count": 0,
                "delayed_count": 0, 
                "truncated_count": 0,
                "skipped_count": 0,
                "protected_count": 0,
                "aligned_count": 0,
                "global_compressed_count": 0
            }
            
            boundary_issues = 0
            for segment in tts_segments:
                if segment.get("skip"):
                    processing_stats["skipped_count"] += 1
                    continue
                
                if segment["final_end"] > effective_boundary_ms:
                    boundary_issues += 1
                    logger.error(f"❌ 最终检查: 片段{segment['subtitle_index']} 仍超出有效边界")
                
                if segment.get("needs_speedup"):
                    processing_stats["speedup_count"] += 1
                if segment.get("is_delayed"):
                    processing_stats["delayed_count"] += 1
                if segment.get("is_truncated"):
                    processing_stats["truncated_count"] += 1
                if segment.get("processing_stage") in ["protected", "last_segment"]:
                    processing_stats["protected_count"] += 1
                if segment.get("alignment_offset"):
                    processing_stats["aligned_count"] += 1
                if segment.get("needs_global_compression"):
                    processing_stats["global_compressed_count"] += 1

            logger.info(f"📋 分阶段处理完成，最终统计:")
            logger.info(f"   ⚡ 音频加速: {processing_stats['speedup_count']} 个")
            logger.info(f"   ⏰ 延迟播放: {processing_stats['delayed_count']} 个") 
            logger.info(f"   ✂️  音频截断: {processing_stats['truncated_count']} 个")
            logger.info(f"   🛡️ 保护处理: {processing_stats['protected_count']} 个")
            logger.info(f"   🎯 智能对齐: {processing_stats['aligned_count']} 个")
            logger.info(f"   ❌ 跳过处理: {processing_stats['skipped_count']} 个")
            if boundary_issues > 0:
                logger.error(f"   ⚠️  边界问题: {boundary_issues} 个")
            
            # 用于存储要叠加的TTS音频
            overlays = []
            valid_tts_count_v2 = 0
            
            # 处理每个TTS片段
            for segment in tts_segments:
                try:
                    # 跳过被标记为跳过的片段
                    if segment.get("skip"):
                        logger.info(f"⏭️ 跳过片段 {segment['subtitle_index']}")
                        continue
                        
                    # 检查TTS音频文件是否存在
                    if not os.path.exists(segment["audio_path"]):
                        logger.warning(f"第 {segment['subtitle_index']} 个TTS音频文件不存在: {segment['audio_path']}")
                        continue
                        
                    # 加载TTS音频并进行质量检查
                    tts_audio = AudioSegment.from_file(segment["audio_path"])
                    logger.debug(f"V2-TTS音频 {segment['subtitle_index']}: 文件大小={os.path.getsize(segment['audio_path'])}字节, 时长={tts_audio.duration_seconds:.2f}s")
                    
                    # 检查音频是否为空或过短 - 进一步放宽要求
                    if tts_audio.duration_seconds < 0.01:  # 从0.1降到0.01秒
                        logger.warning(f"第 {segment['subtitle_index']} 个TTS音频过短 ({tts_audio.duration_seconds:.3f}s)，跳过")
                        continue
                        
                    # 检查音频是否是静音 - 移除静音跳过逻辑，全部处理
                    audio_rms = tts_audio.rms
                    if audio_rms < 5:  # 极端低的阈值
                        logger.warning(f"第 {segment['subtitle_index']} 个TTS音频RMS极低 (RMS={audio_rms})，但继续处理")
                    else:
                        logger.debug(f"第 {segment['subtitle_index']} 个TTS音频 RMS={audio_rms}")
                    
                    # 强制处理所有TTS音频，不管RMS多低
                        
                    valid_tts_count_v2 += 1
                    
                    # 应用音频调整
                    # 0. 先增强音频音量（避免在后续处理中被削弱）
                    tts_boost_db = 3  # TTS音频增益（分贝）
                    tts_audio = tts_audio + tts_boost_db
                    logger.debug(f"🔊 字幕{segment['subtitle_index']} 增加 {tts_boost_db}dB 增益")
                    
                    # 1. 先应用全局压缩（如果需要）
                    if segment.get("needs_global_compression"):
                        global_ratio = segment["global_compression_ratio"]
                        tts_audio = tts_audio.speedup(playback_speed=1.0/global_ratio)
                        logger.debug(f"🔒 字幕{segment['subtitle_index']} 应用全局压缩 {global_ratio:.3f}")
                    
                    # 2. 再应用局部加速（如果需要）
                    if segment.get("needs_speedup"):
                        speedup_ratio = segment["speedup_ratio"]
                        tts_audio = tts_audio.speedup(playback_speed=speedup_ratio)
                        logger.debug(f"⚡ 字幕{segment['subtitle_index']} 音频已加速{speedup_ratio:.2f}x")
                    
                    # 处理截断音频
                    if segment.get("is_truncated"):
                        # 计算需要保留的音频时长（毫秒）
                        truncated_duration_ms = segment["adjusted_tts_duration"]
                        if truncated_duration_ms > 0 and truncated_duration_ms < len(tts_audio):
                            # 截取音频到指定时长
                            tts_audio = tts_audio[:int(truncated_duration_ms)]
                            severity = segment.get("truncation_severity", "unknown")
                            logger.info(f"✂️ 字幕{segment['subtitle_index']} 音频已截断到 {truncated_duration_ms/1000:.2f}s (级别: {severity})")
                        elif truncated_duration_ms <= 0:
                            # 如果调整后的时长<=0，跳过这个片段
                            logger.warning(f"⚠️ 字幕{segment['subtitle_index']} 调整后时长为0，跳过处理")
                            continue
                    
                    # 智能对齐处理
                    final_start_time = segment["final_start"]
                    if segment.get("alignment_offset"):
                        final_start_time = segment["final_start"]
                        logger.debug(f"🎯 字幕{segment['subtitle_index']} 应用对齐偏移")
                    
                    # 添加到叠加列表
                    overlays.append({
                        "audio": tts_audio,
                        "start_time": int(final_start_time),
                        "duration": len(tts_audio),
                        "subtitle_index": segment["subtitle_index"],
                        "processing_stage": segment.get("processing_stage", "standard")
                    })
                    
                    # 更新背景音量包络
                    start_sample = int((final_start_time / 1000.0) * background.frame_rate)
                    duration_samples = int((len(tts_audio) / 1000.0) * background.frame_rate)
                    
                    if start_sample < total_samples:
                        # 计算淡入淡出位置
                        fade_duration_samples = int((fade_duration / 1000.0) * background.frame_rate)
                        fade_out_start = max(0, start_sample - fade_duration_samples // 2)
                        fade_out_end = min(total_samples, start_sample + fade_duration_samples // 2)
                        fade_in_start = max(0, start_sample + duration_samples - fade_duration_samples // 2)
                        fade_in_end = min(total_samples, start_sample + duration_samples + fade_duration_samples // 2)
                        
                        # 应用音量包络
                        if fade_out_start < fade_out_end:
                            fade_out_samples = np.linspace(1.0, background_min_volume, fade_out_end - fade_out_start)
                            volume_envelope[fade_out_start:fade_out_end] = np.minimum(
                                volume_envelope[fade_out_start:fade_out_end], fade_out_samples
                            )
                        
                        low_volume_start = fade_out_end
                        low_volume_end = min(total_samples, fade_in_start)
                        if low_volume_start < low_volume_end:
                            volume_envelope[low_volume_start:low_volume_end] = np.minimum(
                                volume_envelope[low_volume_start:low_volume_end], background_min_volume
                            )
                        
                        if fade_in_start < fade_in_end:
                            fade_in_samples = np.linspace(background_min_volume, 1.0, fade_in_end - fade_in_start)
                            volume_envelope[fade_in_start:fade_in_end] = fade_in_samples
                    
                except Exception as e:
                    logger.error(f"处理字幕{segment['subtitle_index']} TTS音频失败: {str(e)}")
                    continue
            
            logger.info("应用音量包络到背景音频...")
            
            # 应用音量包络
            if background.channels == 2:
                background_samples_reshaped = background_samples.reshape((-1, 2))
                volume_envelope_stereo = np.column_stack([volume_envelope, volume_envelope])
                background_samples_processed = (background_samples_reshaped * volume_envelope_stereo).astype(np.int16)
                background_samples_final = background_samples_processed.flatten()
            else:
                background_samples_final = (background_samples * volume_envelope).astype(np.int16)
            
            # 重建背景音频
            modified_background = background._spawn(background_samples_final.tobytes())
            
            logger.info(f"叠加TTS音频...（共 {len(overlays)} 个音频片段）")
            
            if len(overlays) == 0:
                logger.error("❌ V2方法没有任何有效的TTS音频可以叠加！启动诊断模式...")
                # 运行详细诊断
                diagnosis = self._diagnose_audio_mixing_issue(subtitles, background_audio_path)
                if diagnosis["critical_issues"] > 0:
                    logger.error(f"发现 {diagnosis['critical_issues']} 个关键问题，无法继续音频混合")
                # 直接复制背景音频到输出路径
                background.export(output_path, format="wav")
                return output_path
            
            # 叠加所有TTS音频
            final_audio = modified_background
            successful_overlays_v2 = 0
            
            for overlay in overlays:
                try:
                    tts_audio = overlay["audio"]
                    
                    # 确保采样率和声道数匹配
                    if tts_audio.frame_rate != final_audio.frame_rate:
                        logger.debug(f"V2-调整TTS音频 {overlay['subtitle_index']} 采样率: {tts_audio.frame_rate} -> {final_audio.frame_rate}")
                        tts_audio = tts_audio.set_frame_rate(final_audio.frame_rate)
                    if tts_audio.channels != final_audio.channels:
                        if final_audio.channels == 2 and tts_audio.channels == 1:
                            logger.debug(f"V2-将TTS音频 {overlay['subtitle_index']} 转换为立体声")
                            tts_audio = tts_audio.set_channels(2)
                        elif final_audio.channels == 1 and tts_audio.channels == 2:
                            logger.debug(f"V2-将TTS音频 {overlay['subtitle_index']} 转换为单声道")
                            tts_audio = tts_audio.set_channels(1)
                    
                    # 检查叠加位置是否合理
                    overlay_start = overlay["start_time"]
                    overlay_end = overlay_start + len(tts_audio)
                    if overlay_end > len(final_audio):
                        logger.warning(f"V2-TTS音频 {overlay['subtitle_index']} 超出背景音频范围，进行截断")
                        available_duration = len(final_audio) - overlay_start
                        if available_duration > 0:
                            tts_audio = tts_audio[:available_duration]
                        else:
                            logger.warning(f"V2-TTS音频 {overlay['subtitle_index']} 开始位置超出范围，跳过")
                            continue
                    
                    # 详细的叠加信息
                    logger.debug(f"V2-叠加TTS音频 {overlay['subtitle_index']}: 位置={overlay_start/1000:.2f}s, 时长={len(tts_audio)/1000:.2f}s, RMS={tts_audio.rms}")
                    
                    # 叠加音频
                    final_audio = final_audio.overlay(tts_audio, position=overlay_start)
                    successful_overlays_v2 += 1
                    logger.info(f"✅ V2-成功叠加第 {overlay['subtitle_index']} 个TTS音频 (位置: {overlay_start/1000:.2f}s)")
                    
                except Exception as e:
                    logger.error(f"❌ V2-叠加第 {overlay['subtitle_index']} 个TTS音频失败: {str(e)}")
                    continue
            
            logger.info(f"🎵 V2-音频叠加完成: {successful_overlays_v2}/{len(overlays)} 个TTS音频成功叠加")
            
            if successful_overlays_v2 == 0:
                logger.error("❌ V2方法没有任何TTS音频成功叠加！启动深度诊断...")
                # 运行详细诊断
                diagnosis = self._diagnose_audio_mixing_issue(subtitles, background_audio_path)
                logger.error("检查上述诊断结果，修复问题后重试")
                # 返回原始背景音频
                background.export(output_path, format="wav")
                return output_path
            
            logger.info("导出最终音频...")
            
            # 严格时长控制：确保最终音频时长与背景音频完全一致
            if STRICT_DURATION_CONTROL:
                target_duration_ms = len(background)
                current_duration_ms = len(final_audio)
                
                if current_duration_ms != target_duration_ms:
                    logger.info(f"🔧 调整最终音频时长: {current_duration_ms/1000:.3f}s → {target_duration_ms/1000:.3f}s")
                    
                    if current_duration_ms > target_duration_ms:
                        # 截断超出部分
                        final_audio = final_audio[:target_duration_ms]
                        logger.info("✂️ 截断超出部分")
                    else:
                        # 用静音填充不足部分
                        silence_duration = target_duration_ms - current_duration_ms
                        silence = AudioSegment.silent(duration=silence_duration)
                        final_audio = final_audio + silence
                        logger.info(f"🔇 填充静音 {silence_duration/1000:.3f}s")
                
                # 最终验证
                final_duration_ms = len(final_audio)
                logger.info(f"✅ 时长验证: 最终={final_duration_ms/1000:.3f}s, 目标={target_duration_ms/1000:.3f}s")
                
                if abs(final_duration_ms - target_duration_ms) > 10:  # 允许10ms误差
                    logger.warning(f"⚠️ 时长误差超过10ms: {abs(final_duration_ms - target_duration_ms)}ms")
            
            # 检查最终音频质量
            logger.info(f"V2-最终音频信息: 时长={final_audio.duration_seconds:.2f}s, 采样率={final_audio.frame_rate}Hz, 声道={final_audio.channels}, RMS={final_audio.rms}")
            
            # 如果最终音频与背景音频差异过大，发出警告
            duration_diff = abs(final_audio.duration_seconds - background.duration_seconds)
            if duration_diff > 0.1:  # 超过100ms差异
                logger.warning(f"⚠️ V2-最终音频时长与背景音频有 {duration_diff:.3f}s 差异")
            
            final_audio.export(output_path, format="wav")
            
            # 验证输出文件
            if os.path.exists(output_path):
                output_size = os.path.getsize(output_path)
                logger.info(f"✅ V2-音频混合完成，输出文件大小: {output_size/1024/1024:.2f}MB")
                
                # 快速验证输出音频
                try:
                    verify_audio = AudioSegment.from_file(output_path)
                    logger.info(f"✅ V2-输出音频验证: 时长={verify_audio.duration_seconds:.2f}s, RMS={verify_audio.rms}")
                except Exception as e:
                    logger.error(f"❌ V2-输出音频验证失败: {str(e)}")
            else:
                logger.error("❌ V2-输出文件未生成")
            
            # 输出处理统计 - 使用分阶段统计
            logger.info(f"🎵 分阶段自适应音频混合完成！")
            logger.info(f"   最终音频时长: {final_audio.duration_seconds:.3f}s")
            logger.info(f"   背景音频时长: {background.duration_seconds:.3f}s")
            
            duration_diff = final_audio.duration_seconds - background.duration_seconds
            if abs(duration_diff) < 0.01:  # 10ms容差
                logger.info(f"✅ 时长完全一致 (误差: {duration_diff*1000:.1f}ms)")
            else:
                if duration_diff > 0:
                    logger.warning(f"⚠️ 音频延长: +{duration_diff:.3f}s")
                else:
                    logger.warning(f"⚠️ 音频缩短: {duration_diff:.3f}s")
            
            logger.info(f"📈 分阶段处理效果总结:")
            logger.info(f"   ⚡ 音频加速: {processing_stats['speedup_count']} 个")
            logger.info(f"   ⏰ 延迟播放: {processing_stats['delayed_count']} 个")
            logger.info(f"   ✂️  音频截断: {processing_stats['truncated_count']} 个")  
            logger.info(f"   🛡️ 保护处理: {processing_stats['protected_count']} 个")
            logger.info(f"   🎯 智能对齐: {processing_stats['aligned_count']} 个")
            logger.info(f"   🔒 全局压缩: {processing_stats['global_compressed_count']} 个")
            logger.info(f"   ❌ 跳过处理: {processing_stats['skipped_count']} 个")
            logger.info(f"   🎵 成功叠加: {successful_overlays_v2}/{len(overlays)} 个")
            
            if needs_global_compression:
                logger.info(f"🔒 全局压缩比例: {global_compression_ratio:.3f} (所有片段)")
            
            if processing_stats['protected_count'] > 0:
                logger.info(f"✨ 启用保护策略，成功保护了最后 {processing_stats['protected_count']} 个重要片段")
            
            return output_path
            
        except Exception as e:
            logger.error(f"改进版音频混合失败: {str(e)}")
            raise

    def _force_overlay_audio(self, background_audio: 'AudioSegment', tts_audio: 'AudioSegment', 
                            position_ms: int, subtitle_index: int) -> 'AudioSegment':
        """
        强制音频叠加方法 - 当标准叠加失败时使用的备用方案
        
        这个方法通过直接操作音频数据来确保TTS音频被正确叠加
        
        参数:
            background_audio: 背景音频
            tts_audio: 要叠加的TTS音频
            position_ms: 叠加位置（毫秒）
            subtitle_index: 字幕索引
            
        返回:
            叠加后的音频
        """
        try:
            from pydub import AudioSegment
            import numpy as np
            
            logger.info(f"🔧 使用强制叠加方法处理TTS音频 {subtitle_index}")
            
            # 确保音频格式一致
            if tts_audio.frame_rate != background_audio.frame_rate:
                tts_audio = tts_audio.set_frame_rate(background_audio.frame_rate)
            if tts_audio.channels != background_audio.channels:
                tts_audio = tts_audio.set_channels(background_audio.channels)
            
            # 如果位置超出背景音频范围，截断或跳过
            if position_ms >= len(background_audio):
                logger.warning(f"⚠️ 叠加位置超出背景音频范围，跳过")
                return background_audio
            
            # 如果TTS音频会超出背景音频长度，截断TTS音频
            available_duration = len(background_audio) - position_ms
            if len(tts_audio) > available_duration:
                tts_audio = tts_audio[:available_duration]
                logger.info(f"✂️ TTS音频已截断到 {available_duration/1000:.2f}s")
            
            # 方法1: 使用pydub的overlay方法
            try:
                result = background_audio.overlay(tts_audio, position=position_ms)
                # 验证叠加是否成功
                if abs(result.rms - background_audio.rms) > 1:
                    logger.info(f"✅ 标准overlay方法成功")
                    return result
                else:
                    raise Exception("标准overlay方法RMS无变化")
            except Exception as e:
                logger.warning(f"⚠️ 标准overlay方法失败: {e}")
            
            # 方法2: 手动数组级别叠加
            try:
                logger.info("🔧 尝试手动数组级别叠加...")
                
                # 转换为numpy数组
                bg_samples = np.array(background_audio.get_array_of_samples())
                tts_samples = np.array(tts_audio.get_array_of_samples())
                
                # 计算起始采样点
                samples_per_ms = background_audio.frame_rate / 1000.0
                start_sample = int(position_ms * samples_per_ms)
                
                # 处理立体声
                if background_audio.channels == 2:
                    bg_samples = bg_samples.reshape((-1, 2))
                    tts_samples = tts_samples.reshape((-1, 2))
                    
                    # 确保不会越界
                    end_sample = min(start_sample + len(tts_samples), len(bg_samples))
                    tts_length = end_sample - start_sample
                    
                    if tts_length > 0:
                        # 叠加音频 - 使用加权混合
                        bg_weight = 0.3  # 背景音权重
                        tts_weight = 0.9  # TTS音权重
                        
                        mixed_segment = (bg_samples[start_sample:end_sample] * bg_weight + 
                                       tts_samples[:tts_length] * tts_weight)
                        
                        # 防止溢出
                        mixed_segment = np.clip(mixed_segment, -32768, 32767)
                        bg_samples[start_sample:end_sample] = mixed_segment.astype(np.int16)
                    
                    # 重新展平
                    bg_samples = bg_samples.flatten()
                else:
                    # 单声道处理
                    end_sample = min(start_sample + len(tts_samples), len(bg_samples))
                    tts_length = end_sample - start_sample
                    
                    if tts_length > 0:
                        # 叠加音频 - 使用加权混合
                        bg_weight = 0.3  # 背景音权重
                        tts_weight = 0.9  # TTS音权重
                        
                        mixed_segment = (bg_samples[start_sample:end_sample] * bg_weight + 
                                       tts_samples[:tts_length] * tts_weight)
                        
                        # 防止溢出
                        mixed_segment = np.clip(mixed_segment, -32768, 32767)
                        bg_samples[start_sample:end_sample] = mixed_segment.astype(np.int16)
                
                # 重建音频
                result = background_audio._spawn(bg_samples.astype(np.int16).tobytes())
                
                # 验证结果
                if abs(result.rms - background_audio.rms) > 1:
                    logger.info(f"✅ 手动数组级别叠加成功 (RMS变化: {result.rms - background_audio.rms:+.1f})")
                    return result
                else:
                    raise Exception("手动叠加方法RMS无变化")
                    
            except Exception as e:
                logger.warning(f"⚠️ 手动数组级别叠加失败: {e}")
            
            # 方法3: 分段替换方法
            try:
                logger.info("🔧 尝试分段替换方法...")
                
                # 分割背景音频
                before_segment = background_audio[:position_ms] if position_ms > 0 else AudioSegment.empty()
                after_start = position_ms + len(tts_audio)
                after_segment = background_audio[after_start:] if after_start < len(background_audio) else AudioSegment.empty()
                
                # 获取要替换的背景音频段
                background_segment = background_audio[position_ms:after_start]
                
                # 将背景音音量降低，然后与TTS音频混合
                reduced_bg = background_segment - 12  # 降低12dB
                
                # 确保TTS音频长度匹配
                if len(tts_audio) > len(background_segment):
                    tts_audio = tts_audio[:len(background_segment)]
                elif len(tts_audio) < len(background_segment):
                    # 用静音填充
                    silence = AudioSegment.silent(duration=len(background_segment) - len(tts_audio))
                    tts_audio = tts_audio + silence
                
                # 混合音频
                mixed_segment = reduced_bg.overlay(tts_audio)
                
                # 重新组合
                result = before_segment + mixed_segment + after_segment
                
                # 验证结果
                if abs(result.rms - background_audio.rms) > 0.5:
                    logger.info(f"✅ 分段替换方法成功 (RMS变化: {result.rms - background_audio.rms:+.1f})")
                    return result
                else:
                    raise Exception("分段替换方法RMS变化不足")
                    
            except Exception as e:
                logger.warning(f"⚠️ 分段替换方法失败: {e}")
            
            # 如果所有方法都失败，返回原始背景音频并记录错误
            logger.error(f"❌ 所有强制叠加方法都失败，TTS音频 {subtitle_index} 未能叠加")
            return background_audio
            
        except Exception as e:
            logger.error(f"❌ 强制叠加方法发生异常: {e}")
            return background_audio

if __name__ == "__main__":
    # 创建命令行参数解析器
    parser = argparse.ArgumentParser(description="Video Translation Program")
    parser.add_argument("--input_video", required=True, help="Input Video File Path")   
    args = parser.parse_args()
    
    video_translation_client = VideoTranslationClient()
    asyncio.run(video_translation_client.process_video(args.input_video))