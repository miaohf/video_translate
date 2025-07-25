import time
import asyncio
from typing import Dict, List, Optional
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self, enable_monitoring: bool = True):
        self.enable_monitoring = enable_monitoring
        self.start_time = None
        self.end_time = None
        
        # 性能数据
        self.batch_times = []
        self.translation_times = []
        self.deduplication_times = []
        self.save_times = []
        self.error_counts = defaultdict(int)
        
        # 实时统计
        self.current_stats = {
            "total_subtitles": 0,
            "processed_subtitles": 0,
            "successful_translations": 0,
            "failed_translations": 0,
            "current_throughput": 0.0,
            "avg_response_time": 0.0
        }
        
        # 监控任务
        self.monitor_task = None
        
    def start_monitoring(self, total_subtitles: int = 0):
        """开始监控"""
        if not self.enable_monitoring:
            return
            
        self.start_time = time.time()
        self.current_stats["total_subtitles"] = total_subtitles
        self.current_stats["processed_subtitles"] = 0
        
        logger.info(f"📊 开始性能监控: 总计 {total_subtitles} 条字幕")
        
        # 启动定期监控任务
        self.monitor_task = asyncio.create_task(self._periodic_monitoring())
    
    def stop_monitoring(self):
        """停止监控"""
        if not self.enable_monitoring:
            return
            
        self.end_time = time.time()
        
        if self.monitor_task:
            self.monitor_task.cancel()
        
        logger.info("📊 性能监控停止")
    
    def record_batch_time(self, batch_index: int, duration: float):
        """记录批次处理时间"""
        if not self.enable_monitoring:
            return
            
        self.batch_times.append((batch_index, duration))
        self.current_stats["avg_response_time"] = sum(t[1] for t in self.batch_times) / len(self.batch_times)
    
    def record_translation_time(self, duration: float):
        """记录翻译时间"""
        if not self.enable_monitoring:
            return
            
        self.translation_times.append(duration)
    
    def record_deduplication_time(self, duration: float):
        """记录去重时间"""
        if not self.enable_monitoring:
            return
            
        self.deduplication_times.append(duration)
    
    def record_save_time(self, duration: float):
        """记录保存时间"""
        if not self.enable_monitoring:
            return
            
        self.save_times.append(duration)
    
    def record_success(self, subtitle_index: int = None):
        """记录成功翻译"""
        if not self.enable_monitoring:
            return
            
        self.current_stats["successful_translations"] += 1
        self.current_stats["processed_subtitles"] += 1
        self._update_throughput()
    
    def record_failure(self, subtitle_index: int = None, error_type: str = "unknown"):
        """记录翻译失败"""
        if not self.enable_monitoring:
            return
            
        self.current_stats["failed_translations"] += 1
        self.current_stats["processed_subtitles"] += 1
        self.error_counts[error_type] += 1
        self._update_throughput()
    
    def _update_throughput(self):
        """更新吞吐量"""
        if self.start_time:
            elapsed_time = time.time() - self.start_time
            if elapsed_time > 0:
                self.current_stats["current_throughput"] = (
                    self.current_stats["processed_subtitles"] / elapsed_time
                )
    
    async def _periodic_monitoring(self):
        """定期监控任务"""
        while True:
            try:
                await asyncio.sleep(10)  # 每10秒输出一次统计
                self._log_performance_stats()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ 性能监控任务错误: {str(e)}")
    
    def _log_performance_stats(self):
        """输出性能统计"""
        if not self.enable_monitoring:
            return
            
        stats = self.get_current_stats()
        
        logger.info(f"📊 性能统计: "
                   f"进度 {stats['processed_subtitles']}/{stats['total_subtitles']} "
                   f"({stats['progress_percentage']:.1f}%), "
                   f"成功率 {stats['success_rate']:.1f}%, "
                   f"吞吐量 {stats['current_throughput']:.2f} 字幕/秒, "
                   f"平均响应时间 {stats['avg_response_time']:.2f}s")
    
    def get_current_stats(self) -> Dict:
        """获取当前统计"""
        if not self.enable_monitoring:
            return {}
        
        total_processed = self.current_stats["processed_subtitles"]
        total_subtitles = self.current_stats["total_subtitles"]
        
        stats = self.current_stats.copy()
        stats["progress_percentage"] = (
            (total_processed / total_subtitles * 100) if total_subtitles > 0 else 0
        )
        stats["success_rate"] = (
            (self.current_stats["successful_translations"] / total_processed * 100) 
            if total_processed > 0 else 0
        )
        
        return stats
    
    def get_performance_report(self) -> Dict:
        """获取完整性能报告"""
        if not self.enable_monitoring or not self.start_time:
            return {}
        
        total_time = (self.end_time or time.time()) - self.start_time
        
        report = {
            "total_time": total_time,
            "total_subtitles": self.current_stats["total_subtitles"],
            "processed_subtitles": self.current_stats["processed_subtitles"],
            "successful_translations": self.current_stats["successful_translations"],
            "failed_translations": self.current_stats["failed_translations"],
            "success_rate": self.current_stats["successful_translations"] / max(self.current_stats["processed_subtitles"], 1) * 100,
            "avg_batch_time": sum(t[1] for t in self.batch_times) / len(self.batch_times) if self.batch_times else 0,
            "avg_translation_time": sum(self.translation_times) / len(self.translation_times) if self.translation_times else 0,
            "avg_deduplication_time": sum(self.deduplication_times) / len(self.deduplication_times) if self.deduplication_times else 0,
            "avg_save_time": sum(self.save_times) / len(self.save_times) if self.save_times else 0,
            "throughput": self.current_stats["processed_subtitles"] / total_time if total_time > 0 else 0,
            "error_distribution": dict(self.error_counts)
        }
        
        logger.info(f"📊 最终性能报告: "
                   f"总时间 {total_time:.2f}s, "
                   f"成功率 {report['success_rate']:.1f}%, "
                   f"吞吐量 {report['throughput']:.2f} 字幕/秒")
        
        return report


