import asyncio
import json
import os
from typing import List, Dict, Any, Optional, Callable
import logging
import time
from tqdm import tqdm
from services.translation_config import TranslationConfig

logger = logging.getLogger(__name__)


class AsyncPipelineProcessor:
    """异步流水线处理器 - 流水线+异步处理方案"""
    
    def __init__(self, translation_service, max_queue_size: int = 200):
        self.translation_service = translation_service
        self.max_queue_size = max_queue_size
        
        # 异步队列
        self.translation_queue = asyncio.Queue(maxsize=max_queue_size)
        self.deduplication_queue = asyncio.Queue(maxsize=max_queue_size)
        self.save_queue = asyncio.Queue(maxsize=max_queue_size)
        
        # 异步信号量控制并发
        self.translation_semaphore = asyncio.Semaphore(
            TranslationConfig.ASYNC_PIPELINE_TRANSLATION_SEMAPHORE
        )
        self.deduplication_semaphore = asyncio.Semaphore(
            TranslationConfig.ASYNC_PIPELINE_DEDUP_SEMAPHORE
        )
        self.save_semaphore = asyncio.Semaphore(
            TranslationConfig.ASYNC_PIPELINE_SAVE_SEMAPHORE
        )
        
        # 性能统计
        self.stats = {
            "total_subtitles": 0,
            "translated_count": 0,
            "deduplicated_count": 0,
            "saved_count": 0,
            "start_time": None,
            "end_time": None
        }
        
    async def process_subtitles_async_pipeline(self, 
                                             subtitles: List[Dict], 
                                             output_path: str,
                                             progress_callback: Optional[Callable] = None) -> List[Dict]:
        """异步流水线处理字幕"""
        
        self.stats["start_time"] = time.time()
        self.stats["total_subtitles"] = len(subtitles)
        
        logger.info(f"🏭 开始异步流水线处理: {len(subtitles)} 条字幕")
        
        # 启动异步工作协程
        translation_workers = TranslationConfig.ASYNC_PIPELINE_TRANSLATION_WORKERS
        dedup_workers = TranslationConfig.ASYNC_PIPELINE_DEDUP_WORKERS
        save_workers = TranslationConfig.ASYNC_PIPELINE_SAVE_WORKERS
        
        translation_tasks = [
            asyncio.create_task(self._async_translation_worker(i))
            for i in range(translation_workers)
        ]
        
        deduplication_tasks = [
            asyncio.create_task(self._async_deduplication_worker(i))
            for i in range(dedup_workers)
        ]
        
        save_tasks = [
            asyncio.create_task(self._async_save_worker(i, output_path))
            for i in range(save_workers)
        ]
        
        # 创建进度监控任务
        progress_task = asyncio.create_task(self._progress_monitor(progress_callback))
        
        # 将字幕放入翻译队列
        for subtitle in subtitles:
            await self.translation_queue.put(subtitle)
        
        # 标记翻译结束
        for _ in range(translation_workers):
            await self.translation_queue.put(None)
        
        # 等待翻译完成后再标记去重结束
        await asyncio.gather(*translation_tasks)
        
        # 标记去重结束
        for _ in range(dedup_workers):
            await self.deduplication_queue.put(None)
        
        # 等待去重和保存工作完成
        await asyncio.gather(*deduplication_tasks, *save_tasks, progress_task)
        
        # 从保存的文件中读取最终结果
        try:
            if os.path.exists(output_path):
                with open(output_path, 'r', encoding='utf-8') as f:
                    final_results = json.load(f)
                logger.info(f"✅ 异步流水线处理完成: {len(final_results)} 条字幕")
                return final_results
            else:
                logger.warning("⚠️ 输出文件不存在，返回原始字幕")
                return subtitles
        except Exception as e:
            logger.error(f"❌ 读取结果失败: {str(e)}")
            return subtitles
    
    async def _async_translation_worker(self, worker_id: int):
        """异步翻译工作器"""
        logger.info(f"🔧 异步翻译工作器 {worker_id} 启动")
        
        while True:
            async with self.translation_semaphore:
                subtitle = await self.translation_queue.get()
                if subtitle is None:
                    logger.info(f"🔧 异步翻译工作器 {worker_id} 完成")
                    break
                
                try:
                    # 提取字幕文本
                    text = subtitle.get("text", "")
                    if not text:
                        logger.warning(f"⚠️ 字幕文本为空，工作器 {worker_id}")
                        await self.deduplication_queue.put(subtitle)
                        continue
                    
                    # 选择翻译方法
                    if TranslationConfig.TRANSLATION_MODE == "contextual_three_step":
                        translated_texts = await self.translation_service.translate_with_context_three_step([text])
                    else:
                        translated_texts = await self.translation_service.translate_batch_with_context([text])
                    
                    # 构建翻译结果
                    if translated_texts and len(translated_texts) == 1:
                        translated_subtitle = subtitle.copy()
                        translated_subtitle["text"] = translated_texts[0]
                        translated_subtitle["original_text"] = text
                        translated_subtitle["translation_quality"] = "good"
                        translated_subtitle["worker_id"] = worker_id
                        translated_subtitle["translation_method"] = "async_pipeline"
                        
                        await self.deduplication_queue.put(translated_subtitle)
                        self.stats["translated_count"] += 1
                        logger.debug(f"✅ 翻译完成: 工作器 {worker_id}, 字幕 {subtitle.get('index', 'unknown')}")
                    else:
                        raise Exception("翻译结果为空或数量不匹配")
                    
                except Exception as e:
                    logger.error(f"❌ 翻译失败: 工作器 {worker_id}, 错误: {str(e)}")
                    subtitle["translation_error"] = str(e)
                    subtitle["worker_id"] = worker_id
                    await self.deduplication_queue.put(subtitle)
    
    async def _async_deduplication_worker(self, worker_id: int):
        """异步去重工作器"""
        logger.info(f"🔍 异步去重工作器 {worker_id} 启动")
        
        # 使用类级别的共享列表
        if not hasattr(self, '_all_subtitles'):
            self._all_subtitles = []
        
        while True:
            async with self.deduplication_semaphore:
                subtitle = await self.deduplication_queue.get()
                if subtitle is None:
                    logger.info(f"🔍 异步去重工作器 {worker_id} 完成，开始去重处理")
                    
                    # 只有第一个工作器执行去重
                    if worker_id == 0:
                        # 执行去重
                        if hasattr(self.translation_service, '_remove_duplicate_subtitles'):
                            deduplicated_subtitles = self.translation_service._remove_duplicate_subtitles(self._all_subtitles)
                        else:
                            deduplicated_subtitles = self._all_subtitles
                        
                        self.stats["deduplicated_count"] = len(deduplicated_subtitles)
                        logger.info(f"🔍 去重完成: {len(self._all_subtitles)} → {len(deduplicated_subtitles)} 条字幕")
                        
                        # 发送去重结果到保存队列
                        await self.save_queue.put(deduplicated_subtitles)
                        await self.save_queue.put(None)
                    break
                
                self._all_subtitles.append(subtitle)
    
    async def _async_save_worker(self, worker_id: int, output_path: str):
        """异步保存工作器"""
        logger.info(f"💾 异步保存工作器 {worker_id} 启动")
        
        while True:
            async with self.save_semaphore:
                subtitles = await self.save_queue.get()
                if subtitles is None:
                    logger.info(f"💾 异步保存工作器 {worker_id} 完成")
                    break
                
                try:
                    # 只有第一个工作器执行保存
                    if worker_id == 0:
                        # 确保输出目录存在
                        output_dir = os.path.dirname(output_path)
                        if output_dir:
                            os.makedirs(output_dir, exist_ok=True)
                        
                        # 保存JSON文件
                        with open(output_path, 'w', encoding='utf-8') as f:
                            json.dump(subtitles, f, ensure_ascii=False, indent=2)
                        
                        # 保存SRT文件
                        srt_path = output_path.replace("_subtitles_zh.json", "_subtitles_zh.srt")
                        with open(srt_path, 'w', encoding='utf-8') as f:
                            for i, subtitle in enumerate(subtitles, 1):
                                start_time = self._format_time(subtitle.get("start", 0))
                                end_time = self._format_time(subtitle.get("end", 0))
                                f.write(f"{i}\n{start_time} --> {end_time}\n{subtitle.get('text', '')}\n\n")
                        
                        self.stats["saved_count"] = len(subtitles)
                        logger.info(f"💾 保存完成: {len(subtitles)} 条字幕")
                        logger.info(f"  📄 JSON: {output_path}")
                        logger.info(f"  📄 SRT: {srt_path}")
                    
                except Exception as e:
                    logger.error(f"❌ 保存失败: {str(e)}")
    
    async def _progress_monitor(self, progress_callback: Optional[Callable] = None):
        """进度监控协程"""
        last_translated = 0
        last_deduplicated = 0
        last_saved = 0
        
        while True:
            current_translated = self.stats["translated_count"]
            current_deduplicated = self.stats["deduplicated_count"]
            current_saved = self.stats["saved_count"]
            
            # 检查是否有进度更新
            if (current_translated != last_translated or 
                current_deduplicated != last_deduplicated or 
                current_saved != last_saved):
                
                progress_info = {
                    "translated": current_translated,
                    "deduplicated": current_deduplicated,
                    "saved": current_saved,
                    "total": self.stats["total_subtitles"],
                    "translation_progress": current_translated / self.stats["total_subtitles"] if self.stats["total_subtitles"] > 0 else 0
                }
                
                if progress_callback:
                    progress_callback(progress_info)
                
                logger.debug(f"📊 进度: 翻译 {current_translated}/{self.stats['total_subtitles']}, "
                           f"去重 {current_deduplicated}, 保存 {current_saved}")
                
                last_translated = current_translated
                last_deduplicated = current_deduplicated
                last_saved = current_saved
            
            # 检查是否完成
            if current_saved > 0:
                break
            
            await asyncio.sleep(0.5)
    
    def get_performance_stats(self) -> Dict:
        """获取性能统计"""
        stats = self.stats.copy()
        if stats["start_time"] and stats["end_time"]:
            stats["duration"] = stats["end_time"] - stats["start_time"]
            stats["throughput"] = stats["translated_count"] / stats["duration"] if stats["duration"] > 0 else 0
        return stats
    
    def _format_time(self, seconds: float) -> str:
        """格式化时间为SRT格式"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = seconds % 60
        milliseconds = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{int(seconds):02d},{milliseconds:03d}" 