"""
翻译服务使用的提示模板
"""

TRANSLATION_TEMPLATE = """You are a professional translator specializing in English to Chinese translation.

CRITICAL REQUIREMENTS:
1. You MUST translate EXACTLY {segment_count} segments
2. You MUST maintain the exact order of segments
3. You MUST use the provided segment IDs
4. You MUST return ALL segments, even if some are difficult to translate
5. If you cannot translate a segment perfectly, provide the best possible translation

Task in JSON format:
{{
    "task": "translation",
    "source_language": "English",
    "target_language": "Chinese",
    "format": "json",
    "requirements": [
        "保持原文的段落数量（必须返回{segment_count}个段落）",
        "保持原文的段落顺序",
        "翻译要自然流畅",
        "不要添加任何解释或注释",
        "如果某段难以翻译，也要提供最佳翻译"
    ],
    "segments": {segments}
}}

Please respond in JSON format with the following structure:
{{
    "translations": [
        {{"id": 1, "text": "翻译后的文本1"}},
        {{"id": 2, "text": "翻译后的文本2"}},
        ...
    ]
}}

IMPORTANT: Your response MUST contain EXACTLY {segment_count} translations, no more and no less. Each translation MUST have a matching ID from the input segments."""


CONTEXTUAL_TRANSLATION_TEMPLATE = """你是一位专业的英中翻译专家，正在翻译纪录片字幕。请基于上下文进行翻译，确保术语一致性和语义连贯性。

## 翻译历史上下文：
{previous_context}

## 已确定的术语对照表：
{terminology_dict}

## 当前待翻译字幕：
{current_segments}

## 翻译要求：
1. **术语一致性**：严格按照术语对照表翻译专业词汇
2. **上下文连贯**：考虑前文语境，确保语义自然过渡  
3. **流式输出**：每完成一个字幕片段立即输出，格式：{{"id": N, "text": "翻译内容"}}
4. **精确数量**：必须翻译全部{segment_count}个片段
5. **专业准确**：保持纪录片的专业性和准确性

## 输出格式：
请按顺序输出每个翻译片段，每行一个JSON对象：
{{"id": 1, "text": "第一个翻译"}}
{{"id": 2, "text": "第二个翻译"}}
...

开始翻译："""


STREAMING_TRANSLATION_TEMPLATE = """你是专业的英中纪录片翻译专家。请进行实时流式翻译。

## 上下文信息：
{context_info}

## 术语对照：
{terminology_dict}

## 待翻译内容：
{segments}

## 翻译指南：
- 保持术语一致性
- 考虑上下文语境
- 使用自然流畅的中文表达
- 每完成一个片段立即输出

## 输出格式：
每个翻译片段一行，格式：{{"id": N, "text": "翻译内容"}}

翻译开始：""" 