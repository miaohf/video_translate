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
    STREAMING_TRANSLATION_TEMPLATE,
    THREE_STEP_TRANSLATION_TEMPLATE,
    THREE_STEP_STREAMING_TEMPLATE,
    REFLECTION_TEMPLATE
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
        # 根据配置选择API类型
        if settings.TRANSLATION_PROVIDER.lower() == "deepseek":
            self.api_url = settings.DEEPSEEK_API_URL
            self.model = settings.DEEPSEEK_MODEL
            self.api_type = "deepseek"
            # DeepSeek不需要OllamaLLM实例
            self.llm = None
        else:
            self.api_url = settings.OLLAMA_API_URL
            self.model = settings.OLLAMA_MODEL
            self.api_type = "ollama"
            self.llm = OllamaLLM(model=self.model)
        
        self._session = None
        
        # 初始化功能模块 - 上下文模式始终启用
        self.context_manager = ContextManager()  # 上下文模式始终启用
        
        # 单条模式：强制设置批次大小为1
        self.batch_size = 1
        self.adaptive_processor = None  # 单条模式下禁用自适应处理器
        
        # 初始化模板 - 上下文模式始终启用
        self.contextual_prompt = PromptTemplate(
            input_variables=["previous_context", "terminology_dict", 
                           "current_segments", "segment_count"],
            template=CONTEXTUAL_TRANSLATION_TEMPLATE
        )
        
        self.streaming_prompt = PromptTemplate(
            input_variables=["context_info", "terminology_dict", "segments"],
            template=STREAMING_TRANSLATION_TEMPLATE
        )
        
        # 三步翻译法模板初始化
        if TranslationConfig.ENABLE_THREE_STEP_TRANSLATION:
            self.three_step_prompt = PromptTemplate(
                input_variables=["previous_context", "terminology_dict", 
                               "current_segments", "segment_count"],
                template=THREE_STEP_TRANSLATION_TEMPLATE
            )
            
            self.three_step_streaming_prompt = PromptTemplate(
                input_variables=["context_info", "terminology_dict", "segments"],
                template=THREE_STEP_STREAMING_TEMPLATE
            )
            
            self.reflection_prompt = PromptTemplate(
                input_variables=["original_text", "current_translation", 
                               "context_info", "terminology_dict"],
                template=REFLECTION_TEMPLATE
            )
        
        logger.info(f"🚀 单条异步翻译服务已初始化")
        logger.info(f"  API类型: {self.api_type.upper()}")
        logger.info(f"  模型: {self.model}")
        logger.info(f"  API地址: {self.api_url}")
        logger.info(f"  处理模式: 单条异步")
        logger.info(f"  上下文功能: ✅ 始终启用")
        logger.info(f"  流式处理: {'✅ 启用' if TranslationConfig.ENABLE_STREAMING else '❌ 禁用'}")
        logger.info(f"  三步翻译法: {'✅ 启用' if TranslationConfig.ENABLE_THREE_STEP_TRANSLATION else '❌ 禁用'}")
        logger.info(f"  翻译模式: {TranslationConfig.TRANSLATION_MODE}")

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建HTTP会话"""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=10, limit_per_host=5, ttl_dns_cache=300,
                use_dns_cache=True, keepalive_timeout=30, enable_cleanup_closed=True
            )
            
            timeout = aiohttp.ClientTimeout(
                total=TranslationConfig.REQUEST_TIMEOUT, connect=30, sock_read=TranslationConfig.REQUEST_TIMEOUT
            )
            
            self._session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        return self._session

    async def close(self):
        """关闭HTTP会话"""
        if self._session and not self._session.closed:
            await self._session.close()
            
    def _prepare_api_request(self, prompt: str, options: dict = None) -> tuple:
        """准备API请求数据，支持Ollama和DeepSeek两种格式"""
        if self.api_type == "deepseek":
            # DeepSeek API格式
            data = {
                "model": self.model,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": options.get("temperature", 0.1) if options else 0.1,
                "max_tokens": options.get("max_tokens", 2048) if options else 2048
            }
            
            headers = {
                "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            
            url = f"{self.api_url}/v1/chat/completions"
            
        else:
            # Ollama API格式
            data = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": options or {"temperature": 0.1}
            }
            
            headers = {"Content-Type": "application/json"}
            url = f"{self.api_url}/api/generate"
        
        return url, data, headers

    def _create_simple_translation_prompt(self, text: str) -> str:
        """为DeepSeek创建简化的翻译提示词"""
        return f"""你是一位专业的英中翻译专家，正在翻译字幕。

## 当前待翻译字幕：
{text}

## 翻译要求：
1. 将英文翻译成中文
2. 保持自然流畅的中文表达
3. 控制句子长度，翻译后的句子长短应与原文接近
4. 使用简洁精炼的中文

## 输出格式：
请直接输出中文翻译，不要包含任何其他内容。

