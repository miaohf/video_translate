import logging
from typing import List, Dict, Any
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
from config import settings
from utils.common import get_file_hash
from services.translation_templates import TRANSLATION_TEMPLATE
from services.translation_config import TranslationConfig

logger = logging.getLogger(__name__)

class TranslationService:
    def __init__(self, batch_size: int = None):
        """
        初始化翻译服务
        
        参数:
            batch_size: 批处理大小，如果为None则使用默认值
        """
        self.api_url = settings.OLLAMA_API_URL
        self.model = settings.OLLAMA_MODEL
        self.llm = OllamaLLM(model=self.model)
        self._session = None
        
        # 使用配置文件中的批处理大小
        if batch_size is None:
            self.batch_size = TranslationConfig.DEFAULT_BATCH_SIZE
        else:
            self.batch_size = TranslationConfig.validate_batch_size(batch_size)
        
        # 初始化提示词模板
        self.translation_prompt = PromptTemplate(
            input_variables=["segments", "segment_count"],
            template=TRANSLATION_TEMPLATE
        )
        
        logger.info(f"翻译服务已初始化，批处理大小: {self.batch_size}")

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 aiohttp 会话"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        """关闭 aiohttp 会话"""
        if self._session and not self._session.closed:
            await self._session.close()

    def _is_chinese_text(self, text: str) -> bool:
        """判断文本是否包含中文"""
        chinese_pattern = re.compile(r'[\u4e00-\u9fff]+')
        return bool(chinese_pattern.search(text))

    def _check_translation_quality(self, original_texts: List[str], translated_texts: List[str]) -> List[bool]:
        """
        检查翻译质量
        
        参数:
            original_texts: 原文列表
            translated_texts: 翻译文本列表
            
        返回:
            质量检查结果列表（True表示翻译成功，False表示翻译失败）
        """
        quality_results = []
        
        for i, (original, translated) in enumerate(zip(original_texts, translated_texts)):
            # 检查1: 翻译是否包含中文
            has_chinese = self._is_chinese_text(translated)
            
            # 检查2: 翻译是否与原文相同（说明翻译失败）
            is_different = original.strip() != translated.strip()
            
            # 检查3: 翻译长度是否合理（不能太短或太长）
            length_ratio = len(translated) / len(original) if len(original) > 0 else 0
            reasonable_length = TranslationConfig.MIN_LENGTH_RATIO <= length_ratio <= TranslationConfig.MAX_LENGTH_RATIO
            
            # 检查4: 翻译是否为空或只包含空白字符
            not_empty = bool(translated.strip())
            
            is_good_translation = has_chinese and is_different and reasonable_length and not_empty
            quality_results.append(is_good_translation)
            
            if not is_good_translation:
                logger.warning(f"翻译质量检查失败 (第{i+1}条): "
                             f"包含中文={has_chinese}, "
                             f"与原文不同={is_different}, "
                             f"长度合理={reasonable_length}, "
                             f"非空={not_empty}")
        
        return quality_results

    def _calculate_retry_delay(self, retry_count: int) -> float:
        """
        计算重试延迟时间（指数退避）
        
        参数:
            retry_count: 当前重试次数
            
        返回:
            延迟时间（秒）
        """
        delay = min(TranslationConfig.BASE_RETRY_DELAY * (2 ** retry_count), TranslationConfig.MAX_RETRY_DELAY)
        return delay

    def save_subtitles(self, subtitles: List[Dict[str, Any]], 
                      output_path: str, original_path: str) -> None:
        """
        保存字幕到文件
        
        参数:
            subtitles: 字幕列表
            output_path: 输出文件路径（中文）
            original_path: 原始字幕文件路径（英文）
        """
        try:
            # 确保输出目录存在
            output_dir = os.path.dirname(output_path)
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
                logger.info(f"Creating output directory: {output_dir}")
            
            # 只保存翻译后的字幕（中文）
            with open(output_path, "w", encoding="utf-8") as f:
                for i, subtitle in enumerate(subtitles, 1):
                    start_time = self.format_time(subtitle["start"])
                    end_time = self.format_time(subtitle["end"])
                    f.write(f"{i}\n{start_time} --> {end_time}\n{subtitle['text']}\n\n")
                    
            logger.info(f"Subtitles saved to {output_path}")
            
            # 保存 JSON 格式的字幕数据
            json_path = output_path.replace("_subtitles_zh.srt", "_subtitles_zh.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(subtitles, f, ensure_ascii=False, indent=2)
            logger.info(f"JSON subtitles saved to {json_path}")
            
        except Exception as e:
            logger.error(f"Error saving subtitles: {str(e)}")
            raise

    def _clean_translation(self, text: str) -> str:
        """
        清理翻译结果，移除 think 标签内容和多余的空行
        
        参数:
            text: 原始翻译文本
            
        返回:
            清理后的文本
        """
        # 移除 <think> 标签及其内容
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        # 移除多余的空行
        text = re.sub(r'\n\s*\n', '\n', text)
        # 移除首尾空白
        return text.strip()

    async def translate_batch(self, texts: List[str]) -> List[str]:
        """
        批量翻译文本
        
        参数:
            texts: 要翻译的文本列表
            
        返回:
            翻译后的文本列表
        """
        max_retries = TranslationConfig.MAX_RETRIES
        retry_count = 0
        
        logger.info(f"开始翻译批次: {len(texts)} 条字幕")
        
        while retry_count < max_retries:
            try:
                session = await self._get_session()
                
                # 准备段落数据
                segments = [{"id": i+1, "text": text} for i, text in enumerate(texts)]
                
                # 使用PromptTemplate格式化提示词
                prompt = self.translation_prompt.format(
                    segments=json.dumps(segments, ensure_ascii=False),
                    segment_count=len(texts)
                )
                
                # 构建请求数据
                data = {
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": TranslationConfig.get_model_options()
                }
                
                # 发送请求
                logger.debug(f"发送翻译请求到: {self.api_url}/api/generate")
                async with session.post(f"{self.api_url}/api/generate", json=data, timeout=TranslationConfig.REQUEST_TIMEOUT) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"API请求失败: 状态码 {response.status}, 错误: {error_text}")
                        raise Exception(f"API request failed with status {response.status}: {error_text}")
                    
                    result = await response.json()
                    if "error" in result:
                        logger.error(f"API返回错误: {result['error']}")
                        raise Exception(f"API error: {result['error']}")
                        
                    translated_text = result.get("response", "").strip()
                    if not translated_text:
                        logger.error("API返回空响应")
                        raise Exception("Empty response from API")
                    
                    # 清理翻译结果中的思考过程
                    translated_text = self._clean_translation(translated_text)
                    
                    try:
                        # 尝试解析JSON响应
                        response_data = json.loads(translated_text)
                        if "translations" in response_data:
                            # 按ID排序并提取翻译文本
                            translations = sorted(response_data["translations"], key=lambda x: x["id"])
                            translated_segments = [t["text"] for t in translations]
                            logger.debug(f"成功解析JSON响应，获得 {len(translated_segments)} 条翻译")
                        else:
                            logger.warning("响应JSON缺少 'translations' 字段")
                            raise ValueError("Invalid response format: missing 'translations' field")
                    except json.JSONDecodeError as e:
                        # 如果JSON解析失败，回退到原来的分割方法
                        logger.warning(f"JSON解析失败: {str(e)}，使用fallback分割方法")
                        translated_segments = [s.strip() for s in translated_text.split("---")]
                        translated_segments = [s for s in translated_segments if s]  # 移除空段落
                        logger.debug(f"Fallback方法获得 {len(translated_segments)} 条翻译")
                    
                    # 检查段落数量是否匹配
                    if len(translated_segments) != len(texts):
                        logger.warning(f"翻译段落数量不匹配: 期望 {len(texts)}, 实际 {len(translated_segments)}")
                        retry_count += 1
                        if retry_count < max_retries:
                            delay = self._calculate_retry_delay(retry_count)
                            logger.info(f"段落数量不匹配，{delay:.1f}秒后进行第 {retry_count + 1}/{max_retries} 次重试")
                            await asyncio.sleep(delay)
                            continue
                        else:
                            logger.error(f"经过 {max_retries} 次重试后仍无法获得正确数量的段落")
                            raise Exception(f"Failed to get correct number of segments after {max_retries} attempts")
                    
                    # 进行翻译质量检查
                    quality_results = self._check_translation_quality(texts, translated_segments)
                    failed_count = sum(1 for result in quality_results if not result)
                    
                    if failed_count > 0:
                        logger.warning(f"翻译质量检查发现 {failed_count}/{len(texts)} 条翻译质量不佳")
                        
                        # 如果失败比例超过阈值，则重试整个批次
                        if failed_count > len(texts) * TranslationConfig.QUALITY_THRESHOLD:
                            retry_count += 1
                            if retry_count < max_retries:
                                delay = self._calculate_retry_delay(retry_count)
                                logger.info(f"翻译质量不佳，{delay:.1f}秒后进行第 {retry_count + 1}/{max_retries} 次重试")
                                await asyncio.sleep(delay)
                                continue
                            else:
                                logger.warning(f"经过 {max_retries} 次重试后翻译质量仍不理想，返回当前结果")
                        else:
                            logger.info(f"翻译质量可接受（失败率: {failed_count/len(texts)*100:.1f}%），继续处理")
                    else:
                        logger.info(f"翻译质量检查通过，所有 {len(texts)} 条翻译质量良好")
                    
                    return translated_segments
                    
            except Exception as e:
                logger.error(f"批量翻译错误: {str(e)}")
                retry_count += 1
                if retry_count < max_retries:
                    delay = self._calculate_retry_delay(retry_count)
                    logger.info(f"翻译出错，{delay:.1f}秒后进行第 {retry_count + 1}/{max_retries} 次重试")
                    await asyncio.sleep(delay)
                    continue
                else:
                    # 所有重试都失败后，返回原始文本
                    logger.error(f"经过 {max_retries} 次重试后翻译仍然失败，返回原始文本")
                    return texts

    async def translate_batch_subtitles(self, subtitles: List[Dict[str, Any]], 
                                      video_name: str,
                                      output_path: str = None,
                                      original_path: str = None) -> List[Dict[str, Any]]:
        """
        批量翻译字幕
        
        参数:
            subtitles: 字幕列表，每个元素为包含 start, end, text, speaker 的字典
            video_name: 视频文件名（不含扩展名）
            output_path: 输出文件路径，如果为 None 则自动生成
            original_path: 原始字幕文件路径，如果为 None 则自动生成
            
        返回:
            翻译后的字幕列表
        """
        try:
            # 创建临时目录
            temp_dir = os.path.join("temp", video_name)
            os.makedirs(temp_dir, exist_ok=True)
            
            # 计算文件哈希值
            file_hash = get_file_hash(video_name)
            
            # 设置输出路径
            if output_path is None:
                output_path = os.path.join(temp_dir, f"{file_hash}_subtitles_zh.srt")
            if original_path is None:
                original_path = os.path.join(temp_dir, f"{file_hash}_subtitles_en.srt")
            
            translated_subtitles = []
            total = len(subtitles)
            successful_translations = 0
            failed_translations = 0
            
            logger.info(f"开始翻译字幕: 总计 {total} 条，批次大小 {self.batch_size}")
            
            # 创建进度条
            with tqdm(total=total, desc="Translation progress", unit="subtitle") as pbar:
                # 按批次处理字幕
                for i in range(0, total, self.batch_size):
                    batch = subtitles[i:i + self.batch_size]
                    batch_start = i + 1
                    batch_end = min(i + self.batch_size, total)
                    
                    logger.debug(f"处理批次 {batch_start}-{batch_end}")
                    
                    # 检查每个字幕是否包含必要的字段
                    valid_batch = []
                    for sub in batch:
                        if "text" not in sub:
                            logger.warning(f"字幕缺少 text 字段: {sub}")
                            failed_translations += 1
                            continue
                        valid_batch.append(sub)
                    
                    if not valid_batch:
                        logger.warning(f"批次 {batch_start}-{batch_end} 没有有效的字幕，跳过")
                        pbar.update(len(batch))
                        continue
                        
                    batch_texts = [sub["text"] for sub in valid_batch]
                    
                    try:
                        # 批量翻译
                        translated_texts = await self.translate_batch(batch_texts)
                        
                        # 检查翻译质量
                        quality_results = self._check_translation_quality(batch_texts, translated_texts)
                        
                        # 更新字幕
                        for j, (subtitle, translated_text) in enumerate(zip(valid_batch, translated_texts)):
                            translated_subtitle = subtitle.copy()
                            translated_subtitle["text"] = translated_text
                            translated_subtitle["original_text"] = subtitle["text"]
                            
                            # 添加翻译质量标记
                            translated_subtitle["translation_quality"] = "good" if quality_results[j] else "poor"
                            
                            translated_subtitles.append(translated_subtitle)
                            
                            if quality_results[j]:
                                successful_translations += 1
                            else:
                                failed_translations += 1
                                logger.warning(f"第 {len(translated_subtitles)} 条字幕翻译质量不佳")
                            
                            # 更新进度条
                            pbar.update(1)
                        
                        # 添加批次间的短暂延迟，避免API过载
                        if i + self.batch_size < total:
                            await asyncio.sleep(TranslationConfig.BATCH_DELAY)
                        
                    except Exception as e:
                        logger.error(f"批次 {batch_start}-{batch_end} 翻译失败: {str(e)}")
                        
                        # 即使翻译失败，也要保留原文
                        for subtitle in valid_batch:
                            translated_subtitle = subtitle.copy()
                            translated_subtitle["original_text"] = subtitle["text"]
                            translated_subtitle["translation_quality"] = "failed"
                            translated_subtitles.append(translated_subtitle)
                            failed_translations += 1
                            pbar.update(1)
                    
                    # 定期保存进度
                    if len(translated_subtitles) % TranslationConfig.PROGRESS_SAVE_INTERVAL == 0:
                        try:
                            self.save_subtitles(translated_subtitles, output_path, original_path)
                            logger.debug(f"已保存进度: {len(translated_subtitles)}/{total} 条字幕")
                        except Exception as e:
                            logger.warning(f"保存进度失败: {str(e)}")
                    
            # 最后保存一次
            self.save_subtitles(translated_subtitles, output_path, original_path)
            
            # 输出翻译统计
            success_rate = (successful_translations / total * 100) if total > 0 else 0
            logger.info(f"翻译完成统计:")
            logger.info(f"  总字幕数: {total}")
            logger.info(f"  成功翻译: {successful_translations} ({success_rate:.1f}%)")
            logger.info(f"  翻译失败: {failed_translations}")
            logger.info(f"  字幕文件已保存: {output_path}")
            
            # 关闭 session
            await self.close()
            
            return translated_subtitles
            
        except Exception as e:
            logger.error(f"批量翻译字幕失败: {str(e)}")
            # 确保关闭 session
            await self.close()
            raise

    def format_time(self, seconds: float) -> str:
        """
        将秒数格式化为 SRT 时间格式
        
        参数:
            seconds: 秒数
            
        返回:
            格式化的时间字符串 (HH:MM:SS,mmm)
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = seconds % 60
        milliseconds = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{int(seconds):02d},{milliseconds:03d}" 