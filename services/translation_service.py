"""
LangChain 1.0 风格的翻译服务
使用现代化的 LangChain 架构和 LCEL (LangChain Expression Language)
"""

import logging
import asyncio
import aiohttp
import os
from typing import List, Dict, Any, Optional, Callable
from collections import defaultdict, deque
import time
import json
import re

# 禁用 LangSmith 追踪（生产环境推荐）
os.environ['LANGCHAIN_TRACING_V2'] = 'false'
os.environ['LANGSMITH_TRACING'] = 'false'

# LangChain 1.0 imports
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser, JsonOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage

from config import settings
from services.translation_config import TranslationConfig
from services.translation_templates import (
    CONTEXTUAL_TRANSLATION_TEMPLATE,
    THREE_STEP_TRANSLATION_TEMPLATE,
    REFLECTION_TEMPLATE
)

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
        # 简化的术语提取逻辑
        technical_terms = re.findall(r'\b[A-Z][a-z]*(?:\s+[A-Z][a-z]*)*\b', original)
        for term in technical_terms:
            if len(term) > 3:  # 过滤短词
                self.terminology_usage_count[term] += 1
                if self.terminology_usage_count[term] >= 2:  # 出现2次以上认为是术语
                    # 这里可以添加更复杂的术语对应逻辑
                    self.terminology_dict[term] = translated
    
    def get_context_summary(self) -> str:
        """获取上下文摘要"""
        if not self.context_buffer:
            return "暂无翻译历史"
        
        recent_translations = list(self.context_buffer)[-3:]  # 最近3条
        context_lines = []
        for item in recent_translations:
            context_lines.append(f"原文: {item['original']}")
            context_lines.append(f"译文: {item['translated']}")
        
        return "\n".join(context_lines)
    
    def get_terminology_dict_str(self) -> str:
        """获取术语词典字符串"""
        if not self.terminology_dict:
            return "暂无专业术语"
        
        terms = []
        for en, zh in self.terminology_dict.items():
            terms.append(f"{en} -> {zh}")
        
        return "\n".join(terms)


class TranslationService:
    """LangChain 1.0 风格的翻译服务"""
    
    def __init__(self):
        # 初始化配置
        self.api_type = settings.TRANSLATION_PROVIDER.lower()
        self.model = settings.OLLAMA_MODEL if self.api_type == "ollama" else settings.DEEPSEEK_MODEL
        
        # 上下文管理器
        self.context_manager = ContextManager()
        
        # 初始化会话
        self._session = None
        
        # 初始化 LLM
        self._init_llm()
        
        # 初始化提示模板
        self._init_prompts()
        
        # 初始化翻译链
        self._init_chains()
        
        logger.info(f"🚀 LangChain 1.0 翻译服务已初始化")
        logger.info(f"  API类型: {self.api_type.upper()}")
        logger.info(f"  模型: {self.model}")
        logger.info(f"  翻译模式: {TranslationConfig.TRANSLATION_MODE}")
    
    def _init_llm(self):
        """初始化 LLM"""
        if self.api_type == "ollama":
            # 使用 ChatOllama (LangChain 1.0 推荐)
            self.llm = ChatOllama(
                model=self.model,
                base_url=settings.OLLAMA_API_URL,
                temperature=TranslationConfig.MODEL_TEMPERATURE,
                num_predict=TranslationConfig.MODEL_MAX_TOKENS,  # 使用统一的参数名
                top_p=TranslationConfig.MODEL_TOP_P,
                top_k=TranslationConfig.MODEL_TOP_K,
                repeat_penalty=TranslationConfig.MODEL_REPEAT_PENALTY,
            )
        else:
            # DeepSeek 使用自定义 HTTP 调用
            self.llm = None
            self._session = None
    
    def _init_prompts(self):
        """初始化提示模板"""
        # 简单翻译提示
        self.simple_prompt = ChatPromptTemplate.from_messages([
            ("system", "你是一位专业的英中翻译专家。请将以下英文翻译成自然流畅的中文，保持原意不变。"),
            ("human", "{text}")
        ])
        
        # 上下文翻译提示
        self.contextual_prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一位专业的英中翻译专家，正在翻译纪录片字幕。

## 翻译历史上下文：
{previous_context}

