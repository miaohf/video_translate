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

# Pydantic for structured output
from pydantic import BaseModel, Field

from config import settings
from services.translation_config import TranslationConfig
from services.translation_templates import (
    CONTEXTUAL_TRANSLATION_TEMPLATE,
    THREE_STEP_TRANSLATION_TEMPLATE,
    REFLECTION_TEMPLATE
)

logger = logging.getLogger(__name__)


# ========== 颜色日志辅助函数 ==========

class LogColors:
    """ANSI 颜色代码"""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    
    # 前景色
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    
    # 高亮前景色
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"

def _color_text(text: str, color: str) -> str:
    """给文本添加颜色"""
    if TranslationConfig.DEBUG_LOG_USE_COLOR:
        return f"{color}{text}{LogColors.RESET}"
    return text

def _format_log_content(content: str) -> str:
    """格式化日志内容（不截断）"""
    max_len = TranslationConfig.DEBUG_LOG_MAX_LENGTH
    if max_len > 0 and len(content) > max_len:
        return content[:max_len] + "..."
    return content

def _log_step(step_name: str, step_num: int, total: int = 3):
    """记录步骤日志"""
    step_colors = {
        1: LogColors.BRIGHT_CYAN,
        2: LogColors.BRIGHT_YELLOW,
        3: LogColors.BRIGHT_GREEN,
    }
    color = step_colors.get(step_num, LogColors.WHITE)
    logger.info(_color_text(f"    {'─'*40}", LogColors.BLUE))
    logger.info(_color_text(f"    📋 Step {step_num}/{total}: {step_name}", color))
    logger.info(_color_text(f"    {'─'*40}", LogColors.BLUE))

def _log_prompt(role: str, content: str):
    """记录提示词日志"""
    role_colors = {
        "System": LogColors.BRIGHT_MAGENTA,
        "Human": LogColors.BRIGHT_CYAN,
    }
    color = role_colors.get(role, LogColors.WHITE)
    formatted_content = _format_log_content(content)
    
    logger.info(_color_text(f"    ┌─ {role} Prompt ─────────────────────", color))
    for line in formatted_content.split('\n'):
        logger.info(_color_text(f"    │ {line}", color))
    logger.info(_color_text(f"    └{'─'*45}", color))

def _log_response(step_name: str, content: str):
    """记录响应日志"""
    formatted_content = _format_log_content(content)
    logger.info(_color_text(f"    ┌─ {step_name} 响应 ─────────────────────", LogColors.BRIGHT_GREEN))
    for line in formatted_content.split('\n'):
        logger.info(_color_text(f"    │ {line}", LogColors.GREEN))
    logger.info(_color_text(f"    └{'─'*45}", LogColors.BRIGHT_GREEN))


# ========== Pydantic 结构化输出模型 ==========

class TranslationItem(BaseModel):
    """单条翻译结果"""
    id: int = Field(description="字幕序号")
    text: str = Field(description="中文翻译")

class BatchTranslationResult(BaseModel):
    """批量翻译结果"""
    translations: List[TranslationItem] = Field(description="翻译结果列表")

# ========== 批量三步翻译法提示模板 ==========

# 第一步：翻译
BATCH_STEP1_TRANSLATE_PROMPT = """你是专业的英中翻译专家。请将以下英文字幕翻译成中文。

待翻译字幕:
{subtitles}

要求:
1. 翻译成自然流畅的中文
2. 保持原文含义完整准确
3. 必须翻译全部 {count} 条"""

# 第二步：反思
BATCH_STEP2_REFLECT_PROMPT = """你是翻译质量评估专家。请对以下翻译结果进行反思评估。

原文:
{originals}

翻译结果:
{translations}

请评估并指出每条翻译的问题:
1. 是否自然流畅？是否符合中文表达习惯？
2. 是否有更好的中文表达方式？
3. 句子长度是否合适？是否需要精简？

输出格式: 每条一行，指出需要改进的地方"""

