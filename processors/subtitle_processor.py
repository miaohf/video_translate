import os
import json
import aiohttp
import logging
from typing import List, Dict, Optional
from datetime import datetime
from utils.common import get_file_hash
from pydub import AudioSegment

logger = logging.getLogger(__name__)

class SubtitleProcessor:
    def __init__(self, stt_server_url: str):
        """
        初始化字幕处理器
        
        参数:
            stt_server_url: 语音识别服务器地址
        """
        self.stt_server_url = stt_server_url
        self.temp_dir = "temp"
        os.makedirs(self.temp_dir, exist_ok=True)
        self._session = None
        
    async def get_session(self) -> aiohttp.ClientSession:
        """
        获取或创建 aiohttp session
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
        
    async def close(self):
        """
        关闭 aiohttp session
        """
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        
    async def process_speaker_diarization(self, audio_path: str, video_name: str, file_hash: str) -> Optional[List[Dict]]:
        """
        处理说话人识别
        
        参数:
            audio_path: 音频文件路径
            video_name: 视频文件名（不含扩展名）
            file_hash: 文件哈希值   
            
        返回:
            说话人片段列表
        """
        # 从音频路径中提取视频名称目录
        video_dir = os.path.dirname(audio_path)
        speaker_cache_file = os.path.join(video_dir, f"{file_hash}_speaker_segments.json")
        speaker_cache_file = os.path.join("temp", video_name, f"{file_hash}_speaker_segments.json")
        
        # 检查缓存
        if os.path.exists(speaker_cache_file):
            logger.info(f"使用缓存的说话人识别结果: {speaker_cache_file}")
            try:
                with open(speaker_cache_file, 'r', encoding='utf-8') as f:
                    speaker_segments = json.load(f)
                    # 合并连续的相同说话人片段
                    speaker_segments = self._merge_consecutive_speakers(speaker_segments)
                    # 提取参考音频
                    self._extract_reference_audio(audio_path, speaker_segments)
                    # 上传参考音频到 TTS 服务器
                    await self._upload_reference_audio(audio_path, speaker_segments)
                    return speaker_segments
            except Exception as e:
                logger.warning(f"读取说话人识别缓存失败: {str(e)}")
        
        # 进行说话人识别
        logger.info("开始说话人识别...")
        try:
            session = await self.get_session()
            with open(audio_path, 'rb') as f:
                async with session.post(
                    f"{self.stt_server_url}/diarize/",
                    data={'file': f},
                    timeout=600  # 10分钟超时
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.warning(f"说话人识别失败: {error_text}")
                        return None
                    
                    result = await response.json()
                    speaker_segments = result.get("segments", [])
                    # 合并连续的相同说话人片段
                    speaker_segments = self._merge_consecutive_speakers(speaker_segments)
                    # 提取参考音频
                    self._extract_reference_audio(audio_path, speaker_segments)
                    # 上传参考音频到 TTS 服务器
                    await self._upload_reference_audio(audio_path, speaker_segments)
                    logger.info(f"识别出 {len(speaker_segments)} 个说话人片段")
            
            # 保存到缓存
            try:
                with open(speaker_cache_file, 'w', encoding='utf-8') as f:
                    json.dump(speaker_segments, f, ensure_ascii=False, indent=2)
                logger.info(f"说话人识别结果已保存到: {speaker_cache_file}")
            except Exception as e:
                logger.warning(f"保存说话人识别结果失败: {str(e)}")
            
            return speaker_segments
            
        except Exception as e:
            logger.error(f"说话人识别过程出错: {str(e)}")
            return None
    
    def _merge_consecutive_speakers(self, speaker_segments: List[Dict]) -> List[Dict]:
        """
        合并连续的相同说话人片段，并为每个说话人选择参考音频
        
        参数:
            speaker_segments: 原始说话人片段列表
            
        返回:
            合并后的说话人片段列表
        """
        if not speaker_segments:
            return []
            
        merged_segments = []
        current_segment = speaker_segments[0].copy()
        
        # 用于存储每个说话人的参考音频信息
        speaker_references = {}
        # 用于存储每个说话人的所有片段
        speaker_segments_dict = {}
        
        for next_segment in speaker_segments[1:]:
            # 如果当前片段和下一个片段的说话人相同，且时间连续
            if (next_segment["speaker"] == current_segment["speaker"] and 
                next_segment["start"] - current_segment["end"] < 1):  # 允许1秒的间隔
                # 更新当前片段的结束时间
                current_segment["end"] = next_segment["end"]
            else:
                # 如果说话人不同或时间不连续，保存当前片段并开始新片段
                merged_segments.append(current_segment)
                
                # 收集当前说话人的片段
                speaker = current_segment["speaker"]
                if speaker not in speaker_segments_dict:
                    speaker_segments_dict[speaker] = []
                speaker_segments_dict[speaker].append(current_segment)
                
                current_segment = next_segment.copy()
        
        # 添加最后一个片段
        merged_segments.append(current_segment)
        
        # 收集最后一个说话人的片段
        speaker = current_segment["speaker"]
        if speaker not in speaker_segments_dict:
            speaker_segments_dict[speaker] = []
        speaker_segments_dict[speaker].append(current_segment)
        
        # 记录合并前后的片段数量
        if len(merged_segments) != len(speaker_segments):
            logger.info(f"合并说话人片段: {len(speaker_segments)} -> {len(merged_segments)}")
        
        # 为每个说话人选择参考音频
        for speaker, segments in speaker_segments_dict.items():
            # 按时长排序
            segments.sort(key=lambda x: x["end"] - x["start"], reverse=True)
            
            # 选择最长的且不超过60秒的片段
            selected_segment = None
            for segment in segments:
                duration = segment["end"] - segment["start"]
                if duration <= 60:
                    selected_segment = segment
                    break
            
            # 如果没有找到合适的片段，使用最长的片段并截取前60秒
            if not selected_segment:
                selected_segment = segments[0]
                selected_segment = {
                    "start": selected_segment["start"],
                    "end": selected_segment["start"] + 60,
                    "speaker": speaker
                }
            
            # 保存参考音频信息
            reference_path = os.path.join("temp", "my_input_video", f"my_input_video_{speaker}.mp3")
            os.makedirs(os.path.dirname(reference_path), exist_ok=True)
            
            speaker_references[speaker] = {
                "path": reference_path,
                "start": selected_segment["start"],
                "end": selected_segment["end"]
            }
            
            # 将参考音频信息添加到对应的片段中
            for segment in merged_segments:
                if segment["speaker"] == speaker:
                    segment["reference_audio"] = speaker_references[speaker]
                    break
            
        return merged_segments
    
    async def _upload_reference_audio(self, audio_path: str, speaker_segments: List[Dict]) -> None:
        """
        上传参考音频文件到 TTS 服务器
        
        参数:
            audio_path: 原始音频文件路径
            speaker_segments: 说话人片段列表
        """
        try:
            # 加载原始音频
            audio = AudioSegment.from_file(audio_path)
            
            # 获取 TTS 服务器地址
            tts_server_url = os.getenv("TTS_SERVER_URL", "http://localhost:8000")
            
            # 为每个说话人提取并上传参考音频
            for segment in speaker_segments:
                if "reference_audio" in segment:
                    ref = segment["reference_audio"]
                    speaker = segment["speaker"]
                    
                    # 提取音频片段（时间单位：毫秒）
                    start_ms = int(ref["start"] * 1000)
                    end_ms = int(ref["end"] * 1000)
                    audio_segment = audio[start_ms:end_ms]
                    
                    # 保存为临时文件
                    temp_path = os.path.join("temp", f"{speaker}_temp.mp3")
                    audio_segment.export(temp_path, format="mp3", bitrate="192k")
                    
                    try:
                        # 上传到 TTS 服务器
                        session = await self.get_session()
                        with open(temp_path, "rb") as f:
                            data = aiohttp.FormData()
                            data.add_field('file',
                                         f,
                                         filename=f"my_input_video-{speaker}.mp3",
                                         content_type="audio/mp3")
                            async with session.post(f"{tts_server_url}/upload_audio", data=data) as response:
                                if response.status != 200:
                                    error_text = await response.text()
                                    logger.error(f"上传参考音频失败: {error_text}")
                                else:
                                    result = await response.json()
                                    logger.info(f"成功上传说话人 {speaker} 的参考音频: {result['file_path']}")
                    
                    finally:
                        # 清理临时文件
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                    
        except Exception as e:
            logger.error(f"上传参考音频失败: {str(e)}")
            raise
    
    def _extract_reference_audio(self, audio_path: str, speaker_segments: List[Dict]) -> None:
        """
        从原始音频中提取每个说话人的参考音频片段
        
        参数:
            audio_path: 原始音频文件路径
            speaker_segments: 说话人片段列表
        """
        try:
            # 加载原始音频
            audio = AudioSegment.from_file(audio_path)
            
            # 为每个说话人提取参考音频
            for segment in speaker_segments:
                if "reference_audio" in segment:
                    ref = segment["reference_audio"]
                    # 提取音频片段（时间单位：毫秒）
                    start_ms = int(ref["start"] * 1000)
                    end_ms = int(ref["end"] * 1000)
                    audio_segment = audio[start_ms:end_ms]
                    
                    # 保存参考音频为MP3格式
                    audio_segment.export(ref["path"], format="mp3", bitrate="192k")
                    logger.info(f"已保存说话人 {segment['speaker']} 的参考音频到: {ref['path']}")
                    
        except Exception as e:
            logger.error(f"提取参考音频失败: {str(e)}")
            raise
    
    def merge_speaker_info(self, segments: List[Dict], speaker_segments: Optional[List[Dict]]) -> List[Dict]:
        """
        合并说话人信息到字幕片段
        
        参数:
            segments: 字幕片段列表
            speaker_segments: 说话人片段列表
            
        返回:
            合并后的字幕片段列表
        """
        if not speaker_segments:
            logger.info("没有说话人信息，使用默认说话人")
            for segment in segments:
                segment["speaker"] = "Unknown"
            return segments
        
        logger.info("合并说话人信息...")
        for segment in segments:
            segment_start = segment["start"]
            segment_end = segment["end"]
            
            # 查找重叠的说话人片段
            speaker_found = False
            max_overlap = 0
            best_speaker = "Unknown"
            
            for speaker_segment in speaker_segments:
                speaker_start = speaker_segment["start"]
                speaker_end = speaker_segment["end"]
                
                # 计算重叠时间
                overlap_start = max(segment_start, speaker_start)
                overlap_end = min(segment_end, speaker_end)
                overlap_duration = max(0, overlap_end - overlap_start)
                
                # 如果重叠时间大于当前最大重叠时间，更新说话人
                if overlap_duration > max_overlap:
                    max_overlap = overlap_duration
                    best_speaker = speaker_segment["speaker"]
                    speaker_found = True
            
            # 设置说话人信息
            segment["speaker"] = best_speaker if speaker_found else "Unknown"
            
            # 记录日志
            if speaker_found:
                logger.debug(f"为片段 {segment_start:.2f}-{segment_end:.2f} 匹配说话人 {best_speaker}")
            else:
                logger.debug(f"未找到片段 {segment_start:.2f}-{segment_end:.2f} 的说话人信息")
        
        return segments
    
    async def get_subtitles(self, audio_path: str, video_name: str) -> List[Dict]:
        """
        获取音频的字幕
        
        参数:
            audio_path: 音频文件路径
            video_name: 视频文件名（不含扩展名）
            
        返回:
            字幕列表
        """
        try:
            # 计算文件哈希值
            file_hash = get_file_hash(video_name)
            
            # 音频路径格式：temp/{video_name}/{file_hash}_audio.wav
            # 缓存文件格式：temp/{video_name}/{file_hash}_subtitles.json
            cache_file = os.path.join("temp", video_name, f"{file_hash}_subtitles.json")
            english_srt_file = os.path.join("temp", video_name, f"{file_hash}_subtitles.srt")           
            
            # 检查字幕缓存
            if os.path.exists(cache_file):
                logger.info(f"使用缓存的字幕文件: {cache_file}")
                with open(cache_file, 'r', encoding='utf-8') as f:
                    subtitles = json.load(f)
                    # 如果存在缓存但不存在 SRT 文件，则生成 SRT 文件
                    if not os.path.exists(english_srt_file):
                        self.save_subtitles_to_srt(subtitles, english_srt_file)
                return subtitles
            
            # 进行说话人识别
            speaker_segments = await self.process_speaker_diarization(audio_path, video_name, file_hash)
            
            # 进行音频转录
            logger.info("开始音频转录...")
            session = await self.get_session()
            with open(audio_path, 'rb') as f:
                async with session.post(
                            f"{self.stt_server_url}/transcribe/",
                            data={'file': f},
                            timeout=600  # 10分钟超时
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise Exception(f"转录失败: {error_text}")
                        
                    result = await response.json()
                    segments = result.get("segments", [])
            
            # 合并说话人信息
            segments = self.merge_speaker_info(segments, speaker_segments)

            logger.info(segments[0])
            
            # 合并连续的相同说话人片段, 避免断句
            segments = self._merge_consecutive_subtitles(segments)
            logger.info(segments[0])
            
            # 保存到缓存
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(segments, f, ensure_ascii=False, indent=2)
            logger.info(f"字幕已保存到: {cache_file}")
            
            # 生成 SRT 文件
            self.save_subtitles_to_srt(segments, english_srt_file)
            
            return segments
            
        except Exception as e:
            logger.error(f"获取字幕失败: {str(e)}")
            raise
        finally:
            # 确保关闭session
            await self.close()
            
    def _is_sentence_end(self, text: str) -> bool:
        """
        检查文本是否以句子结束标点符号结尾
        """
        sentence_end_punctuations = {'.', '。', '!', '！', '?', '？', ';', '；'}
        return text.strip()[-1] in sentence_end_punctuations if text.strip() else False

    def _merge_consecutive_subtitles(self, segments: List[Dict]) -> List[Dict]:
        """
        合并连续的相同说话人字幕片段，根据标点符号判断是否合并
        """
        if not segments:
            return []
        merged_segments = []
        current_segment = segments[0].copy()
        for next_segment in segments[1:]:
            if (next_segment["speaker"] == current_segment["speaker"] and 
                next_segment["start"] - current_segment["end"] < 0.5):
                if not self._is_sentence_end(current_segment["text"]):
                    current_segment["end"] = next_segment["end"]
                    current_segment["text"] = current_segment["text"] + " " + next_segment["text"]
                else:
                    merged_segments.append(current_segment)
                    current_segment = next_segment.copy()
            else:
                merged_segments.append(current_segment)
                current_segment = next_segment.copy()
        merged_segments.append(current_segment)
        if len(merged_segments) != len(segments):
            logger.info(f"合并字幕片段: {len(segments)} -> {len(merged_segments)}")
        return merged_segments
    
    def save_subtitles_to_srt(self, subtitles: List[Dict], output_path: str):
        """
        将字幕保存为 SRT 格式
        
        参数:
            subtitles: 字幕列表
            output_path: 输出文件路径
        """
        try:
            logger.info(f"保存 SRT 文件: {output_path}")
            with open(output_path, 'w', encoding='utf-8') as f:
                for i, subtitle in enumerate(subtitles, 1):
                    # 写入序号
                    f.write(f"{i}\n")
                    
                    # 写入时间戳
                    start_time = self.format_time(subtitle["start"])
                    end_time = self.format_time(subtitle["end"])
                    f.write(f"{start_time} --> {end_time}\n")
                    
                    # 写入说话人信息和文本
                    speaker = subtitle.get("speaker", "Unknown")
                    text = subtitle["text"]
                    f.write(f"[{speaker}] {text}\n\n")
            
            logger.info(f"SRT 文件已保存: {output_path}")
            
        except Exception as e:
            logger.error(f"保存 SRT 文件失败: {str(e)}")
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