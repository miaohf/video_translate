import logging
from typing import List, Dict, Any, Optional, Callable
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
import time
from collections import defaultdict, deque
from config import settings
from utils.common import get_file_hash
from services.translation_templates import (
    TRANSLATION_TEMPLATE, 
    CONTEXTUAL_TRANSLATION_TEMPLATE,
    STREAMING_TRANSLATION_TEMPLATE
)
from services.translation_config import TranslationConfig

logger = logging.getLogger(__name__)


class ContextManager:
    """上下文管理器 - 管理翻译历史和术语一致性"""
    
    def __init__(self, window_size: int = TranslationConfig.CONTEXT_WINDOW_SIZE):
        self.window_size = window_size
        self.context_buffer = deque(maxlen=window_size)
        self.terminology_dict = {}
        self.terminology_usage_count = defaultdict(int)
        
    def add_translation(self, original: str, translated: str, segment_info: Dict = None):
        """添加翻译到上下文缓冲区"""
        context_item = {
            "original": original,
            "translated": translated,
            "timestamp": time.time(),
            "info": segment_info or {}
        }
        self.context_buffer.append(context_item)
        self._extract_terminology(original, translated)
    
    def _extract_terminology(self, original: str, translated: str):
        """从翻译对中提取术语"""
        # 提取英文专业词汇
        en_terms = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b|\b[A-Z]{2,}\b|\b\w+[-]\w+\b', original)
        zh_terms = re.findall(r'[\u4e00-\u9fff]{2,}', translated)
        
        for en_term in en_terms:
            if en_term.lower() not in ['the', 'and', 'this', 'that', 'with', 'from']:
                self.terminology_usage_count[en_term] += 1
                if self.terminology_usage_count[en_term] >= 2:
                    for zh_term in zh_terms:
                        if len(zh_term) >= 2:
                            self.terminology_dict[en_term] = zh_term
                            break
    
    def get_context_string(self) -> str:
        """获取上下文字符串"""
        if not self.context_buffer:
            return "暂无翻译历史。"
        
        context_parts = []
        for i, item in enumerate(list(self.context_buffer)[-5:], 1):
            context_parts.append(f"{i}. 英文: {item['original'][:50]}...")
            context_parts.append(f"   中文: {item['translated'][:50]}...")
        
        return "\n".join(context_parts)
    
    def get_terminology_string(self) -> str:
        """获取术语词典字符串"""
        if not self.terminology_dict:
            return "暂无确定术语。"
        
        sorted_terms = sorted(
            self.terminology_dict.items(), 
            key=lambda x: self.terminology_usage_count[x[0]], 
            reverse=True
        )[:10]
        
        return "\n".join([f"- {en} → {zh}" for en, zh in sorted_terms])


