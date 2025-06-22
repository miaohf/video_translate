"""
VTT字幕文件解析器和生成器
"""

import re
import os
import logging
from typing import List, Dict, Optional
from datetime import timedelta

logger = logging.getLogger(__name__)

class VTTParser:
    """VTT字幕文件解析器和生成器"""
    
    @staticmethod
    def parse_time(time_str: str) -> float:
        """
        解析VTT时间格式为秒数
        
        参数:
            time_str: VTT时间格式字符串 (HH:MM:SS.mmm 或 MM:SS.mmm)
            
        返回:
            秒数（浮点数）
        """
        try:
            # 移除可能的空格
            time_str = time_str.strip()
            
            # 支持两种格式：HH:MM:SS.mmm 和 MM:SS.mmm
            if time_str.count(':') == 2:
                # HH:MM:SS.mmm 格式
                hours, minutes, seconds = time_str.split(':')
                hours = int(hours)
                minutes = int(minutes)
                seconds = float(seconds)
            else:
                # MM:SS.mmm 格式
                hours = 0
                minutes, seconds = time_str.split(':')
                minutes = int(minutes)
                seconds = float(seconds)
            
            total_seconds = hours * 3600 + minutes * 60 + seconds
            return total_seconds
            
        except Exception as e:
            logger.error(f"解析时间格式失败: {time_str}, 错误: {str(e)}")
            return 0.0
    
    @staticmethod
    def format_time(seconds: float) -> str:
        """
        将秒数格式化为VTT时间格式
        
        参数:
            seconds: 秒数
            
        返回:
            VTT格式的时间字符串 (HH:MM:SS.mmm)
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = seconds % 60
        milliseconds = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{int(seconds):02d}.{milliseconds:03d}"
    
    @staticmethod
    def clean_text(text: str) -> str:
        """
        清理VTT文本，移除标签和特殊字符
        
        参数:
            text: 原始文本
            
        返回:
            清理后的文本
        """
        # 移除VTT标签 (如 <c.colorname>text</c>)
        text = re.sub(r'<[^>]+>', '', text)
        
        # 移除位置标签 (如 align:start position:0%)
        text = re.sub(r'\s*align:\w+\s*', '', text)
        text = re.sub(r'\s*position:\d+%\s*', '', text)
        text = re.sub(r'\s*line:\d+%\s*', '', text)
        text = re.sub(r'\s*size:\d+%\s*', '', text)
        
        # 移除多余的空白字符
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        return text
    
    @classmethod
    def parse_vtt_file(cls, vtt_file_path: str) -> List[Dict]:
        """
        解析VTT字幕文件
        
        参数:
            vtt_file_path: VTT文件路径
            
        返回:
            字幕列表，每个元素包含 start, end, text, speaker 字段
        """
        if not os.path.exists(vtt_file_path):
            logger.error(f"VTT文件不存在: {vtt_file_path}")
            return []
        
        logger.info(f"开始解析VTT文件: {vtt_file_path}")
        
        try:
            with open(vtt_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 分割成行
            lines = content.split('\n')
            
            subtitles = []
            current_subtitle = None
            
            # 跳过WEBVTT头部
            skip_header = True
            
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                
                # 跳过头部信息
                if skip_header:
                    if line.startswith('WEBVTT') or line.startswith('Kind:') or line.startswith('Language:'):
                        continue
                    elif line == '':
                        skip_header = False
                        continue
                    else:
                        skip_header = False
                
                # 空行表示字幕块结束
                if line == '':
                    if current_subtitle and current_subtitle.get('text'):
                        subtitles.append(current_subtitle)
                    current_subtitle = None
                    continue
                
                # 检查是否是时间行
                time_pattern = r'(\d{1,2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}\.\d{3})'
                time_match = re.match(time_pattern, line)
                
                if time_match:
                    # 开始新的字幕块
                    start_time_str = time_match.group(1)
                    end_time_str = time_match.group(2)
                    
                    current_subtitle = {
                        'start': cls.parse_time(start_time_str),
                        'end': cls.parse_time(end_time_str),
                        'text': '',
                        'speaker': 'Unknown'  # VTT文件通常不包含说话人信息
                    }
                    
                elif current_subtitle is not None:
                    # 这是字幕文本行
                    clean_text = cls.clean_text(line)
                    if clean_text:
                        # 检查是否包含说话人信息 [Speaker] text
                        speaker_match = re.match(r'^\[([^\]]+)\]\s*(.*)$', clean_text)
                        if speaker_match:
                            current_subtitle['speaker'] = speaker_match.group(1)
                            clean_text = speaker_match.group(2)
                        
                        if current_subtitle['text']:
                            current_subtitle['text'] += ' ' + clean_text
                        else:
                            current_subtitle['text'] = clean_text
            
            # 处理最后一个字幕
            if current_subtitle and current_subtitle.get('text'):
                subtitles.append(current_subtitle)
            
            logger.info(f"成功解析VTT文件，共 {len(subtitles)} 条字幕")
            
            # 验证字幕数据
            valid_subtitles = []
            for i, subtitle in enumerate(subtitles):
                if subtitle['start'] >= subtitle['end']:
                    logger.warning(f"第 {i+1} 条字幕时间无效: start={subtitle['start']}, end={subtitle['end']}")
                    continue
                
                if not subtitle['text'].strip():
                    logger.warning(f"第 {i+1} 条字幕文本为空")
                    continue
                
                valid_subtitles.append(subtitle)
            
            logger.info(f"有效字幕数量: {len(valid_subtitles)}")
            return valid_subtitles
            
        except Exception as e:
            logger.error(f"解析VTT文件失败: {str(e)}")
            return []
    
    @classmethod
    def save_vtt_file(cls, subtitles: List[Dict], vtt_file_path: str, language: str = 'en') -> None:
        """
        保存字幕为VTT文件
        
        参数:
            subtitles: 字幕列表
            vtt_file_path: 输出VTT文件路径
            language: 语言代码
        """
        try:
            logger.info(f"保存VTT文件: {vtt_file_path}")
            
            # 确保输出目录存在
            os.makedirs(os.path.dirname(vtt_file_path), exist_ok=True)
            
            with open(vtt_file_path, 'w', encoding='utf-8') as f:
                # 写入VTT头部
                f.write("WEBVTT\n")
                f.write(f"Kind: captions\n")
                f.write(f"Language: {language}\n\n")
                
                # 写入字幕内容
                for subtitle in subtitles:
                    # 写入时间戳
                    start_time = cls.format_time(subtitle["start"])
                    end_time = cls.format_time(subtitle["end"])
                    f.write(f"{start_time} --> {end_time}\n")
                    
                    # 写入文本（包含说话人信息）
                    speaker = subtitle.get("speaker", "Unknown")
                    text = subtitle["text"]
                    
                    if speaker and speaker != "Unknown":
                        f.write(f"[{speaker}] {text}\n\n")
                    else:
                        f.write(f"{text}\n\n")
            
            logger.info(f"VTT文件已保存: {vtt_file_path}")
            
        except Exception as e:
            logger.error(f"保存VTT文件失败: {str(e)}")
            raise
    
    @staticmethod
    def find_vtt_files(video_path: str) -> List[str]:
        """
        查找与视频文件相关的VTT字幕文件
        
        参数:
            video_path: 视频文件路径
            
        返回:
            找到的VTT文件路径列表
        """
        vtt_files = []
        
        # 获取视频文件信息
        video_dir = os.path.dirname(video_path)
        video_name = os.path.splitext(os.path.basename(video_path))[0]
        
        # 常见的VTT文件命名模式
        patterns = [
            f"{video_name}.vtt",
            f"{video_name}.en.vtt",
            f"{video_name}_en.vtt",
            f"{video_name}.english.vtt",
            f"{video_name}_english.vtt"
        ]
        
        # 在视频同目录下查找
        for pattern in patterns:
            vtt_path = os.path.join(video_dir, pattern)
            if os.path.exists(vtt_path):
                vtt_files.append(vtt_path)
                logger.info(f"找到VTT文件: {vtt_path}")
        
        # 在downloads目录下查找（根据实际项目结构）
        downloads_dir = "downloads"
        if os.path.exists(downloads_dir):
            for root, dirs, files in os.walk(downloads_dir):
                for file in files:
                    if file.endswith('.vtt') and video_name in file:
                        vtt_path = os.path.join(root, file)
                        if vtt_path not in vtt_files:
                            vtt_files.append(vtt_path)
                            logger.info(f"在downloads目录找到VTT文件: {vtt_path}")
        
        return vtt_files
    
    @staticmethod
    def convert_json_to_vtt_format(json_subtitles: List[Dict]) -> List[Dict]:
        """
        将JSON格式的字幕转换为VTT标准格式
        
        参数:
            json_subtitles: JSON格式的字幕列表
            
        返回:
            VTT标准格式的字幕列表
        """
        vtt_subtitles = []
        
        for subtitle in json_subtitles:
            vtt_subtitle = {
                'start': subtitle.get('start', 0.0),
                'end': subtitle.get('end', 0.0),
                'text': subtitle.get('text', ''),
                'speaker': subtitle.get('speaker', 'Unknown')
            }
            
            # 保留其他字段
            for key, value in subtitle.items():
                if key not in vtt_subtitle:
                    vtt_subtitle[key] = value
            
            vtt_subtitles.append(vtt_subtitle)
        
        return vtt_subtitles
    
    @staticmethod
    def merge_subtitles_for_tts(subtitles: List[Dict]) -> List[Dict]:
        """
        为TTS合并字幕，将断句的字幕合并成完整的句子
        
        参数:
            subtitles: 原始字幕列表
            
        返回:
            合并后适合TTS的字幕列表
        """
        if not subtitles:
            return []
        
        logger.info(f"开始为TTS合并字幕: {len(subtitles)} 条原始字幕")
        
        merged = []
        current_merged = None
        
        # TTS合并参数（更宽松的合并策略）
        max_merged_duration = 30.0   # 最大合并片段时长（秒）
        max_gap_duration = 2.0       # 最大间隔时长（秒）
        max_chars_per_merged = 300   # 每个合并片段最大字符数
        
        # 句子结束标记
        sentence_endings = ['.', '!', '?', '。', '！', '？']
        # 需要继续的标记
        continuation_marks = [',', ';', ':', '-', '，', '；', '：', '—', '、']
        
        for i, subtitle in enumerate(subtitles):
            text = subtitle.get("text", "").strip()
            if not text:
                continue
                
            current_start = subtitle["start"]
            current_end = subtitle["end"]
            
            if current_merged is None:
                # 开始新的合并片段
                current_merged = subtitle.copy()
                current_merged["text"] = text
            else:
                # 检查是否可以与当前合并片段合并
                gap_duration = current_start - current_merged["end"]
                merged_duration = current_end - current_merged["start"]
                current_text = current_merged["text"]
                merged_text_length = len(current_text + " " + text)
                
                # 判断是否应该合并
                should_merge = False
                
                # 1. 如果当前文本以延续标记结尾，应该合并
                if any(current_text.rstrip().endswith(mark) for mark in continuation_marks):
                    should_merge = True
                
                # 2. 如果当前文本不以句子结束标记结尾，且间隔较短，应该合并
                elif not any(current_text.rstrip().endswith(end) for end in sentence_endings):
                    if gap_duration <= max_gap_duration:
                        should_merge = True
                
                # 3. 如果新文本以小写字母开头，很可能是续句
                elif text and text[0].islower():
                    should_merge = True
                
                # 4. 检查字符长度和时长限制
                if should_merge:
                    if (merged_text_length > max_chars_per_merged or 
                        merged_duration > max_merged_duration):
                        should_merge = False
                
                if should_merge:
                    # 合并到当前片段
                    current_merged["end"] = current_end
                    
                    # 智能连接文本
                    if current_text and text:
                        # 如果当前文本以标点结尾
                        if current_text[-1] in '.!?。！？':
                            # 句子结束，但如果间隔很短且下一句首字母小写，可能需要连接
                            if gap_duration < 0.5 and text[0].islower():
                                current_merged["text"] = current_text + " " + text
                            else:
                                current_merged["text"] = current_text + " " + text
                        elif current_text[-1] in ',;:，；：':
                            # 逗号、分号等，直接连接
                            current_merged["text"] = current_text + " " + text
                        elif current_text[-1] == '-' or current_text[-1] == '—':
                            # 破折号，可能是中断，直接连接
                            current_merged["text"] = current_text + text
                        else:
                            # 其他情况，加空格连接
                            current_merged["text"] = current_text + " " + text
                    else:
                        current_merged["text"] = (current_text or "") + " " + (text or "")
                    
                    # 保留其他字段（保持第一个片段的信息）
                    for key, value in subtitle.items():
                        if key not in ["start", "end", "text"] and key not in current_merged:
                            current_merged[key] = value
                
                else:
                    # 不能合并，保存当前合并片段并开始新的
                    if current_merged["text"].strip():
                        # 清理文本格式
                        current_merged["text"] = " ".join(current_merged["text"].split())
                        merged.append(current_merged)
                    
                    current_merged = subtitle.copy()
                    current_merged["text"] = text
        
        # 添加最后一个合并片段
        if current_merged and current_merged["text"].strip():
            current_merged["text"] = " ".join(current_merged["text"].split())
            merged.append(current_merged)
        
        logger.info(f"TTS字幕合并完成: {len(subtitles)} -> {len(merged)} 条字幕")
        
        # 打印合并后的统计信息
        for i, seg in enumerate(merged):
            duration = seg["end"] - seg["start"]
            char_count = len(seg["text"])
            logger.debug(f"TTS合并 {i+1}: ({duration:.1f}s, {char_count} 字符): '{seg['text'][:100]}{'...' if char_count > 100 else ''}'")
        
        return merged 