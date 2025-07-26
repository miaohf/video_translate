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
    from config import settings as app_config
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
        temp_base_dir = app_config.TEMP_DIR if app_config else "temp"
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
        temp_base_dir = app_config.TEMP_DIR if app_config else "temp"
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
                    # 生成字幕（传递video_path参数和人声分离设置）
                    from config import ENABLE_VOCAL_SEPARATION
                    subtitles = await self.subtitle_processor.get_subtitles(
                        audio_path, video_name, video_path, 
                        use_vocal_separation=ENABLE_VOCAL_SEPARATION
                    )

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
            final_audio_path = await self._mix_audio_simple(
                updated_subtitles, 
                video_name,
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
            
            # 控制是否生成副本文件（可通过配置关闭）
            SAVE_FINAL_AUDIO_COPY = False  # 设置为False可以禁用副本生成
            
            if SAVE_FINAL_AUDIO_COPY:
                try:
                    shutil.copy2(final_audio_path, final_audio_copy)
                    logger.info(f"最终音频已保存到: {final_audio_copy}")
                except Exception as e:
                    logger.warning(f"保存最终音频副本失败: {str(e)}")
                    final_audio_copy = None
            else:
                logger.info("已禁用最终音频副本生成")
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

    async def _mix_audio_simple(self, subtitles: List[Dict], video_name: str, output_path: str) -> str:
        """
        简化的音频合并方法
        
        特点：
        1. 使用人声背景分离后的背景音作为合并的背景音
        2. TTS生成的音频按照对应的字幕时间合并
        3. 如果TTS生成的音频时长不足，在尾部用静音补足
        4. 如果TTS时长超过字幕时长，加快播放使其时长与字幕时长一致
        
        参数:
            subtitles: 包含generated_audio信息的字幕列表
            video_name: 视频名称
            output_path: 输出文件路径
            
        返回:
            合成后的音频文件路径
        """
        try:
            from pydub import AudioSegment
            
            logger.info("🎵 开始简化音频合并...")
            
            # 1. 获取人声分离后的背景音频
            file_hash = get_file_hash(video_name)
            background_audio_path = os.path.join("temp", video_name, "separated_audio", f"{file_hash}_background.wav")
            
            if not os.path.exists(background_audio_path):
                logger.warning(f"⚠️ 人声分离背景音频不存在: {background_audio_path}")
                # 尝试使用原始音频作为背景
                original_audio_path = os.path.join("temp", video_name, f"{file_hash}_audio.mp3")
                if os.path.exists(original_audio_path):
                    logger.info("使用原始音频作为背景音")
                    background_audio_path = original_audio_path
                else:
                    logger.error("❌ 找不到任何背景音频文件")
                    raise FileNotFoundError("找不到背景音频文件")
            
            # 加载背景音频
            logger.info(f"加载背景音频: {background_audio_path}")
            background = AudioSegment.from_file(background_audio_path)
            logger.info(f"背景音频信息: 时长={background.duration_seconds:.2f}s, 采样率={background.frame_rate}Hz, 声道={background.channels}")
            
            # 2. 处理TTS音频并合并
            logger.info("处理TTS音频...")
            
            # 创建最终的音频（从背景音频开始）
            final_audio = background
            tts_boost_db = 3  # TTS音频增益（分贝）
            
            processed_count = 0
            total_subtitles = len(subtitles)
            
            for i, subtitle in enumerate(subtitles):
                try:
                    generated_audio_path = subtitle.get("generated_audio")
                    if not generated_audio_path or not os.path.exists(generated_audio_path):
                        logger.warning(f"第 {i+1} 个字幕缺少生成的音频文件: {generated_audio_path}")
                        continue
                    
                    # 加载TTS音频
                    tts_audio = AudioSegment.from_file(generated_audio_path)
                    
                    # 检查TTS音频是否有效
                    if tts_audio.duration_seconds < 0.01:
                        logger.warning(f"第 {i+1} 个TTS音频过短 ({tts_audio.duration_seconds:.3f}s)，跳过")
                        continue
                        
                    # 获取字幕时间信息
                    subtitle_start_ms = subtitle["start"] * 1000  # 转换为毫秒
                    subtitle_end_ms = subtitle["end"] * 1000
                    subtitle_duration_ms = subtitle_end_ms - subtitle_start_ms
                    
                    # 获取TTS音频时长
                    tts_duration_ms = len(tts_audio)
                    
                    logger.info(f"字幕{i+1}: 字幕时长={subtitle_duration_ms/1000:.2f}s, TTS时长={tts_duration_ms/1000:.2f}s")
                    
                    # 3. 时长对齐处理
                    if tts_duration_ms > subtitle_duration_ms:
                        # TTS时长超过字幕时长，加快播放
                        speedup_ratio = tts_duration_ms / subtitle_duration_ms
                        tts_audio = tts_audio.speedup(playback_speed=speedup_ratio)
                        logger.info(f"✅ 字幕{i+1} 加速{speedup_ratio:.2f}x: {tts_duration_ms/1000:.2f}s → {len(tts_audio)/1000:.2f}s")
                    elif tts_duration_ms < subtitle_duration_ms:
                        # TTS时长不足，在尾部用静音补足
                        silence_duration_ms = subtitle_duration_ms - tts_duration_ms
                        silence = AudioSegment.silent(duration=silence_duration_ms)
                        tts_audio = tts_audio + silence
                        logger.info(f"✅ 字幕{i+1} 补足静音: {tts_duration_ms/1000:.2f}s → {len(tts_audio)/1000:.2f}s (+{silence_duration_ms/1000:.2f}s)")
                    else:
                        # 时长正好匹配
                        logger.info(f"✅ 字幕{i+1} 时长匹配: {tts_duration_ms/1000:.2f}s")
                    
                    # 增强TTS音频音量
                    tts_audio = tts_audio + tts_boost_db
                    
                    # 确保采样率和声道数匹配
                    if tts_audio.frame_rate != final_audio.frame_rate:
                        logger.debug(f"调整TTS音频 {i+1} 采样率: {tts_audio.frame_rate} -> {final_audio.frame_rate}")
                        tts_audio = tts_audio.set_frame_rate(final_audio.frame_rate)
                    
                    if tts_audio.channels != final_audio.channels:
                        if final_audio.channels == 2 and tts_audio.channels == 1:
                            logger.debug(f"将TTS音频 {i+1} 转换为立体声")
                            tts_audio = tts_audio.set_channels(2)
                        elif final_audio.channels == 1 and tts_audio.channels == 2:
                            logger.debug(f"将TTS音频 {i+1} 转换为单声道")
                            tts_audio = tts_audio.set_channels(1)
                    
                    # 检查叠加位置是否合理
                    if subtitle_start_ms >= len(final_audio):
                        logger.warning(f"⚠️ 字幕{i+1} 开始时间超出背景音频范围，跳过")
                        continue
                    
                    # 如果TTS音频会超出背景音频长度，截断TTS音频
                    available_duration = len(final_audio) - subtitle_start_ms
                    if len(tts_audio) > available_duration:
                        tts_audio = tts_audio[:available_duration]
                        logger.warning(f"⚠️ 字幕{i+1} TTS音频已截断到 {available_duration/1000:.2f}s")
                    
                    # 叠加TTS音频到背景音频
                    logger.info(f"🎵 叠加字幕{i+1}: 位置={subtitle_start_ms/1000:.2f}s, 时长={len(tts_audio)/1000:.2f}s")
                    final_audio = final_audio.overlay(tts_audio, position=int(subtitle_start_ms))
                    
                    processed_count += 1
                    logger.info(f"✅ 成功处理第 {i+1}/{total_subtitles} 个字幕")
                    
                except Exception as e:
                    logger.error(f"处理第 {i+1} 个字幕时出错: {str(e)}")
                    continue
            
            logger.info(f"🎵 音频合并完成: 成功处理 {processed_count}/{total_subtitles} 个字幕")
            
            if processed_count == 0:
                logger.warning("⚠️ 没有任何TTS音频被处理，返回原始背景音频")
                final_audio = background
            
            # 导出最终音频 - 使用MP3格式以提高兼容性
            logger.info("导出最终音频...")
            
            # 确保音频格式为兼容的格式
            # 兼容格式参数：
            # - 采样率: 44.1kHz (CD音质)
            # - 声道数: 2 (立体声)
            # - 格式: MP3 (与MoviePy更兼容)
            compatible_audio = final_audio.set_frame_rate(44100).set_channels(2)
            
            # 导出为MP3格式 - 提高与MoviePy的兼容性
            compatible_audio.export(
                output_path.replace('.wav', '.mp3'), 
                format="mp3",
                bitrate="192k"  # 高质量MP3
            )
            
            # 更新输出路径为MP3文件
            output_path = output_path.replace('.wav', '.mp3')
            
            # 验证输出文件
            if os.path.exists(output_path):
                output_size = os.path.getsize(output_path)
                logger.info(f"✅ 简化音频合并完成，输出文件大小: {output_size/1024/1024:.2f}MB")
                
                # 快速验证输出音频
                try:
                    verify_audio = AudioSegment.from_file(output_path)
                    logger.info(f"✅ 输出音频验证: 时长={verify_audio.duration_seconds:.2f}s, 采样率={verify_audio.frame_rate}Hz, 声道={verify_audio.channels}")
                except Exception as e:
                    logger.error(f"❌ 输出音频验证失败: {str(e)}")
            else:
                logger.error("❌ 输出文件未生成")
            
            return output_path
            
        except Exception as e:
            logger.error(f"简化音频合并失败: {str(e)}")
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