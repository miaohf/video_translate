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
            # 创建连接器配置，增加连接稳定性
            connector = aiohttp.TCPConnector(
                limit=10,  # 连接池大小
                limit_per_host=5,  # 每个主机的最大连接数
                ttl_dns_cache=300,  # DNS缓存时间
                use_dns_cache=True,
                keepalive_timeout=30,  # 保持连接超时时间
                enable_cleanup_closed=True  # 自动清理关闭的连接
            )
            
            # 设置超时配置
            timeout = aiohttp.ClientTimeout(
                total=TranslationConfig.REQUEST_TIMEOUT,
                connect=30,  # 连接超时
                sock_read=60  # 读取超时
            )
            
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout
            )
        return self._session

    async def close(self):
        """关闭 aiohttp 会话"""
        if self._session and not self._session.closed:
            await self._session.close()
            
    async def test_connection(self) -> bool:
        """测试与Ollama API的连接"""
        try:
            session = await self._get_session()
            test_data = {
                "model": self.model,
                "prompt": "测试连接",
                "stream": False,
                "options": {"temperature": 0.1}
            }
            
            async with session.post(f"{self.api_url}/api/generate", json=test_data) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info("Ollama API连接测试成功")
                    return True
                else:
                    logger.error(f"Ollama API连接测试失败: 状态码 {response.status}")
                    return False
                    
        except Exception as e:
            logger.error(f"Ollama API连接测试异常: {type(e).__name__}: {str(e)}")
            return False

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
            logger.debug(f"质量检查第{i+1}条: 原文='{original}', 译文='{translated}'")
            
            # 检查1: 翻译是否包含中文
            has_chinese = self._is_chinese_text(translated)
            
            # 检查2: 翻译是否与原文相同（说明翻译失败）
            is_different = original.strip() != translated.strip()
            
            # 检查3: 翻译长度是否合理（对于中英翻译，适当放宽限制）
            if len(original) > 0:
                # 计算字符长度比例
                char_ratio = len(translated) / len(original)
                # 计算单词/字符数比例（英文单词vs中文字符）
                original_word_count = len(original.split())
                translated_char_count = len([c for c in translated if '\u4e00' <= c <= '\u9fff'])
                word_char_ratio = translated_char_count / original_word_count if original_word_count > 0 else char_ratio
                
                # 放宽长度检查：要么字符比例合理，要么单词-字符比例合理
                reasonable_length = (
                    TranslationConfig.MIN_LENGTH_RATIO <= char_ratio <= TranslationConfig.MAX_LENGTH_RATIO or
                    0.5 <= word_char_ratio <= 4.0  # 英文单词到中文字符的合理比例
                )
                
                logger.debug(f"长度检查 - 字符比例: {char_ratio:.2f}, 单词-字符比例: {word_char_ratio:.2f}")
            else:
                reasonable_length = True
            
            # 检查4: 翻译是否为空或只包含空白字符
            not_empty = bool(translated.strip())
            
            # 检查5: 检查是否包含明显的错误标识（如"我无法翻译"等）
            error_indicators = ["无法翻译", "不能翻译", "翻译失败", "error", "failed"]
            no_error_indicators = not any(indicator in translated.lower() for indicator in error_indicators)
            
            # 综合评估：所有条件都要满足
            is_good_translation = has_chinese and is_different and reasonable_length and not_empty and no_error_indicators
            quality_results.append(is_good_translation)
            
            # 记录详细的检查结果
            if not is_good_translation:
                logger.warning(f"翻译质量检查失败 (第{i+1}条): "
                             f"包含中文={has_chinese}, "
                             f"与原文不同={is_different}, "
                             f"长度合理={reasonable_length}, "
                             f"非空={not_empty}, "
                             f"无错误标识={no_error_indicators}")
                logger.debug(f"  原文 ({len(original)}字符): {original}")
                logger.debug(f"  译文 ({len(translated)}字符): {translated}")
            else:
                logger.debug(f"翻译质量检查通过 (第{i+1}条)")
        
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
                try:
                    # 使用会话自带的超时配置，不再额外指定timeout参数
                    async with session.post(f"{self.api_url}/api/generate", json=data) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            logger.error(f"API请求失败: 状态码 {response.status}, 错误: {error_text}")
                            logger.error(f"请求URL: {self.api_url}/api/generate")
                            logger.error(f"请求头: {dict(response.headers)}")
                            raise Exception(f"API request failed with status {response.status}: {error_text}")
                        
                        # 读取响应内容
                        result = await response.json()
                        
                except asyncio.TimeoutError:
                    logger.error(f"API请求超时: 超过 {TranslationConfig.REQUEST_TIMEOUT} 秒")
                    logger.error(f"请求URL: {self.api_url}/api/generate")
                    raise Exception(f"API request timeout after {TranslationConfig.REQUEST_TIMEOUT} seconds")
                except aiohttp.ClientError as client_error:
                    error_type = type(client_error).__name__
                    logger.error(f"客户端连接错误 [{error_type}]: {str(client_error)}")
                    logger.error(f"请求URL: {self.api_url}/api/generate")
                    # 如果是连接错误，可能需要重新创建会话
                    if self._session and not self._session.closed:
                        await self._session.close()
                        self._session = None
                    raise
                except Exception as network_error:
                    error_type = type(network_error).__name__
                    logger.error(f"网络请求异常 [{error_type}]: {str(network_error)}")
                    logger.error(f"请求URL: {self.api_url}/api/generate")
                    raise
                
                if "error" in result:
                    logger.error(f"API返回错误: {result['error']}")
                    raise Exception(f"API error: {result['error']}")
                    
                translated_text = result.get("response", "").strip()
                if not translated_text:
                    logger.error("API返回空响应")
                    raise Exception("Empty response from API")
                
                # 清理翻译结果中的思考过程
                translated_text = self._clean_translation(translated_text)
                logger.debug(f"清理后的翻译文本: {translated_text}")
                
                # 根据批次大小决定解析方式
                if len(texts) == 1:
                    # 单条翻译，直接使用清理后的文本
                    translated_segments = [translated_text]
                    logger.debug(f"单条翻译模式，结果: {translated_text}")
                else:
                    # 多条翻译，尝试解析JSON或使用分割方法
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
                        # 如果JSON解析失败，尝试多种分割方法
                        logger.debug(f"JSON解析失败: {str(e)}，尝试文本分割方法")
                        
                        # 方法1: 尝试用 "---" 分割
                        if "---" in translated_text:
                            translated_segments = [s.strip() for s in translated_text.split("---")]
                            translated_segments = [s for s in translated_segments if s]
                            logger.debug(f"使用 '---' 分割获得 {len(translated_segments)} 条翻译")
                        # 方法2: 尝试用换行符分割
                        elif "\n" in translated_text:
                            translated_segments = [s.strip() for s in translated_text.split("\n")]
                            translated_segments = [s for s in translated_segments if s and not s.isdigit()]
                            logger.debug(f"使用换行分割获得 {len(translated_segments)} 条翻译")
                        # 方法3: 如果没有合适的分割符，且文本看起来是合并的翻译
                        else:
                            # 对于无法分割的情况，尝试按照原文数量均分（不太准确，但作为最后手段）
                            logger.warning("无法找到合适的分割方法，将整个文本作为单条翻译")
                            translated_segments = [translated_text]
                
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
                # 详细的错误信息记录
                error_type = type(e).__name__
                error_message = str(e) if str(e) else "未知错误（无错误消息）"
                
                # 记录完整的错误信息
                logger.error(f"批量翻译错误 [{error_type}]: {error_message}")
                
                # 如果是网络相关错误，记录更多信息
                if hasattr(e, 'status'):
                    logger.error(f"HTTP状态码: {e.status}")
                if hasattr(e, 'message'):
                    logger.error(f"HTTP错误消息: {e.message}")
                if hasattr(e, 'headers'):
                    logger.error(f"响应头: {e.headers}")
                
                # 记录异常的堆栈跟踪（用于调试）
                import traceback
                logger.debug(f"异常堆栈跟踪:\n{traceback.format_exc()}")
                
                retry_count += 1
                if retry_count < max_retries:
                    delay = self._calculate_retry_delay(retry_count)
                    logger.info(f"翻译出错，{delay:.1f}秒后进行第 {retry_count + 1}/{max_retries} 次重试")
                    await asyncio.sleep(delay)
                    continue
                else:
                    # 所有重试都失败后，返回原始文本
                    logger.error(f"经过 {max_retries} 次重试后翻译仍然失败，最后错误: [{error_type}] {error_message}")
                    return texts

    async def translate_subtitles(self, subtitles: List[Dict[str, Any]], 
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
        # 首先测试连接
        logger.info("测试Ollama API连接...")
        if not await self.test_connection():
            logger.error("无法连接到Ollama API，请检查服务是否运行")
            raise Exception("无法连接到Ollama API")
            
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