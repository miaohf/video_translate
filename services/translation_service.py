import logging
from typing import List, Dict, Any
from tqdm import tqdm
from langchain_ollama import OllamaLLM
from langchain.prompts import PromptTemplate
from langchain.schema.runnable import RunnablePassthrough
import os
import json
import aiohttp
import asyncio
from pathlib import Path
import re
from config import STT_SERVER_URL, MODEL_NAME

logger = logging.getLogger(__name__)

class TranslationService:
    def __init__(self):
        """
        初始化翻译服务
        """
        self.api_url = STT_SERVER_URL
        self.model = MODEL_NAME
        self.llm = OllamaLLM(model=self.model)
        logger.info("Translation service initialized")

    def save_subtitles(self, subtitles: List[Dict[str, Any]], 
                      output_path: str, original_path: str) -> None:
        """
        保存字幕到文件
        
        参数:
            subtitles: 字幕列表
            output_path: 输出文件路径（中文）
            original_path: 原始字幕文件路径（英文）
        """
        try:
            # 确保输出目录存在
            output_dir = os.path.dirname(output_path)
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
                logger.info(f"Creating output directory: {output_dir}")
            
            # 保存翻译后的字幕（中文）
            with open(output_path, "w", encoding="utf-8") as f:
                for i, subtitle in enumerate(subtitles, 1):
                    start_time = self.format_time(subtitle["start"])
                    end_time = self.format_time(subtitle["end"])
                    f.write(f"{i}\n{start_time} --> {end_time}\n{subtitle['translated_text']}\n\n")
                    
            # 保存原始字幕（英文）
            with open(original_path, "w", encoding="utf-8") as f:
                for i, subtitle in enumerate(subtitles, 1):
                    start_time = self.format_time(subtitle["start"])
                    end_time = self.format_time(subtitle["end"])
                    f.write(f"{i}\n{start_time} --> {end_time}\n{subtitle['text']}\n\n")
                    
            logger.info(f"Subtitles saved to {output_path} and {original_path}")
            
        except Exception as e:
            logger.error(f"Error saving subtitles: {str(e)}")
            raise

    def _clean_translation(self, text: str) -> str:
        """
        清理翻译结果，移除 think 标签内容
        
        参数:
            text: 原始翻译文本
            
        返回:
            清理后的文本
        """
        # 移除 <think> 标签及其内容
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        # 移除多余的空行
        text = re.sub(r'\n\s*\n', '\n', text)
        # 移除首尾空白
        return text.strip()

    async def translate(self, text: str, source_lang: str = "en", target_lang: str = "zh") -> str:
        """
        使用 Ollama 进行翻译
        
        参数:
            text: 要翻译的文本
            source_lang: 源语言
            target_lang: 目标语言
            
        返回:
            翻译后的文本
        """
        try:
            logger.debug(f"Translating text: {text[:100]}...")
            
            # 构建翻译提示
            prompt = f"Translate this English text to Chinese: {text}"
            
            # 构建请求数据
            data = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "top_p": 0.95,
                    "top_k": 50,
                    "num_ctx": 4096,
                    "repeat_penalty": 1.1
                }
            }
            
            # 发送请求
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=data) as response:
                    if response.status != 200:
                        raise Exception(f"API request failed with status {response.status}")
                    
                    result = await response.json()
                    translated_text = result.get("response", "").strip()
                    
                    # 清理翻译结果
                    translated_text = self._clean_translation(translated_text)
                    
                    logger.debug(f"Translation result: {translated_text[:100]}...")
                    
                    if not translated_text:
                        logger.warning("Empty translation result")
                        return f"[Translation error: Empty result]"
                    
                    return translated_text
                    
        except Exception as e:
            logger.error(f"Translation error: {str(e)}")
            raise

    async def translate_batch(self, subtitles: List[Dict[str, Any]], 
                            video_name: str,
                            output_path: str = None,
                            original_path: str = None) -> List[Dict[str, Any]]:
        """
        批量翻译字幕
        
        参数:
            subtitles: 字幕列表，每个元素为包含 start, end, text, speaker 的字典
            video_name: 视频文件名（不含扩展名）
            output_path: 输出文件路径，如果为 None 则自动生成
            original_path: 原始字幕文件路径，如果为 None 则自动生成
            
        返回:
            翻译后的字幕列表
        """
        try:
            # 创建临时目录
            temp_dir = os.path.join("temp", video_name)
            os.makedirs(temp_dir, exist_ok=True)
            
            # 设置输出路径
            if output_path is None:
                output_path = os.path.join(temp_dir, "subtitles_zh.srt")
            if original_path is None:
                original_path = os.path.join(temp_dir, "subtitles_en.srt")
            
            translated_subtitles = []
            total = len(subtitles)
            
            # 创建进度条
            with tqdm(total=total, desc="Translation progress", unit="subtitle") as pbar:
                for subtitle in subtitles:
                    translated_text = await self.translate(subtitle["text"])
                    
                    # 创建新的字幕条目
                    translated_subtitle = subtitle.copy()
                    translated_subtitle["text"] = translated_text
                    translated_subtitles.append(translated_subtitle)
                    
                    # 更新进度条
                    pbar.update(1)
                    
                    # 每翻译10个字幕保存一次
                    if len(translated_subtitles) % 10 == 0:
                        self.save_subtitles(translated_subtitles, output_path, original_path)
                    
            # 最后保存一次
            self.save_subtitles(translated_subtitles, output_path, original_path)
            logger.info("Translation completed, saving subtitle files")
            
            return translated_subtitles
            
        except Exception as e:
            logger.error(f"Batch translation error: {str(e)}")
            raise

    def format_time(self, seconds: float) -> str:
        """
        将秒数格式化为 SRT 时间格式
        
        参数:
            seconds: 秒数
            
        返回:
            格式化的时间字符串 (HH:MM:SS,mmm)
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = seconds % 60
        milliseconds = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{int(seconds):02d},{milliseconds:03d}" 