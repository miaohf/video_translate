import os
import logging
import shutil
from fastapi import APIRouter, HTTPException, BackgroundTasks, UploadFile, File, Form, Request
from datetime import datetime, timezone
from typing import Optional, Union, List

from models.api_models import (
    TranslateRequest, TranslateResponse, TaskStatusResponse, 
    CancelResponse, TaskStatus
)
from services.task_manager import task_manager
from services.translation_task_service import translation_task_service
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["translation"])

@router.post("/translate", response_model=TranslateResponse)
async def start_translation(
    request: Request,
    background_tasks: BackgroundTasks,
    translate_request: Optional[TranslateRequest] = None,
    video_id: Optional[int] = Form(None),
    audio_file: Optional[UploadFile] = File(None),
    voice_role_files: List[UploadFile] = File([]),
    callback_url: Optional[str] = Form(None),
    source_language: str = Form("en"),
    target_language: str = Form("zh"),
    voice_type: Optional[str] = Form("female"),
    voice_speed: Optional[float] = Form(1.0),
    summarize: Optional[bool] = Form(False)  # 新增：summarize参数
):
    """启动翻译任务（支持本地文件路径和音频文件上传两种方式）"""
    try:
        content_type = request.headers.get("content-type", "")
        
        # 方式1: JSON请求体（本地文件路径）
        if "application/json" in content_type and translate_request:
            return await _handle_local_file_translation(translate_request, background_tasks)
        
        # 方式2: 音频文件上传
        elif "multipart/form-data" in content_type and audio_file:
            return await _handle_upload_translation(
                request, video_id, audio_file, voice_role_files, callback_url, source_language, 
                target_language, voice_type, voice_speed, background_tasks, summarize
            )
        
        # 方式3: 混合模式（JSON + 音频文件上传）
        elif translate_request and audio_file:
            return await _handle_upload_translation(
                request, translate_request.video_id, audio_file, voice_role_files, translate_request.callback_url,
                translate_request.source_language, translate_request.target_language,
                translate_request.voice_type, translate_request.voice_speed, background_tasks, translate_request.summarize
            )
        
        else:
            raise HTTPException(
                status_code=400,
                detail={
                    "success": False,
                    "error_code": "INVALID_REQUEST",
                    "message": "Invalid request format",
                    "details": "Please use either JSON with video_file_path or multipart/form-data with audio_file"
                }
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

async def _handle_local_file_translation(request: TranslateRequest, background_tasks: BackgroundTasks):
    """处理本地文件路径翻译请求"""
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
    
    # 验证voice_mappings中的音频文件是否存在
    if request.voice_mappings:
        for mapping in request.voice_mappings:
            if not os.path.exists(mapping.audio_file_path):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "success": False,
                        "error_code": "VOICE_MAPPING_FILE_NOT_FOUND",
                        "message": "Voice mapping audio file not found",
                        "details": f"Audio file path: {mapping.audio_file_path}"
                    }
                )
    
    # 创建任务
    task_id = task_manager.create_task(
        video_id=request.video_id,
        video_file_path=request.video_file_path,
        callback_url=request.callback_url
    )
    
    # 启动后台任务，传递voice_mappings和summarize参数
    background_tasks.add_task(
        translation_task_service.process_translation_task,
        task_id,
        request.video_file_path,
        request.callback_url,
        request.voice_mappings,
        request.summarize  # 新增：传递summarize参数
    )
    
    logger.info(f"Started translation task {task_id} for local file: {request.video_file_path}")
    if request.voice_mappings:
        logger.info(f"Voice mappings configured: {len(request.voice_mappings)} mappings")
    if request.summarize:
        logger.info(f"Content summarization enabled for task {task_id}")
    
    return TranslateResponse(
        success=True,
        task_id=task_id,
        message="Translation task started for local file",
        estimated_duration=settings.DEFAULT_ESTIMATED_DURATION
    )

