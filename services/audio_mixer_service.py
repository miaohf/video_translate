import os
import logging
import numpy as np
from typing import List, Dict
from pydub import AudioSegment

logger = logging.getLogger(__name__)

class AudioMixerService:
    """音频混合服务"""
    
    @staticmethod
    def _resolve_audio_overlaps(audio_segments: List[Dict], min_gap_ms: int) -> List[Dict]:
        """
        解决音频片段之间的重叠问题，考虑音频片段与字幕时长的关系，处理连锁调整
        
        参数:
            audio_segments: 音频片段列表，包含开始时间、结束时间等信息
            min_gap_ms: 音频之间的最小间隔（毫秒）
            
        返回:
            调整后的音频片段列表
        """
        if not audio_segments:
            return []
        
        # 保持原始顺序，不按开始时间排序
        # 这样可以确保字幕播放顺序与原始顺序一致
        sorted_segments = audio_segments.copy()  # 保持原始顺序
        resolved_segments = []
        
        for i, current_segment in enumerate(sorted_segments):
            current_start = current_segment["start_time_ms"]
            current_end = current_segment["end_time_ms"]
            current_duration = current_segment["duration_ms"]
            subtitle = current_segment["subtitle"]
            
            # 计算字幕时长
            subtitle_duration = (subtitle["end"] - subtitle["start"]) * 1000  # 转换为毫秒
            
            # 找到与当前片段重叠的最晚结束的片段
            latest_end_time = 0
            conflicting_segment = None
            
            for resolved_segment in resolved_segments:
                # 检查是否有时间重叠
                if (resolved_segment["end_time_ms"] + min_gap_ms > current_start and 
                    resolved_segment["start_time_ms"] < current_end):
                    if resolved_segment["end_time_ms"] > latest_end_time:
                        latest_end_time = resolved_segment["end_time_ms"]
                        conflicting_segment = resolved_segment
            
            if conflicting_segment:
                # 存在重叠，需要调整当前片段
                overlap_ms = latest_end_time + min_gap_ms - current_start
                
                # 策略1：如果当前音频片段时长小于字幕时长，可以尝试提前开始时间
                if current_duration < subtitle_duration:
                    # 计算可以提前的最大时间
                    max_advance = min(overlap_ms, subtitle_duration - current_duration)
                    if max_advance > 0:
                        new_start_time = current_start - max_advance
                        # 检查提前后是否还会与其他片段重叠
                        still_conflicts = False
                        for resolved_segment in resolved_segments:
                            if (resolved_segment["end_time_ms"] + min_gap_ms > new_start_time and 
                                resolved_segment["start_time_ms"] < new_start_time + current_duration):
                                still_conflicts = True
                                break
                        
                        if not still_conflicts:
                            new_end_time = new_start_time + current_duration
                            logger.info(f"Advancing audio {current_segment['index']+1} start time by {max_advance}ms: {current_start/1000:.2f}s -> {new_start_time/1000:.2f}s")
                            
                            adjusted_segment = current_segment.copy()
                            adjusted_segment["start_time_ms"] = new_start_time
                            adjusted_segment["end_time_ms"] = new_end_time
                            resolved_segments.append(adjusted_segment)
                            continue
                
                # 策略2：延后当前音频到安全位置
                new_start_time = latest_end_time + min_gap_ms
                new_end_time = new_start_time + current_duration
                logger.warning(f"Detected overlap: Audio {current_segment['index']+1} overlaps with audio {conflicting_segment['index']+1}")
                logger.info(f"Adjusting audio {current_segment['index']+1}: {current_start/1000:.2f}s -> {new_start_time/1000:.2f}s")
                
                adjusted_segment = current_segment.copy()
                adjusted_segment["start_time_ms"] = new_start_time
                adjusted_segment["end_time_ms"] = new_end_time
                resolved_segments.append(adjusted_segment)
            else:
                # 没有重叠，直接添加
                resolved_segments.append(current_segment)
        
        logger.info("Audio overlap resolution completed")
        
        # 统计调整信息
        adjusted_count = 0
        for original, resolved in zip(sorted_segments, resolved_segments):
            if (abs(original["start_time_ms"] - resolved["start_time_ms"]) > 10 or 
                abs(original["end_time_ms"] - resolved["end_time_ms"]) > 10):
                adjusted_count += 1
        
        if adjusted_count > 0:
            logger.info(f"Resolved audio overlaps: adjusted {adjusted_count}/{len(audio_segments)} segments")
        else:
            logger.info("No audio overlaps detected")
        
        return resolved_segments
    
    @staticmethod
    async def mix_audio_with_background(
        subtitles: List[Dict], 
        background_audio_path: str, 
        output_path: str
    ) -> str:
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
            # 配置参数
            fade_duration = 3000  # 渐变时间（毫秒）
            background_min_volume = 0.02  # 背景音最低音量（2%）
            background_max_volume = 0.8  # 背景音最高音量（30%）
            fade_curve_power = 2.5  # 渐变曲线指数（>1为凹曲线，更陡峭）
            min_gap_between_audio = 200  # 音频之间的最小间隔（毫秒）
            
            logger.info("Loading background audio...")
            background = AudioSegment.from_file(background_audio_path)
            
            logger.info("Processing TTS audio insertion and overlap detection...")
            
            # 第一步：计算所有音频的时间范围，并检测重叠
            audio_segments = []
            for i, subtitle in enumerate(subtitles):
                generated_audio_path = subtitle.get("generated_audio")
                if not generated_audio_path or not os.path.exists(generated_audio_path):
                    logger.warning(f"Subtitle {i+1} missing generated audio file")
                    continue
                
                # 使用结束时间对齐：中文语音结束时间 = 原字幕结束时间
                original_end_time_ms = subtitle["end"] * 1000  # 原字幕结束时间（毫秒）
                generated_duration_ms = subtitle.get("generated_duration", 0) * 1000  # 中文语音时长（毫秒）
                
                # 计算中文语音开始时间：结束时间 - 语音时长
                start_time_ms = max(0, original_end_time_ms - generated_duration_ms)
                
                audio_segments.append({
                    "index": i,
                    "start_time_ms": start_time_ms,
                    "end_time_ms": original_end_time_ms,
                    "duration_ms": generated_duration_ms,
                    "audio_path": generated_audio_path,
                    "subtitle": subtitle
                })
            
            # 第二步：解决重叠问题
            logger.info("Resolving audio overlaps...")
            resolved_segments = AudioMixerService._resolve_audio_overlaps(audio_segments, min_gap_between_audio)
            
            # 第三步：显示调整后的音频时间安排
            print("\n" + "="*150)
            print("音频合成时间安排预览（保持原始字幕顺序）")
            print("="*150)
            print(f"{'序号':<4} {'原始时间':<20} {'调整后时间':<20} {'状态':<8} {'字幕内容'}")
            print("-"*150)
            
            for i, (original, resolved) in enumerate(zip(audio_segments, resolved_segments)):
                # 删除换行符并显示更多内容（80个字符）
                subtitle_text = original["subtitle"]["text"].replace('\n', ' ').replace('\r', ' ')
                if len(subtitle_text) > 80:
                    subtitle_text = subtitle_text[:80] + "..."
                
                # 显示原始计算的时间（基于字幕结束时间对齐）
                original_time = f"{original['start_time_ms']/1000:.2f}-{original['end_time_ms']/1000:.2f}s"
                # 显示调整后的实际音频播放时间
                resolved_time = f"{resolved['start_time_ms']/1000:.2f}-{resolved['end_time_ms']/1000:.2f}s"
                
                # 判断是否有调整（检查开始时间或结束时间的变化）
                if (abs(original['start_time_ms'] - resolved['start_time_ms']) > 10 or 
                    abs(original['end_time_ms'] - resolved['end_time_ms']) > 10):
                    status = "已调整"
                else:
                    status = "无变化"
                
                print(f"{i+1:<4} {original_time:<20} {resolved_time:<20} {status:<8} {subtitle_text}")
            
            print("-"*150)
            print(f"总计: {len(resolved_segments)} 个音频片段")
            
            # 统计调整信息
            adjusted_count = 0
            for original, resolved in zip(audio_segments, resolved_segments):
                if (abs(original['start_time_ms'] - resolved['start_time_ms']) > 10 or 
                    abs(original['end_time_ms'] - resolved['end_time_ms']) > 10):
                    adjusted_count += 1
            if adjusted_count > 0:
                print(f"其中 {adjusted_count} 个片段的时间被调整以避免重叠")
            
            print("播放顺序：保持原始字幕顺序 1 -> 2 -> 3 -> ... -> " + str(len(resolved_segments)))
            
            print("="*150)
            
            # 等待用户确认
            # while True:
            #     user_input = input("\n是否继续进行音频合成？(Y/y 继续, N/n 取消): ").strip().lower()
            #     if user_input in ['y', 'yes']:
            #         print("开始音频合成...")
            #         break
            #     elif user_input in ['n', 'no']:
            #         print("音频合成已取消")
            #         return None
            #     else:
            #         print("请输入 Y 或 N")
            
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
            
            logger.info("Processing TTS audio insertion...")
            
            # 用于存储要叠加的TTS音频
            overlays = []
            
            # 第四步：应用音量控制和生成重叠信息
            for segment in resolved_segments:
                i = segment["index"]
                start_time_ms = segment["start_time_ms"]
                end_time_ms = segment["end_time_ms"]  # 使用调整后的结束时间
                
                # 转换为采样点位置
                start_sample = int((start_time_ms / 1000.0) * background.frame_rate)
                end_sample = int((end_time_ms / 1000.0) * background.frame_rate)
                
                # 检查时间边界
                if start_sample >= total_samples:
                    logger.warning(f"Subtitle {i+1} calculated start time exceeds background audio length")
                    continue
                if end_sample > total_samples:
                    logger.warning(f"Subtitle {i+1} end time exceeds background audio length, adjusting")
                    end_sample = total_samples
                
                # 计算音量控制的关键采样点（以采样点为单位）
                fade_duration_samples = int((fade_duration / 1000.0) * background.frame_rate)
                
                # 背景音提前开始淡出，在中文语音开始前就完成淡出
                fade_out_start = max(0, start_sample - fade_duration_samples)
                fade_out_end = start_sample  # 在中文语音开始时完成淡出
                
                # 背景音在中文语音结束后开始淡入
                fade_in_start = end_sample  # 从中文语音结束时开始淡入
                fade_in_end = min(total_samples, end_sample + fade_duration_samples)
                
                # 设置音量包络
                # 淡出阶段（在中文语音开始前）- 使用非线性曲线
                if fade_out_start < fade_out_end:
                    # 创建非线性淡出曲线（指数衰减，更快下降）
                    fade_out_length = fade_out_end - fade_out_start
                    linear_fade = np.linspace(0, 1, fade_out_length)
                    # 使用指数曲线：从background_max_volume快速降到min_volume
                    fade_out_samples = background_max_volume - (linear_fade ** fade_curve_power) * (background_max_volume - background_min_volume)
                    volume_envelope[fade_out_start:fade_out_end] = np.minimum(
                        volume_envelope[fade_out_start:fade_out_end], fade_out_samples
                    )
                    logger.debug(f"Applied exponential fade-out: {background_max_volume:.2f} -> {background_min_volume:.2f}")
                
                # 低音量阶段（中文语音播放期间）
                low_volume_start = fade_out_end
                low_volume_end = min(total_samples, fade_in_start)
                if low_volume_start < low_volume_end:
                    volume_envelope[low_volume_start:low_volume_end] = np.minimum(
                        volume_envelope[low_volume_start:low_volume_end], background_min_volume
                    )
                    logger.debug(f"Applied low volume: {background_min_volume:.2f} for {(low_volume_end - low_volume_start)/background.frame_rate:.2f}s")
                
                # 淡入阶段（在中文语音结束后）- 使用非线性曲线
                if fade_in_start < fade_in_end:
                    # 创建非线性淡入曲线（指数增长，更快上升）
                    fade_in_length = fade_in_end - fade_in_start
                    linear_fade = np.linspace(0, 1, fade_in_length)
                    # 使用指数曲线：从min_volume快速升到background_max_volume
                    fade_in_samples = background_min_volume + (linear_fade ** fade_curve_power) * (background_max_volume - background_min_volume)
                    volume_envelope[fade_in_start:fade_in_end] = fade_in_samples
                    logger.debug(f"Applied exponential fade-in: {background_min_volume:.2f} -> {background_max_volume:.2f}")
                
                # 记录要叠加的TTS音频（使用调整后的开始时间）
                overlays.append({
                    "audio_path": segment["audio_path"],
                    "start_time": int(start_time_ms),
                    "subtitle_index": i + 1
                })
                
                # 记录时间调整信息
                original_calculated_start = max(0, segment["subtitle"]["end"] * 1000 - segment["duration_ms"])
                if abs(start_time_ms - original_calculated_start) > 10:  # 如果调整超过10ms
                    logger.info(f"Adjusted TTS audio {i+1}: original start {original_calculated_start/1000:.2f}s -> adjusted start {start_time_ms/1000:.2f}s")
                
                logger.debug(f"Processed TTS audio {i+1}: end-aligned at {end_time_ms/1000:.2f}s, start: {start_time_ms/1000:.2f}s, duration: {segment['duration_ms']/1000:.2f}s")
            
            logger.info("Applying volume envelope to background audio...")
            
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
            
            logger.info("Overlaying TTS audio...")
            
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
                    
                    logger.debug(f"Overlayed TTS audio {overlay['subtitle_index']}")
                    
                except Exception as e:
                    logger.error(f"Failed to overlay TTS audio {overlay['subtitle_index']}: {str(e)}")
                    continue
            
            logger.info("Exporting final audio...")
            final_audio.export(output_path, format="wav")
            
            logger.info(f"Audio mixing completed, final duration: {final_audio.duration_seconds:.2f}s")
            return output_path
            
        except Exception as e:
            logger.error(f"Audio mixing failed: {str(e)}")
            raise 