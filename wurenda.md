# 吴恩达的TranslationAgent

## TranslationAgent构成

整个[TranslationAgent (github.com)]在流程上分为短文本的一次性翻译和长文本的分chunk翻译（按照Token进行划分）。但是不论长文本翻译还是短文本翻译，总体流程遵循执行、纠正再执行的逻辑循环实现。

这种按照自省思路来使用大模型的逻辑在近阶段的一些大模型应用论文和项目中经常出现，比如：
- DoubleCheck的Prompt
- [CRAG(Corrective Retrieval Augmented Generation)]的论文
- LangChain使用的ReAct

这种自省的逻辑其实都体现了一个核心思路：别让大模型一次做太复杂的事。感觉大模型在推理解决问题方面的方案在逐渐统一：

1. 大模型逐步规划
2. 执行计划
3. 结合结果重新规划
4. 再执行
5. ...

## 翻译流程

翻译分为三个阶段：

1. `chunk_initial_translation`：单次翻译，得到结果
2. `chunk_reflect_on_translation`：审视检查翻译结果，决定如何改进
3. `chunk_improve_translation`：根据改进点重新翻译得到结果

## Prompt设计详解

### 一、首轮翻译-one_chunk_initial_translation

#### System Prompt
```
你是一个语言专家，擅长把信息从{source_lang}翻译成{target_lang}
```

#### Message Prompt
```
这是一个从{source_lang}到{target_lang}的翻译，请为这段文本提供{target_lang}的译文。除了译文，不要提供任何解释或其他文字。
{source_lang}:{source_text}

{target_lang}:
```

### 二、自省翻译结果-one_chunk_reflect_on_translation

#### System Prompt
```
你是一个语言专家，擅长把信息从{source_lang}翻译成{target_lang}。
你会得到一段源语言的文本和一段译文，你的目标是改进这段译文。
```

#### Message Prompt
```
你的任务是仔细查看源文本和对应的{source_lang}到{target_lang}的译文，然后给出有建设性的批评和有用的建议来改进译文。
译文的最终风格和语气应与在{country}口语中使用的{target_lang}的风格相匹配。

<SOURCE_TEXT>
{source_text}
</SOURCE_TEXT>

<TRANSLATION>
{translation_1}
</TRANSLATION>

在撰写建议时，请注意是否有方法可以改进翻译的：
(i) 准确性（通过纠正添加、误译、遗漏或未翻译文本的错误）
(ii) 流畅性（通过应用{target_lang}语法、拼写和标点规则，并确保没有不必要的重复）
(iii) 风格（通过确保翻译反映源文本的风格并考虑任何文化背景）
(iv) 术语（通过确保术语使用一致并反映源文本领域；并且仅确保您使用等效术语）

列出具体、有用且有建设性的建议，以改进翻译。
每条建议应针对翻译的一个特定部分。
仅输出建议，不输出其他内容。
```

### 三、改进翻译结果-one_chunk_improve_translation

#### System Prompt
```
你是一个语言专家，擅长从{source_lang}到{target_lang}的翻译编辑。
```

#### Message Prompt
```
你的任务是仔细阅读并编辑从{source_lang}到{target_lang}的翻译，同时考虑专家建议和建设性批评。

<SOURCE_TEXT>
{source_text}
</SOURCE_TEXT>

<TRANSLATION>
{translation_1}
</TRANSLATION>

<EXPERT_SUGGESTIONS>
{reflection}
</EXPERT_SUGGESTIONS>

请根据专家建议编辑翻译，确保：
(i) 准确性（纠正添加、误译、遗漏或未翻译文本的错误）
(ii) 流畅性（应用{target_lang}语法、拼写和标点规则，确保没有不必要的重复）
(iii) 风格（确保翻译反映源文本的风格）
(iv) 术语（确保术语使用适当且一致）
(v) 其他错误

仅输出新的翻译，不输出其他内容。
```

## 总结

吴恩达老师的这个项目在实际测试中效果确实很好，主要得益于：
1. 自省式的实现思路
2. Prompt的使用非常到位

当然项目也有其局限性，正如Git上的Readme所述。后续我们还会分析长文本是如何实现自省和翻译的。