async def _handle_upload_translation(
    request: Request,
    video_id: Optional[int],
    audio_file: UploadFile,
    voice_role_files: List[UploadFile],
    callback_url: Optional[str],
    source_language: str,
    target_language: str,
    voice_type: Optional[str],
    voice_speed: Optional[float],
    background_tasks: BackgroundTasks,
    summarize: Optional[bool] = False # 新增：summarize参数
):
    """处理音频文件上传翻译请求"""
    # 调试：打印接收到的所有表单数据
    logger.info(f"Received audio_file: {audio_file.filename if audio_file else 'None'}")
    logger.info(f"Received voice_role_files count: {len(voice_role_files)}")
    for i, role_file in enumerate(voice_role_files):
        logger.info(f"  voice_role_files[{i}]: {role_file.filename}")
    
    # 显示所有接收到的表单字段（调试用）
    logger.info("All form fields received:")
    form_data = await request.form()
    for field_name, field_value in form_data.items():
        logger.info(f"  {field_name}: {field_value}")
    
    # 验证音频文件类型
    if not audio_file.filename.lower().endswith(('.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac')):
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error_code": "INVALID_FILE_TYPE",
                "message": "Invalid audio file type",
                "details": "Supported formats: mp3, wav, m4a, aac, ogg, flac"
            }
        )
    
    # 如果没有提供video_id，使用时间戳生成一个
    if video_id is None:
        video_id = int(datetime.now().timestamp())
        logger.info(f"Generated video_id: {video_id}")
    
    # 创建上传目录
    upload_dir = os.path.join(settings.TEMP_DIR, "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    
    # 生成唯一文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_extension = os.path.splitext(audio_file.filename)[1]
    unique_filename = f"{video_id}_{timestamp}{file_extension}"
    file_path = os.path.join(upload_dir, unique_filename)
    
    # 保存上传的音频文件
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(audio_file.file, buffer)
    except Exception as e:
        logger.error(f"Failed to save uploaded audio file: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error_code": "FILE_SAVE_ERROR",
                "message": "Failed to save uploaded audio file",
                "details": str(e)
            }
        )
    
    logger.info(f"Audio file uploaded: {file_path} (size: {os.path.getsize(file_path)} bytes)")
    
    # 处理角色音频文件
    voice_mappings = []
    logger.info(f"Received {len(voice_role_files)} voice role files")
    
    if voice_role_files:
        # 创建角色音频目录
        voice_roles_dir = os.path.join(settings.TEMP_DIR, "voice_roles", str(video_id))
        os.makedirs(voice_roles_dir, exist_ok=True)
        
        for i, role_file in enumerate(voice_role_files):
            logger.info(f"Processing voice role file {i+1}: {role_file.filename} (size: {role_file.size} bytes)")
            
            if role_file.filename.lower().endswith(('.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac')):
                # 尝试从原始文件名中提取说话人信息
                original_name = os.path.splitext(role_file.filename)[0]
                file_extension = os.path.splitext(role_file.filename)[1]
                
                # 从文件名中提取speaker_id，如果失败则使用索引
                import re
                if 'SPEAKER' in original_name.upper():
                    speaker_match = re.search(r'SPEAKER_\d+', original_name.upper())
                    if speaker_match:
                        detected_speaker_id = speaker_match.group(0)
                    else:
                        detected_speaker_id = f"SPEAKER_{i:02d}"
                else:
                    detected_speaker_id = f"SPEAKER_{i:02d}"
                
                # 生成角色音频文件名
                role_filename = f"voice_role_{detected_speaker_id.lower()}{file_extension}"
                role_file_path = os.path.join(voice_roles_dir, role_filename)
                
                try:
                    with open(role_file_path, "wb") as buffer:
                        shutil.copyfileobj(role_file.file, buffer)
                    
                    # 创建语音角色映射
                    voice_mapping = {
                        "speaker_id": detected_speaker_id,
                        "voice_role_id": i + 1,
                        "voice_role_name": f"voice_role_{detected_speaker_id.lower()}",
                        "audio_file_path": role_file_path
                    }
                    voice_mappings.append(voice_mapping)
                    
                    logger.info(f"Voice role file uploaded: {role_file_path} (size: {os.path.getsize(role_file_path)} bytes)")
                    
                except Exception as e:
                    logger.error(f"Failed to save voice role file {role_file.filename}: {str(e)}")
                    raise HTTPException(
                        status_code=500,
                        detail={
                            "success": False,
                            "error_code": "VOICE_ROLE_FILE_SAVE_ERROR",
                            "message": "Failed to save voice role file",
                            "details": f"File: {role_file.filename}, Error: {str(e)}"
                        }
                    )
            else:
                logger.warning(f"Skipping invalid voice role file: {role_file.filename}")
        
        logger.info(f"Processed {len(voice_mappings)} voice role files")
    
    # 创建任务
    task_id = task_manager.create_task(
        video_id=video_id,
        video_file_path=file_path,
        callback_url=callback_url
    )
    
    # 启动后台任务，传递voice_mappings参数
    background_tasks.add_task(
        translation_task_service.process_translation_task,
        task_id,
        file_path,
        callback_url,
        voice_mappings if voice_mappings else None,
        summarize # 新增：传递summarize参数
    )
    
    logger.info(f"Started translation task {task_id} for uploaded audio {video_id}")
    
    return TranslateResponse(
        success=True,
        task_id=task_id,
        message="Translation task started for uploaded audio file",
        estimated_duration=settings.DEFAULT_ESTIMATED_DURATION
    )

@router.get("/tasks/{task_id}/status", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """查询任务状态"""
    task_data = task_manager.get_task(task_id)
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

@router.post("/tasks/{task_id}/cancel", response_model=CancelResponse)
async def cancel_task(task_id: str):
    """取消翻译任务"""
    if task_manager.cancel_task(task_id):
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

@router.get("/tasks/{task_id}/summary")
async def get_task_summary(task_id: str):
    """获取任务的内容总结"""
    task_data = task_manager.get_task(task_id)
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
    
    video_id = task_data["video_id"]
    
    # 导入总结服务
    from services.summarization_service import summarization_service
    
    # 获取总结文件URL
    summary_url = summarization_service.get_summary_file_url(video_id)
    
    if not summary_url:
        raise HTTPException(
            status_code=404,
            detail={
                "success": False,
                "error_code": "SUMMARY_NOT_FOUND",
                "message": "Summary not found",
                "details": f"No summary available for task {task_id}"
            }
        )
    
    return {
        "success": True,
        "task_id": task_id,
        "video_id": video_id,
        "summary_url": summary_url,
        "summary_metadata": task_data.get("summary_metadata")
    } 