class AdaptiveBatchProcessor:
    """自适应批次处理器 - 根据性能动态调整批次大小"""
    
    def __init__(self, initial_batch_size: int = TranslationConfig.DEFAULT_BATCH_SIZE):
        self.current_batch_size = initial_batch_size
        self.performance_history = deque(maxlen=10)
        
    def record_performance(self, batch_size: int, response_time: float, 
                          success_rate: float, quality_score: float):
        """记录性能数据"""
        efficiency_score = self._calculate_efficiency_score(
            batch_size, response_time, success_rate, quality_score
        )
        
        performance_data = {
            "batch_size": batch_size,
            "response_time": response_time,
            "success_rate": success_rate,
            "quality_score": quality_score,
            "timestamp": time.time(),
            "efficiency_score": efficiency_score
        }
        self.performance_history.append(performance_data)
        
    def _calculate_efficiency_score(self, batch_size: int, response_time: float, 
                                  success_rate: float, quality_score: float) -> float:
        """计算效率得分"""
        time_efficiency = max(0, 1 - (response_time - 5) / 25)
        throughput = batch_size / max(response_time, 1)
        
        return (throughput * 0.3 + success_rate * 0.3 + 
                quality_score * 0.2 + time_efficiency * 0.2)
    
    def get_optimal_batch_size(self) -> int:
        """获取最优批次大小"""
        if len(self.performance_history) < 3:
            return self.current_batch_size
        
        recent_data = list(self.performance_history)[-5:]
        avg_efficiency = sum(d["efficiency_score"] for d in recent_data) / len(recent_data)
        
        if avg_efficiency < 0.6:
            avg_response_time = sum(d["response_time"] for d in recent_data) / len(recent_data)
            if avg_response_time > TranslationConfig.MAX_RESPONSE_TIME:
                self.current_batch_size = max(1, self.current_batch_size - 1)
                logger.info(f"响应时间过长，减小批次大小到 {self.current_batch_size}")
            
            avg_success_rate = sum(d["success_rate"] for d in recent_data) / len(recent_data)
            if avg_success_rate < TranslationConfig.MIN_SUCCESS_RATE:
                self.current_batch_size = max(1, self.current_batch_size - 1)
                logger.info(f"成功率过低，减小批次大小到 {self.current_batch_size}")
        
        elif avg_efficiency > 0.8:
            if self.current_batch_size < TranslationConfig.MAX_BATCH_SIZE:
                recent_response_time = sum(d["response_time"] for d in recent_data[-2:]) / 2
                if recent_response_time < TranslationConfig.MIN_RESPONSE_TIME:
                    self.current_batch_size = min(TranslationConfig.MAX_BATCH_SIZE, 
                                                 self.current_batch_size + 1)
                    logger.info(f"效率良好，增加批次大小到 {self.current_batch_size}")
        
        return TranslationConfig.validate_batch_size(self.current_batch_size)