## 已确定的术语对照表：
{terminology_dict}

## 翻译要求：
1. **术语一致性**：严格按照术语对照表翻译专业词汇
2. **上下文连贯**：考虑前文语境，确保语义自然过渡
3. **专业准确**：保持纪录片的专业性和准确性
4. **长度控制**：翻译后的句子长短应与原文接近
5. **简洁表达**：使用精炼的中文，避免冗长句式

请翻译以下内容："""),
            ("human", "{text}")
        ])
        
        # 三步翻译提示
        if TranslationConfig.ENABLE_THREE_STEP_TRANSLATION:
            self.three_step_prompt = ChatPromptTemplate.from_messages([
                ("system", """你是一位专业的英中翻译专家。请使用三步翻译法：

1. **直译**：先进行逐字逐句的直译
2. **意译**：基于直译结果，调整为自然流畅的中文表达
3. **润色**：最终优化，确保译文准确、自然、简洁

## 上下文信息：
{previous_context}

## 术语对照：
{terminology_dict}

请按照三步法翻译以下内容，只输出最终的润色结果："""),
                ("human", "{text}")
            ])
    
    def _init_chains(self):
        """初始化 LangChain 链"""
        # 输出解析器
        self.str_parser = StrOutputParser()
        
        # 简单翻译链
        self.simple_chain = self.simple_prompt | self.llm | self.str_parser
        
        # 上下文翻译链
        self.contextual_chain = (
            {
                "text": RunnablePassthrough(),
                "previous_context": RunnableLambda(lambda _: self.context_manager.get_context_summary()),
                "terminology_dict": RunnableLambda(lambda _: self.context_manager.get_terminology_dict_str())
            }
            | self.contextual_prompt 
            | self.llm 
            | self.str_parser
        )
        
        # 三步翻译链
        if TranslationConfig.ENABLE_THREE_STEP_TRANSLATION:
            self.three_step_chain = (
                {
                    "text": RunnablePassthrough(),
                    "previous_context": RunnableLambda(lambda _: self.context_manager.get_context_summary()),
                    "terminology_dict": RunnableLambda(lambda _: self.context_manager.get_terminology_dict_str())
                }
                | self.three_step_prompt 
                | self.llm 
                | self.str_parser
            )
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 HTTP 会话"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=TranslationConfig.REQUEST_TIMEOUT)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session
    
    async def _make_deepseek_request(self, prompt: str) -> str:
        """DeepSeek API 请求"""
        session = await self._get_session()
        
        data = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": TranslationConfig.MODEL_TEMPERATURE,
            "max_tokens": TranslationConfig.MODEL_MAX_TOKENS
        }
        
        headers = {
            "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        async with session.post(f"{settings.DEEPSEEK_API_URL}/v1/chat/completions", 
                               json=data, headers=headers) as response:
            if response.status == 200:
                result = await response.json()
                return result["choices"][0]["message"]["content"]
            else:
                raise Exception(f"DeepSeek API error: {response.status}")
    
    async def translate_single(self, text: str, use_context: bool = True) -> str:
        """翻译单个文本"""
        try:
            if self.api_type == "ollama":
                # 使用 LangChain 链
                if use_context and TranslationConfig.ENABLE_THREE_STEP_TRANSLATION:
                    result = await self.three_step_chain.ainvoke(text)
                elif use_context:
                    result = await self.contextual_chain.ainvoke(text)
                else:
                    result = await self.simple_chain.ainvoke({"text": text})
            else:
                # DeepSeek API
                if use_context:
                    context = self.context_manager.get_context_summary()
                    terms = self.context_manager.get_terminology_dict_str()
                    prompt = f"""你是专业的英中翻译专家。

上下文: {context}
术语对照: {terms}

