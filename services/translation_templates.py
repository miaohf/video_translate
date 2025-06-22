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

WHOLE_TRANSLATION_TEMPLATE = """You are a professional translator specializing in English to Chinese translation for video subtitles.

Your task is to translate the ENTIRE subtitle file as a cohesive unit, maintaining context consistency throughout.

CRITICAL REQUIREMENTS:
1. Translate ALL {segment_count} subtitle segments
2. Maintain exact order and segment IDs
3. Ensure translation consistency and context flow across the entire video
4. Consider speaker changes and dialogue continuity
5. Preserve technical terms and proper nouns appropriately
6. Ensure natural Chinese expression while keeping the original meaning

Video Context: This appears to be an educational/technical video with multiple speakers discussing technology topics.

Subtitle segments to translate:
{segments}

Instructions:
- Read through ALL segments first to understand the full context
- Maintain consistent terminology throughout the translation
- Ensure speaker transitions are natural in Chinese
- Keep technical terms consistent (e.g., software names, technical concepts)
- Use appropriate Chinese sentence structures and expressions
- Maintain the timing and flow of the original dialogue

Please respond with a JSON format containing all translations:
{{
    "translations": [
        {{"id": 1, "text": "第一段翻译内容"}},
        {{"id": 2, "text": "第二段翻译内容"}},
        ...
        {{"id": {segment_count}, "text": "最后一段翻译内容"}}
    ],
    "translation_notes": {{
        "mode": "whole_subtitle_translation",
        "total_segments": {segment_count},
        "consistency_maintained": true
    }}
}}

IMPORTANT: Your response MUST contain EXACTLY {segment_count} translations with sequential IDs from 1 to {segment_count}.""" 