from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Dict, Optional, List
import uuid
import asyncio
import logging
import os
from datetime import datetime, timezone
import json
from pathlib import Path
import aiohttp
from enum import Enum

from main import VideoTranslationClient
from utils.common import get_file_hash
from config_manager import config

logger = logging.getLogger(__name__)

# 创建FastAPI应用
app = FastAPI(
    title="Video Translation API",
    description="API for video translation service",
    version="1.0.0"
)

# 挂载静态文件服务（用于提供翻译后的视频文件）
os.makedirs(config.output_dir, exist_ok=True)
app.mount("/files", StaticFiles(directory=config.output_dir), name="files")

# 任务状态枚举
class TaskStatus(str, Enum):
    STARTED = "started"
    EXTRACTING = "extracting"
    TRANSLATING = "translating"
    GENERATING_TTS = "generating_tts"
    COMPOSING = "composing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

# 请求和响应模型
class TranslateRequest(BaseModel):
    video_id: int
    video_file_path: str
    callback_url: Optional[str] = None
    source_language: str = "en"
    target_language: str = "zh"
    voice_type: str = "female"
    voice_speed: float = 1.0

class TranslateResponse(BaseModel):
    success: bool
    task_id: str
    message: str
    estimated_duration: Optional[int] = None

class TaskStatusResponse(BaseModel):
    task_id: str
    video_id: int
    status: TaskStatus
    progress: int
    current_step: str
    error_message: Optional[str] = None
    started_at: str
    estimated_completion: Optional[str] = None
    translated_video_url: Optional[str] = None

class CallbackData(BaseModel):
    video_id: int
    task_id: str
    status: TaskStatus
    progress: int
    current_step: str
    error_message: Optional[str] = None
    translated_video_url: Optional[str] = None

class CancelResponse(BaseModel):
    success: bool
    message: str

class ErrorResponse(BaseModel):
    success: bool
    error_code: str
    message: str
    details: Optional[str] = None

# 全局任务存储
tasks: Dict[str, Dict] = {}
translation_client = VideoTranslationClient()

class TaskManager:
    """任务管理器"""
    
    @staticmethod
    def create_task(video_id: int, video_file_path: str, callback_url: Optional[str] = None) -> str:
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
        tasks[task_id] = task_data
        return task_id
    
    @staticmethod
    def update_task_status(task_id: str, status: TaskStatus, progress: int, current_step: str, error_message: Optional[str] = None):
        """更新任务状态"""
        if task_id in tasks:
            tasks[task_id].update({
                "status": status,
                "progress": progress,
                "current_step": current_step,
                "error_message": error_message
            })
            
            # 如果任务完成，设置完成时间
            if status == TaskStatus.COMPLETED:
                tasks[task_id]["estimated_completion"] = datetime.now(timezone.utc).isoformat()
    
    @staticmethod
    def get_task(task_id: str) -> Optional[Dict]:
        """获取任务信息"""
        return tasks.get(task_id)
    
    @staticmethod
    def cancel_task(task_id: str) -> bool:
        """取消任务"""
        if task_id in tasks:
            tasks[task_id]["cancelled"] = True
            tasks[task_id]["status"] = TaskStatus.CANCELLED
            tasks[task_id]["current_step"] = "Task cancelled by user"
            return True
        return False

