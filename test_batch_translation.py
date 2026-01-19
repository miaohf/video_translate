"""
测试批量翻译功能
使用 nemotron-3-nano 模型一次性翻译多条字幕
"""

import asyncio
import aiohttp
import json
import time
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Ollama API 配置
OLLAMA_URL = "http://127.0.0.1:61434"
MODEL = "nemotron-3-nano:latest"

# 测试字幕数据（模拟10条字幕）
TEST_SUBTITLES = [
    {"id": 1, "text": "Hello, welcome to our documentary about artificial intelligence."},
    {"id": 2, "text": "Machine learning is transforming our world in many ways."},
    {"id": 3, "text": "Deep neural networks can process complex patterns."},
    {"id": 4, "text": "Artificial intelligence has many applications in healthcare."},
    {"id": 5, "text": "Self-driving cars rely on computer vision and AI."},
    {"id": 6, "text": "Natural language processing helps computers understand human speech."},
    {"id": 7, "text": "AI is being used to solve climate change problems."},
    {"id": 8, "text": "Robotics and AI are revolutionizing manufacturing."},
    {"id": 9, "text": "The future of AI is both exciting and challenging."},
    {"id": 10, "text": "We must ensure AI is developed responsibly and ethically."},
]

# 批量翻译提示词模板
BATCH_TRANSLATION_PROMPT = """你是一位专业的英中翻译专家。请将以下字幕翻译成中文。

## 输入格式
每行一条字幕，格式为: [序号] 原文

## 输出格式
每行一条翻译，格式为: [序号] 译文
请严格按照输入的序号顺序输出，确保序号一一对应。

## 翻译要求
1. 保持自然流畅的中文表达
2. 保持原意不变
3. 翻译后的句子长短应与原文接近

## 待翻译字幕：
{subtitles}

## 开始翻译（只输出译文，每行一条）：
"""


async def test_single_translation():
    """测试单条翻译（对照组）"""
    logger.info("=" * 60)
    logger.info("测试1: 逐条翻译（对照组）")
    logger.info("=" * 60)
    
    async with aiohttp.ClientSession() as session:
        start_time = time.time()
        results = []
        
        for sub in TEST_SUBTITLES:
            prompt = f"请将以下英文翻译成中文：{sub['text']}"
            
            data = {
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1}
            }
            
            try:
                async with session.post(f"{OLLAMA_URL}/api/generate", json=data) as response:
                    if response.status == 200:
                        result = await response.json()
                        translated = result.get("response", "").strip()
                        results.append({"id": sub["id"], "original": sub["text"], "translated": translated})
                        logger.info(f"  [{sub['id']}] {translated[:50]}...")
                    else:
                        logger.error(f"  [{sub['id']}] 请求失败: {response.status}")
            except Exception as e:
                logger.error(f"  [{sub['id']}] 异常: {e}")
        
        elapsed = time.time() - start_time
        logger.info(f"\n逐条翻译完成: {len(results)}/{len(TEST_SUBTITLES)} 条")
        logger.info(f"总耗时: {elapsed:.2f}s, 平均: {elapsed/len(TEST_SUBTITLES):.2f}s/条")
        
        return results, elapsed


async def test_batch_translation():
    """测试批量翻译"""
    logger.info("=" * 60)
    logger.info("测试2: 批量翻译（一次性提交）")
    logger.info("=" * 60)
    
    # 构建批量翻译输入
    subtitle_lines = "\n".join([f"[{sub['id']}] {sub['text']}" for sub in TEST_SUBTITLES])
    prompt = BATCH_TRANSLATION_PROMPT.format(subtitles=subtitle_lines)
    
    logger.info(f"输入 token 估计: ~{len(prompt.split())*1.5:.0f} tokens")
    
    async with aiohttp.ClientSession() as session:
        start_time = time.time()
        
        data = {
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 4096  # 增加输出 token 限制
            }
        }
        
        try:
            async with session.post(f"{OLLAMA_URL}/api/generate", json=data, timeout=aiohttp.ClientTimeout(total=300)) as response:
                if response.status == 200:
                    result = await response.json()
                    translated_text = result.get("response", "").strip()
                    
                    elapsed = time.time() - start_time
                    logger.info(f"\n批量翻译完成，耗时: {elapsed:.2f}s")
                    logger.info(f"\n原始输出:\n{translated_text}")
                    
                    # 解析结果
                    results = parse_batch_result(translated_text)
                    logger.info(f"\n解析结果: {len(results)}/{len(TEST_SUBTITLES)} 条")
                    
                    for r in results:
                        logger.info(f"  [{r['id']}] {r['translated'][:50]}...")
                    
                    return results, elapsed
                else:
                    logger.error(f"请求失败: {response.status}")
                    return [], 0
        except Exception as e:
            logger.error(f"异常: {e}")
            return [], 0


