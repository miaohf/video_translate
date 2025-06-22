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
from services.translation_templates import TRANSLATION_TEMPLATE, WHOLE_TRANSLATION_TEMPLATE
from services.translation_config import TranslationConfig
from utils.vtt_parser import VTTParser

logger = logging.getLogger(__name__)

class TranslationService:
    def __init__(self, batch_size: int = None, translation_mode: str = None):
        """
        初始化翻译服务
        
        参数:
            batch_size: 批处理大小，如果为None则使用默认值
            translation_mode: 翻译模式，如果为None则从配置文件读取
        """
        self.api_url = settings.OLLAMA_API_URL
        self.model = settings.OLLAMA_MODEL
        self.llm = OllamaLLM(model=self.model)
        self._session = None
        
        # 设置翻译模式：优先使用传入参数，否则从配置读取
        if translation_mode is None:
            translation_mode = settings.TRANSLATION_MODE
        self.translation_mode = translation_mode if translation_mode in ["batch", "whole"] else "batch"
        
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
        
        logger.info(f"翻译服务已初始化，模式: {self.translation_mode}，批处理大小: {self.batch_size}")

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
            
            # 检查3: 翻译是否为空或只包含空白字符
            not_empty = bool(translated.strip())
            
            # 移除长度检查，因为中英文长度差异较大，过于严苛
            is_good_translation = has_chinese and is_different and not_empty
            quality_results.append(is_good_translation)
            
            if not is_good_translation:
                logger.warning(f"翻译质量检查失败 (第{i+1}条): "
                             f"包含中文={has_chinese}, "
                             f"与原文不同={is_different}, "
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
        保存字幕到文件（VTT格式）
        
        参数:
            subtitles: 字幕列表
            output_path: 输出文件路径（中文VTT）
            original_path: 原始字幕文件路径（英文VTT）
        """
        try:
            # 确保输出目录存在
            output_dir = os.path.dirname(output_path)
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
                logger.info(f"Creating output directory: {output_dir}")
            
            # 保存翻译后的字幕（中文VTT）
            VTTParser.save_vtt_file(subtitles, output_path, 'zh')
            logger.info(f"翻译字幕已保存为VTT格式: {output_path}")
            
            # 保存 JSON 格式的字幕数据（兼容性）
            json_path = output_path.replace("_subtitles_zh.vtt", "_subtitles_zh.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(subtitles, f, ensure_ascii=False, indent=2)
            logger.info(f"翻译字幕已保存为JSON格式: {json_path}")
            
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
                output_path = os.path.join(temp_dir, f"{file_hash}_subtitles_zh.vtt")
            if original_path is None:
                original_path = os.path.join(temp_dir, f"{file_hash}_subtitles_en.vtt")
            
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

    async def translate_whole_subtitles(self, subtitles: List[Dict[str, Any]], 
                                      video_name: str,
                                      output_path: str = None,
                                      original_path: str = None) -> List[Dict[str, Any]]:
        """
        整体翻译字幕文件 - 一次性翻译所有字幕以保持上下文一致性
        
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
                output_path = os.path.join(temp_dir, f"{file_hash}_subtitles_zh_whole.vtt")
            if original_path is None:
                original_path = os.path.join(temp_dir, f"{file_hash}_subtitles_en.vtt")
            
            # 检查是否包含有效的字幕
            valid_subtitles = [sub for sub in subtitles if "text" in sub and sub["text"].strip()]
            if not valid_subtitles:
                logger.warning("没有有效的字幕内容需要翻译")
                return subtitles
            
            total = len(valid_subtitles)
            logger.info(f"开始整体翻译字幕: 总计 {total} 条")
            
            # 检查字幕总长度，如果太长则分成大批次
            total_text_length = sum(len(sub["text"]) for sub in valid_subtitles)
            max_context_length = TranslationConfig.MAX_WHOLE_CONTENT_LENGTH
            
            if total_text_length > max_context_length:
                logger.info(f"字幕总长度 {total_text_length} 超过整体翻译限制 {max_context_length}，将使用大批次翻译")
                return await self._translate_large_batches_whole(valid_subtitles, video_name, output_path, original_path)
            
            # 准备整体翻译
            segments = [{"id": i+1, "text": sub["text"], "speaker": sub.get("speaker", "Unknown")} 
                       for i, sub in enumerate(valid_subtitles)]
            
            # 使用整体翻译模板
            whole_translation_prompt = PromptTemplate(
                input_variables=["segments", "segment_count"],
                template=WHOLE_TRANSLATION_TEMPLATE
            )
            
            prompt = whole_translation_prompt.format(
                segments=json.dumps(segments, ensure_ascii=False, indent=2),
                segment_count=len(segments)
            )
            
            max_retries = TranslationConfig.MAX_RETRIES
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    session = await self._get_session()
                    
                    # 构建请求数据
                    data = {
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": TranslationConfig.get_model_options()
                    }
                    
                    logger.info("开始整体翻译请求...")
                    
                    # 发送请求
                    async with session.post(
                        f"{self.api_url}/api/generate",
                        json=data,
                        timeout=aiohttp.ClientTimeout(total=TranslationConfig.REQUEST_TIMEOUT * 2)  # 整体翻译需要更长时间
                    ) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            raise Exception(f"API请求失败: {response.status} - {error_text}")
                        
                        result = await response.json()
                        raw_response = result.get("response", "").strip()
                        
                        # 清理响应
                        cleaned_response = self._clean_translation(raw_response)
                        
                        # 解析JSON响应
                        try:
                            if cleaned_response.startswith('```json'):
                                cleaned_response = cleaned_response[7:]
                            if cleaned_response.endswith('```'):
                                cleaned_response = cleaned_response[:-3]
                            
                            response_data = json.loads(cleaned_response.strip())
                            translations = response_data.get("translations", [])
                            
                            if len(translations) != total:
                                logger.warning(f"整体翻译段落数量不匹配: 期望 {total}, 实际 {len(translations)}")
                                raise Exception(f"段落数量不匹配: 期望 {total}, 实际 {len(translations)}")
                            
                            # 提取翻译文本
                            translated_texts = [t.get("text", "") for t in translations]
                            
                            # 检查翻译质量
                            original_texts = [sub["text"] for sub in valid_subtitles]
                            quality_results = self._check_translation_quality(original_texts, translated_texts)
                            successful_translations = sum(quality_results)
                            failed_translations = len(quality_results) - successful_translations
                            
                            # 更新字幕
                            translated_subtitles = []
                            for i, (subtitle, translated_text) in enumerate(zip(valid_subtitles, translated_texts)):
                                translated_subtitle = subtitle.copy()
                                translated_subtitle["text"] = translated_text
                                translated_subtitle["original_text"] = subtitle["text"]
                                translated_subtitle["translation_quality"] = "good" if quality_results[i] else "poor"
                                translated_subtitle["translation_mode"] = "whole"
                                translated_subtitles.append(translated_subtitle)
                            
                            # 保存翻译结果
                            self.save_subtitles(translated_subtitles, output_path, original_path)
                            
                            # 输出翻译统计
                            success_rate = (successful_translations / total * 100) if total > 0 else 0
                            logger.info(f"整体翻译完成统计:")
                            logger.info(f"  总字幕数: {total}")
                            logger.info(f"  成功翻译: {successful_translations} ({success_rate:.1f}%)")
                            logger.info(f"  翻译失败: {failed_translations}")
                            logger.info(f"  字幕文件已保存: {output_path}")
                            
                            # 保存翻译笔记（如果有）
                            if "translation_notes" in response_data:
                                notes_path = output_path.replace(".vtt", "_notes.json")
                                with open(notes_path, 'w', encoding='utf-8') as f:
                                    json.dump(response_data["translation_notes"], f, ensure_ascii=False, indent=2)
                                logger.info(f"翻译笔记已保存: {notes_path}")
                            
                            await self.close()
                            return translated_subtitles
                            
                        except json.JSONDecodeError as e:
                            logger.error(f"JSON解析失败: {str(e)}")
                            logger.debug(f"原始响应: {cleaned_response[:500]}...")
                            raise Exception(f"JSON解析失败: {str(e)}")
                    
                except Exception as e:
                    logger.error(f"整体翻译错误: {str(e)}")
                    retry_count += 1
                    if retry_count < max_retries:
                        delay = self._calculate_retry_delay(retry_count)
                        logger.info(f"整体翻译出错，{delay:.1f}秒后进行第 {retry_count + 1}/{max_retries} 次重试")
                        await asyncio.sleep(delay)
                        continue
                    else:
                        logger.error(f"整体翻译经过 {max_retries} 次重试后仍然失败，回退到批次翻译")
                        await self.close()
                        return await self.translate_batch_subtitles(subtitles, video_name)
            
        except Exception as e:
            logger.error(f"整体翻译字幕失败: {str(e)}")
            await self.close()
            raise

    async def _translate_large_batches_whole(self, subtitles: List[Dict[str, Any]], 
                                           video_name: str,
                                           output_path: str,
                                           original_path: str) -> List[Dict[str, Any]]:
        """
        使用整体翻译方式处理大批次字幕
        
        参数:
            subtitles: 字幕列表
            video_name: 视频文件名
            output_path: 输出文件路径
            original_path: 原始字幕文件路径
            
        返回:
            翻译后的字幕列表
        """
        large_batch_size = TranslationConfig.LARGE_BATCH_SIZE
        max_context_per_batch = TranslationConfig.MAX_WHOLE_CONTENT_LENGTH
        
        translated_subtitles = []
        total = len(subtitles)
        successful_translations = 0
        failed_translations = 0
        
        logger.info(f"使用整体翻译大批次模式: 总计 {total} 条，目标批次大小 {large_batch_size}")
        
        # 创建进度条
        with tqdm(total=total, desc="Whole translation (large batches)", unit="subtitle") as pbar:
            i = 0
            while i < total:
                # 动态计算当前批次大小
                current_batch = []
                current_text_length = 0
                
                while (i < total and 
                       len(current_batch) < large_batch_size and 
                       current_text_length < max_context_per_batch):
                    
                    subtitle_text_length = len(subtitles[i]["text"])
                    if current_text_length + subtitle_text_length <= max_context_per_batch:
                        current_batch.append(subtitles[i])
                        current_text_length += subtitle_text_length
                        i += 1
                    else:
                        break
                
                if not current_batch:
                    # 如果单条字幕就超过限制，强制处理
                    current_batch = [subtitles[i]]
                    i += 1
                
                batch_start = i - len(current_batch) + 1
                batch_end = i
                
                logger.debug(f"处理整体翻译大批次 {batch_start}-{batch_end} ({len(current_batch)} 条字幕)")
                
                try:
                    # 使用整体翻译方法处理当前批次
                    batch_translated = await self._translate_batch_whole(current_batch)
                    
                    # 更新统计
                    for sub in batch_translated:
                        if sub.get("translation_quality") == "good":
                            successful_translations += 1
                        else:
                            failed_translations += 1
                        pbar.update(1)
                    
                    translated_subtitles.extend(batch_translated)
                    
                    # 添加批次间延迟
                    if i < total:
                        await asyncio.sleep(TranslationConfig.BATCH_DELAY)
                    
                except Exception as e:
                    logger.error(f"整体翻译大批次 {batch_start}-{batch_end} 失败: {str(e)}")
                    
                    # 失败时保留原文
                    for subtitle in current_batch:
                        translated_subtitle = subtitle.copy()
                        translated_subtitle["original_text"] = subtitle["text"]
                        translated_subtitle["translation_quality"] = "failed"
                        translated_subtitle["translation_mode"] = "whole_failed"
                        translated_subtitles.append(translated_subtitle)
                        failed_translations += 1
                        pbar.update(1)
        
        # 保存翻译结果
        self.save_subtitles(translated_subtitles, output_path, original_path)
        
        # 输出统计
        success_rate = (successful_translations / total * 100) if total > 0 else 0
        logger.info(f"整体翻译大批次完成统计:")
        logger.info(f"  总字幕数: {total}")
        logger.info(f"  成功翻译: {successful_translations} ({success_rate:.1f}%)")
        logger.info(f"  翻译失败: {failed_translations}")
        logger.info(f"  字幕文件已保存: {output_path}")
        
        return translated_subtitles

    async def _translate_batch_whole(self, batch_subtitles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        使用整体翻译方式处理单个批次
        
        参数:
            batch_subtitles: 批次字幕列表
            
        返回:
            翻译后的批次字幕列表
        """
        segments = [{"id": i+1, "text": sub["text"], "speaker": sub.get("speaker", "Unknown")} 
                   for i, sub in enumerate(batch_subtitles)]
        
        # 使用整体翻译模板
        whole_translation_prompt = PromptTemplate(
            input_variables=["segments", "segment_count"],
            template=WHOLE_TRANSLATION_TEMPLATE
        )
        
        prompt = whole_translation_prompt.format(
            segments=json.dumps(segments, ensure_ascii=False, indent=2),
            segment_count=len(segments)
        )
        
        max_retries = 3  # 批次级别的重试次数较少
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                session = await self._get_session()
                
                data = {
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": TranslationConfig.get_model_options()
                }
                
                async with session.post(
                    f"{self.api_url}/api/generate",
                    json=data,
                    timeout=aiohttp.ClientTimeout(total=TranslationConfig.REQUEST_TIMEOUT)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise Exception(f"API请求失败: {response.status} - {error_text}")
                    
                    result = await response.json()
                    raw_response = result.get("response", "").strip()
                    cleaned_response = self._clean_translation(raw_response)
                    
                    # 解析JSON响应
                    try:
                        if cleaned_response.startswith('```json'):
                            cleaned_response = cleaned_response[7:]
                        if cleaned_response.endswith('```'):
                            cleaned_response = cleaned_response[:-3]
                        
                        response_data = json.loads(cleaned_response.strip())
                        translations = response_data.get("translations", [])
                        
                        if len(translations) != len(batch_subtitles):
                            raise Exception(f"批次翻译段落数量不匹配: 期望 {len(batch_subtitles)}, 实际 {len(translations)}")
                        
                        # 提取翻译文本并检查质量
                        translated_texts = [t.get("text", "") for t in translations]
                        original_texts = [sub["text"] for sub in batch_subtitles]
                        quality_results = self._check_translation_quality(original_texts, translated_texts)
                        
                        # 更新字幕
                        translated_batch = []
                        for i, (subtitle, translated_text) in enumerate(zip(batch_subtitles, translated_texts)):
                            translated_subtitle = subtitle.copy()
                            translated_subtitle["text"] = translated_text
                            translated_subtitle["original_text"] = subtitle["text"]
                            translated_subtitle["translation_quality"] = "good" if quality_results[i] else "poor"
                            translated_subtitle["translation_mode"] = "whole_batch"
                            translated_batch.append(translated_subtitle)
                        
                        return translated_batch
                        
                    except json.JSONDecodeError as e:
                        logger.error(f"批次JSON解析失败: {str(e)}")
                        raise Exception(f"JSON解析失败: {str(e)}")
                
            except Exception as e:
                logger.error(f"批次整体翻译错误: {str(e)}")
                retry_count += 1
                if retry_count < max_retries:
                    delay = self._calculate_retry_delay(retry_count)
                    await asyncio.sleep(delay)
                    continue
                else:
                    # 最后的回退：返回原文
                    logger.error(f"批次整体翻译失败，返回原文")
                    failed_batch = []
                    for subtitle in batch_subtitles:
                        failed_subtitle = subtitle.copy()
                        failed_subtitle["original_text"] = subtitle["text"]
                        failed_subtitle["translation_quality"] = "failed"
                        failed_subtitle["translation_mode"] = "whole_failed"
                        failed_batch.append(failed_subtitle)
                    return failed_batch

    async def translate_subtitles_auto(self, subtitles: List[Dict[str, Any]], 
                                     video_name: str,
                                     translation_mode: str = None,
                                     output_path: str = None,
                                     original_path: str = None) -> List[Dict[str, Any]]:
        """
        自动选择翻译模式的统一接口
        
        参数:
            subtitles: 字幕列表
            video_name: 视频文件名
            translation_mode: 翻译模式 ("batch" 或 "whole")，如果为None则使用默认配置
            output_path: 输出文件路径
            original_path: 原始字幕文件路径
            
        返回:
            翻译后的字幕列表
        """
        # 验证翻译模式
        if translation_mode is None:
            translation_mode = "batch"  # 默认使用批量翻译
        else:
            translation_mode = translation_mode if translation_mode in ["batch", "whole"] else "batch"
        
        logger.info(f"使用翻译模式: {translation_mode}")
        
        if translation_mode == "whole":
            return await self.translate_whole_subtitles(subtitles, video_name, output_path, original_path)
        else:
            return await self.translate_batch_subtitles(subtitles, video_name, output_path, original_path) 