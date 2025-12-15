from pydantic import BaseModel
from typing import Optional, List
from enum import Enum

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

# 语音角色映射模型
class VoiceRoleMapping(BaseModel):
    speaker_id: str
    voice_role_id: int
    voice_role_name: str
    audio_file_path: str

# 请求和响应模型
class TranslateRequest(BaseModel):
    video_id: Optional[int] = None
    video_file_path: str
    callback_url: Optional[str] = None
    source_language: str = "en"
    target_language: str = "zh"
    voice_type: Optional[str] = "female"
    voice_speed: Optional[float] = 1.0
    voice_mappings: Optional[List[VoiceRoleMapping]] = None
    summarize: Optional[bool] = False  # 新增：是否进行内容总结

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
    summary_url: Optional[str] = None  # 新增：总结文件URL
    summary_metadata: Optional[dict] = None  # 新增：总结元数据

class CallbackData(BaseModel):
    video_id: int
    task_id: str
    status: TaskStatus
    progress: int
    current_step: str
    error_message: Optional[str] = None
    translated_video_url: Optional[str] = None
    summary_url: Optional[str] = None  # 新增：总结文件URL
    summary_metadata: Optional[dict] = None  # 新增：总结元数据

class CancelResponse(BaseModel):
    success: bool
    message: str

class ErrorResponse(BaseModel):
    success: bool
    error_code: str
    message: str
    details: Optional[str] = None 