开始翻译："""

    def _parse_api_response(self, response_data: dict) -> str:
        """解析API响应，支持Ollama和DeepSeek两种格式"""
        if self.api_type == "deepseek":
            # DeepSeek响应格式
            if "choices" in response_data and len(response_data["choices"]) > 0:
                return response_data["choices"][0]["message"]["content"]
            else:
                raise ValueError("DeepSeek API响应格式无效")
        else:
            # Ollama响应格式
            return response_data.get("response", "")

    async def test_connection(self) -> bool:
        """测试API连接 - 支持Ollama和DeepSeek两种API"""
        try:
            session = await self._get_session()
            
            # 打印API信息
            logger.info(f"🔌 测试{self.api_type.upper()} API连接...")
            logger.info(f"  模型: {self.model}")
            logger.info(f"  API地址: {self.api_url}")
            
            # 检查DeepSeek API密钥
            if self.api_type == "deepseek" and not settings.DEEPSEEK_API_KEY:
                logger.error("❌ DeepSeek API密钥未配置")
                return False
            
            # 准备测试请求
            url, data, headers = self._prepare_api_request("测试连接", {"temperature": 0.1, "max_tokens": 10})
            
            async with session.post(url, json=data, headers=headers) as response:
                if response.status == 200:
                    logger.info(f"✅ {self.api_type.upper()} API连接测试成功")
                    return True
                else:
                    logger.error(f"❌ {self.api_type.upper()} API连接失败: 状态码 {response.status}")
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

    async def translate_single_subtitle(self, text: str) -> str:
        """单条字幕异步翻译方法"""
        start_time = time.time()
        
        # 对于DeepSeek API，使用简化的翻译方法
        if self.api_type == "deepseek":
            try:
                logger.debug(f"🧠 DeepSeek单条翻译")
                
                # 使用简化的翻译提示词
                prompt = self._create_simple_translation_prompt(text)
                
                session = await self._get_session()
                url, data, headers = self._prepare_api_request(prompt, TranslationConfig.get_model_options())
                
                async with session.post(url, json=data, headers=headers) as response:
                    if response.status != 200:
                        raise Exception(f"DeepSeek API请求失败: {response.status}")
                    
                    result = await response.json()
                    translated_text = self._clean_translation(self._parse_api_response(result))
                    
                    # 更新上下文
                    if self.context_manager:
                        self.context_manager.add_translation(text, translated_text)
                    
                    logger.debug(f"✅ DeepSeek单条翻译完成")
                    return translated_text
                    
            except Exception as e:
                logger.error(f"❌ DeepSeek单条翻译失败: {str(e)}")
                return text
        
        # 对于Ollama API，使用原有的复杂逻辑
        if not self.context_manager:
            # 如果没有上下文管理器，使用基础翻译
            result = await self.translate_batch([text])
            return result[0] if result else text
        
        try:
            context_info = self.context_manager.get_context_string()
            terminology_dict = self.context_manager.get_terminology_string()
            segments = [{"id": 1, "text": text}]
            
            # 根据翻译模式选择方法
            if TranslationConfig.TRANSLATION_MODE == "contextual_three_step":
                # 三步翻译法
                if TranslationConfig.ENABLE_STREAMING:
                    prompt = self.three_step_streaming_prompt.format(
                        context_info=context_info,
                        terminology_dict=terminology_dict,
                        segments=json.dumps(segments, ensure_ascii=False)
                    )
                    logger.debug(f"🌊 单条三步流式翻译")
                    translated_segments = await self._stream_translate(prompt)
                else:
                    prompt = self.three_step_prompt.format(
                        previous_context=context_info,
                        terminology_dict=terminology_dict,
                        current_segments=json.dumps(segments, ensure_ascii=False),
                        segment_count=1
                    )
                    logger.debug(f"🧠 单条三步翻译")
                    
                    session = await self._get_session()
                    url, data, headers = self._prepare_api_request(prompt, TranslationConfig.get_three_step_options())
                    
                    async with session.post(url, json=data, headers=headers) as response:
                        if response.status != 200:
                            raise Exception(f"三步翻译API请求失败: {response.status}")
                        
                        result = await response.json()
                        translated_text = self._clean_translation(self._parse_api_response(result))
                        translated_segments = self._parse_contextual_response(translated_text, 1)
            else:
                # 上下文直译法
                if TranslationConfig.ENABLE_STREAMING:
                    prompt = self.streaming_prompt.format(
                        context_info=context_info,
                        terminology_dict=terminology_dict,
                        segments=json.dumps(segments, ensure_ascii=False)
                    )
                    logger.debug(f"🌊 单条流式翻译")
                    translated_segments = await self._stream_translate(prompt)
                else:
                    prompt = self.contextual_prompt.format(
                        previous_context=context_info,
                        terminology_dict=terminology_dict,
                        current_segments=json.dumps(segments, ensure_ascii=False),
                        segment_count=1
                    )
                    logger.debug(f"🧠 单条上下文翻译")
                    
                    session = await self._get_session()
                    url, data, headers = self._prepare_api_request(prompt, TranslationConfig.get_model_options())
                    
                    async with session.post(url, json=data, headers=headers) as response:
                        if response.status != 200:
                            raise Exception(f"API请求失败: {response.status}")
                        
                        result = await response.json()
                        translated_text = self._clean_translation(self._parse_api_response(result))
                        translated_segments = self._parse_contextual_response(translated_text, 1)
            
            # 检查结果
            if not translated_segments or len(translated_segments) != 1:
                raise Exception(f"单条翻译数量不匹配: 期望1个，实际{len(translated_segments) if translated_segments else 0}个")
            
            translated_text = translated_segments[0]
            
            # 更新上下文和性能数据
            quality_result = self._check_translation_quality([text], [translated_text])
            quality_score = quality_result[0] if quality_result else False
            
            self.context_manager.add_translation(text, translated_text)
            
            response_time = time.time() - start_time
            success_rate = 1.0 if quality_score else 0.0
            
            if self.adaptive_processor:
                self.adaptive_processor.record_performance(
                    1, response_time, success_rate, 1.0 if quality_score else 0.0
                )
            
            logger.debug(f"✅ 单条翻译完成: 质量 {quality_score}, 时间 {response_time:.1f}s")
            return translated_text
            
        except Exception as e:
            logger.error(f"❌ 单条翻译失败: {str(e)}")
            # 返回原文
            return text

    async def translate_batch_with_context(self, texts: List[str], current_batch_size: int = None) -> List[str]:
        """基于上下文的智能翻译"""
        start_time = time.time()
        
        if not self.context_manager:
            return await self.translate_batch(texts)
        
        # 使用传入的批次大小或当前批次大小
        if current_batch_size is None:
            current_batch_size = len(texts)
        
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
                logger.info(f"🌊 流式上下文翻译: {len(texts)} 条 (批次大小: {current_batch_size})")
                translated_segments = await self._stream_translate(prompt)
            else:
                # 批量处理
                prompt = self.contextual_prompt.format(
                    previous_context=context_info,
                    terminology_dict=terminology_dict,
                    current_segments=json.dumps(segments, ensure_ascii=False),
                    segment_count=len(texts)
                )
                logger.info(f"🧠 上下文批量翻译: {len(texts)} 条 (批次大小: {current_batch_size})")
                
                session = await self._get_session()
                url, data, headers = self._prepare_api_request(prompt, TranslationConfig.get_model_options())
                
                async with session.post(url, json=data, headers=headers) as response:
                    if response.status != 200:
                        raise Exception(f"API请求失败: {response.status}")
                    
                    result = await response.json()
                    translated_text = self._clean_translation(self._parse_api_response(result))
                    translated_segments = self._parse_contextual_response(translated_text, len(texts))
            
            # 检查结果
            if len(translated_segments) != len(texts):
                if current_batch_size > 1:
                    # 降级：减少批次大小到1，但保持上下文翻译模式
                    logger.warning(f"⚠️ 上下文翻译数量不匹配 ({len(translated_segments)} vs {len(texts)})，降级到单条处理")
                    # 递归调用，但使用单条处理
                    single_results = []
                    for text in texts:
                        try:
                            single_result = await self.translate_batch_with_context([text], current_batch_size=1)
                            single_results.extend(single_result)
                        except Exception as e:
                            logger.error(f"❌ 单条翻译失败: {str(e)}")
                            # 抛出异常，让上层处理失败情况
                            raise Exception(f"单条翻译失败: {str(e)}")
                    return single_results
                else:
                    # 已经是单条处理但仍然失败
                    raise Exception(f"单条翻译数量不匹配: 期望1个，实际{len(translated_segments)}个")
            
            # 更新上下文和性能数据
            quality_results = self._check_translation_quality(texts, translated_segments)
            quality_score = sum(quality_results) / len(quality_results) if quality_results else 0
            
            for original, translated in zip(texts, translated_segments):
                self.context_manager.add_translation(original, translated)
            
            response_time = time.time() - start_time
            success_rate = quality_score
            
            if self.adaptive_processor:
                self.adaptive_processor.record_performance(
                    current_batch_size, response_time, success_rate, quality_score
                )
                # 不在这里更新batch_size，由上层调用者控制
            
            logger.info(f"✅ 上下文翻译完成: 质量 {quality_score:.2f}, 时间 {response_time:.1f}s, 批次 {current_batch_size}")
            return translated_segments
            
        except Exception as e:
            logger.error(f"❌ 上下文翻译失败 (批次大小: {current_batch_size}): {str(e)}")
            # 不再降级到传统翻译，直接抛出异常让上层处理
            raise

    async def _stream_translate(self, prompt: str) -> List[str]:
        """流式翻译实现"""
        session = await self._get_session()
        
        # 注意：流式翻译目前只支持Ollama API
        if self.api_type == "deepseek":
            logger.warning("⚠️ DeepSeek API暂不支持流式翻译，降级到普通翻译")
            # 降级到普通翻译
            url, data, headers = self._prepare_api_request(prompt, TranslationConfig.get_streaming_options())
            async with session.post(url, json=data, headers=headers) as response:
                if response.status != 200:
                    raise Exception(f"流式降级请求失败: {response.status}")
                
                result = await response.json()
                translated_text = self._clean_translation(self._parse_api_response(result))
                return self._fallback_parse_streaming_result(translated_text)
        
        # Ollama流式翻译
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
                                                # 确保提取的是纯文本
                                                text_content = segment_data['text']
                                                if isinstance(text_content, str) and text_content.startswith('{"'):
                                                    # text字段本身是JSON字符串，需要进一步解析
                                                    try:
                                                        inner_json = json.loads(text_content)
                                                        if 'text' in inner_json:
                                                            text_content = inner_json['text']
                                                    except json.JSONDecodeError:
                                                        pass
                                                segment_data['text'] = text_content
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
                # 使用_extract_text_from_part方法处理可能的嵌套JSON
                clean_text = self._extract_text_from_part(line)
                translations.append(clean_text)
        
        return translations

    def _parse_contextual_response(self, response_text: str, expected_count: int) -> List[str]:
        """解析上下文翻译响应"""
        translations = []
        
        # 清理响应文本
        response_text = self._clean_translation(response_text)
        
        # 尝试JSON解析
        lines = response_text.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('{"id"') and '"text"' in line:
                try:
                    segment_data = json.loads(line)
                    if 'text' in segment_data:
                        # 确保提取的是纯文本，如果text字段包含JSON，进一步解析
                        text_content = segment_data['text']
                        if isinstance(text_content, str) and text_content.startswith('{"'):
                            # text字段本身是JSON字符串，需要进一步解析
                            try:
                                inner_json = json.loads(text_content)
                                if 'text' in inner_json:
                                    text_content = inner_json['text']
                            except json.JSONDecodeError:
                                pass  # 如果解析失败，使用原始文本
                        translations.append(text_content)
                except json.JSONDecodeError:
                    continue
        
        if len(translations) == expected_count:
            return translations
        
        # 后备解析方法1：尝试解析嵌套的JSON格式
        logger.warning(f"主要解析失败，尝试后备解析方法。期望 {expected_count} 个，获得 {len(translations)} 个")
        
        # 重新解析，寻找所有可能的JSON对象
        translations = []
        json_pattern = r'\{"id":\s*\d+,\s*"text":\s*"([^"]+)"\}'
        matches = re.findall(json_pattern, response_text)
        if matches and len(matches) == expected_count:
            return matches
        
        # 后备解析方法2：基于分隔符
        if "---" in response_text:
            parts = response_text.split("---")
            translations = [self._extract_text_from_part(part) for part in parts if part.strip()]
        else:
            lines = response_text.split('\n')
            translations = []
            for line in lines:
                line = line.strip()
                if (line and not line.isdigit() and len(line) > 3 and 
                    self._is_chinese_text(line) and not line.startswith('#')):
                    # 进一步清理可能的JSON格式
                    clean_text = self._extract_text_from_part(line)
                    if clean_text:
                        translations.append(clean_text)
        
        # 确保数量匹配
        if len(translations) > expected_count:
            translations = translations[:expected_count]
        elif len(translations) < expected_count:
            while len(translations) < expected_count:
                translations.append(translations[-1] if translations else "翻译失败")
        
        return translations

    def _extract_text_from_part(self, text_part: str) -> str:
        """从文本片段中提取纯文本内容"""
        text_part = text_part.strip()
        
        # 如果是JSON格式，尝试解析
        if text_part.startswith('{') and text_part.endswith('}'):
            try:
                json_data = json.loads(text_part)
                if 'text' in json_data:
                    return json_data['text']
            except json.JSONDecodeError:
                pass
        
        # 移除可能的JSON包装
        if text_part.startswith('{"id"') and '"text"' in text_part:
            try:
                json_data = json.loads(text_part)
                if 'text' in json_data:
                    text_content = json_data['text']
                    # 如果text字段本身还是JSON，继续解析
                    if isinstance(text_content, str) and text_content.startswith('{"'):
                        try:
                            inner_json = json.loads(text_content)
                            if 'text' in inner_json:
                                return inner_json['text']
                        except json.JSONDecodeError:
                            pass
                    return text_content
            except json.JSONDecodeError:
                pass
        
        # 使用正则表达式提取文本
        patterns = [
            r'"text":\s*"([^"]+)"',  # 提取JSON中的text字段
            r'：\s*"([^"]+)"',       # 中文冒号后的引号内容
            r':\s*"([^"]+)"',        # 英文冒号后的引号内容
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text_part)
            if matches:
                return matches[0]
        
        # 如果都没有匹配，返回清理后的文本
        # 移除常见的JSON符号和格式
        clean_text = re.sub(r'\{"id":\s*\d+,\s*"text":\s*"', '', text_part)
        clean_text = re.sub(r'"\}$', '', clean_text)
        clean_text = re.sub(r'^[^"]*"', '', clean_text)
        clean_text = re.sub(r'"[^"]*$', '', clean_text)
        
        return clean_text.strip() if clean_text.strip() else text_part

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
                
                url, data, headers = self._prepare_api_request(prompt, TranslationConfig.get_model_options())
                
                async with session.post(url, json=data, headers=headers) as response:
                    if response.status != 200:
                        raise Exception(f"API请求失败: {response.status}")
                    
                    result = await response.json()
                    translated_text = self._clean_translation(self._parse_api_response(result))
                    
                    # 解析结果
                    if len(texts) == 1:
                        # 单个文本也需要用_extract_text_from_part处理可能的嵌套JSON
                        translated_segments = [self._extract_text_from_part(translated_text)]
                    else:
                        try:
                            response_data = json.loads(translated_text)
                            if "translations" in response_data:
                                translations = sorted(response_data["translations"], key=lambda x: x["id"])
                                # 使用_extract_text_from_part处理每个text字段，防止嵌套JSON
                                translated_segments = [self._extract_text_from_part(t["text"]) for t in translations]
                            else:
                                raise ValueError("无效响应格式")
                        except json.JSONDecodeError:
                            # 后备解析 - 使用_extract_text_from_part处理嵌套JSON
                            if "---" in translated_text:
                                parts = [s.strip() for s in translated_text.split("---") if s.strip()]
                                translated_segments = [self._extract_text_from_part(part) for part in parts]
                            else:
                                lines = [s.strip() for s in translated_text.split("\n") 
                                        if s.strip() and not s.isdigit()]
                                translated_segments = [self._extract_text_from_part(line) for line in lines]
                
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
        """智能字幕翻译主方法 - 单条异步处理"""
        
        # 设置路径
        temp_dir = os.path.join("temp", video_name)
        os.makedirs(temp_dir, exist_ok=True)
        
        file_hash = get_file_hash(video_name)
        if output_path is None:
            output_path = os.path.join(temp_dir, f"{file_hash}_subtitles_zh.srt")
        if original_path is None:
            original_path = os.path.join(temp_dir, f"{file_hash}_subtitles_en.srt")
            
        # 检查是否已存在带音频的翻译文件
        audio_json_path = os.path.join(temp_dir, f"{file_hash}_subtitles_zh_with_audio.json")
        if os.path.exists(audio_json_path):
            logger.info(f"🎯 发现已存在翻译文件: {audio_json_path}")
            try:
                with open(audio_json_path, "r", encoding="utf-8") as f:
                    existing_subtitles = json.load(f)
                logger.info(f"✅ 成功加载已存在的翻译: {len(existing_subtitles)} 条字幕")
                return existing_subtitles
            except Exception as e:
                logger.warning(f"⚠️ 读取已存在翻译文件失败: {str(e)}，将重新翻译")
        
        # 测试连接
        logger.info("🔌 测试Ollama API连接...")
        if not await self.test_connection():
            raise Exception("无法连接到Ollama API")
            
        try:
            # 初始化统计和状态
            translated_subtitles = []
            failed_items = []  # 失败的字幕项目
            successful_translations = 0
            failed_translations = 0
            total = len(subtitles)
            
            logger.info(f"🚀 开始单条异步翻译: 总计 {total} 条字幕")
            logger.info(f"  🧠 上下文: {'✅' if self.context_manager else '❌'}")
            logger.info(f"  🌊 流式: {'✅' if TranslationConfig.ENABLE_STREAMING else '❌'}")
            
            # 单条翻译处理
            logger.info("🌍 开始单条异步翻译")
            with tqdm(total=total, desc="🌍 单条翻译中", unit="字幕") as pbar:
                for i, subtitle in enumerate(subtitles):
                    # 验证数据
                    if "text" not in subtitle:
                        pbar.update(1)
                        continue
                        
                    text = subtitle["text"]
                    
                    try:
                        # 单条异步翻译
                        translated_text = await self.translate_single_subtitle(text)
                        
                        # 成功处理结果
                        quality_results = self._check_translation_quality([text], [translated_text])
                        
                        translated_subtitle = subtitle.copy()
                        translated_subtitle["text"] = translated_text
                        translated_subtitle["original_text"] = subtitle["text"]
                        translated_subtitle["translation_quality"] = "good" if quality_results[0] else "poor"
                        translated_subtitle["context_used"] = self.context_manager is not None
                        translated_subtitle["batch_size_used"] = 1
                        translated_subtitle["original_index"] = i
                        
                        translated_subtitles.append(translated_subtitle)
                        
                        if quality_results[0]:
                            successful_translations += 1
                        else:
                            failed_translations += 1
                        
                        logger.debug(f"✅ 单条翻译成功: 索引 {i}")
                        
                    except Exception as e:
                        logger.error(f"❌ 单条翻译失败: 索引 {i}, 错误: {str(e)}")
                        
                        # 标记失败的字幕
                        failed_item = {
                            "subtitle": subtitle,
                            "original_index": i,
                            "error": str(e)
                        }
                        failed_items.append(failed_item)
                        failed_translations += 1
                        
                        # 保留原文
                        translated_subtitle = subtitle.copy()
                        translated_subtitle["original_text"] = subtitle["text"]
                        translated_subtitle["translation_quality"] = "failed"
                        translated_subtitle["context_used"] = False
                        translated_subtitle["batch_size_used"] = 1
                        translated_subtitle["original_index"] = i
                        translated_subtitle["translation_error"] = str(e)
                        
                        translated_subtitles.append(translated_subtitle)
                    
                    pbar.update(1)
                    
                    # 单条间延迟
                    if i + 1 < total:
                        await asyncio.sleep(TranslationConfig.BATCH_DELAY)
                    
                    # 定期保存
                    if len(translated_subtitles) % TranslationConfig.PROGRESS_SAVE_INTERVAL == 0:
                        try:
                            self.save_subtitles(translated_subtitles, output_path, original_path)
                        except Exception as e:
                            logger.warning(f"⚠️ 保存进度失败: {str(e)}")
            
            # 第二轮：失败重试
            if failed_items:
                logger.info(f"🔄 开始失败重试: {len(failed_items)} 条失败字幕")
                retry_success = 0
                
                # 创建重试结果映射，避免重复
                retry_results = {}
                
                with tqdm(total=len(failed_items), desc="🔄 重试失败字幕", unit="字幕") as retry_pbar:
                    for failed_item in failed_items:
                        try:
                            subtitle = failed_item["subtitle"]
                            text = subtitle["text"]
                            original_index = failed_item["original_index"]
                            
                            # 单条重试
                            translated_text = await self.translate_single_subtitle(text)
                            
                            # 重试成功
                            quality_results = self._check_translation_quality([text], [translated_text])
                            
                            translated_subtitle = subtitle.copy()
                            translated_subtitle["text"] = translated_text
                            translated_subtitle["original_text"] = subtitle["text"]
                            translated_subtitle["translation_quality"] = "good" if quality_results[0] else "poor"
                            translated_subtitle["context_used"] = self.context_manager is not None
                            translated_subtitle["batch_size_used"] = 1
                            translated_subtitle["original_index"] = original_index
                            translated_subtitle["retry_success"] = True
                            
                            # 存储重试结果，而不是直接追加
                            retry_results[original_index] = translated_subtitle
                            retry_success += 1
                            failed_translations -= 1
                            successful_translations += 1
                            
                            logger.debug(f"✅ 重试成功: 索引 {original_index}")
                        
                        except Exception as e:
                            logger.error(f"❌ 重试失败: 索引 {failed_item['original_index']}, 错误: {str(e)}")
                            
                            # 重试失败，保留原文
                            subtitle = failed_item["subtitle"]
                            translated_subtitle = subtitle.copy()
                            translated_subtitle["original_text"] = subtitle["text"]
                            translated_subtitle["translation_quality"] = "failed"
                            translated_subtitle["context_used"] = False
                            translated_subtitle["batch_size_used"] = 1
                            translated_subtitle["original_index"] = failed_item["original_index"]
                            translated_subtitle["retry_success"] = False
                            translated_subtitle["retry_error"] = str(e)
                            
                            # 存储重试失败结果
                            retry_results[failed_item["original_index"]] = translated_subtitle
                        
                        retry_pbar.update(1)
                        
                        # 重试间延迟
                        await asyncio.sleep(0.5)
                
                # 用重试结果替换原始失败条目
                for i, subtitle in enumerate(translated_subtitles):
                    original_index = subtitle.get("original_index")
                    if original_index in retry_results:
                        translated_subtitles[i] = retry_results[original_index]
                        logger.debug(f"🔄 替换失败条目: 索引 {original_index}")
                
                logger.info(f"🔄 重试完成: {retry_success}/{len(failed_items)} 成功")
            
            # 排序结果（按原始索引）
            translated_subtitles.sort(key=lambda x: x.get("original_index", 0))
            
            # 去重处理：移除重复的字幕条目
            if TranslationConfig.ENABLE_DEDUPLICATION:
                original_count = len(translated_subtitles)
                translated_subtitles = self._remove_duplicate_subtitles(translated_subtitles)
                final_count = len(translated_subtitles)
                if original_count != final_count:
                    logger.info(f"🔄 去重完成: {original_count} → {final_count} 条字幕")
            else:
                logger.debug("🔄 去重功能已禁用")
            
            # 最终保存
            self.save_subtitles(translated_subtitles, output_path, original_path)
            
            # 统计报告
            success_rate = (successful_translations / total * 100) if total > 0 else 0
            logger.info(f"🎉 单条异步翻译完成!")
            logger.info(f"  📊 总计: {total} 条")
            logger.info(f"  ✅ 成功: {successful_translations} ({success_rate:.1f}%)")
            logger.info(f"  ❌ 失败: {failed_translations}")
            logger.info(f"  🔄 重试: {len(failed_items)} 条，成功 {retry_success if 'retry_success' in locals() else 0} 条")
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

    # ========== 三步翻译法实现 ==========

    async def translate_with_context_three_step(self, texts: List[str], current_batch_size: int = None) -> List[str]:
        """上下文 + 三步翻译法：结合上下文和三步翻译法的优势"""
        start_time = time.time()
        logger.info(f"🎯 开始上下文+三步翻译法: {len(texts)} 条字幕")
        
        try:
            # 获取上下文信息（上下文模式始终启用）
            context_info = self.context_manager.get_context_string()
            terminology_dict = self.context_manager.get_terminology_string()
            
            segments = [{"id": i+1, "text": text} for i, text in enumerate(texts)]
            
            # 第一步：使用上下文+三步翻译法进行初步翻译
            if TranslationConfig.ENABLE_STREAMING and len(texts) <= 3:
                prompt = self.three_step_streaming_prompt.format(
                    context_info=context_info,
                    terminology_dict=terminology_dict,
                    segments=json.dumps(segments, ensure_ascii=False)
                )
                logger.info(f"🌊 上下文+三步流式翻译: {len(texts)} 条")
                translated_segments = await self._stream_translate(prompt)
            else:
                prompt = self.three_step_prompt.format(
                    previous_context=context_info,
                    terminology_dict=terminology_dict,
                    current_segments=json.dumps(segments, ensure_ascii=False),
                    segment_count=len(texts)
                )
                logger.info(f"🎯 上下文+三步批量翻译: {len(texts)} 条")
                
                session = await self._get_session()
                url, data, headers = self._prepare_api_request(prompt, TranslationConfig.get_three_step_options())
                
                async with session.post(url, json=data, headers=headers) as response:
                    if response.status != 200:
                        raise Exception(f"上下文+三步翻译API请求失败: {response.status}")
                    
                    result = await response.json()
                    translated_text = self._clean_translation(self._parse_api_response(result))
                    translated_segments = self._parse_contextual_response(translated_text, len(texts))
            
            # 检查初步翻译结果
            if len(translated_segments) != len(texts):
                logger.warning(f"⚠️ 上下文+三步翻译数量不匹配，降级到上下文翻译")
                return await self.translate_batch_with_context(texts, current_batch_size)
            
            # 第二步：反思优化（可选）
            if TranslationConfig.ENABLE_REFLECTION_OPTIMIZATION:
                optimized_segments = []
                for i, (original_text, translated_text) in enumerate(zip(texts, translated_segments)):
                    try:
                        optimized_text = await self._reflect_and_optimize(
                            original_text, translated_text, context_info, terminology_dict
                        )
                        optimized_segments.append(optimized_text)
                        logger.debug(f"✅ 反思优化完成: 字幕 {i+1}")
                    except Exception as e:
                        logger.warning(f"⚠️ 反思优化失败: 字幕 {i+1}, 使用原翻译")
                        optimized_segments.append(translated_text)
                
                translated_segments = optimized_segments
            
            # 更新上下文（上下文模式始终启用）
            for original, translated in zip(texts, translated_segments):
                self.context_manager.add_translation(original, translated)
            
            # 性能记录
            response_time = time.time() - start_time
            quality_results = self._check_translation_quality(texts, translated_segments)
            quality_score = sum(quality_results) / len(quality_results) if quality_results else 0
            
            if self.adaptive_processor:
                self.adaptive_processor.record_performance(
                    len(texts), response_time, quality_score, quality_score
                )
            
            logger.info(f"✅ 上下文+三步翻译完成: 质量 {quality_score:.2f}, 时间 {response_time:.1f}s")
            return translated_segments
            
        except Exception as e:
            logger.error(f"❌ 上下文+三步翻译失败: {str(e)}")
            # 降级到上下文翻译
            logger.info("🔄 降级到上下文翻译方法")
            return await self.translate_batch_with_context(texts, current_batch_size)

    async def translate_with_three_step_method(self, texts: List[str], current_batch_size: int = None) -> List[str]:
        """使用吴恩达三步翻译法进行翻译"""
        if not TranslationConfig.ENABLE_THREE_STEP_TRANSLATION:
            return await self.translate_batch_with_context(texts, current_batch_size)
        
        start_time = time.time()
        logger.info(f"🎯 开始三步翻译法: {len(texts)} 条字幕")
        
        try:
            # 获取上下文信息
            context_info = ""
            terminology_dict = ""
            if self.context_manager:
                context_info = self.context_manager.get_context_string()
                terminology_dict = self.context_manager.get_terminology_string()
            
            segments = [{"id": i+1, "text": text} for i, text in enumerate(texts)]
            
            # 第一步：使用三步翻译法进行初步翻译
            if TranslationConfig.ENABLE_STREAMING and len(texts) <= 3:
                prompt = self.three_step_streaming_prompt.format(
                    context_info=context_info,
                    terminology_dict=terminology_dict,
                    segments=json.dumps(segments, ensure_ascii=False)
                )
                logger.info(f"🌊 三步流式翻译: {len(texts)} 条")
                translated_segments = await self._stream_translate(prompt)
            else:
                prompt = self.three_step_prompt.format(
                    previous_context=context_info,
                    terminology_dict=terminology_dict,
                    current_segments=json.dumps(segments, ensure_ascii=False),
                    segment_count=len(texts)
                )
                logger.info(f"🎯 三步批量翻译: {len(texts)} 条")
                
                session = await self._get_session()
                url, data, headers = self._prepare_api_request(prompt, TranslationConfig.get_three_step_options())
                
                async with session.post(url, json=data, headers=headers) as response:
                    if response.status != 200:
                        raise Exception(f"三步翻译API请求失败: {response.status}")
                    
                    result = await response.json()
                    translated_text = self._clean_translation(self._parse_api_response(result))
                    translated_segments = self._parse_contextual_response(translated_text, len(texts))
            
            # 检查初步翻译结果
            if len(translated_segments) != len(texts):
                logger.warning(f"⚠️ 三步翻译数量不匹配，降级到传统翻译")
                return await self.translate_batch_with_context(texts, current_batch_size)
            
            # 第二步：反思优化（可选）
            if TranslationConfig.ENABLE_REFLECTION_OPTIMIZATION:
                optimized_segments = []
                for i, (original_text, translated_text) in enumerate(zip(texts, translated_segments)):
                    try:
                        optimized_text = await self._reflect_and_optimize(
                            original_text, translated_text, context_info, terminology_dict
                        )
                        optimized_segments.append(optimized_text)
                        logger.debug(f"✅ 反思优化完成: 字幕 {i+1}")
                    except Exception as e:
                        logger.warning(f"⚠️ 反思优化失败: 字幕 {i+1}, 使用原翻译")
                        optimized_segments.append(translated_text)
                
                translated_segments = optimized_segments
            
            # 更新上下文
            if self.context_manager:
                for original, translated in zip(texts, translated_segments):
                    self.context_manager.add_translation(original, translated)
            
            # 性能记录
            response_time = time.time() - start_time
            quality_results = self._check_translation_quality(texts, translated_segments)
            quality_score = sum(quality_results) / len(quality_results) if quality_results else 0
            
            if self.adaptive_processor:
                self.adaptive_processor.record_performance(
                    len(texts), response_time, quality_score, quality_score
                )
            
            logger.info(f"✅ 三步翻译完成: 质量 {quality_score:.2f}, 时间 {response_time:.1f}s")
            return translated_segments
            
        except Exception as e:
            logger.error(f"❌ 三步翻译失败: {str(e)}")
            # 降级到传统翻译
            logger.info("🔄 降级到传统翻译方法")
            return await self.translate_batch_with_context(texts, current_batch_size)

    async def _reflect_and_optimize(self, original_text: str, current_translation: str, 
                                  context_info: str, terminology_dict: str) -> str:
        """反思并优化翻译结果"""
        try:
            # 构建反思提示
            prompt = self.reflection_prompt.format(
                original_text=original_text,
                current_translation=current_translation,
                context_info=context_info,
                terminology_dict=terminology_dict
            )
            
            session = await self._get_session()
            url, data, headers = self._prepare_api_request(prompt, TranslationConfig.get_three_step_options())
            
            async with session.post(url, json=data, headers=headers) as response:
                if response.status != 200:
                    raise Exception(f"反思优化API请求失败: {response.status}")
                
                result = await response.json()
                reflection_text = self._clean_translation(self._parse_api_response(result))
                
                # 解析反思结果
                try:
                    reflection_data = json.loads(reflection_text)
                    if "optimized_translation" in reflection_data:
                        optimized_text = reflection_data["optimized_translation"]
                        
                        # 质量检查
                        if self._is_valid_translation(optimized_text):
                            return optimized_text
                        else:
                            logger.warning("⚠️ 反思优化结果无效，使用原翻译")
                            return current_translation
                    else:
                        raise ValueError("反思结果中缺少优化翻译")
                        
                except json.JSONDecodeError:
                    # 如果JSON解析失败，尝试提取翻译文本
                    optimized_text = self._extract_optimized_translation(reflection_text)
                    if optimized_text and self._is_valid_translation(optimized_text):
                        return optimized_text
                    else:
                        logger.warning("⚠️ 无法解析反思结果，使用原翻译")
                        return current_translation
                        
        except Exception as e:
            logger.error(f"❌ 反思优化失败: {str(e)}")
            return current_translation

    def _is_valid_translation(self, text: str) -> bool:
        """检查翻译结果是否有效"""
        if not text or len(text.strip()) == 0:
            return False
        
        # 检查是否包含中文字符
        chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
        if len(chinese_chars) < len(text) * 0.3:  # 至少30%是中文字符
            return False
        
        # 检查是否包含明显的错误标记
        error_indicators = ['error', 'failed', 'invalid', '无法翻译', '翻译失败']
        if any(indicator in text.lower() for indicator in error_indicators):
            return False
        
        return True

    def _extract_optimized_translation(self, reflection_text: str) -> str:
        """从反思文本中提取优化后的翻译"""
        # 尝试多种模式匹配
        patterns = [
            r'"optimized_translation":\s*"([^"]+)"',
            r'优化后的翻译[：:]\s*(.+)',
            r'最终翻译[：:]\s*(.+)',
            r'改进翻译[：:]\s*(.+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, reflection_text)
            if match:
                return match.group(1).strip()
        
        # 如果没有找到模式匹配，尝试提取最后一段中文文本
        lines = reflection_text.split('\n')
        for line in reversed(lines):
            line = line.strip()
            if line and self._is_chinese_text(line) and len(line) > 5:
                return line
        
        return ""

    async def translate_batch_enhanced(self, texts: List[str]) -> List[str]:
        """增强的批量翻译方法，根据配置选择翻译模式（上下文模式始终启用）"""
        if TranslationConfig.TRANSLATION_MODE == "contextual_three_step":
            return await self.translate_with_context_three_step(texts)
        else:
            return await self.translate_batch_with_context(texts) 

    def _remove_duplicate_subtitles(self, subtitles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """移除重复的字幕条目，优先保留质量更好的翻译"""
        # 按原始索引分组
        grouped_subtitles = {}
        
        for subtitle in subtitles:
            original_index = subtitle.get("original_index")
            if original_index not in grouped_subtitles:
                grouped_subtitles[original_index] = []
            grouped_subtitles[original_index].append(subtitle)
        
        # 对每个索引组，选择最佳翻译
        unique_subtitles = []
        for original_index, group in grouped_subtitles.items():
            if len(group) == 1:
                # 只有一个条目，直接保留
                unique_subtitles.append(group[0])
            else:
                # 多个条目，选择最佳的一个
                best_subtitle = self._select_best_subtitle(group)
                unique_subtitles.append(best_subtitle)
                
                if len(group) > 1:
                    log_message = f"🔄 发现重复字幕: 索引 {original_index}, 保留最佳翻译，移除 {len(group)-1} 个重复条目"
                    if TranslationConfig.DEDUPLICATION_LOG_LEVEL == "info":
                        logger.info(log_message)
                    elif TranslationConfig.DEDUPLICATION_LOG_LEVEL == "debug":
                        logger.debug(log_message)
                    elif TranslationConfig.DEDUPLICATION_LOG_LEVEL == "warning":
                        logger.warning(log_message)
        
        return unique_subtitles
    
    def _select_best_subtitle(self, subtitles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """从多个重复字幕中选择最佳的一个"""
        if not subtitles:
            return {}
        
        if len(subtitles) == 1:
            return subtitles[0]
        
        # 评分系统：选择质量最好的字幕
        best_subtitle = subtitles[0]
        best_score = self._calculate_subtitle_quality_score(subtitles[0])
        
        for subtitle in subtitles[1:]:
            score = self._calculate_subtitle_quality_score(subtitle)
            if score > best_score:
                best_score = score
                best_subtitle = subtitle
        
        return best_subtitle
    
    def _calculate_subtitle_quality_score(self, subtitle: Dict[str, Any]) -> float:
        """计算字幕质量评分"""
        score = 0.0
        
        # 翻译质量评分
        quality = subtitle.get("translation_quality", "poor")
        if quality == "good":
            score += 10.0
        elif quality == "poor":
            score += 5.0
        elif quality == "failed":
            score += 0.0
        
        # 重试成功加分
        if subtitle.get("retry_success", False):
            score += 2.0
        
        # 上下文使用加分
        if subtitle.get("context_used", False):
            score += 1.0
        
        # 文本长度合理性评分
        original_text = subtitle.get("original_text", "")
        translated_text = subtitle.get("text", "")
        
        if original_text and translated_text:
            length_ratio = len(translated_text) / len(original_text)
            if 0.5 <= length_ratio <= 2.0:  # 合理的长度比例
                score += 1.0
        
        # 中文内容比例评分
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', translated_text))
        if len(translated_text) > 0:
            chinese_ratio = chinese_chars / len(translated_text)
            if chinese_ratio >= 0.5:  # 至少50%是中文
                score += 1.0
        
        return score 