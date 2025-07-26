import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Optional
from models.api_models import TaskStatus

logger = logging.getLogger(__name__)

class TaskManager:
    """任务管理器"""
    
    def __init__(self):
        self.tasks: Dict[str, Dict] = {}
    
    def create_task(self, video_id: int, video_file_path: str, callback_url: Optional[str] = None) -> str:
        """创建新任务"""
        task_id = str(uuid.uuid4())
        task_data = {
            "task_id": task_id,
            "video_id": video_id,
            "video_file_path": video_file_path,
            "callback_url": callback_url,
            "status": TaskStatus.STARTED,
            "progress": 0,
            "current_step": "Task created",
            "error_message": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "estimated_completion": None,
            "translated_video_url": None,
            "cancelled": False
        }
        self.tasks[task_id] = task_data
        return task_id
    
    def update_task_status(self, task_id: str, status: TaskStatus, progress: int, current_step: str, error_message: Optional[str] = None):
        """更新任务状态"""
        if task_id in self.tasks:
            self.tasks[task_id].update({
                "status": status,
                "progress": progress,
                "current_step": current_step,
                "error_message": error_message
            })
            
            # 如果任务完成，设置完成时间
            if status == TaskStatus.COMPLETED:
                self.tasks[task_id]["estimated_completion"] = datetime.now(timezone.utc).isoformat()
    
    def get_task(self, task_id: str) -> Optional[Dict]:
        """获取任务信息"""
        return self.tasks.get(task_id)
    
    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        if task_id in self.tasks:
            self.tasks[task_id]["cancelled"] = True
            self.tasks[task_id]["status"] = TaskStatus.CANCELLED
            self.tasks[task_id]["current_step"] = "Task cancelled by user"
            return True
        return False
    
    def is_task_cancelled(self, task_id: str) -> bool:
        """检查任务是否被取消"""
        return self.tasks.get(task_id, {}).get("cancelled", False)
    
    def get_all_tasks(self) -> Dict[str, Dict]:
        """获取所有任务"""
        return self.tasks

# 全局任务管理器实例
task_manager = TaskManager() 