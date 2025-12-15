import os
import json
import aiohttp
import logging
from typing import List, Dict, Optional
from datetime import datetime
from utils.common import get_file_hash
from utils.vtt_parser import VTTParser

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
        speaker_cache_file = os.path.join("temp", video_name, f"{file_hash}_speaker_segments.json")
        logger.info(f"speaker_cache_file: {speaker_cache_file}")
        
        # 检查缓存
        if os.path.exists(speaker_cache_file):
            logger.info(f"使用缓存的说话人识别结果: {speaker_cache_file}")
            try:
                with open(speaker_cache_file, 'r', encoding='utf-8') as f:
                    speaker_segments = json.load(f)
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
            best_audio_path = None
            
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
                    best_audio_path = speaker_segment.get("audio_path")
                    speaker_found = True
            
            # 设置说话人信息
            segment["speaker"] = best_speaker if speaker_found else "Unknown"
            if best_audio_path:
                segment["reference_audio"] = best_audio_path
            
            # 记录日志
            if speaker_found:
                logger.debug(f"为片段 {segment_start:.2f}-{segment_end:.2f} 匹配说话人 {best_speaker}")
            else:
                logger.debug(f"未找到片段 {segment_start:.2f}-{segment_end:.2f} 的说话人信息")
        
        return segments
    
    def merge_speaker_segments(self, segments: List[Dict]) -> List[Dict]:
        """
        合并同一说话人的连续字幕片段，处理断句问题
        
        Args:
            segments: 包含speaker信息的字幕片段列表
            
        Returns:
            合并后的字幕片段列表
        """
        if not segments:
            return []
        
        logger.info(f"开始合并说话人片段: {len(segments)} 个输入片段")
        
        merged = []
        current_merged = None
        
        # 合并参数
        max_merged_duration = 30.0   # 最大合并片段时长（秒）
        max_gap_duration = 0.5       # 最大间隔时长（秒）
        max_chars_per_merged = 200   # 每个合并片段最大字符数
        
        for segment in segments:
            if not segment.get("text", "").strip():
                continue
                
            current_speaker = segment.get("speaker", "UNKNOWN")
            current_text = segment["text"].strip()
            current_start = segment["start"]
            current_end = segment["end"]
            
            if current_merged is None:
                # 开始新的合并片段
                current_merged = {
                    "start": current_start,
                    "end": current_end,
                    "text": current_text,
                    "speaker": current_speaker
                }
                # 保留其他字段
                for key, value in segment.items():
                    if key not in current_merged:
                        current_merged[key] = value
            else:
                # 检查是否可以与当前合并片段合并
                same_speaker = current_merged["speaker"] == current_speaker
                gap_duration = current_start - current_merged["end"]
                merged_duration = current_end - current_merged["start"]
                merged_text_length = len(current_merged["text"] + " " + current_text)
                
                # 检查是否为断句情况
                previous_text = current_merged["text"].strip()
                is_incomplete_sentence = self._is_incomplete_sentence(previous_text)
                
                # 合并条件：同一说话人 + (正常合并条件 OR 断句合并)
                should_merge = same_speaker and (
                    # 正常合并条件
                    (gap_duration <= max_gap_duration and
                     merged_duration <= max_merged_duration and
                     merged_text_length <= max_chars_per_merged) or
                    # 断句合并条件：前一句没有结束标点符号
                    (is_incomplete_sentence and gap_duration <= 3.0)  # 断句允许更大的间隔
                )
                
                if should_merge:
                    # 合并到当前片段
                    current_merged["end"] = current_end
                    # 智能连接文本
                    merged_text = current_merged["text"]
                    if merged_text and current_text:
                        # 检查是否为断句合并
                        if is_incomplete_sentence:
                            # 断句合并，直接连接或添加适当连接词
                            if merged_text.endswith(('，', '、', '和', '或', '但', '而', '且')):
                                current_merged["text"] = merged_text + current_text
                            else:
                                current_merged["text"] = merged_text + current_text
                        # 检查是否需要添加标点
                        elif merged_text[-1] in '.!?。！？':
                            current_merged["text"] = merged_text + " " + current_text
                        elif merged_text[-1] in ',;:，；：':
                            current_merged["text"] = merged_text + " " + current_text
                        elif not merged_text.endswith(' ') and current_text[0].isupper():
                            # 如果下一句开头是大写字母，可能是新句子
                            if gap_duration > 1.0:  # 如果间隔较长，添加句号
                                current_merged["text"] = merged_text + ". " + current_text
                            else:
                                current_merged["text"] = merged_text + " " + current_text
                        else:
                            current_merged["text"] = merged_text + " " + current_text
                    else:
                        current_merged["text"] = merged_text + " " + current_text
                else:
                    # 不能合并，保存当前合并片段并开始新的
                    merged.append(current_merged)
                    current_merged = {
                        "start": current_start,
                        "end": current_end,
                        "text": current_text,
                        "speaker": current_speaker
                    }
                    # 保留其他字段
                    for key, value in segment.items():
                        if key not in current_merged:
                            current_merged[key] = value
        
        # 添加最后一个合并片段
        if current_merged:
            merged.append(current_merged)
        
        logger.info(f"完成说话人片段合并: {len(segments)} -> {len(merged)} 个片段")
        
        # 打印合并统计
        for i, seg in enumerate(merged):
            duration = seg["end"] - seg["start"]
            char_count = len(seg["text"])
            logger.debug(f"合并片段 {i+1}: {seg['speaker']} ({duration:.1f}s, {char_count} 字符): '{seg['text'][:80]}{'...' if char_count > 80 else ''}'")
        
        return merged

    def _is_incomplete_sentence(self, text: str) -> bool:
        """
        判断句子是否为不完整的句子（用于识别断句）
        
        Args:
            text: 文本内容
            
        Returns:
            是否为不完整句子
        """
        if not text:
            return False
            
        text = text.strip()
        
        # 检查是否以标点符号结尾
        ending_punctuation = '.!?。！？'
        if text[-1] in ending_punctuation:
            return False
            
        # 检查是否以逗号、分号等中间标点结尾（可能是断句）
        middle_punctuation = ',;:，；：'
        if text[-1] in middle_punctuation:
            return True
            
        # 检查是否以连接词结尾（明显的断句）
        incomplete_endings = [
            'and', 'or', 'but', 'because', 'so', 'that', 'which', 'who', 'when', 'where', 'how',
            '和', '或', '但', '因为', '所以', '那', '这', '当', '在', '如何', '什么', '哪里',
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'has', 'have', 'had', 'will', 'would',
            '是', '有', '会', '将', '可以', '能够', '应该', '必须', '正在', '已经'
        ]
        
        # 检查最后几个词
        words = text.split()
        if words:
            last_word = words[-1].lower().strip('.,;:!?，。；：！？')
            if last_word in incomplete_endings:
                return True
                
        # 检查是否以数字或不完整的短语结尾
        if len(words) <= 2:  # 很短的片段可能是断句
            return True
            
        return False

    async def get_subtitles(self, audio_path: str, video_name: str, video_path: str = None, use_vocal_separation: bool = True) -> List[Dict]:
        """
        获取音频的字幕
        
        参数:
            audio_path: 音频文件路径
            video_name: 视频文件名（不含扩展名）
            video_path: 视频文件路径（用于查找VTT文件）
            use_vocal_separation: 是否使用人声分离
            
        返回:
            字幕列表
        """
        logger.info(f"get_subtitles: {audio_path}, {video_name}, {video_path}, {use_vocal_separation}")
        try:
            # 计算文件哈希值
            file_hash = get_file_hash(video_name)
            
            # 检查是否存在已有的字幕文件
            if video_path:
                existing_subtitles = self.check_existing_subtitles(video_path, video_name, file_hash)
                if existing_subtitles:
                    # 对字幕进行说话人合并处理（包含断句处理）
                    logger.info("📝 对已有字幕进行说话人合并和断句处理...")
                    subtitles = self.merge_speaker_segments(existing_subtitles)
                    
                    # 保存为VTT格式
                    cache_vtt_file = os.path.join("temp", video_name, f"{file_hash}_subtitles.vtt")
                    VTTParser.save_vtt_file(subtitles, cache_vtt_file, 'en')
                    logger.info(f"✅ 处理后的字幕已保存为VTT格式: {cache_vtt_file}")
                    
                    return subtitles
            
            # 如果没有找到已有字幕，进行转录
            logger.info("🎤 开始音频转录...")
            
            # 决定使用的音频文件
            processing_audio_path = audio_path
            if use_vocal_separation:
                try:
                    # 先进行人声分离
                    logger.info("🎵 开始人声分离...")
                    from processors.audio_processor import AudioProcessor
                    audio_processor = AudioProcessor()
                    vocals_path, background_path = audio_processor.separate_vocals_and_background(audio_path, video_name)
                    
                    # 使用分离后的人声进行后续处理
                    processing_audio_path = vocals_path
                    logger.info(f"✅ 使用分离后的人声进行识别: {vocals_path}")
                    
                except Exception as e:
                    logger.warning(f"⚠️ 人声分离失败，使用原始音频: {str(e)}")
                    processing_audio_path = audio_path
            
            # 对人声进行说话人识别
            logger.info("👤 开始说话人识别...")
            speaker_segments = await self.process_speaker_diarization(processing_audio_path, video_name, file_hash)
            
            # 对人声进行音频转录
            logger.info("📝 开始音频转录...")
            session = await self.get_session()
            with open(processing_audio_path, 'rb') as f:
                async with session.post(
                            f"{self.stt_server_url}/transcribe/",
                            data={'file': f},
                            timeout=1200  # 10分钟超时
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise Exception(f"转录失败: {error_text}")
                        
                    result = await response.json()
                    segments = result.get("segments", [])
            
            # 合并说话人信息
            segments = self.merge_speaker_info(segments, speaker_segments)
            
            # 对字幕进行说话人合并处理（包含断句处理）
            logger.info("📝 对转录字幕进行说话人合并和断句处理...")
            segments = self.merge_speaker_segments(segments)
            
            # 保存为VTT格式
            cache_vtt_file = os.path.join("temp", video_name, f"{file_hash}_subtitles.vtt")
            VTTParser.save_vtt_file(segments, cache_vtt_file, 'en')
            logger.info(f"✅ 处理后的字幕已保存为VTT格式: {cache_vtt_file}")
            
            # 兼容性：同时保存JSON格式（可选）
            cache_json_file = os.path.join("temp", video_name, f"{file_hash}_subtitles.json")
            with open(cache_json_file, 'w', encoding='utf-8') as f:
                json.dump(segments, f, ensure_ascii=False, indent=2)
            logger.info(f"📄 处理后的字幕已保存为JSON格式: {cache_json_file}")
            
            return segments
            
        except Exception as e:
            logger.error(f"获取字幕失败: {str(e)}")
            raise
        finally:
            # 确保关闭session
            await self.close()
    
    def save_subtitles_to_vtt(self, subtitles: List[Dict], output_path: str, language: str = 'en'):
        """
        将字幕保存为 VTT 格式
        
        参数:
            subtitles: 字幕列表
            output_path: 输出文件路径
            language: 语言代码
        """
        try:
            logger.info(f"保存 VTT 文件: {output_path}")
            VTTParser.save_vtt_file(subtitles, output_path, language)
            logger.info(f"VTT 文件已保存: {output_path}")
            
        except Exception as e:
            logger.error(f"保存 VTT 文件失败: {str(e)}")
            raise
            
    def save_subtitles_to_json(self, subtitles: List[Dict], output_path: str):
        """
        将字幕保存为 JSON 格式
        
        参数:
            subtitles: 字幕列表
            output_path: 输出文件路径
        """
        try:
            logger.info(f"保存 JSON 文件: {output_path}")
            # 确保输出目录存在
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(subtitles, f, ensure_ascii=False, indent=2)
            
            logger.info(f"JSON 文件已保存: {output_path}")
            
        except Exception as e:
            logger.error(f"保存 JSON 文件失败: {str(e)}")
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

    def check_existing_subtitles(self, video_path: str, video_name: str, file_hash: str) -> Optional[List[Dict]]:
        """
        检查是否存在已有的字幕文件
        
        参数:
            video_path: 视频文件路径
            video_name: 视频文件名（不含扩展名）
            file_hash: 文件哈希值
            
        返回:
            字幕列表或None
        """
        try:
            # 检查缓存的字幕文件
            cache_json_file = os.path.join("temp", video_name, f"{file_hash}_subtitles.json")
            if os.path.exists(cache_json_file):
                logger.info(f"发现缓存的字幕文件: {cache_json_file}")
                with open(cache_json_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            
            # 检查缓存的VTT文件
            cache_vtt_file = os.path.join("temp", video_name, f"{file_hash}_subtitles.vtt")
            if os.path.exists(cache_vtt_file):
                logger.info(f"发现缓存的VTT字幕文件: {cache_vtt_file}")
                subtitles = VTTParser.parse_vtt_file(cache_vtt_file)
                if subtitles:
                    return subtitles
            
            # 在视频文件同目录下查找VTT文件，并智能选择最佳字幕文件
            if video_path:
                vtt_files = VTTParser.find_vtt_files(video_path)
                if vtt_files:
                    # 使用智能选择逻辑选择最佳字幕文件
                    best_vtt_file = VTTParser.select_best_subtitle_file(vtt_files)
                    if best_vtt_file:
                        logger.info(f"🎯 智能选择字幕文件: {best_vtt_file}")
                        subtitles = VTTParser.parse_vtt_file(best_vtt_file)
                    if subtitles:
                        return subtitles
                    else:
                        logger.warning("⚠️ 未找到合适的字幕文件")
            
            return None
            
        except Exception as e:
            logger.error(f"检查现有字幕文件失败: {str(e)}")
            return None 