class TranslationService:
    """智能翻译服务 - 集成流式处理、上下文感知、自适应批次等功能"""
    
    def __init__(self, batch_size: int = None):
        self.api_url = settings.OLLAMA_API_URL
        self.model = settings.OLLAMA_MODEL
        self.llm = OllamaLLM(model=self.model)
        self._session = None
        
        # 初始化功能模块
        self.context_manager = ContextManager() if TranslationConfig.ENABLE_CONTEXT else None
        
        if TranslationConfig.ENABLE_ADAPTIVE_BATCH:
            initial_batch_size = batch_size or TranslationConfig.DEFAULT_BATCH_SIZE
            self.adaptive_processor = AdaptiveBatchProcessor(initial_batch_size)
            self.batch_size = self.adaptive_processor.current_batch_size
        else:
            self.batch_size = TranslationConfig.validate_batch_size(
                batch_size or TranslationConfig.DEFAULT_BATCH_SIZE
            )
            self.adaptive_processor = None
        
        # 初始化模板
        self.translation_prompt = PromptTemplate(
            input_variables=["segments", "segment_count"],
            template=TRANSLATION_TEMPLATE
        )
        
        if TranslationConfig.ENABLE_CONTEXT:
            self.contextual_prompt = PromptTemplate(
                input_variables=["previous_context", "terminology_dict", 
                               "current_segments", "segment_count"],
                template=CONTEXTUAL_TRANSLATION_TEMPLATE
            )
            
            self.streaming_prompt = PromptTemplate(
                input_variables=["context_info", "terminology_dict", "segments"],
                template=STREAMING_TRANSLATION_TEMPLATE
            )
        
        logger.info(f"🚀 智能翻译服务已初始化")
        logger.info(f"  批处理大小: {self.batch_size}")
        logger.info(f"  上下文功能: {'✅ 启用' if TranslationConfig.ENABLE_CONTEXT else '❌ 禁用'}")
        logger.info(f"  流式处理: {'✅ 启用' if TranslationConfig.ENABLE_STREAMING else '❌ 禁用'}")
        logger.info(f"  自适应批次: {'✅ 启用' if TranslationConfig.ENABLE_ADAPTIVE_BATCH else '❌ 禁用'}")

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建HTTP会话"""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=10, limit_per_host=5, ttl_dns_cache=300,
                use_dns_cache=True, keepalive_timeout=30, enable_cleanup_closed=True
            )
            
            timeout = aiohttp.ClientTimeout(
                total=TranslationConfig.REQUEST_TIMEOUT, connect=30, sock_read=60
            )
            
            self._session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        return self._session

    async def close(self):
        """关闭HTTP会话"""
        if self._session and not self._session.closed:
            await self._session.close()
            
    async def test_connection(self) -> bool:
        """测试API连接"""
        try:
            session = await self._get_session()
            test_data = {
                "model": self.model,
                "prompt": "测试连接",
                "stream": False,
                "options": {"temperature": 0.1}
            }
            
            async with session.post(f"{self.api_url}/api/generate", json=test_data) as response:
                if response.status == 200:
                    logger.info("✅ Ollama API连接测试成功")
                    return True
                else:
                    logger.error(f"❌ API连接失败: 状态码 {response.status}")
                    return False
        except Exception as e:
            logger.error(f"❌ API连接异常: {str(e)}")
            return False

    def _is_chinese_text(self, text: str) -> bool:
        """判断文本是否包含中文"""
        return bool(re.search(r'[\u4e00-\u9fff]+', text))

    def _check_translation_quality(self, original_texts: List[str], translated_texts: List[str]) -> List[bool]:
        """检查翻译质量"""
        quality_results = []
        
        for original, translated in zip(original_texts, translated_texts):
            has_chinese = self._is_chinese_text(translated)
            is_different = original.strip() != translated.strip()
            not_empty = bool(translated.strip())
            
            # 长度合理性检查
            if len(original) > 0:
                char_ratio = len(translated) / len(original)
                reasonable_length = (TranslationConfig.MIN_LENGTH_RATIO <= char_ratio <= 
                                   TranslationConfig.MAX_LENGTH_RATIO)
            else:
                reasonable_length = True
            
            # 错误标识检查
            error_indicators = ["无法翻译", "不能翻译", "翻译失败", "error", "failed"]
            no_error_indicators = not any(indicator in translated.lower() for indicator in error_indicators)
            
            is_good = has_chinese and is_different and reasonable_length and not_empty and no_error_indicators
            quality_results.append(is_good)
        
        return quality_results

    def _clean_translation(self, text: str) -> str:
        """清理翻译结果"""
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        text = re.sub(r'\n\s*\n', '\n', text)
        return text.strip()

    async def translate_batch_with_context(self, texts: List[str]) -> List[str]:
        """基于上下文的智能翻译"""
        start_time = time.time()
        
        if not self.context_manager:
            return await self.translate_batch(texts)
        
        try:
            context_info = self.context_manager.get_context_string()
            terminology_dict = self.context_manager.get_terminology_string()
            segments = [{"id": i+1, "text": text} for i, text in enumerate(texts)]
            
            # 选择翻译方法
            if TranslationConfig.ENABLE_STREAMING and len(texts) <= 5:
                # 流式处理
                prompt = self.streaming_prompt.format(
                    context_info=context_info,
                    terminology_dict=terminology_dict,
                    segments=json.dumps(segments, ensure_ascii=False)
                )
                logger.info(f"🌊 流式上下文翻译: {len(texts)} 条")
                translated_segments = await self._stream_translate(prompt)
            else:
                # 批量处理
                prompt = self.contextual_prompt.format(
                    previous_context=context_info,
                    terminology_dict=terminology_dict,
                    current_segments=json.dumps(segments, ensure_ascii=False),
                    segment_count=len(texts)
                )
                logger.info(f"🧠 上下文批量翻译: {len(texts)} 条")
                
                session = await self._get_session()
                data = {
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": TranslationConfig.get_model_options()
                }
                
                async with session.post(f"{self.api_url}/api/generate", json=data) as response:
                    if response.status != 200:
                        raise Exception(f"API请求失败: {response.status}")
                    
                    result = await response.json()
                    translated_text = self._clean_translation(result.get("response", ""))
                    translated_segments = self._parse_contextual_response(translated_text, len(texts))
            
            # 检查结果
            if len(translated_segments) != len(texts):
                logger.warning("⚠️ 上下文翻译数量不匹配，降级处理")
                return await self.translate_batch(texts)
            
            # 更新上下文和性能数据
            quality_results = self._check_translation_quality(texts, translated_segments)
            quality_score = sum(quality_results) / len(quality_results) if quality_results else 0
            
            for original, translated in zip(texts, translated_segments):
                self.context_manager.add_translation(original, translated)
            
            response_time = time.time() - start_time
            success_rate = quality_score
            
            if self.adaptive_processor:
                self.adaptive_processor.record_performance(
                    len(texts), response_time, success_rate, quality_score
                )
                self.batch_size = self.adaptive_processor.get_optimal_batch_size()
            
            logger.info(f"✅ 上下文翻译完成: 质量 {quality_score:.2f}, 时间 {response_time:.1f}s")
            return translated_segments
            
        except Exception as e:
            logger.error(f"❌ 上下文翻译失败: {str(e)}")
            return await self.translate_batch(texts)

    async def _stream_translate(self, prompt: str) -> List[str]:
        """流式翻译实现"""
        session = await self._get_session()
        
        data = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "options": TranslationConfig.get_streaming_options()
        }
        
        buffer = ""
        segments = []
        
        try:
            async with session.post(f"{self.api_url}/api/generate", json=data) as response:
                if response.status != 200:
                    raise Exception(f"流式请求失败: {response.status}")
                
                async for line in response.content:
                    if line:
                        try:
                            chunk = json.loads(line.decode('utf-8'))
                            if 'response' in chunk:
                                buffer += chunk['response']
                                
                                while '\n' in buffer:
                                    line_content, buffer = buffer.split('\n', 1)
                                    line_content = line_content.strip()
                                    
                                    if line_content:
                                        try:
                                            segment_data = json.loads(line_content)
                                            if 'id' in segment_data and 'text' in segment_data:
                                                segments.append(segment_data)
                                        except json.JSONDecodeError:
                                            pass
                            
                            if chunk.get('done', False):
                                break
                        except json.JSONDecodeError:
                            continue
        
        except Exception as e:
            logger.error(f"❌ 流式翻译失败: {str(e)}")
            raise
        
        if segments:
            segments.sort(key=lambda x: x.get('id', 0))
            return [seg['text'] for seg in segments]
        else:
            return self._fallback_parse_streaming_result(buffer)
    
    def _fallback_parse_streaming_result(self, buffer: str) -> List[str]:
        """流式结果后备解析"""
        buffer = self._clean_translation(buffer)
        lines = [line.strip() for line in buffer.split('\n') if line.strip()]
        
        translations = []
        for line in lines:
            if (len(line) > 3 and not line.isdigit() and self._is_chinese_text(line)):
                translations.append(line)
        
        return translations

    def _parse_contextual_response(self, response_text: str, expected_count: int) -> List[str]:
        """解析上下文翻译响应"""
        translations = []
        
        # 尝试JSON解析
        lines = response_text.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('{"id"') and '"text"' in line:
                try:
                    segment_data = json.loads(line)
                    if 'text' in segment_data:
                        translations.append(segment_data['text'])
                except json.JSONDecodeError:
                    continue
        
        if len(translations) == expected_count:
            return translations
        
        # 后备解析方法
        if "---" in response_text:
            parts = response_text.split("---")
            translations = [part.strip() for part in parts if part.strip()]
        else:
            lines = response_text.split('\n')
            translations = []
            for line in lines:
                line = line.strip()
                if (line and not line.isdigit() and len(line) > 3 and 
                    self._is_chinese_text(line) and not line.startswith('#')):
                    translations.append(line)
        
        # 确保数量匹配
        if len(translations) > expected_count:
            translations = translations[:expected_count]
        elif len(translations) < expected_count:
            while len(translations) < expected_count:
                translations.append(translations[-1] if translations else "翻译失败")
        
        return translations

    async def translate_batch(self, texts: List[str]) -> List[str]:
        """传统批量翻译（兼容性保留）"""
        max_retries = TranslationConfig.MAX_RETRIES
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                session = await self._get_session()
                
                segments = [{"id": i+1, "text": text} for i, text in enumerate(texts)]
                prompt = self.translation_prompt.format(
                    segments=json.dumps(segments, ensure_ascii=False),
                    segment_count=len(texts)
                )
                
                data = {
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": TranslationConfig.get_model_options()
                }
                
                async with session.post(f"{self.api_url}/api/generate", json=data) as response:
                    if response.status != 200:
                        raise Exception(f"API请求失败: {response.status}")
                    
                    result = await response.json()
                    translated_text = self._clean_translation(result.get("response", ""))
                    
                    # 解析结果
                    if len(texts) == 1:
                        translated_segments = [translated_text]
                    else:
                        try:
                            response_data = json.loads(translated_text)
                            if "translations" in response_data:
                                translations = sorted(response_data["translations"], key=lambda x: x["id"])
                                translated_segments = [t["text"] for t in translations]
                            else:
                                raise ValueError("无效响应格式")
                        except json.JSONDecodeError:
                            # 后备解析
                            if "---" in translated_text:
                                translated_segments = [s.strip() for s in translated_text.split("---") if s.strip()]
                            else:
                                translated_segments = [s.strip() for s in translated_text.split("\n") 
                                                     if s.strip() and not s.isdigit()]
                
                # 检查数量
                if len(translated_segments) != len(texts):
                    retry_count += 1
                    if retry_count < max_retries:
                        await asyncio.sleep(TranslationConfig.BASE_RETRY_DELAY * retry_count)
                        continue
                    else:
                        raise Exception(f"段落数量不匹配: 期望{len(texts)}, 实际{len(translated_segments)}")
                
                return translated_segments
                    
            except Exception as e:
                logger.error(f"❌ 批量翻译错误: {str(e)}")
                retry_count += 1
                if retry_count < max_retries:
                    await asyncio.sleep(TranslationConfig.BASE_RETRY_DELAY * retry_count)
                    continue
                else:
                    logger.error(f"❌ 翻译失败，返回原文")
                    return texts

    async def translate_subtitles(self, subtitles: List[Dict[str, Any]], 
                                 video_name: str,
                                 output_path: str = None,
                                 original_path: str = None) -> List[Dict[str, Any]]:
        """智能字幕翻译主方法"""
        
        # 测试连接
        logger.info("🔌 测试Ollama API连接...")
        if not await self.test_connection():
            raise Exception("无法连接到Ollama API")
        
        try:
            # 设置路径
            temp_dir = os.path.join("temp", video_name)
            os.makedirs(temp_dir, exist_ok=True)
            
            file_hash = get_file_hash(video_name)
            if output_path is None:
                output_path = os.path.join(temp_dir, f"{file_hash}_subtitles_zh.srt")
            if original_path is None:
                original_path = os.path.join(temp_dir, f"{file_hash}_subtitles_en.srt")
            
            translated_subtitles = []
            total = len(subtitles)
            successful_translations = 0
            failed_translations = 0
            
            logger.info(f"🚀 开始智能翻译: 总计 {total} 条字幕")
            logger.info(f"  📊 批次大小: {self.batch_size}")
            logger.info(f"  🧠 上下文: {'✅' if self.context_manager else '❌'}")
            logger.info(f"  🌊 流式: {'✅' if TranslationConfig.ENABLE_STREAMING else '❌'}")
            logger.info(f"  📈 自适应: {'✅' if self.adaptive_processor else '❌'}")
            
            # 进度条翻译
            with tqdm(total=total, desc="🌍 智能翻译中", unit="字幕") as pbar:
                i = 0
                while i < total:
                    current_batch_size = self.batch_size
                    batch = subtitles[i:i + current_batch_size]
                    
                    # 验证数据
                    valid_batch = [sub for sub in batch if "text" in sub]
                    if not valid_batch:
                        pbar.update(len(batch))
                        i += current_batch_size
                        continue
                    
                    batch_texts = [sub["text"] for sub in valid_batch]
                    
                    try:
                        # 智能翻译
                        if TranslationConfig.ENABLE_CONTEXT and self.context_manager:
                            translated_texts = await self.translate_batch_with_context(batch_texts)
                        else:
                            translated_texts = await self.translate_batch(batch_texts)
                        
                        # 处理结果
                        quality_results = self._check_translation_quality(batch_texts, translated_texts)
                        
                        for j, (subtitle, translated_text) in enumerate(zip(valid_batch, translated_texts)):
                            translated_subtitle = subtitle.copy()
                            translated_subtitle["text"] = translated_text
                            translated_subtitle["original_text"] = subtitle["text"]
                            translated_subtitle["translation_quality"] = "good" if quality_results[j] else "poor"
                            translated_subtitle["context_used"] = self.context_manager is not None
                            
                            translated_subtitles.append(translated_subtitle)
                            
                            if quality_results[j]:
                                successful_translations += 1
                            else:
                                failed_translations += 1
                            
                            pbar.update(1)
                        
                        # 批次间延迟
                        if i + current_batch_size < total:
                            await asyncio.sleep(TranslationConfig.BATCH_DELAY)
                        
                    except Exception as e:
                        logger.error(f"❌ 批次翻译失败: {str(e)}")
                        
                        # 失败保留原文
                        for subtitle in valid_batch:
                            translated_subtitle = subtitle.copy()
                            translated_subtitle["original_text"] = subtitle["text"]
                            translated_subtitle["translation_quality"] = "failed"
                            translated_subtitles.append(translated_subtitle)
                            failed_translations += 1
                            pbar.update(1)
                    
                    # 定期保存
                    if len(translated_subtitles) % TranslationConfig.PROGRESS_SAVE_INTERVAL == 0:
                        try:
                            self.save_subtitles(translated_subtitles, output_path, original_path)
                        except Exception as e:
                            logger.warning(f"⚠️ 保存进度失败: {str(e)}")
                    
                    i += current_batch_size
            
            # 最终保存
            self.save_subtitles(translated_subtitles, output_path, original_path)
            
            # 统计报告
            success_rate = (successful_translations / total * 100) if total > 0 else 0
            logger.info(f"🎉 翻译完成!")
            logger.info(f"  📊 总计: {total} 条")
            logger.info(f"  ✅ 成功: {successful_translations} ({success_rate:.1f}%)")
            logger.info(f"  ❌ 失败: {failed_translations}")
            logger.info(f"  💾 文件: {output_path}")
            
            if self.context_manager:
                logger.info(f"  🧠 术语: {len(self.context_manager.terminology_dict)} 个")
            
            await self.close()
            return translated_subtitles
            
        except Exception as e:
            logger.error(f"❌ 字幕翻译失败: {str(e)}")
            await self.close()
            raise

    def save_subtitles(self, subtitles: List[Dict[str, Any]], output_path: str, original_path: str):
        """保存字幕文件"""
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # 保存SRT
            with open(output_path, "w", encoding="utf-8") as f:
                for i, subtitle in enumerate(subtitles, 1):
                    start_time = self.format_time(subtitle["start"])
                    end_time = self.format_time(subtitle["end"])
                    f.write(f"{i}\n{start_time} --> {end_time}\n{subtitle['text']}\n\n")
            
            # 保存JSON
            json_path = output_path.replace("_subtitles_zh.srt", "_subtitles_zh.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(subtitles, f, ensure_ascii=False, indent=2)
            
            logger.info(f"💾 字幕已保存: {output_path}")
            
        except Exception as e:
            logger.error(f"❌ 保存失败: {str(e)}")
            raise

    def format_time(self, seconds: float) -> str:
        """格式化时间为SRT格式"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = seconds % 60
        milliseconds = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{int(seconds):02d},{milliseconds:03d}" 