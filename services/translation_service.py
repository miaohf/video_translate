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
from config import settings

logger = logging.getLogger(__name__)

class TranslationService:
    def __init__(self):
        """
        初始化翻译服务
        """
        self.api_url = settings.OLLAMA_API_URL
        self.model = settings.OLLAMA_MODEL
        self.llm = OllamaLLM(model=self.model)
        self._session = None
        self.batch_size = 5  # 批量翻译的大小
        logger.info("Translation service initialized")

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 aiohttp 会话"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        """关闭 aiohttp 会话"""
        if self._session and not self._session.closed:
            await self._session.close()

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
            
            # 只保存翻译后的字幕（中文）
            with open(output_path, "w", encoding="utf-8") as f:
                for i, subtitle in enumerate(subtitles, 1):
                    start_time = self.format_time(subtitle["start"])
                    end_time = self.format_time(subtitle["end"])
                    f.write(f"{i}\n{start_time} --> {end_time}\n{subtitle['text']}\n\n")
                    
            logger.info(f"Subtitles saved to {output_path}")
            
        except Exception as e:
            logger.error(f"Error saving subtitles: {str(e)}")
            raise

    def _clean_translation(self, text: str) -> str:
        """
        清理翻译结果，移除 think 标签内容和多余的空行
        
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

    async def translate_batch(self, texts: List[str]) -> List[str]:
        """
        批量翻译文本
        
        参数:
            texts: 要翻译的文本列表
            
        返回:
            翻译后的文本列表
        """
        try:
            session = await self._get_session()
            
            # 构建批量翻译提示
            combined_text = "\n---\n".join(texts)
            prompt = f"Translate these English texts to Chinese, keep the same number of segments:\n{combined_text}"
            
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
            async with session.post(f"{self.api_url}/api/generate", json=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"API request failed with status {response.status}: {error_text}")
                
                result = await response.json()
                if "error" in result:
                    raise Exception(f"API error: {result['error']}")
                    
                translated_text = result.get("response", "").strip()
                if not translated_text:
                    raise Exception("Empty response from API")
                
                # 清理翻译结果中的思考过程
                translated_text = self._clean_translation(translated_text)
                
                # 分割翻译结果
                translated_segments = translated_text.split("\n---\n")
                
                # 确保返回的段落数量与输入相同
                if len(translated_segments) != len(texts):
                    logger.warning(f"Translation segment count mismatch: got {len(translated_segments)}, expected {len(texts)}")
                    # 如果段落数量不匹配，返回原始文本
                    return texts
                
                return translated_segments
                
        except Exception as e:
            logger.error(f"Batch translation error: {str(e)}")
            # 发生错误时返回原始文本
            return texts

    async def translate_batch_subtitles(self, subtitles: List[Dict[str, Any]], 
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
                # 按批次处理字幕
                for i in range(0, total, self.batch_size):
                    batch = subtitles[i:i + self.batch_size]
                    batch_texts = [sub["text"] for sub in batch]
                    
                    # 批量翻译
                    translated_texts = await self.translate_batch(batch_texts)
                    
                    # 更新字幕
                    for subtitle, translated_text in zip(batch, translated_texts):
                        translated_subtitle = subtitle.copy()
                        translated_subtitle["text"] = translated_text
                        translated_subtitle["original_text"] = subtitle["text"]
                        translated_subtitles.append(translated_subtitle)
                        
                        # 更新进度条
                        pbar.update(1)
                    
                    # 每翻译10个字幕保存一次
                    if len(translated_subtitles) % 10 == 0:
                        self.save_subtitles(translated_subtitles, output_path, original_path)
                    
            # 最后保存一次
            self.save_subtitles(translated_subtitles, output_path, original_path)
            logger.info("Translation completed, saving subtitle files")
            
            # 关闭 session
            await self.close()
            
            return translated_subtitles
            
        except Exception as e:
            logger.error(f"Batch translation error: {str(e)}")
            # 确保关闭 session
            await self.close()
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