#!/usr/bin/env python3
"""
测试翻译质量检查修复效果的脚本
"""

import logging
import sys
import re

# 设置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class MockTranslationConfig:
    """模拟翻译配置"""
    MIN_LENGTH_RATIO = 0.3
    MAX_LENGTH_RATIO = 3.0

class QualityChecker:
    """翻译质量检查器"""
    
    def _is_chinese_text(self, text: str) -> bool:
        """判断文本是否包含中文"""
        chinese_pattern = re.compile(r'[\u4e00-\u9fff]+')
        return bool(chinese_pattern.search(text))
    
    def _check_translation_quality(self, original_texts, translated_texts):
        """检查翻译质量"""
        quality_results = []
        
        for i, (original, translated) in enumerate(zip(original_texts, translated_texts)):
            print(f"\n质量检查第{i+1}条:")
            print(f"  原文: '{original}'")
            print(f"  译文: '{translated}'")
            
            # 检查1: 翻译是否包含中文
            has_chinese = self._is_chinese_text(translated)
            print(f"  包含中文: {has_chinese}")
            
            # 检查2: 翻译是否与原文相同
            is_different = original.strip() != translated.strip()
            print(f"  与原文不同: {is_different}")
            
            # 检查3: 翻译长度是否合理
            if len(original) > 0:
                char_ratio = len(translated) / len(original)
                original_word_count = len(original.split())
                translated_char_count = len([c for c in translated if '\u4e00' <= c <= '\u9fff'])
                word_char_ratio = translated_char_count / original_word_count if original_word_count > 0 else char_ratio
                
                reasonable_length = (
                    MockTranslationConfig.MIN_LENGTH_RATIO <= char_ratio <= MockTranslationConfig.MAX_LENGTH_RATIO or
                    0.5 <= word_char_ratio <= 4.0
                )
                
                print(f"  字符长度比例: {char_ratio:.2f}")
                print(f"  单词-字符比例: {word_char_ratio:.2f}")
                print(f"  长度合理: {reasonable_length}")
            else:
                reasonable_length = True
                print(f"  长度合理: {reasonable_length} (原文为空)")
            
            # 检查4: 翻译是否为空
            not_empty = bool(translated.strip())
            print(f"  非空: {not_empty}")
            
            # 检查5: 检查错误标识
            error_indicators = ["无法翻译", "不能翻译", "翻译失败", "error", "failed"]
            no_error_indicators = not any(indicator in translated.lower() for indicator in error_indicators)
            print(f"  无错误标识: {no_error_indicators}")
            
            # 综合评估
            is_good_translation = has_chinese and is_different and reasonable_length and not_empty and no_error_indicators
            quality_results.append(is_good_translation)
            
            print(f"  ✅ 质量评估: {'通过' if is_good_translation else '❌ 失败'}")
        
        return quality_results

def test_quality_check():
    """测试质量检查"""
    print("🧪 测试翻译质量检查逻辑\n" + "="*50)
    
    checker = QualityChecker()
    
    # 测试用例
    test_cases = [
        {
            "name": "正常翻译",
            "original": ["Hello, this is a test."],
            "translated": ["你好，这是一个测试。"],
            "expected": [True]
        },
        {
            "name": "翻译与原文相同",
            "original": ["Hello world."],
            "translated": ["Hello world."],
            "expected": [False]
        },
        {
            "name": "翻译为空",
            "original": ["Hello world."],
            "translated": [""],
            "expected": [False]
        },
        {
            "name": "翻译不包含中文",
            "original": ["Hello world."],
            "translated": ["Hello there."],
            "expected": [False]
        },
        {
            "name": "翻译过短",
            "original": ["This is a very long sentence with many words and complex meaning."],
            "translated": ["短"],
            "expected": [False]  # 可能通过，因为单词-字符比例检查
        },
        {
            "name": "翻译包含错误标识",
            "original": ["Hello world."],
            "translated": ["我无法翻译这个句子"],
            "expected": [False]
        },
        {
            "name": "实际Ollama返回结果",
            "original": ["Hello, this is a test for translation."],
            "translated": ["你好，这是一次翻译测试。"],
            "expected": [True]
        }
    ]
    
    all_passed = True
    
    for i, test_case in enumerate(test_cases):
        print(f"\n📝 测试 {i+1}: {test_case['name']}")
        print("-" * 30)
        
        results = checker._check_translation_quality(test_case["original"], test_case["translated"])
        expected = test_case["expected"]
        
        if results == expected:
            print(f"✅ 测试通过")
        else:
            print(f"❌ 测试失败")
            print(f"   期望结果: {expected}")
            print(f"   实际结果: {results}")
            all_passed = False
    
    print("\n" + "="*50)
    if all_passed:
        print("🎉 所有质量检查测试通过!")
    else:
        print("❌ 部分测试失败，需要进一步调整")
    
    return all_passed

if __name__ == "__main__":
    test_quality_check() 