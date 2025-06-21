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
import time
from pathlib import Path
import re
from config import settings
from utils.common import get_file_hash, format_time
from services.translation_templates import (
    INITIAL_TRANSLATION_SYSTEM,
    INITIAL_TRANSLATION_TEMPLATE,
    REFLECTION_SYSTEM,
    REFLECTION_TEMPLATE,
    IMPROVEMENT_SYSTEM,
    IMPROVEMENT_TEMPLATE,
    SIMPLE_TRANSLATION_SYSTEM,
    SIMPLE_TRANSLATION_TEMPLATE
)

logger = logging.getLogger(__name__)

class TranslationService:
    def __init__(self):
        """
        初始化翻译服务，基于吴恩达TranslationAgent的三阶段翻译流程
        针对字幕翻译进行优化，专注于简洁性和自然对话
        支持多种翻译提供商：Ollama 和 DeepSeek
        """
        # 翻译提供商配置
        self.provider = settings.TRANSLATION_PROVIDER.lower()
        
        # Ollama 配置
        self.ollama_api_url = settings.OLLAMA_API_URL
        self.ollama_model = settings.OLLAMA_MODEL
        
        # DeepSeek 配置
        self.deepseek_api_url = settings.DEEPSEEK_API_URL
        self.deepseek_api_key = settings.DEEPSEEK_API_KEY
        self.deepseek_model = settings.DEEPSEEK_MODEL
        
        # 检查配置
        if self.provider == "deepseek":
            if not self.deepseek_api_key:
                raise ValueError("DEEPSEEK_API_KEY must be set when using DeepSeek provider")
            logger.info(f"Translation service initialized with DeepSeek API ({self.deepseek_model})")
        elif self.provider == "ollama":
            self.llm = OllamaLLM(model=self.ollama_model)
            logger.info(f"Translation service initialized with Ollama ({self.ollama_model})")
        else:
            raise ValueError(f"Unsupported translation provider: {self.provider}")
        
        self._session = None
        self.batch_size = 8  # 增加批量大小以提高效率
        self.source_lang = "English"
        self.target_lang = "Chinese"
        self.country = "China"
        
        logger.info("Translation service initialized with Wu Enda's TranslationAgent approach for subtitles")

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 aiohttp 会话"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        """关闭 aiohttp 会话"""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _call_llm(self, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> str:
        """
        调用LLM API，支持 Ollama 和 DeepSeek
        
        参数:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            temperature: 温度参数
            
        返回:
            LLM响应文本
        """
        if self.provider == "deepseek":
            return await self._call_deepseek_api(system_prompt, user_prompt, temperature)
        elif self.provider == "ollama":
            return await self._call_ollama_api(system_prompt, user_prompt, temperature)
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

    async def _call_deepseek_api(self, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> str:
        """
        调用 DeepSeek API
        """
        session = await self._get_session()
        
        # 构建 DeepSeek API 请求格式
        data = {
            "model": self.deepseek_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature,
            "top_p": 0.95,
            "max_tokens": 4096,
            "stream": False
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.deepseek_api_key}"
        }
        
        async with session.post(f"{self.deepseek_api_url}/chat/completions", json=data, headers=headers) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"DeepSeek API request failed with status {response.status}: {error_text}")
            
            result = await response.json()
            if "error" in result:
                raise Exception(f"DeepSeek API error: {result['error']}")
                
            choices = result.get("choices", [])
            if not choices:
                raise Exception("No choices in DeepSeek API response")
                
            response_text = choices[0].get("message", {}).get("content", "").strip()
            if not response_text:
                raise Exception("Empty response from DeepSeek API")
                
            return self._clean_translation(response_text)

    async def _call_ollama_api(self, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> str:
        """
        调用 Ollama API
        """
        session = await self._get_session()
        
        # 构建完整的提示词
        full_prompt = f"System: {system_prompt}\n\nUser: {user_prompt}"
        
        data = {
            "model": self.ollama_model,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "top_p": 0.95,
                "top_k": 50,
                "num_ctx": 4096,
                "repeat_penalty": 1.1
            }
        }
        
        async with session.post(f"{self.ollama_api_url}/api/generate", json=data) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Ollama API request failed with status {response.status}: {error_text}")
            
            result = await response.json()
            if "error" in result:
                raise Exception(f"Ollama API error: {result['error']}")
                
            response_text = result.get("response", "").strip()
            if not response_text:
                raise Exception("Empty response from Ollama API")
                
            return self._clean_translation(response_text)

    async def translate_single_with_reflection(self, source_text: str) -> str:
        """
        使用三阶段翻译流程翻译单个文本
        针对字幕翻译进行优化
        
        参数:
            source_text: 源文本
            
        返回:
            改进后的翻译文本
        """
        try:
            # 第一阶段：初始翻译
            initial_system = INITIAL_TRANSLATION_SYSTEM.format(
                source_lang=self.source_lang,
                target_lang=self.target_lang
            )
            initial_prompt = INITIAL_TRANSLATION_TEMPLATE.format(
                source_lang=self.source_lang,
                target_lang=self.target_lang,
                source_text=source_text
            )
            initial_translation = await self._call_llm(
                initial_system, 
                initial_prompt,
                temperature=0.1
            )
            
            # 第二阶段：反思检查
            reflection_system = REFLECTION_SYSTEM.format(
                source_lang=self.source_lang,
                target_lang=self.target_lang
            )
            reflection_prompt = REFLECTION_TEMPLATE.format(
                source_lang=self.source_lang,
                target_lang=self.target_lang,
                country=self.country,
                source_text=source_text,
                translation_1=initial_translation
            )
            reflection = await self._call_llm(
                reflection_system,
                reflection_prompt,
                temperature=0.3
            )
            
            # 第三阶段：改进翻译
            improvement_system = IMPROVEMENT_SYSTEM.format(
                source_lang=self.source_lang,
                target_lang=self.target_lang
            )
            improvement_prompt = IMPROVEMENT_TEMPLATE.format(
                source_lang=self.source_lang,
                target_lang=self.target_lang,
                country=self.country,
                source_text=source_text,
                translation_1=initial_translation,
                reflection=reflection
            )
            final_translation = await self._call_llm(
                improvement_system,
                improvement_prompt,
                temperature=0.1
            )
            
            logger.debug(f"Three-stage subtitle translation completed for: {source_text[:50]}...")
            return final_translation
            
        except Exception as e:
            logger.error(f"Three-stage translation failed: {str(e)}")
            # 如果三阶段翻译失败，回退到简单翻译
            return await self._simple_translation_fallback(source_text)

    async def _simple_translation_fallback(self, source_text: str) -> str:
        """
        简单翻译回退方案
        """
        try:
            simple_system = SIMPLE_TRANSLATION_SYSTEM
            simple_prompt = SIMPLE_TRANSLATION_TEMPLATE.format(
                source_lang=self.source_lang,
                target_lang=self.target_lang,
                source_text=source_text
            )
            return await self._call_llm(
                simple_system,
                simple_prompt,
                temperature=0.1
            )
        except Exception as e:
            logger.error(f"Fallback translation failed: {str(e)}")
            return source_text  # 最后的回退：返回原文

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
                    start_time = format_time(subtitle["start"])
                    end_time = format_time(subtitle["end"])
                    f.write(f"{i}\n{start_time} --> {end_time}\n{subtitle['text']}\n\n")
                    
            logger.info(f"Subtitles saved to {output_path}")
            
            # 保存 JSON 格式的字幕数据
            json_path = output_path.replace("_subtitles_zh.srt", "_subtitles_zh.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(subtitles, f, ensure_ascii=False, indent=2)
            logger.info(f"JSON subtitles saved to {json_path}")
            
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

    async def translate_batch_parallel(self, texts: List[str]) -> List[str]:
        """
        并行批量翻译文本，使用三阶段翻译流程
        针对字幕翻译进行优化
        
        参数:
            texts: 要翻译的文本列表
            
        返回:
            翻译后的文本列表
        """
        # 使用信号量限制并发数，避免API过载
        semaphore = asyncio.Semaphore(3)  # 最多3个并发请求
        
        async def translate_with_semaphore(text):
            async with semaphore:
                try:
                    return await self.translate_single_with_reflection(text)
                except Exception as e:
                    logger.error(f"Failed to translate text: {text[:50]}..., error: {str(e)}")
                    return text  # 返回原文作为回退
        
        # 并行执行所有翻译任务
        tasks = [translate_with_semaphore(text) for text in texts]
        translated_texts = await asyncio.gather(*tasks)
        
        return translated_texts

    async def translate_batch(self, texts: List[str]) -> List[str]:
        """
        批量翻译文本，使用三阶段翻译流程
        针对字幕翻译进行优化
        
        参数:
            texts: 要翻译的文本列表
            
        返回:
            翻译后的文本列表
        """
        # 如果文本数量较多，使用并行翻译
        if len(texts) > 3:
            return await self.translate_batch_parallel(texts)
        
        # 少量文本使用串行翻译
        translated_texts = []
        
        for text in texts:
            try:
                # 对每个文本使用三阶段翻译
                translated_text = await self.translate_single_with_reflection(text)
                translated_texts.append(translated_text)
                
                # 减少延迟时间
                await asyncio.sleep(0.05)
                
            except Exception as e:
                logger.error(f"Failed to translate text: {text[:50]}..., error: {str(e)}")
                translated_texts.append(text)  # 添加原文作为回退
        
        return translated_texts

    def _estimate_translation_time(self, total_subtitles: int) -> str:
        """
        估算翻译时间
        
        参数:
            total_subtitles: 字幕总数
            
        返回:
            估算时间字符串
        """
        # 每个字幕大约需要6-10秒（3个API调用 + 网络延迟）
        estimated_seconds = total_subtitles * 8
        
        if estimated_seconds < 60:
            return f"{estimated_seconds}秒"
        elif estimated_seconds < 3600:
            minutes = estimated_seconds // 60
            return f"{minutes}分钟"
        else:
            hours = estimated_seconds // 3600
            minutes = (estimated_seconds % 3600) // 60
            return f"{hours}小时{minutes}分钟"

    async def translate_batch_subtitles(self, subtitles: List[Dict[str, Any]], 
                                      video_name: str,
                                      output_path: str = None,
                                      original_path: str = None) -> List[Dict[str, Any]]:
        """
        批量翻译字幕，使用改进的三阶段翻译流程
        
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
            
            # 计算文件哈希值
            file_hash = get_file_hash(video_name)
            
            # 设置输出路径
            if output_path is None:
                output_path = os.path.join(temp_dir, f"{file_hash}_subtitles_zh.srt")
            if original_path is None:
                original_path = os.path.join(temp_dir, f"{file_hash}_subtitles_en.srt")
            
            translated_subtitles = []
            total = len(subtitles)
            
            # 估算翻译时间
            estimated_time = self._estimate_translation_time(total)
            logger.info(f"Starting three-stage subtitle translation, total: {total}, estimated time: {estimated_time}")
            
            start_time = time.time()
            
            # 创建进度条，显示更详细的信息
            with tqdm(total=total, desc="Wu Enda 3-Stage Translation", unit="sub", 
                     bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]') as pbar:
                
                # 按批次处理字幕
                for i in range(0, total, self.batch_size):
                    batch_start_time = time.time()
                    batch = subtitles[i:i + self.batch_size]
                    
                    # 检查每个字幕是否包含必要的字段
                    valid_batch = []
                    for sub in batch:
                        if "text" not in sub:
                            logger.warning(f"Subtitle missing text field: {sub}")
                            continue
                        valid_batch.append(sub)
                    
                    if not valid_batch:
                        logger.warning("No valid subtitles in current batch, skipping")
                        continue
                        
                    batch_texts = [sub["text"] for sub in valid_batch]
                    
                    # 使用优化的三阶段翻译批量翻译
                    translated_texts = await self.translate_batch(batch_texts)
                    
                    # 更新字幕
                    for subtitle, translated_text in zip(valid_batch, translated_texts):
                        translated_subtitle = subtitle.copy()
                        translated_subtitle["text"] = translated_text
                        translated_subtitle["original_text"] = subtitle["text"]
                        translated_subtitles.append(translated_subtitle)
                        
                        # 更新进度条
                        pbar.update(1)
                    
                    # 计算批次处理时间并更新进度条描述
                    batch_time = time.time() - batch_start_time
                    avg_time_per_subtitle = batch_time / len(valid_batch)
                    remaining_subtitles = total - len(translated_subtitles)
                    estimated_remaining = remaining_subtitles * avg_time_per_subtitle
                    
                    pbar.set_postfix({
                        'batch': f'{len(valid_batch)}',
                        'avg_time': f'{avg_time_per_subtitle:.1f}s/sub',
                        'ETA': f'{estimated_remaining/60:.1f}min'
                    })
                    
                    # 每完成一批次保存一次
                    if len(translated_subtitles) % (self.batch_size * 2) == 0:
                        self.save_subtitles(translated_subtitles, output_path, original_path)
                    
            # 最后保存一次
            self.save_subtitles(translated_subtitles, output_path, original_path)
            
            total_time = time.time() - start_time
            logger.info(f"Three-stage subtitle translation completed in {total_time/60:.1f} minutes, subtitle files saved")
            
            # 确保关闭 session
            await self.close()
            
            return translated_subtitles
            
        except Exception as e:
            logger.error(f"Batch subtitle translation error: {str(e)}")
            # 确保关闭 session
            await self.close()
            raise 