async def send_callback(callback_url: str, data: CallbackData, max_retries: int = 3):
    """发送回调通知"""
    if not callback_url:
        return
    
    for attempt in range(max_retries):
        try:
            timeout = aiohttp.ClientTimeout(total=30)  # 30秒超时
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    callback_url, 
                    json=data.dict(),
                    headers={"Content-Type": "application/json"}
                ) as response:
                    response_text = await response.text()
                    
                    if response.status == 200:
                        logger.info(f"✅ Callback sent successfully to {callback_url}")
                        return
                    else:
                        logger.warning(f"⚠️ Callback failed with status {response.status}, response: {response_text}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2 ** attempt)  # 指数退避
                        
        except asyncio.TimeoutError:
            logger.error(f"⏰ Callback timeout to {callback_url} (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
        except Exception as e:
            logger.error(f"❌ Failed to send callback to {callback_url} (attempt {attempt + 1}/{max_retries}): {str(e)}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
    
    logger.error(f"💥 All callback attempts failed for {callback_url}")

async def process_translation_task(task_id: str, video_file_path: str, callback_url: Optional[str] = None):
    """异步处理翻译任务"""
    try:
        task_data = tasks[task_id]
        video_id = task_data["video_id"]
        
        # 检查任务是否被取消
        def check_cancelled():
            return tasks.get(task_id, {}).get("cancelled", False)
        
        # 步骤1: 提取音频
        if check_cancelled():
            return
            
        TaskManager.update_task_status(task_id, TaskStatus.EXTRACTING, 10, "Extracting audio from video")
        await send_callback(callback_url, CallbackData(
            video_id=video_id,
            task_id=task_id,
            status=TaskStatus.EXTRACTING,
            progress=10,
            current_step="Extracting audio from video"
        ))
        
        # 获取视频文件名
        video_name = Path(video_file_path).stem
        file_hash = get_file_hash(video_name)
        
        # 提取音频
        audio_path = translation_client.audio_processor.extract_audio(video_file_path, video_name)
        
        if check_cancelled():
            return
            
        # 步骤2: 生成字幕
        TaskManager.update_task_status(task_id, TaskStatus.EXTRACTING, 30, "Generating subtitles")
        await send_callback(callback_url, CallbackData(
            video_id=video_id,
            task_id=task_id,
            status=TaskStatus.EXTRACTING,
            progress=30,
            current_step="Generating subtitles"
        ))
        
        # 检查是否存在已有字幕
        subtitle_json_path = os.path.join(config.temp_dir, video_name, f"{file_hash}_subtitles.json")
        if os.path.exists(subtitle_json_path):
            with open(subtitle_json_path, "r", encoding="utf-8") as f:
                subtitles = json.load(f)
        else:
            subtitles = await translation_client.subtitle_processor.get_subtitles(audio_path, video_name, video_file_path)
        
        if check_cancelled():
            return
            
        # 步骤3: 翻译字幕
        TaskManager.update_task_status(task_id, TaskStatus.TRANSLATING, 50, "Translating subtitles")
        await send_callback(callback_url, CallbackData(
            video_id=video_id,
            task_id=task_id,
            status=TaskStatus.TRANSLATING,
            progress=50,
            current_step="Translating subtitles"
        ))
        
        # 使用配置的翻译模式
        translation_mode = config.translation_mode
        use_whole_translation = (translation_mode == 'whole')
        
        if use_whole_translation:
            subtitles = await translation_client.translation_service.translate_whole_subtitles(
                subtitles=subtitles,
                video_name=video_name
            )
        else:
            subtitles = await translation_client.translation_service.translate_batch_subtitles(
                subtitles=subtitles,
                video_name=video_name
            )
        
        logger.info(f"翻译完成，使用模式: {translation_mode} ({'整体翻译' if use_whole_translation else '批量翻译'})")
        
        if check_cancelled():
            return
            
        # 步骤4: 创建参考音频
        TaskManager.update_task_status(task_id, TaskStatus.GENERATING_TTS, 65, "Creating reference audio segments")
        subtitles = translation_client.audio_processor.create_audio_segments(audio_path, subtitles, video_name)
        
        # 上传参考音频
        subtitles = await translation_client.audio_processor.upload_reference_audio(subtitles)
        
        if check_cancelled():
            return
            
        # 步骤5: 生成TTS音频
        TaskManager.update_task_status(task_id, TaskStatus.GENERATING_TTS, 80, "Generating TTS audio")
        await send_callback(callback_url, CallbackData(
            video_id=video_id,
            task_id=task_id,
            status=TaskStatus.GENERATING_TTS,
            progress=80,
            current_step="Generating TTS audio"
        ))
        
        tts_audio_path = await translation_client._generate_tts_audio(subtitles, video_name)
        
        if check_cancelled():
            return
            
        # 步骤6: 保存结果文件
        TaskManager.update_task_status(task_id, TaskStatus.COMPOSING, 95, "Saving translation results")
        
        # 保存翻译后的字幕
        output_subtitle_path = os.path.join(config.output_dir, f"{video_id}_{file_hash}_subtitles_zh.json")
        os.makedirs(os.path.dirname(output_subtitle_path), exist_ok=True)
        translation_client.subtitle_processor.save_subtitles_to_json(subtitles, output_subtitle_path)
        
        # 复制音频文件到输出目录
        output_audio_path = os.path.join(config.output_dir, f"{video_id}_{file_hash}_translated_audio.wav")
        if tts_audio_path and os.path.exists(tts_audio_path):
            import shutil
            shutil.copy2(tts_audio_path, output_audio_path)
        
        # 生成文件访问URL
        translated_audio_url = f"{config.api_base_url}/files/{video_id}_{file_hash}_translated_audio.wav"
        
        # 更新任务为完成状态
        TaskManager.update_task_status(task_id, TaskStatus.COMPLETED, 100, "Translation completed")
        tasks[task_id]["translated_video_url"] = translated_audio_url
        
        # 发送完成回调
        await send_callback(callback_url, CallbackData(
            video_id=video_id,
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            current_step="Translation completed",
            translated_video_url=translated_audio_url
        ))
        
        logger.info(f"Translation task {task_id} completed successfully")
        
    except Exception as e:
        error_message = str(e)
        logger.error(f"Translation task {task_id} failed: {error_message}")
        
        TaskManager.update_task_status(task_id, TaskStatus.FAILED, 0, "Translation failed", error_message)
        
        # 发送失败回调
        if callback_url:
            await send_callback(callback_url, CallbackData(
                video_id=task_data["video_id"],
                task_id=task_id,
                status=TaskStatus.FAILED,
                progress=0,
                current_step="Translation failed",
                error_message=error_message
            ))

@app.post("/translate", response_model=TranslateResponse)
async def start_translation(request: TranslateRequest, background_tasks: BackgroundTasks):
    """启动翻译任务"""
    try:
        # 验证视频文件是否存在
        if not os.path.exists(request.video_file_path):
            raise HTTPException(
                status_code=400,
                detail={
                    "success": False,
                    "error_code": "FILE_NOT_FOUND",
                    "message": "Video file not found",
                    "details": f"File path: {request.video_file_path}"
                }
            )
        
        # 创建任务
        task_id = TaskManager.create_task(
            video_id=request.video_id,
            video_file_path=request.video_file_path,
            callback_url=request.callback_url
        )
        
        # 启动后台任务
        background_tasks.add_task(
            process_translation_task,
            task_id,
            request.video_file_path,
            request.callback_url
        )
        
        logger.info(f"Started translation task {task_id} for video {request.video_id}")
        
        return TranslateResponse(
            success=True,
            task_id=task_id,
            message="Translation task started",
            estimated_duration=config.default_estimated_duration
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start translation: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error_code": "INTERNAL_ERROR",
                "message": "Failed to start translation task",
                "details": str(e)
            }
        )

@app.get("/tasks/{task_id}/status", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """查询任务状态"""
    task_data = TaskManager.get_task(task_id)
    if not task_data:
        raise HTTPException(
            status_code=404,
            detail={
                "success": False,
                "error_code": "TASK_NOT_FOUND",
                "message": "Task not found",
                "details": f"Task ID: {task_id}"
            }
        )
    
    return TaskStatusResponse(**task_data)

@app.post("/tasks/{task_id}/cancel", response_model=CancelResponse)
async def cancel_task(task_id: str):
    """取消翻译任务"""
    if TaskManager.cancel_task(task_id):
        logger.info(f"Task {task_id} cancelled successfully")
        return CancelResponse(
            success=True,
            message="Task cancelled successfully"
        )
    else:
        raise HTTPException(
            status_code=404,
            detail={
                "success": False,
                "error_code": "TASK_NOT_FOUND",
                "message": "Task not found",
                "details": f"Task ID: {task_id}"
            }
        )

@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/tasks")
async def list_tasks():
    """列出所有任务（用于调试）"""
    return {"tasks": list(tasks.keys()), "total": len(tasks)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.api_host, port=config.api_port)