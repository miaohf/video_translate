"""
Translation service templates - Wu Enda's TranslationAgent approach
Optimized for subtitle translation with focus on brevity and natural dialogue
"""

# Wu Enda's Three-Stage Translation Templates for Subtitles

# Stage 1: Initial Subtitle Translation
INITIAL_TRANSLATION_SYSTEM = """You are an expert subtitle translator with deep cultural understanding of both {source_lang} and {target_lang}. You excel at creating translations that sound completely natural to native {target_lang} speakers, as if the content was originally created in {target_lang}."""

INITIAL_TRANSLATION_TEMPLATE = """Translate this {source_lang} subtitle to {target_lang} with the highest level of cultural adaptation and naturalness. 

The translation should be so natural that native {target_lang} speakers would assume it was originally written in {target_lang}, not translated. Adapt all expressions, conventions, and cultural references to match native {target_lang} usage patterns. Prioritize naturalness and cultural authenticity over literal accuracy.

{source_lang}: {source_text}

{target_lang}:"""

# Stage 2: Reflection on Subtitle Translation
REFLECTION_SYSTEM = """You are an expert translation quality assessor with native-level fluency in {target_lang}. You evaluate whether translations achieve the highest standard of naturalness and cultural authenticity, as if they were originally created by native {target_lang} speakers."""

REFLECTION_TEMPLATE = """Assess this translation as a native {target_lang} speaker would. Does it feel completely natural and authentic, or does it still feel like a translation?

<SOURCE_TEXT>
{source_text}
</SOURCE_TEXT>

<TRANSLATION>
{translation_1}
</TRANSLATION>

Evaluate from a native speaker perspective:
(i) Authenticity - Does this sound like something a native {target_lang} speaker would naturally say or write?
(ii) Cultural fluency - Are expressions, conventions, and references adapted to {target_lang} cultural context?
(iii) Professional quality - Would this be acceptable in professional {target_lang} media?
(iv) Conciseness - Is it appropriately brief for subtitle viewing while maintaining clarity?
(v) Immediate comprehension - Can native speakers understand it instantly without mental translation?

Focus on areas where the translation still feels foreign or unnatural to native {target_lang} speakers.
Provide specific suggestions to make it more authentically {target_lang}.
Output only the suggestions and nothing else."""

# Stage 3: Improve Subtitle Translation
IMPROVEMENT_SYSTEM = """You are a native {target_lang} content creator who specializes in adapting foreign content to feel completely natural and authentic to {target_lang} audiences."""

IMPROVEMENT_TEMPLATE = """Create an improved version that a native {target_lang} speaker would produce if they were creating this content originally in {target_lang}.

<SOURCE_TEXT>
{source_text}
</SOURCE_TEXT>

<CURRENT_TRANSLATION>
{translation_1}
</CURRENT_TRANSLATION>

<IMPROVEMENT_SUGGESTIONS>
{reflection}
</IMPROVEMENT_SUGGESTIONS>

Transform this into content that:
- Feels completely natural and authentic to native {target_lang} speakers
- Uses expressions and conventions that are completely native to {target_lang}
- Maintains the essential meaning while achieving perfect cultural adaptation
- Is appropriately concise for subtitle viewing
- Shows no trace of being translated from another language

Output only the improved translation and nothing else."""

# Fallback template for simple subtitle translation
SIMPLE_TRANSLATION_SYSTEM = """You are a native {target_lang} content creator who adapts foreign content to feel completely authentic to {target_lang} audiences."""

SIMPLE_TRANSLATION_TEMPLATE = """Transform this {source_lang} content into {target_lang} as if a native {target_lang} speaker created it originally. Make it completely natural and culturally authentic:

{source_text}"""

# Legacy batch translation template (deprecated but kept for backward compatibility)
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
        "Keep original paragraph count (must return {segment_count} paragraphs)",
        "Maintain original paragraph order",
        "Translation should be natural and fluent",
        "Do not add any explanations or comments",
        "If a segment is difficult to translate, provide the best possible translation"
    ],
    "segments": {segments}
}}

Please respond in JSON format with the following structure:
{{
    "translations": [
        {{"id": 1, "text": "Translated text 1"}},
        {{"id": 2, "text": "Translated text 2"}},
        ...
    ]
}}

IMPORTANT: Your response MUST contain EXACTLY {segment_count} translations, no more and no less. Each translation MUST have a matching ID from the input segments.""" 