class PipelinePerformanceMonitor(PerformanceMonitor):
    """流水线性能监控器"""
    
    def __init__(self, enable_monitoring: bool = True):
        super().__init__(enable_monitoring)
        self.pipeline_stats = {
            "translation_queue_size": 0,
            "deduplication_queue_size": 0,
            "save_queue_size": 0,
            "translation_worker_active": False,
            "deduplication_worker_active": False,
            "save_worker_active": False
        }
    
    def update_pipeline_stats(self, **kwargs):
        """更新流水线统计"""
        if not self.enable_monitoring:
            return
            
        self.pipeline_stats.update(kwargs)
    
    def get_pipeline_stats(self) -> Dict:
        """获取流水线统计"""
        if not self.enable_monitoring:
            return {}
        
        return self.pipeline_stats.copy()
    
    async def _periodic_monitoring(self):
        """定期监控任务（包含流水线信息）"""
        while True:
            try:
                await asyncio.sleep(10)
                self._log_performance_stats()
                self._log_pipeline_stats()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ 流水线性能监控任务错误: {str(e)}")
    
    def _log_pipeline_stats(self):
        """输出流水线统计"""
        if not self.enable_monitoring:
            return
            
        pipeline_stats = self.get_pipeline_stats()
        
        logger.info(f"🏭 流水线状态: "
                   f"翻译队列 {pipeline_stats['translation_queue_size']}, "
                   f"去重队列 {pipeline_stats['deduplication_queue_size']}, "
                   f"保存队列 {pipeline_stats['save_queue_size']}, "
                   f"翻译工作器 {'活跃' if pipeline_stats['translation_worker_active'] else '空闲'}, "
                   f"去重工作器 {'活跃' if pipeline_stats['deduplication_worker_active'] else '空闲'}, "
                   f"保存工作器 {'活跃' if pipeline_stats['save_worker_active'] else '空闲'}") 