请翻译: {text}"""
                else:
                    prompt = f"请将以下英文翻译成中文: {text}"
                
                result = await self._make_deepseek_request(prompt)
            
            # 添加到上下文
            if use_context:
                self.context_manager.add_translation(text, result)
            
            return result.strip()
            
        except Exception as e:
            logger.error(f"翻译失败: {e}")
            return f"翻译失败: {str(e)}"
    
    async def translate_batch(self, texts: List[str], use_context: bool = True) -> List[str]:
        """批量翻译"""
        results = []
        for text in texts:
            result = await self.translate_single(text, use_context)
            results.append(result)
            # 添加小延迟避免API限制
            await asyncio.sleep(TranslationConfig.BATCH_DELAY)
        return results
    
    def _is_translation_successful(self, subtitle: Dict[str, Any]) -> bool:
        """
        检查字幕是否已成功翻译
        
        成功翻译的标志:
        1. 存在 original_text 字段（表示已处理过）
        2. text 不是错误信息（不以"翻译失败:"开头）
        3. translation_failed 标记不为 True
        4. text 与 original_text 不完全相同（确实翻译了）
        """
        # 如果没有 original_text，说明还没翻译过
        if 'original_text' not in subtitle:
            return False
        
        # 如果明确标记为失败
        if subtitle.get('translation_failed', False):
            return False
        
        text = subtitle.get('text', '')
        original_text = subtitle.get('original_text', '')
        
        # 如果 text 是错误信息
        if text.startswith('翻译失败:'):
            return False
        
        # 如果 text 和 original_text 完全相同，可能是失败后保留原文
        # 但需要排除原文本身就是中文的情况
        if text == original_text:
            # 检查是否包含中文字符
            has_chinese = bool(re.search(r'[\u4e00-\u9fff]', text))
            if not has_chinese:
                return False
        
        return True

    async def translate_subtitles(self, subtitles: List[Dict[str, Any]], 
                                progress_callback: Optional[Callable] = None,
                                max_retries: int = 3) -> List[Dict[str, Any]]:
        """
        翻译字幕列表，支持跳过已翻译和自动重试失败项
        
        参数:
            subtitles: 字幕列表
            progress_callback: 进度回调函数
            max_retries: 失败重试次数
        """
        translated_subtitles = []
        total = len(subtitles)
        skipped_count = 0
        failed_count = 0
        
        for i, subtitle in enumerate(subtitles):
            try:
                # 检查是否已成功翻译（支持断点续传）
                if self._is_translation_successful(subtitle):
                    translated_subtitles.append(subtitle)
                    skipped_count += 1
                    logger.info(f"⏭️ 跳过已翻译: {i+1}/{total} - {subtitle.get('text', '')[:30]}...")
                    continue
                
                # 获取原文（可能在 original_text 或 text 中）
                original_text = subtitle.get('original_text', subtitle.get('text', ''))
                
                if original_text.strip():
                    translated_text = await self.translate_single(original_text, use_context=True)
                    
                    # 检查翻译结果是否有效
                    is_failed = translated_text.startswith('翻译失败:')
                    
                    # 创建翻译后的字幕
                    translated_subtitle = subtitle.copy()
                    translated_subtitle['text'] = translated_text if not is_failed else original_text
                    translated_subtitle['original_text'] = original_text
                    translated_subtitle['translation_failed'] = is_failed
                    
                    if is_failed:
                        translated_subtitle['translation_error'] = translated_text
                        failed_count += 1
                        logger.warning(f"❌ 翻译失败: {i+1}/{total} - {original_text[:30]}...")
                    else:
                        logger.info(f"✅ 翻译成功: {i+1}/{total} - {original_text[:30]}...")
                    
                    translated_subtitles.append(translated_subtitle)
                else:
                    # 空文本直接添加
                    translated_subtitles.append(subtitle)
                
                # 进度回调
                if progress_callback:
                    progress = int((i + 1) / total * 100)
                    await progress_callback(progress, f"翻译字幕 {i+1}/{total}")
                
                logger.info(f"翻译进度: {i+1}/{total} - {original_text[:50]}...")
                
            except Exception as e:
                logger.error(f"翻译字幕失败 {i+1}: {e}")
                # 失败时标记并保留原文
                original_text = subtitle.get('original_text', subtitle.get('text', ''))
                failed_subtitle = subtitle.copy()
                failed_subtitle['original_text'] = original_text
                failed_subtitle['translation_failed'] = True
                failed_subtitle['translation_error'] = str(e)
                translated_subtitles.append(failed_subtitle)
                failed_count += 1
        
        # 统计信息
        logger.info(f"📊 首轮翻译完成: 总计{total}, 跳过{skipped_count}, 成功{total-skipped_count-failed_count}, 失败{failed_count}")
        
        # 自动重试失败的字幕
        if failed_count > 0 and max_retries > 0:
            logger.info(f"🔄 开始重试 {failed_count} 条失败字幕...")
            translated_subtitles = await self.retry_failed_translations(
                translated_subtitles, 
                max_retries=max_retries,
                progress_callback=progress_callback
            )
        
        return translated_subtitles
    
    async def retry_failed_translations(self, subtitles: List[Dict[str, Any]], 
                                       max_retries: int = 3,
                                       progress_callback: Optional[Callable] = None) -> List[Dict[str, Any]]:
        """
        重试翻译失败的字幕
        
        参数:
            subtitles: 包含失败标记的字幕列表
            max_retries: 最大重试次数
            progress_callback: 进度回调
        """
        # 找出所有失败的字幕索引
        failed_indices = [
            i for i, sub in enumerate(subtitles) 
            if sub.get('translation_failed', False)
        ]
        
        if not failed_indices:
            logger.info("✅ 没有需要重试的失败字幕")
            return subtitles
        
        logger.info(f"🔄 发现 {len(failed_indices)} 条失败字幕需要重试")
        
        retry_count = 0
        while failed_indices and retry_count < max_retries:
            retry_count += 1
            logger.info(f"🔄 第 {retry_count}/{max_retries} 轮重试，剩余 {len(failed_indices)} 条...")
            
            # 重试前等待一段时间，让服务恢复
            await asyncio.sleep(2)
            
            still_failed = []
            
            for idx in failed_indices:
                subtitle = subtitles[idx]
                original_text = subtitle.get('original_text', subtitle.get('text', ''))
                
                try:
                    translated_text = await self.translate_single(original_text, use_context=True)
                    
                    # 检查结果
                    if translated_text.startswith('翻译失败:'):
                        still_failed.append(idx)
                        logger.warning(f"  ❌ 重试失败 [{idx+1}]: {original_text[:30]}...")
                    else:
                        # 更新为成功
                        subtitles[idx]['text'] = translated_text
                        subtitles[idx]['translation_failed'] = False
                        if 'translation_error' in subtitles[idx]:
                            del subtitles[idx]['translation_error']
                        logger.info(f"  ✅ 重试成功 [{idx+1}]: {original_text[:30]}...")
                        
                except Exception as e:
                    still_failed.append(idx)
                    subtitles[idx]['translation_error'] = str(e)
                    logger.error(f"  ❌ 重试异常 [{idx+1}]: {e}")
                
                # 添加延迟避免请求过快
                await asyncio.sleep(TranslationConfig.BATCH_DELAY)
            
            failed_indices = still_failed
            
            if not failed_indices:
                logger.info(f"🎉 所有失败字幕重试成功！")
                break
        
        if failed_indices:
            logger.warning(f"⚠️ 仍有 {len(failed_indices)} 条字幕翻译失败，已达到最大重试次数")
        
        return subtitles
    
    async def test_connection(self) -> bool:
        """测试连接"""
        try:
            result = await self.translate_single("Hello", use_context=False)
            return bool(result and result != "翻译失败")
        except Exception as e:
            logger.error(f"连接测试失败: {e}")
            return False
    
    async def close(self):
        """关闭资源"""
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("翻译服务已关闭")


# 便捷函数
async def create_translation_service() -> TranslationService:
    """创建翻译服务实例"""
    return TranslationService()


# 测试函数
async def test_translation_service():
    """测试翻译服务"""
    service = await create_translation_service()
    
    try:
        # 测试连接
        print("测试连接...")
        connection_ok = await service.test_connection()
        print(f"连接状态: {connection_ok}")
        
        if connection_ok:
            # 测试翻译
            print("\n测试翻译...")
            result = await service.translate_single("Hello, welcome to our documentary about artificial intelligence.")
            print(f"翻译结果: {result}")
            
            # 测试批量翻译
            print("\n测试批量翻译...")
            texts = [
                "Machine learning is transforming our world.",
                "Deep neural networks can process complex patterns.",
                "Artificial intelligence has many applications."
            ]
            results = await service.translate_batch(texts)
            for i, result in enumerate(results):
                print(f"{i+1}. {result}")
    
    finally:
        await service.close()


if __name__ == "__main__":
    asyncio.run(test_translation_service())