# 第三步：优化
BATCH_STEP3_OPTIMIZE_PROMPT = """你是专业的英中翻译专家。请基于反思意见优化翻译。

原文:
{originals}

初次翻译:
{translations}

反思意见:
{reflections}

请输出优化后的最终翻译:
1. 调整句式结构，使其更符合中文习惯
2. 优化词汇选择，使用更地道的中文表达
3. 控制句子长度，保持简洁明了
4. 必须输出全部 {count} 条优化翻译"""

# 批量翻译提示模板（文本格式，备用）
BATCH_TRANSLATION_PROMPT = """你是专业的英中翻译专家。请翻译以下全部字幕。

## 待翻译字幕（共{count}条，必须全部翻译）:
{subtitles}

## 要求:
- 翻译成自然流畅的中文
- 必须翻译所有{count}条，从[1]到[{count}]
- 每行格式: [序号] 译文

## 输出（直接开始，不要解释）:
"""

# 批量翻译提示模板（JSON 结构化输出）- 简单模式备用
BATCH_TRANSLATION_JSON_PROMPT = """你是专业的英中翻译专家。请将以下英文字幕翻译成中文。

待翻译字幕:
{subtitles}

要求:
1. 翻译成自然流畅的中文
2. 必须翻译全部 {count} 条
3. 保持简洁，适合字幕显示"""


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
        
        # 根据 API 类型选择模型
        if self.api_type == "ollama":
            self.model = settings.OLLAMA_MODEL
        elif self.api_type == "vllm":
            self.model = settings.VLLM_MODEL
        else:
            self.model = settings.DEEPSEEK_MODEL
        
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
                num_predict=TranslationConfig.MODEL_MAX_TOKENS,
                top_p=TranslationConfig.MODEL_TOP_P,
                top_k=TranslationConfig.MODEL_TOP_K,
                repeat_penalty=TranslationConfig.MODEL_REPEAT_PENALTY,
            )
        elif self.api_type == "vllm":
            # vLLM 使用 OpenAI 兼容 API
            from langchain_openai import ChatOpenAI
            self.llm = ChatOpenAI(
                model=self.model,
                openai_api_base=f"{settings.VLLM_API_URL}/v1",
                openai_api_key=settings.VLLM_API_KEY,
                temperature=TranslationConfig.MODEL_TEMPERATURE,
                max_tokens=TranslationConfig.MODEL_MAX_TOKENS,
                top_p=TranslationConfig.MODEL_TOP_P,
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

1. **翻译**：先进行准确的翻译
2. **反思**：评估翻译是否自然流畅，符合中文表达习惯
3. **优化**：根据反思意见进行最终优化

## 上下文信息：
{previous_context}

## 术语对照：
{terminology_dict}

请按照三步法翻译以下内容，只输出最终的优化结果："""),
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
        """翻译单个文本 - 使用三步翻译法"""
        try:
            if self.api_type in ("ollama", "vllm") and use_context and TranslationConfig.ENABLE_THREE_STEP_TRANSLATION:
                # 真正的三步翻译法：3次独立请求
                result = await self._translate_single_three_step(text)
            elif self.api_type in ("ollama", "vllm"):
                # 简单翻译模式
                if use_context:
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
    
    async def _translate_single_three_step(self, text: str) -> str:
        """
        单条三步翻译法：发送3次独立请求
        
        1. 翻译
        2. 反思
        3. 优化
        """
        context = self.context_manager.get_context_summary()
        terms = self.context_manager.get_terminology_dict_str()
        
        # ========== 第一步：翻译 ==========
        step1_prompt = f"""你是专业的英中翻译专家。请将以下英文翻译成中文。

上下文: {context}
术语对照: {terms}

原文: {text}

请翻译成自然流畅的中文，只输出翻译结果："""
        
        first_translation = await self.simple_chain.ainvoke({"text": step1_prompt})
        first_translation = self._strip_thinking_tags(first_translation).strip()
        
        # ========== 第二步：反思 ==========
        step2_prompt = f"""你是翻译质量评估专家。请评估以下翻译的质量。

原文: {text}
翻译: {first_translation}

请评估:
1. 是否自然流畅？是否符合中文表达习惯？
2. 是否有更好的中文表达方式？
3. 长度是否合适？

请指出需要改进的地方："""
        
        reflection = await self.simple_chain.ainvoke({"text": step2_prompt})
        reflection = self._strip_thinking_tags(reflection).strip()
        
        # ========== 第三步：优化 ==========
        step3_prompt = f"""你是专业的英中翻译专家。请基于反思意见优化翻译。

原文: {text}
初次翻译: {first_translation}
反思意见: {reflection}

请输出优化后的最终翻译（只输出翻译结果，不要解释）："""
        
        optimized = await self.simple_chain.ainvoke({"text": step3_prompt})
        optimized = self._strip_thinking_tags(optimized).strip()
        
        return optimized
    
    async def translate_batch(self, texts: List[str], use_context: bool = True) -> List[str]:
        """批量翻译（逐条模式）"""
        results = []
        for text in texts:
            result = await self.translate_single(text, use_context)
            results.append(result)
            # 添加小延迟避免API限制
            await asyncio.sleep(TranslationConfig.BATCH_DELAY)
        return results
    
    def _strip_thinking_tags(self, text: str) -> str:
        """去除 LLM 输出中的思考链标签 <think>...</think>"""
        # 移除 <think>...</think> 标签及其内容
        result = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        return result.strip()
    
    def _parse_batch_translation_result(self, result: str, expected_count: int) -> Dict[int, str]:
        """
        解析批量翻译结果
        
        格式: [序号] 译文
        返回: {序号: 译文} 字典
        """
        # 先去除思考链
        result = self._strip_thinking_tags(result)
        
        translations = {}
        
        # 匹配 [序号] 译文 格式
        pattern = r'\[(\d+)\]\s*(.+?)(?=\[\d+\]|$)'
        matches = re.findall(pattern, result, re.DOTALL)
        
        for idx_str, text in matches:
            try:
                idx = int(idx_str)
                # 清理文本：去除前后空白和多余换行
                clean_text = text.strip()
                # 只取第一行（防止解析到下一条的内容）
                clean_text = clean_text.split('\n')[0].strip()
                if clean_text:
                    translations[idx] = clean_text
            except ValueError:
                continue
        
        # 检查完整性
        if len(translations) < expected_count:
            logger.warning(f"批量翻译解析不完整: 期望 {expected_count} 条，实际 {len(translations)} 条")
        
        return translations
    
    async def _translate_batch_structured(self, batch_indices: List[int], subtitles: List[Dict[str, Any]]) -> Dict[int, str]:
        """
        使用三步翻译法 + Pydantic 结构化输出进行批量翻译
        
        三步翻译流程:
        1. 翻译 - 准确翻译
        2. 反思 - 评估翻译质量，指出问题
        3. 优化 - 基于反思结果优化翻译
        
        返回: {本地序号: 译文} 字典
        """
        # 构造批量输入
        batch_texts = []
        for local_idx, global_idx in enumerate(batch_indices, 1):
            subtitle = subtitles[global_idx]
            original_text = subtitle.get('original_text', subtitle.get('text', ''))
            batch_texts.append(f"{local_idx}. {original_text}")
        
        input_text = "\n".join(batch_texts)
        count = len(batch_indices)
        
        if self.api_type in ("ollama", "vllm"):
            # 创建支持结构化输出的 LLM
            if self.api_type == "ollama":
                batch_llm = ChatOllama(
                    model=self.model,
                    base_url=settings.OLLAMA_API_URL,
                    temperature=TranslationConfig.MODEL_TEMPERATURE,
                    num_predict=TranslationConfig.BATCH_TRANSLATION_MAX_TOKENS,
                    top_p=TranslationConfig.MODEL_TOP_P,
                    top_k=TranslationConfig.MODEL_TOP_K,
                    repeat_penalty=TranslationConfig.MODEL_REPEAT_PENALTY,
                    format="json",
                )
            else:  # vllm
                from langchain_openai import ChatOpenAI
                batch_llm = ChatOpenAI(
                    model=self.model,
                    openai_api_base=f"{settings.VLLM_API_URL}/v1",
                    openai_api_key=settings.VLLM_API_KEY,
                    temperature=TranslationConfig.MODEL_TEMPERATURE,
                    max_tokens=TranslationConfig.BATCH_TRANSLATION_MAX_TOKENS,
                    top_p=TranslationConfig.MODEL_TOP_P,
                    model_kwargs={"response_format": {"type": "json_object"}},
                )
            structured_llm = batch_llm.with_structured_output(BatchTranslationResult)
            
            # ========== 第一步：翻译 ==========
            if TranslationConfig.DEBUG_LOG_PROMPTS:
                _log_step("初次翻译", 1, 3)
            else:
                logger.info(f"    📝 Step 1/3: 初次翻译...")
            
            step1_prompt = ChatPromptTemplate.from_messages([
                ("system", "你是专业的英中翻译专家。"),
                ("human", BATCH_STEP1_TRANSLATE_PROMPT)
            ])
            step1_chain = step1_prompt | structured_llm
            
            # 调试日志：打印请求提示词
            if TranslationConfig.DEBUG_LOG_PROMPTS:
                full_prompt = BATCH_STEP1_TRANSLATE_PROMPT.format(subtitles=input_text, count=count)
                _log_prompt("System", "你是专业的英中翻译专家。")
                _log_prompt("Human", full_prompt)
            
            step1_result = await step1_chain.ainvoke({
                "subtitles": input_text,
                "count": count
            })
            
            # 调试日志：打印响应内容
            if TranslationConfig.DEBUG_LOG_RESPONSES:
                if step1_result and hasattr(step1_result, 'translations'):
                    result_text = "\n".join([f"{t.id}. {t.text}" for t in step1_result.translations])
                    _log_response("Step1", f"获得 {len(step1_result.translations)} 条翻译:\n{result_text}")
            
            # 解析初次翻译结果
            first_translations = {}
            if step1_result and hasattr(step1_result, 'translations'):
                for item in step1_result.translations:
                    if 1 <= item.id <= count:
                        first_translations[item.id] = item.text
            
            # 如果翻译失败，直接返回
            if len(first_translations) < count * 0.5:
                logger.warning(f"    ⚠️ 翻译结果不完整 ({len(first_translations)}/{count})，跳过后续步骤")
                return first_translations
            
            # 构造翻译结果文本
            translations_text = "\n".join([f"{i}. {first_translations.get(i, '[缺失]')}" for i in range(1, count + 1)])
            
            # ========== 第二步：反思 ==========
            if TranslationConfig.DEBUG_LOG_PROMPTS:
                _log_step("反思评估", 2, 3)
            else:
                logger.info(f"    🔍 Step 2/3: 反思评估...")
            
            # 反思使用普通 LLM（不需要结构化输出）
            if self.api_type == "ollama":
                reflect_llm = ChatOllama(
                    model=self.model,
                    base_url=settings.OLLAMA_API_URL,
                    temperature=0.3,  # 稍高温度鼓励批判性思考
                    num_predict=TranslationConfig.BATCH_TRANSLATION_MAX_TOKENS,
                )
            else:  # vllm
                from langchain_openai import ChatOpenAI
                reflect_llm = ChatOpenAI(
                    model=self.model,
                    openai_api_base=f"{settings.VLLM_API_URL}/v1",
                    openai_api_key=settings.VLLM_API_KEY,
                    temperature=0.3,
                    max_tokens=TranslationConfig.BATCH_TRANSLATION_MAX_TOKENS,
                )
            
            step2_prompt = ChatPromptTemplate.from_messages([
                ("system", "你是翻译质量评估专家。请批判性地评估翻译质量。"),
                ("human", BATCH_STEP2_REFLECT_PROMPT)
            ])
            step2_chain = step2_prompt | reflect_llm | StrOutputParser()
            
            # 调试日志：打印反思请求
            if TranslationConfig.DEBUG_LOG_PROMPTS:
                full_prompt = BATCH_STEP2_REFLECT_PROMPT.format(
                    originals=input_text, 
                    translations=translations_text,
                    count=count
                )
                _log_prompt("System", "你是翻译质量评估专家。请批判性地评估翻译质量。")
                _log_prompt("Human", full_prompt)
            
            reflections = await step2_chain.ainvoke({
                "originals": input_text,
                "translations": translations_text,
                "count": count
            })
            
            # 去除思考链标签
            reflections = self._strip_thinking_tags(reflections)
            
            # 调试日志：打印反思响应
            if TranslationConfig.DEBUG_LOG_RESPONSES:
                _log_response("Step2", reflections)
            
            # ========== 第三步：优化 ==========
            if TranslationConfig.DEBUG_LOG_PROMPTS:
                _log_step("优化翻译", 3, 3)
            else:
                logger.info(f"    ✨ Step 3/3: 优化翻译...")
            
            step3_prompt = ChatPromptTemplate.from_messages([
                ("system", "你是专业的英中翻译专家。请基于反思意见输出最优翻译。"),
                ("human", BATCH_STEP3_OPTIMIZE_PROMPT)
            ])
            step3_chain = step3_prompt | structured_llm
            
            # 调试日志：打印优化请求
            if TranslationConfig.DEBUG_LOG_PROMPTS:
                full_prompt = BATCH_STEP3_OPTIMIZE_PROMPT.format(
                    originals=input_text,
                    translations=translations_text,
                    reflections=reflections,
                    count=count
                )
                _log_prompt("System", "你是专业的英中翻译专家。请基于反思意见输出最优翻译。")
                _log_prompt("Human", full_prompt)
            
            step3_result = await step3_chain.ainvoke({
                "originals": input_text,
                "translations": translations_text,
                "reflections": reflections,
                "count": count
            })
            
            # 调试日志：打印优化响应
            if TranslationConfig.DEBUG_LOG_RESPONSES:
                if step3_result and hasattr(step3_result, 'translations'):
                    result_text = "\n".join([f"{t.id}. {t.text}" for t in step3_result.translations])
                    _log_response("Step3", f"获得 {len(step3_result.translations)} 条优化翻译:\n{result_text}")
            
            # 解析最终优化结果
            translations = {}
            if step3_result and hasattr(step3_result, 'translations'):
                for item in step3_result.translations:
                    if 1 <= item.id <= count:
                        translations[item.id] = item.text
            
            # 如果优化结果不完整，用初次翻译结果补充
            for i in range(1, count + 1):
                if i not in translations and i in first_translations:
                    translations[i] = first_translations[i]
            
            return translations
        else:
            # DeepSeek 使用传统方式（简化版三步）
            prompt = BATCH_TRANSLATION_PROMPT.format(subtitles=input_text, count=count)
            result = await self._make_deepseek_request(prompt)
            return self._parse_batch_translation_result(result, count)
    
    async def _translate_batch_once(self, batch_indices: List[int], subtitles: List[Dict[str, Any]], 
                                    translated_subtitles: List[Dict[str, Any]], 
                                    use_structured: bool = True) -> tuple:
        """
        执行一次批量翻译
        
        参数:
            batch_indices: 要翻译的字幕索引
            subtitles: 原始字幕列表
            translated_subtitles: 翻译结果列表（会被修改）
            use_structured: 是否使用结构化输出
        
        返回: (成功数, 失败的索引列表)
        """
        success_count = 0
        failed_indices = []
        
        try:
            if use_structured and self.api_type in ("ollama", "vllm"):
                # 使用结构化输出
                translations = await self._translate_batch_structured(batch_indices, subtitles)
            else:
                # 使用传统文本解析
                batch_texts = []
                for local_idx, global_idx in enumerate(batch_indices, 1):
                    subtitle = subtitles[global_idx]
                    original_text = subtitle.get('original_text', subtitle.get('text', ''))
                    batch_texts.append(f"[{local_idx}] {original_text}")
                
                input_text = "\n".join(batch_texts)
                prompt = BATCH_TRANSLATION_PROMPT.format(subtitles=input_text, count=len(batch_indices))
                
                if self.api_type == "ollama":
                    batch_llm = ChatOllama(
                        model=self.model,
                        base_url=settings.OLLAMA_API_URL,
                        temperature=TranslationConfig.MODEL_TEMPERATURE,
                        num_predict=TranslationConfig.BATCH_TRANSLATION_MAX_TOKENS,
                        top_p=TranslationConfig.MODEL_TOP_P,
                        top_k=TranslationConfig.MODEL_TOP_K,
                        repeat_penalty=TranslationConfig.MODEL_REPEAT_PENALTY,
                    )
                    messages = [HumanMessage(content=prompt)]
                    response = await batch_llm.ainvoke(messages)
                    result = response.content
                elif self.api_type == "vllm":
                    from langchain_openai import ChatOpenAI
                    batch_llm = ChatOpenAI(
                        model=self.model,
                        openai_api_base=f"{settings.VLLM_API_URL}/v1",
                        openai_api_key=settings.VLLM_API_KEY,
                        temperature=TranslationConfig.MODEL_TEMPERATURE,
                        max_tokens=TranslationConfig.BATCH_TRANSLATION_MAX_TOKENS,
                    )
                    messages = [HumanMessage(content=prompt)]
                    response = await batch_llm.ainvoke(messages)
                    result = response.content
                else:
                    result = await self._make_deepseek_request(prompt)
                
                translations = self._parse_batch_translation_result(result, len(batch_indices))
        except Exception as e:
            logger.warning(f"结构化输出失败，回退到文本解析: {e}")
            # 回退到传统方式
            batch_texts = []
            for local_idx, global_idx in enumerate(batch_indices, 1):
                subtitle = subtitles[global_idx]
                original_text = subtitle.get('original_text', subtitle.get('text', ''))
                batch_texts.append(f"[{local_idx}] {original_text}")
            
            input_text = "\n".join(batch_texts)
            prompt = BATCH_TRANSLATION_PROMPT.format(subtitles=input_text, count=len(batch_indices))
            
            if self.api_type == "ollama":
                batch_llm = ChatOllama(
                    model=self.model,
                    base_url=settings.OLLAMA_API_URL,
                    temperature=TranslationConfig.MODEL_TEMPERATURE,
                    num_predict=TranslationConfig.BATCH_TRANSLATION_MAX_TOKENS,
                )
            elif self.api_type == "vllm":
                from langchain_openai import ChatOpenAI
                batch_llm = ChatOpenAI(
                    model=self.model,
                    openai_api_base=f"{settings.VLLM_API_URL}/v1",
                    openai_api_key=settings.VLLM_API_KEY,
                    temperature=TranslationConfig.MODEL_TEMPERATURE,
                    max_tokens=TranslationConfig.BATCH_TRANSLATION_MAX_TOKENS,
                )
            else:
                result = await self._make_deepseek_request(prompt)
                translations = self._parse_batch_translation_result(result, len(batch_indices))
                batch_llm = None
            
            if batch_llm:
                messages = [HumanMessage(content=prompt)]
                response = await batch_llm.ainvoke(messages)
                translations = self._parse_batch_translation_result(response.content, len(batch_indices))
        
        # 应用翻译结果
        for local_idx, global_idx in enumerate(batch_indices, 1):
            if local_idx in translations:
                translated_subtitles[global_idx] = subtitles[global_idx].copy()
                original_text = subtitles[global_idx].get('original_text', subtitles[global_idx].get('text', ''))
                translated_subtitles[global_idx]['original_text'] = original_text
                translated_subtitles[global_idx]['text'] = translations[local_idx]
                translated_subtitles[global_idx]['translation_failed'] = False
                success_count += 1
            else:
                failed_indices.append(global_idx)
        
        return success_count, failed_indices
    
    async def translate_subtitles_batch_mode(self, subtitles: List[Dict[str, Any]], 
                                            batch_size: int = None,
                                            progress_callback: Optional[Callable] = None) -> List[Dict[str, Any]]:
        """
        自适应批量翻译字幕
        
        特性:
        - 自动根据成功率调整批次大小
        - 失败的部分自动拆分成小批次重试
        - 最终回退到逐条翻译
        
        参数:
            subtitles: 字幕列表
            batch_size: 初始批大小（默认使用配置值）
            progress_callback: 进度回调
        
        返回:
            翻译后的字幕列表
        """
        if batch_size is None:
            batch_size = TranslationConfig.BATCH_TRANSLATION_SIZE
        
        total = len(subtitles)
        translated_subtitles = [s.copy() for s in subtitles]  # 深复制
        
        # 找出需要翻译的字幕索引
        pending_indices = []
        for i, subtitle in enumerate(subtitles):
            if not self._is_translation_successful(subtitle):
                pending_indices.append(i)
        
        if not pending_indices:
            logger.info("✅ 所有字幕已翻译，无需处理")
            return translated_subtitles
        
        use_structured = TranslationConfig.USE_STRUCTURED_OUTPUT
        mode_str = "结构化JSON" if use_structured else "文本解析"
        logger.info(f"📝 自适应批量翻译: 共 {total} 条，待翻译 {len(pending_indices)} 条，初始批次 {batch_size}，模式: {mode_str}")
        
        # 自适应批量翻译
        current_batch_size = min(batch_size, len(pending_indices))
        remaining_indices = pending_indices.copy()
        total_success = 0
        batch_num = 0
        
        # 最小批次阈值：低于此值时切换到逐条翻译
        min_batch_threshold = max(3, batch_size // 10)  # 最小为3，或初始批次的1/10
        
        while remaining_indices and current_batch_size >= min_batch_threshold:
            batch_num += 1
            # 取当前批次
            batch_indices = remaining_indices[:current_batch_size]
            
            logger.info(f"🔄 批次 {batch_num}: 处理 {len(batch_indices)} 条 (批次大小: {current_batch_size})")
            
            try:
                success_count, failed_indices = await self._translate_batch_once(
                    batch_indices, subtitles, translated_subtitles, use_structured=use_structured
                )
                
                success_rate = success_count / len(batch_indices) if batch_indices else 0
                logger.info(f"  ✅ 成功 {success_count}/{len(batch_indices)} ({success_rate*100:.1f}%)")
                
                # 移除成功的索引
                successful_indices = [idx for idx in batch_indices if idx not in failed_indices]
                for idx in successful_indices:
                    if idx in remaining_indices:
                        remaining_indices.remove(idx)
                total_success += success_count
                
                # 根据成功率调整批次大小
                if success_rate < 0.5:
                    # 成功率低于50%，减半批次大小
                    new_batch_size = max(min_batch_threshold, current_batch_size // 2)
                    logger.info(f"  📉 成功率低，批次大小: {current_batch_size} → {new_batch_size}")
                    current_batch_size = new_batch_size
                elif success_rate >= 0.9 and current_batch_size < batch_size:
                    # 成功率高于90%，可以尝试增大批次
                    new_batch_size = min(batch_size, int(current_batch_size * 1.5))
                    logger.info(f"  📈 成功率高，批次大小: {current_batch_size} → {new_batch_size}")
                    current_batch_size = new_batch_size
                
            except Exception as e:
                logger.error(f"  ❌ 批次失败: {e}")
                # 出错时减半批次大小
                new_batch_size = max(min_batch_threshold, current_batch_size // 2)
                logger.info(f"  📉 异常发生，批次大小: {current_batch_size} → {new_batch_size}")
                current_batch_size = new_batch_size
            
            # 进度回调
            if progress_callback:
                done = len(pending_indices) - len(remaining_indices)
                progress = int(done / len(pending_indices) * 100)
                await progress_callback(progress, f"批量翻译 {done}/{len(pending_indices)}")
            
            # 批次间延迟
            await asyncio.sleep(0.3)
        
        # 剩余的用逐条方式处理
        if remaining_indices:
            logger.info(f"🔄 对剩余 {len(remaining_indices)} 条字幕进行逐条翻译...")
            for i, global_idx in enumerate(remaining_indices):
                try:
                    original_text = subtitles[global_idx].get('original_text', subtitles[global_idx].get('text', ''))
                    if original_text:
                        translated_text = await self.translate_single(original_text, use_context=True)
                        if not translated_text.startswith('翻译失败:'):
                            translated_subtitles[global_idx]['original_text'] = original_text
                            translated_subtitles[global_idx]['text'] = translated_text
                            translated_subtitles[global_idx]['translation_failed'] = False
                            if 'translation_error' in translated_subtitles[global_idx]:
                                del translated_subtitles[global_idx]['translation_error']
                            total_success += 1
                            logger.info(f"  ✅ [{global_idx+1}] 成功")
                        else:
                            translated_subtitles[global_idx]['original_text'] = original_text
                            translated_subtitles[global_idx]['translation_failed'] = True
                            translated_subtitles[global_idx]['translation_error'] = translated_text
                            logger.warning(f"  ❌ [{global_idx+1}] 失败")
                except Exception as e:
                    translated_subtitles[global_idx]['translation_failed'] = True
                    translated_subtitles[global_idx]['translation_error'] = str(e)
                    logger.warning(f"  ❌ [{global_idx+1}] 异常: {e}")
                
                # 进度回调
                if progress_callback:
                    done = len(pending_indices) - len(remaining_indices) + i + 1
                    progress = int(done / len(pending_indices) * 100)
                    await progress_callback(progress, f"逐条翻译 {i+1}/{len(remaining_indices)}")
                
                await asyncio.sleep(TranslationConfig.BATCH_DELAY)
        
        # 最终统计
        final_failed = sum(1 for s in translated_subtitles if s.get('translation_failed', False))
        logger.info(f"📊 翻译完成: 成功 {len(pending_indices) - final_failed}/{len(pending_indices)} 条")
        
        return translated_subtitles
    
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
                                max_retries: int = 3,
                                use_batch_mode: bool = None) -> List[Dict[str, Any]]:
        """
        翻译字幕列表，支持跳过已翻译和自动重试失败项
        
        参数:
            subtitles: 字幕列表
            progress_callback: 进度回调函数
            max_retries: 失败重试次数
            use_batch_mode: 是否使用批量模式（None时使用配置值）
        """
        # 判断是否使用批量模式
        if use_batch_mode is None:
            use_batch_mode = TranslationConfig.ENABLE_BATCH_TRANSLATION
        
        if use_batch_mode:
            logger.info("📦 使用批量翻译模式")
            return await self.translate_subtitles_batch_mode(
                subtitles, 
                progress_callback=progress_callback
            )
        
        # 逐条翻译模式
        logger.info("📝 使用逐条翻译模式")
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
