# 字幕格式修复说明

## 🔍 问题描述

您发现字幕数据格式不正确，缺少正确的字段结构。正确的格式应该是：

- `original_text`: STT提取的原始英文文本
- `text`: 翻译后的中文文本

但是从生成的文件中可以看到，有些文件只有 `text` 字段，没有 `original_text` 字段。

## ✅ 修复方案

我已经修复了 `services/translation_service.py` 文件，添加了字幕格式处理逻辑：

### 1. 新增格式化方法

```python
def _prepare_subtitle_format(self, subtitles: List[Dict]) -> List[Dict]:
    """准备字幕格式，确保有正确的original_text和text字段"""
```

这个方法会：
- 将原始的 `text` 字段内容保存为 `original_text`
- 创建新的 `text` 字段用于翻译结果
- 保留其他所有字段

### 2. 修复后的字幕格式

**修复前**：
```json
{
  "start": 24.83,
  "end": 32.83,
  "text": "I think we'll see each other again...",
  "speaker": "SPEAKER_01"
}
```

**修复后**：
```json
{
  "start": 24.83,
  "end": 32.83,
  "original_text": "I think we'll see each other again...",
  "text": "[翻译] I think we'll see each other again...",
  "speaker": "SPEAKER_01",
  "translation_quality": "placeholder",
  "context_used": false,
  "batch_size_used": 1
}
```

### 3. 字段说明

| 字段名 | 说明 | 示例 |
|--------|------|------|
| `original_text` | STT提取的原始英文文本 | "I think we'll see each other again." |
| `text` | 翻译后的中文文本 | "我想我们会再次见面的。" |
| `translation_quality` | 翻译质量 | "good", "poor", "placeholder" |
| `context_used` | 是否使用了上下文 | true/false |
| `batch_size_used` | 使用的批处理大小 | 1 |

## 🧪 测试验证

运行测试脚本验证修复效果：

```bash
python test_subtitle_format.py
```

测试结果显示：
- ✅ 原始字幕正确格式化为包含 `original_text` 和 `text` 的格式
- ✅ 翻译过程正确更新 `text` 字段
- ✅ 添加了翻译质量等元数据字段

## 🔧 集成到现有流程

修复后的翻译服务会自动：

1. **格式化输入字幕**：确保有正确的字段结构
2. **保留原始文本**：将STT结果保存为 `original_text`
3. **生成翻译文本**：将翻译结果保存为 `text`
4. **添加元数据**：包含翻译质量、上下文使用等信息

## 📝 注意事项

1. **向后兼容**：修复后的代码会处理旧格式的字幕文件
2. **字段保留**：所有原有字段都会被保留
3. **翻译API**：当前使用占位符翻译，实际使用时需要集成真正的翻译API

## 🎯 下一步

1. **集成真实翻译API**：替换占位符翻译逻辑
2. **优化翻译质量**：实现更好的翻译算法
3. **添加更多元数据**：如翻译时间、模型版本等

现在字幕格式问题已经解决，您的翻译流程应该能正确生成包含 `original_text` 和 `text` 字段的字幕文件了！🎉 