import os
import torch
import logging
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pyannote.audio import Pipeline
import torchaudio
import gc
from dotenv import load_dotenv
import uvicorn
from contextlib import asynccontextmanager, contextmanager
from typing import List, Dict
import signal
import whisperx
import numpy as np

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 定义上传文件目录
UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# 定义处理超时时间（秒）
PROCESSING_TIMEOUT = 600  # 10分钟

# 启用 TF32 以提高性能
if torch.cuda.is_available():
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    logger.info("TF32 enabled for better performance")

# 全局变量
pipeline = None
whisper_model = None
device = "cuda" if torch.cuda.is_available() else "cpu"

@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务器生命周期管理"""
    # 启动时加载模型
    load_models()
    logger.info("Starting STT server...")
    yield
    # 关闭时清理资源
    if device == "cuda":
        torch.cuda.empty_cache()
    gc.collect()

# 初始化 FastAPI 应用
app = FastAPI(lifespan=lifespan)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def load_models():
    """加载所需的模型"""
    global pipeline, whisper_model
    
    # 获取 Hugging Face token
    hf_token = os.getenv("HF_TOKEN")
    if not hf_token:
        raise ValueError("HF_TOKEN environment variable not set. Please set it before running the server.")

    # 加载说话人识别模型
    logger.info("Loading speaker recognition model...")
    logger.info("Please ensure you have accepted the terms of use for the following models:")
    logger.info("1. https://huggingface.co/pyannote/speaker-diarization-3.1")
    logger.info("2. https://huggingface.co/pyannote/segmentation-3.0")
    
    try:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token
        )
        if device == "cuda":
            pipeline = pipeline.to(torch.device(device))
            logger.info("Using GPU for speaker recognition")
        logger.info("Speaker recognition model loaded successfully!")
    except Exception as e:
        logger.error(f"Failed to load speaker recognition model: {str(e)}")
        raise

    # 加载 Whisper 模型
    logger.info("Loading Whisper model...")
    try:
        whisper_model = whisperx.load_model(
            "small",  # 使用small模型而不是large-v3
            device="cpu",  # 使用CPU模式避免GPU内存问题
            compute_type="int8"  # 使用int8量化减少内存使用
        )
        logger.info("Whisper model loaded successfully!")
    except Exception as e:
        logger.error(f"Failed to load Whisper model: {str(e)}")
        raise

@app.post("/diarize/")
async def diarize_speakers(file: UploadFile = File(...)):
    """处理说话人识别请求"""
    try:
        logger.info(f"Received speaker recognition request: {file.filename}")
        
        # 保存上传的音频文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_audio_path = f"{timestamp}.mp3"
        
        with open(temp_audio_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        file_size = os.path.getsize(temp_audio_path) / (1024 * 1024)  # 转换为 MB
        logger.info(f"Audio file saved successfully, size: {file_size:.2f}MB")
        
        # 使用超时上下文管理器
        with timeout(PROCESSING_TIMEOUT):
            # 执行说话人识别
            logger.info("Starting speaker diarization...")
            diarization = pipeline(temp_audio_path)
            
            # 提取说话人片段
            segments = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                segments.append({
                    "start": turn.start,
                    "end": turn.end,
                    "speaker": speaker
                })
            
            logger.info(f"Speaker diarization completed. Found {len(segments)} segments")
            
            # 清理临时文件
            if os.path.exists(temp_audio_path):
                os.remove(temp_audio_path)
            
            return {"status": "success", "segments": segments}
            
    except TimeoutError:
        logger.error(f"Speaker diarization timeout after {PROCESSING_TIMEOUT} seconds")
        if os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)
        raise HTTPException(status_code=504, detail="Speaker diarization timeout")
    except Exception as e:
        logger.error(f"Speaker diarization failed: {str(e)}")
        if os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)
        raise HTTPException(status_code=500, detail=str(e))

def process_transcription(audio_path: str) -> List[Dict]:
    """
    处理音频转录
    
    Args:
        audio_path: 音频文件路径
    
    Returns:
        转录结果列表
    """
    try:
        logger.info(f"Starting transcription for: {audio_path}")
        
        # 使用 Whisper 进行转录
        result = whisper_model.transcribe(audio_path)
        
        # 提取转录片段
        segments = []
        for segment in result["segments"]:
            segments.append({
                "start": segment["start"],
                "end": segment["end"],
                "text": segment["text"].strip()
            })
        
        logger.info(f"Transcription completed. Generated {len(segments)} segments")
        return segments
        
    except Exception as e:
        logger.error(f"Transcription failed: {str(e)}")
        raise

@app.post("/transcribe/")
async def transcribe_audio(file: UploadFile = File(...)):
    """
    Transcribe audio file
    
    Args:
        file: Audio file to transcribe
    
    Returns:
        Transcription results
    """
    file_path = None
    try:
        # 生成唯一文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{file.filename}"
        file_path = os.path.join(UPLOAD_DIR, filename)
        
        # 保存上传的文件
        logger.info(f"Received transcription request: {filename}")
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        logger.info(f"Audio file saved successfully, size: {len(content)/1024/1024:.2f}MB")
        
        # 使用超时上下文管理器
        with timeout(PROCESSING_TIMEOUT):
            # 使用简单的转录方法
            logger.info("Using simple transcription method...")
            segments = process_transcription(file_path)
            
            # 清理临时文件
            if os.path.exists(file_path):
                os.remove(file_path)
            
            return {"status": "success", "results": segments}
            
    except TimeoutError:
        logger.error(f"Transcription timeout after {PROCESSING_TIMEOUT} seconds")
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=504, detail="Transcription timeout")
    except Exception as e:
        logger.error(f"Transcription failed: {str(e)}")
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=str(e))

@contextmanager
def timeout(seconds):
    """
    Timeout context manager

    Args:
        seconds: Timeout duration in seconds
    """
    def signal_handler(signum, frame):
        raise TimeoutError(f"Processing timeout ({seconds} seconds)")

    signal.signal(signal.SIGALRM, signal_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001) 