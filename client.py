import os
import argparse
import requests
import tempfile
import soundfile as sf
import numpy as np
from pydub import AudioSegment
import librosa
from typing import List, Dict, Optional
import json
import logging
from tqdm import tqdm
import subprocess
from datetime import datetime
import time
import aiohttp
import asyncio
import platform

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("video-translation-client")

class TranslationService:
    def __init__(self, model: str = "gemma3:12b"):
        self.ollama_api_url = "http://localhost:11434/api/generate"
        self.model = model
        
    def translate(self, text: str, source_lang: str = "en", target_lang: str = "zh") -> str:
        """直接调用 Ollama 进行翻译"""
        try:
            response = requests.post(
                self.ollama_api_url,
                json={
                    "model": self.model,
                    "prompt": f"直接输出以下{source_lang}的{target_lang}翻译：{text}",
                    "options": {
                        "temperature": 0.2
                    },
                    "stream": False
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                return result["response"].strip()
            else:
                raise Exception(f"翻译请求失败: {response.text}")
                
        except Exception as e:
            logger.error(f"翻译出错: {str(e)}")
            raise

    async def translate_batch(self, texts: List[str], source_lang: str = "en", target_lang: str = "zh", batch_size: int = 5) -> List[str]:
        """异步批量翻译文本"""
        async def translate_single(text: str, index: int) -> tuple[int, str]:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        self.ollama_api_url,
                        json={
                            "model": self.model,
                            "prompt": f"直接输出以下{source_lang}的{target_lang}翻译：{text}",
                            "options": {
                                "temperature": 0.2
                            },
                            "stream": False
                        }
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            return index, result["response"].strip()
                        else:
                            raise Exception(f"翻译请求失败: {await response.text()}")
            except Exception as e:
                logger.error(f"翻译出错: {str(e)}")
                raise

        # 将文本分成批次
        batches = [texts[i:i + batch_size] for i in range(0, len(texts), batch_size)]
        results = [""] * len(texts)  # 预分配结果列表
        
        # 创建进度条
        pbar = tqdm(total=len(texts), desc="翻译进度")
        
        for batch_start_idx, batch in enumerate(batches):
            # 并发处理每个批次
            tasks = [translate_single(text, batch_start_idx * batch_size + i) for i, text in enumerate(batch)]
            batch_results = await asyncio.gather(*tasks)
            
            # 更新结果并显示
            for idx, translated_text in batch_results:
                results[idx] = translated_text
                # 显示翻译结果
                logger.info(f"第 {idx + 1} 条: {texts[idx]} -> {translated_text}")
            
            # 更新进度条
            pbar.update(len(batch))
            
        pbar.close()
        return results

class VideoTranslationClient:
    def __init__(self, stt_server_url: str, tts_server_url: str, speaker: str = None):
        self.stt_server_url = stt_server_url
        self.tts_server_url = tts_server_url
        self.speaker = speaker
        self.translation_service = TranslationService()
        
        # 打印环境信息
        logger.info(f"系统信息：")
        logger.info(f"- 操作系统: {platform.system()} {platform.release()}")
        logger.info(f"- Python 版本: {platform.python_version()}")
        
        # 确保temp目录存在
        os.makedirs("temp", exist_ok=True)
        
    def get_file_hash(self, text: str, length: int = 20) -> str:
        """生成文本的短哈希值"""
        import hashlib
        return hashlib.md5(text.encode()).hexdigest()[:length]
        
    def extract_audio(self, video_path: str) -> str:
        """从视频中提取音频"""
        logger.info(f"正在从视频中提取音频: {video_path}")
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        file_hash = self.get_file_hash(base_name)
        audio_path = os.path.join("temp", f"{file_hash}_original.wav")
        
        # 检查是否已存在音频文件
        if os.path.exists(audio_path):
            logger.info(f"发现已存在的音频文件: {audio_path}")
            return audio_path
            
        audio = AudioSegment.from_file(video_path)
        audio.export(audio_path, format="wav")
        return audio_path
    
    def get_subtitles(self, audio_path: str) -> List[Dict]:
        """从服务器获取字幕"""
        logger.info("正在获取字幕...")
        try:
            # 获取基础文件名和哈希值
            base_name = os.path.splitext(os.path.basename(audio_path))[0]
            subtitle_path = os.path.join("temp", f"{base_name}_subtitles.srt")
            
            # 检查是否已存在字幕文件
            if os.path.exists(subtitle_path):
                logger.info(f"发现已存在的字幕文件: {subtitle_path}")
                # 从已存在的字幕文件中读取
                subtitles = []
                with open(subtitle_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    blocks = content.strip().split('\n\n')
                    for block in blocks:
                        lines = block.split('\n')
                        if len(lines) >= 3:
                            index = int(lines[0])
                            time_range = lines[1]
                            start_time, end_time = time_range.split(' --> ')
                            start_seconds = self.parse_time(start_time)
                            end_seconds = self.parse_time(end_time)
                            text = lines[2]
                            speaker = None
                            if text.startswith('[') and ']' in text:
                                speaker_end = text.find(']')
                                speaker = text[1:speaker_end]
                                text = text[speaker_end + 1:].strip()
                            subtitles.append({
                                "index": index,
                                "text": text,
                                "start": start_seconds,
                                "end": end_seconds,
                                "speaker": speaker
                            })
                return subtitles
            
            # 设置请求超时时间
            timeout = (30, 300)  # (连接超时, 读取超时)
            
            # 显示文件大小
            file_size = os.path.getsize(audio_path) / (1024 * 1024)  # 转换为MB
            logger.info(f"音频文件大小: {file_size:.2f}MB")
            
            # 检查文件是否存在
            if not os.path.exists(audio_path):
                raise FileNotFoundError(f"音频文件不存在: {audio_path}")
            
            # 检查文件是否可读
            if not os.access(audio_path, os.R_OK):
                raise PermissionError(f"无法读取音频文件: {audio_path}")
            
            # 检查服务器是否可访问
            try:
                response = requests.head(f"{self.stt_server_url}/transcribe/", timeout=5)
                if response.status_code != 405:  # 405 是正常的，因为我们期望这个端点只接受 POST
                    raise ConnectionError(f"STT服务器不可用: {response.status_code}")
            except requests.RequestException as e:
                raise ConnectionError(f"无法连接到STT服务器: {str(e)}")
            
            logger.info(f"正在连接STT服务器: {self.stt_server_url}")
            
            # 使用 with 语句确保文件正确关闭
            with open(audio_path, 'rb') as f:
                files = {'file': (os.path.basename(audio_path), f, 'audio/wav')}
                logger.info("正在发送音频文件到STT服务器...")
                
                # 发送请求并显示进度
                try:
                    response = requests.post(
                        f"{self.stt_server_url}/transcribe/",
                        files=files,
                        timeout=timeout,
                        headers={'Accept': 'application/json'}
                    )
                    
                    # 检查响应状态
                    response.raise_for_status()
                    
                    # 解析响应
                    result = response.json()
                    subtitles = result.get("subtitles", [])
                    
                    if not subtitles:
                        raise ValueError("服务器返回的字幕列表为空")
                    
                    # 保存原始字幕文本为 SRT 格式
                    logger.info(f"正在保存字幕文件: {subtitle_path}")
                    with open(subtitle_path, "w", encoding="utf-8") as f:
                        for i, subtitle in enumerate(subtitles, 1):
                            f.write(f"{i}\n")
                            start_time = self.format_time(subtitle["start"])
                            end_time = self.format_time(subtitle["end"])
                            f.write(f"{start_time} --> {end_time}\n")
                            speaker_text = f"[{subtitle['speaker']}] " if subtitle.get('speaker') else ""
                            f.write(f"{speaker_text}{subtitle['text']}\n\n")
                    
                    logger.info(f"已获取 {len(subtitles)} 条字幕")
                    return subtitles
                    
                except requests.Timeout as e:
                    if "timeout" in str(e).lower():
                        raise TimeoutError("获取字幕超时，请检查STT服务器状态或尝试使用较短的音频文件")
                    else:
                        raise TimeoutError(f"请求超时: {str(e)}")
                except requests.HTTPError as e:
                    if e.response.status_code == 413:
                        raise ValueError("音频文件太大，请确保文件小于100MB")
                    elif e.response.status_code == 408:
                        raise TimeoutError("服务器处理超时，请尝试使用较短的音频文件")
                    else:
                        raise Exception(f"服务器错误: {e.response.status_code} - {e.response.text}")
                except requests.RequestException as e:
                    raise ConnectionError(f"请求失败: {str(e)}")
                except json.JSONDecodeError:
                    raise ValueError("服务器返回的数据格式错误")
                except Exception as e:
                    raise Exception(f"处理响应时出错: {str(e)}")
        except Exception as e:
            logger.error(f"获取字幕时出错: {str(e)}")
            raise
    
    async def translate_subtitles(self, subtitles: List[Dict], video_path: str = None) -> List[Dict]:
        """异步翻译字幕"""
        logger.info("正在翻译字幕...")
        translated_subtitles = []
        
        # 获取基础文件名和哈希值
        base_name = os.path.splitext(os.path.basename(video_path))[0] if video_path else "unknown"
        file_hash = self.get_file_hash(base_name)
        translated_srt_path = os.path.join("temp", f"{file_hash}_translated.srt")
        
        # 检查是否已存在翻译结果
        if os.path.exists(translated_srt_path):
            logger.info(f"发现已存在的翻译文件: {translated_srt_path}")
            # 从已存在的翻译文件中读取
            with open(translated_srt_path, 'r', encoding='utf-8') as f:
                content = f.read()
                # 解析SRT文件
                blocks = content.strip().split('\n\n')
                for block in blocks:
                    lines = block.split('\n')
                    if len(lines) >= 3:
                        index = int(lines[0])
                        time_range = lines[1]
                        translated_text = lines[2]
                        # 找到对应的原始字幕
                        original_subtitle = next((s for s in subtitles if s.get('index') == index), None)
                        if original_subtitle:
                            original_subtitle['translated_text'] = translated_text
                            translated_subtitles.append(original_subtitle)
            return translated_subtitles
        
        try:
            # 准备要翻译的文本列表
            texts_to_translate = [subtitle["text"] for subtitle in subtitles]
            
            # 批量翻译
            translated_texts = await self.translation_service.translate_batch(texts_to_translate)
            
            # 更新字幕并保存结果
            for i, (subtitle, translated_text) in enumerate(zip(subtitles, translated_texts)):
                subtitle["translated_text"] = translated_text
                translated_subtitles.append(subtitle)
                
                # 保存当前翻译结果到SRT文件
                with open(translated_srt_path, "a", encoding="utf-8") as f:
                    f.write(f"{i+1}\n")
                    start_time = self.format_time(subtitle["start"])
                    end_time = self.format_time(subtitle["end"])
                    f.write(f"{start_time} --> {end_time}\n")
                    speaker_text = f"[{subtitle['speaker']}] " if subtitle.get('speaker') else ""
                    f.write(f"{speaker_text}{translated_text}\n\n")
                
        except Exception as e:
            logger.error(f"批量翻译时出错: {str(e)}")
            # 发生错误时，使用原文作为译文
            for i, subtitle in enumerate(subtitles):
                subtitle["translated_text"] = f"[翻译错误: {str(e)}]"
                translated_subtitles.append(subtitle)
                
                # 保存错误信息到SRT文件
                with open(translated_srt_path, "a", encoding="utf-8") as f:
                    f.write(f"{i+1}\n")
                    start_time = self.format_time(subtitle["start"])
                    end_time = self.format_time(subtitle["end"])
                    f.write(f"{start_time} --> {end_time}\n")
                    speaker_text = f"[{subtitle['speaker']}] " if subtitle.get('speaker') else ""
                    f.write(f"{speaker_text}[翻译错误: {str(e)}]\n\n")
        
        return translated_subtitles
    
    def parse_time(self, time_str: str) -> float:
        """将SRT时间格式转换为秒数"""
        hours, minutes, seconds = time_str.replace(',', '.').split(':')
        return float(hours) * 3600 + float(minutes) * 60 + float(seconds)
        
    def generate_chinese_audio(self, subtitles: List[Dict]) -> str:
        """生成中文语音"""
        logger.info("正在生成中文语音...")
        temp_audio_path = os.path.join("temp", "chinese_audio.wav")
        
        # 检查是否已存在中文音频文件
        if os.path.exists(temp_audio_path):
            logger.info(f"发现已存在的中文音频文件: {temp_audio_path}")
            return temp_audio_path
            
        sample_rate = 16000
        
        # 使用 OpenAI TTS API 生成中文语音
        audio_segments = []
        total = len(subtitles)
        
        for i, subtitle in enumerate(tqdm(subtitles, desc="生成中文语音")):
            try:
                response = requests.post(
                    f"{self.tts_server_url}/tts",
                    json={
                        "text": subtitle["translated_text"],
                        "speaker": self.speaker if self.speaker else "alloy"
                    }
                )
                
                if response.status_code == 200:
                    # 保存临时音频文件
                    temp_segment_path = os.path.join("temp", f"segment_{i}.wav")
                    with open(temp_segment_path, 'wb') as f:
                        f.write(response.content)
                    
                    # 读取音频数据
                    audio_data, _ = librosa.load(temp_segment_path, sr=sample_rate)
                    
                    # 计算静音段
                    silence_duration = int((subtitle["end"] - subtitle["start"]) * sample_rate) - len(audio_data)
                    if silence_duration > 0:
                        silence = np.zeros(silence_duration)
                        audio_data = np.concatenate([audio_data, silence])
                    
                    audio_segments.append(audio_data)
                    os.remove(temp_segment_path)
                    
                    # 定期清理内存
                    if i % 10 == 0:
                        import gc
                        gc.collect()
                else:
                    raise Exception(f"生成语音失败: {response.text}")
            except Exception as e:
                logger.error(f"生成第 {i+1} 段语音时出错: {str(e)}")
                # 发生错误时，使用静音段
                silence_duration = int((subtitle["end"] - subtitle["start"]) * sample_rate)
                audio_segments.append(np.zeros(silence_duration))
        
        # 合并所有音频段
        if audio_segments:
            final_audio = np.concatenate(audio_segments)
            sf.write(temp_audio_path, final_audio, sample_rate)
            return temp_audio_path
        else:
            raise Exception("没有生成任何音频段")
    
    def mix_audio(self, original_audio_path: str, chinese_audio_path: str, subtitles: List[Dict]) -> str:
        """混合原始音频和中文音频"""
        logger.info("正在混合音频...")
        mixed_audio_path = os.path.join("temp", "mixed_audio.wav")
        
        # 检查是否已存在混合音频文件
        if os.path.exists(mixed_audio_path):
            logger.info(f"发现已存在的混合音频文件: {mixed_audio_path}")
            return mixed_audio_path
        
        try:
            # 准备音频文件
            with open(original_audio_path, 'rb') as f1, open(chinese_audio_path, 'rb') as f2:
                files = {
                    'original_audio': ('original.wav', f1, 'audio/wav'),
                    'chinese_audio': ('chinese.wav', f2, 'audio/wav')
                }
                
                # 准备字幕信息
                data = {
                    'subtitles': json.dumps(subtitles)
                }
                
                # 调用音频混合 API
                response = requests.post(
                    f"{self.tts_server_url}/mix_audio",
                    files=files,
                    data=data
                )
                
                if response.status_code == 200:
                    # 保存混合后的音频
                    with open(mixed_audio_path, 'wb') as f:
                        f.write(response.content)
                    return mixed_audio_path
                else:
                    raise Exception(f"音频混合失败: {response.text}")
                    
        except Exception as e:
            logger.error(f"混合音频时出错: {str(e)}")
            raise
    
    def create_final_video(self, video_path: str, audio_path: str, subtitles: List[Dict], output_path: str) -> str:
        """创建最终视频"""
        logger.info("正在生成最终视频...")
        
        # 创建字幕文件
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        srt_path = os.path.join("temp", f"{base_name}.srt")
        
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, subtitle in enumerate(subtitles, 1):
                start_time = self.format_time(subtitle["start"])
                end_time = self.format_time(subtitle["end"])
                f.write(f"{i}\n")
                f.write(f"{start_time} --> {end_time}\n")
                speaker_text = f"[{subtitle['speaker']}] " if subtitle['speaker'] else ""
                f.write(f"{speaker_text}{subtitle['translated_text']}\n\n")
        
        # 使用ffmpeg合并视频和音频
        ffmpeg_cmd = f'ffmpeg -i {video_path} -i {audio_path} -c:v copy -c:a aac -map 0:v:0 -map 1:a:0 {output_path}'
        result = subprocess.run(ffmpeg_cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg 处理失败: {result.stderr}")
        
        return output_path
    
    def format_time(self, seconds: float) -> str:
        """将秒数格式化为SRT时间格式"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = seconds % 60
        milliseconds = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{int(seconds):02d},{milliseconds:03d}"
    
    async def process_video(self, video_path: str, output_path: str, speaker_name: str = None):
        """异步处理视频文件"""
        # 初始化临时文件路径变量
        audio_path = None
        chinese_audio_path = None
        mixed_audio_path = None
        
        try:
            logger.info("\n开始处理视频...")
            logger.info(f"输入视频: {video_path}")
            logger.info(f"输出视频: {output_path}")
            
            # 检查输入文件是否存在
            if not os.path.exists(video_path):
                raise FileNotFoundError(f"输入视频文件不存在: {video_path}")
            
            # 检查输出目录是否可写
            output_dir = os.path.dirname(output_path)
            if output_dir and not os.access(output_dir, os.W_OK):
                raise PermissionError(f"输出目录没有写入权限: {output_dir}")
            
            # 1. 提取音频
            logger.info("\n1. 正在提取音频...")
            audio_path = self.extract_audio(video_path)
            
            # 2. 生成字幕
            logger.info("\n2. 正在生成字幕...")
            subtitles = self.get_subtitles(audio_path)
            
            # 3. 翻译字幕
            logger.info("\n3. 正在翻译字幕...")
            subtitles = await self.translate_subtitles(subtitles)
            
            # 4. 生成中文语音
            logger.info("\n4. 正在生成中文语音...")
            chinese_audio_path = self.generate_chinese_audio(subtitles)
            
            # 5. 混合音频
            logger.info("\n5. 正在混合音频...")
            mixed_audio_path = self.mix_audio(audio_path, chinese_audio_path, subtitles)
            
            # 6. 生成最终视频
            logger.info("\n6. 正在生成最终视频...")
            self.create_final_video(video_path, mixed_audio_path, subtitles, output_path)
            
            # 清理临时文件
            logger.info("\n清理临时文件...")
            for temp_file in [audio_path, chinese_audio_path, mixed_audio_path]:
                try:
                    if temp_file and os.path.exists(temp_file):
                        os.remove(temp_file)
                except Exception as e:
                    logger.warning(f"清理临时文件 {temp_file} 时出错: {str(e)}")
            
            logger.info("\n处理完成！")
            logger.info(f"输出视频已保存到: {output_path}")
            
            return {
                "status": "success",
                "output_video": output_path,
                "speaker_count": len(set(sub["speaker"] for sub in subtitles if sub["speaker"])),
                "subtitle_count": len(subtitles)
            }
            
        except Exception as e:
            logger.error(f"\n处理过程中出现错误: {str(e)}")
            # 确保清理所有临时文件
            for temp_file in [audio_path, chinese_audio_path, mixed_audio_path]:
                try:
                    if temp_file and os.path.exists(temp_file):
                        os.remove(temp_file)
                except:
                    pass
            raise

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="视频翻译程序")
    parser.add_argument("--input_video", required=True, help="输入视频文件路径")
    parser.add_argument("--output_video", required=True, help="输出视频文件路径")
    parser.add_argument("--stt_server", default="http://localhost:8001", help="语音识别服务器地址")
    parser.add_argument("--tts_server", default="http://localhost:8000", help="语音合成服务器地址")
    parser.add_argument("--speaker", help="TTS说话人名称")
    
    args = parser.parse_args()
    
    client = VideoTranslationClient(
        stt_server_url=args.stt_server,
        tts_server_url=args.tts_server,
        speaker=args.speaker
    )
    
    asyncio.run(client.process_video(args.input_video, args.output_video))