def parse_batch_result(text: str) -> list:
    """解析批量翻译结果"""
    results = []
    lines = text.strip().split("\n")
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # 尝试解析 [序号] 译文 格式
        if line.startswith("["):
            try:
                # 提取序号和文本
                end_bracket = line.index("]")
                id_str = line[1:end_bracket]
                translated = line[end_bracket+1:].strip()
                
                results.append({
                    "id": int(id_str),
                    "translated": translated
                })
            except (ValueError, IndexError):
                # 尝试其他格式
                pass
        elif line[0].isdigit():
            # 尝试 "序号. 译文" 或 "序号、译文" 格式
            for sep in [". ", "、", ") ", "） "]:
                if sep in line:
                    parts = line.split(sep, 1)
                    try:
                        id_num = int(parts[0].strip())
                        translated = parts[1].strip()
                        results.append({"id": id_num, "translated": translated})
                        break
                    except ValueError:
                        pass
    
    return results


async def test_batch_translation_json():
    """测试 JSON 格式的批量翻译"""
    logger.info("=" * 60)
    logger.info("测试3: 批量翻译（JSON格式）")
    logger.info("=" * 60)
    
    # 使用 JSON 格式
    subtitles_json = json.dumps(TEST_SUBTITLES, ensure_ascii=False)
    
    prompt = f"""你是一位专业的英中翻译专家。请将以下字幕翻译成中文。

## 输入（JSON格式）:
{subtitles_json}

## 输出要求:
请返回 JSON 数组，每个元素包含 id 和 text（翻译后的中文）。
只输出 JSON，不要其他内容。

## 开始翻译:
"""
    
    async with aiohttp.ClientSession() as session:
        start_time = time.time()
        
        data = {
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 4096
            }
        }
        
        try:
            async with session.post(f"{OLLAMA_URL}/api/generate", json=data, timeout=aiohttp.ClientTimeout(total=300)) as response:
                if response.status == 200:
                    result = await response.json()
                    translated_text = result.get("response", "").strip()
                    
                    elapsed = time.time() - start_time
                    logger.info(f"\n批量翻译完成，耗时: {elapsed:.2f}s")
                    logger.info(f"\n原始输出:\n{translated_text}")
                    
                    # 尝试解析 JSON
                    try:
                        # 提取 JSON 部分
                        json_start = translated_text.find("[")
                        json_end = translated_text.rfind("]") + 1
                        if json_start >= 0 and json_end > json_start:
                            json_str = translated_text[json_start:json_end]
                            results = json.loads(json_str)
                            logger.info(f"\n解析结果: {len(results)}/{len(TEST_SUBTITLES)} 条")
                            for r in results:
                                logger.info(f"  [{r.get('id')}] {r.get('text', '')[:50]}...")
                            return results, elapsed
                    except json.JSONDecodeError as e:
                        logger.error(f"JSON 解析失败: {e}")
                    
                    return [], elapsed
                else:
                    logger.error(f"请求失败: {response.status}")
                    return [], 0
        except Exception as e:
            logger.error(f"异常: {e}")
            return [], 0


async def main():
    """主测试函数"""
    logger.info("🚀 开始测试批量翻译功能")
    logger.info(f"   模型: {MODEL}")
    logger.info(f"   测试字幕数: {len(TEST_SUBTITLES)} 条")
    logger.info("")
    
    # 测试1: 逐条翻译
    single_results, single_time = await test_single_translation()
    
    logger.info("\n" + "=" * 60 + "\n")
    
    # 测试2: 批量翻译（文本格式）
    batch_results, batch_time = await test_batch_translation()
    
    logger.info("\n" + "=" * 60 + "\n")
    
    # 测试3: 批量翻译（JSON格式）
    json_results, json_time = await test_batch_translation_json()
    
    # 结果对比
    logger.info("\n" + "=" * 60)
    logger.info("📊 测试结果对比")
    logger.info("=" * 60)
    logger.info(f"逐条翻译: {single_time:.2f}s ({len(single_results)}/{len(TEST_SUBTITLES)} 条成功)")
    logger.info(f"批量翻译(文本): {batch_time:.2f}s ({len(batch_results)}/{len(TEST_SUBTITLES)} 条成功)")
    logger.info(f"批量翻译(JSON): {json_time:.2f}s ({len(json_results)}/{len(TEST_SUBTITLES)} 条成功)")
    
    if single_time > 0 and batch_time > 0:
        speedup = single_time / batch_time
        logger.info(f"\n📈 批量翻译(文本)加速比: {speedup:.2f}x")
    
    if single_time > 0 and json_time > 0:
        speedup = single_time / json_time
        logger.info(f"📈 批量翻译(JSON)加速比: {speedup:.2f}x")


if __name__ == "__main__":
    asyncio.run(main())

