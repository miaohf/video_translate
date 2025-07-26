import logging
from fastapi import APIRouter
from datetime import datetime, timezone

from services.task_manager import task_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

@router.get("/tasks")
async def list_tasks():
    """列出所有任务（用于调试）"""
    all_tasks = task_manager.get_all_tasks()
    return {"tasks": list(all_tasks.keys()), "total": len(all_tasks)} 