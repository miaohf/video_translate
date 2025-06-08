from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from faster_whisper import WhisperModel
import uvicorn
from tempfile import NamedTemporaryFile
import os
from datetime import datetime
import logging
from tqdm import tqdm
import asyncio
from typing import Optional, List, Dict
import signal
from contextlib import contextmanager
import time
from pyannote.audio import Pipeline
import numpy as np
import soundfile as sf
import torchaudio
from speechbrain.pretrained import VAD
from dotenv import load_dotenv
import torch

# Load environment variables from .env file
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("stt-server")

# 配置 CUDA
if torch.cuda.is_available():
    # Enable TF32 for better performance
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    logger.info("TF32 enabled for better performance")

app = FastAPI()

# Get Hugging Face access token
HF_TOKEN = os.getenv("HF_TOKEN")
if not HF_TOKEN:
    raise ValueError("HF_TOKEN environment variable not set. Please set it before running the server.")

# Create directory for audio file uploads
UPLOAD_DIR = "audio_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Set timeout (seconds)
PROCESSING_TIMEOUT = 300  # 5 minutes

# Initialize models
try:
    logger.info("Loading speaker recognition model...")
    logger.info("Please ensure you have accepted the terms of use for the following models:")
    logger.info("1. https://huggingface.co/pyannote/speaker-diarization-3.1")
    logger.info("2. https://huggingface.co/pyannote/segmentation-3.0")
    
    logger.info("Loading speaker recognition model...")
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=HF_TOKEN
    )
    
    # Use GPU if available
    if torch.cuda.is_available():
        logger.info("Using GPU for speaker recognition")
        pipeline = pipeline.to(torch.device("cuda"))
    else:
        logger.info("Using CPU for speaker recognition")
    
    logger.info("Speaker recognition model loaded successfully!")
except ValueError as ve:
    logger.error(f"Configuration error: {str(ve)}")
    raise
except Exception as e:
    logger.error(f"Failed to load speaker recognition model: {str(e)}")
    logger.error("Please ensure:")
    logger.error("1. HF_TOKEN is correctly set")
    logger.error("2. All required model terms of use are accepted")
    logger.error("3. Network connection is stable")
    raise

@contextmanager
def timeout(seconds):
    """
    Timeout context manager
    
    Args:
        seconds: Timeout duration in seconds
    """
    def signal_handler(signum, frame):
        raise TimeoutError(f"Processing timeout ({seconds} seconds)")
    
    # Set signal handler
    signal.signal(signal.SIGALRM, signal_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        # Cancel alarm
        signal.alarm(0)

# Load faster-whisper model
logger.info("Loading Whisper model...")
try:
    model = WhisperModel(
        "small",
        device="cpu",  # Use CPU mode
        compute_type="int8"  # Use int8 quantization to reduce memory usage
    )
    logger.info("Whisper model loaded successfully!")
except Exception as e:
    logger.error(f"Failed to load model: {str(e)}")
    raise

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    Middleware to log all requests
    
    Args:
        request: Request object
        call_next: Next handler function
    """
    start_time = time.time()
    logger.info(f"Received request: {request.method} {request.url}")
    
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        logger.info(f"Request completed: {request.method} {request.url} - Time: {process_time:.2f}s")
        return response
    except Exception as e:
        logger.error(f"Request failed: {request.method} {request.url} - Error: {str(e)}")
        raise

def process_diarization(audio_path: str) -> List[Dict]:
    """
    Process speaker diarization
    
    Args:
        audio_path: Path to audio file
    
    Returns:
        List of speaker segments
    """
    try:
        logger.info("Starting speaker diarization...")
        logger.info("Preprocessing audio...")
        
        # Load audio
        waveform, sample_rate = torchaudio.load(audio_path)
        
        # Convert stereo to mono if needed
        if waveform.shape[0] > 1:
            waveform = torch.mean(waveform, dim=0, keepdim=True)
        
        # Normalize audio
        waveform = waveform / torch.max(torch.abs(waveform))
        
        # Perform speaker diarization
        logger.info("Starting speaker diarization...")
        diarization = pipeline(
            {"waveform": waveform, "sample_rate": sample_rate},
            min_speakers=1,
            max_speakers=10
        )
        
        # Process results
        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segment = {
                "start": turn.start,
                "end": turn.end,
                "speaker": speaker
            }
            segments.append(segment)
        
        # Statistics
        unique_speakers = set(seg["speaker"] for seg in segments)
        logger.info(f"Identified {len(unique_speakers)} unique speakers")
        logger.info(f"Generated {len(segments)} speaker segments")
        
        return segments
        
    except Exception as e:
        logger.error(f"Speaker diarization failed: {str(e)}")
        raise

def process_transcription(audio_path: str) -> List[Dict]:
    """
    Process audio transcription with improved sentence segmentation
    
    Args:
        audio_path: Path to audio file
    
    Returns:
        List of transcription results
    """
    try:
        logger.info("Starting audio transcription...")
        
        # Use Whisper for transcription
        segments, info = model.transcribe(
            audio_path,
            language="en",  # Force English language
            task="transcribe",  # Transcription task
            beam_size=5,  # Use beam search
            vad_filter=True  # Use voice activity detection
        )
        
        # Process results
        results = []
        current_segment = None
        
        # 断句参数配置
        min_segment_duration = 1.0  # 最小片段时长（秒）
        max_segment_duration = 10.0  # 最大片段时长（秒）
        max_pause_duration = 0.8  # 最大停顿时长（秒）
        max_chars_per_segment = 100  # 每个片段最大字符数
        
        # 句子结束标记
        sentence_endings = ['.', '!', '?']
        # 自然断句标记
        natural_breaks = [',', ';', ':', ' - ']
        
        for segment in segments:
            text = segment.text.strip()
            if not text:  # 跳过空文本
                continue
                
            if current_segment is None:
                # 开始新片段
                current_segment = {
                    "start": segment.start,
                    "end": segment.end,
                    "text": text
                }
            else:
                # 检查是否需要合并片段
                pause_duration = segment.start - current_segment["end"]
                current_duration = current_segment["end"] - current_segment["start"]
                current_text = current_segment["text"]
                
                # 检查是否在句子结束处
                ends_with_sentence = any(current_text.rstrip().endswith(end) for end in sentence_endings)
                # 检查是否在自然断句处
                has_natural_break = any(break_mark in current_text for break_mark in natural_breaks)
                
                # 断句决策逻辑
                should_split = False
                
                # 1. 如果当前片段太长，强制分割
                if len(current_text) > max_chars_per_segment:
                    should_split = True
                
                # 2. 如果当前片段时长超过最大限制，且不在句子中间，则分割
                elif current_duration > max_segment_duration and (ends_with_sentence or has_natural_break):
                    should_split = True
                
                # 3. 如果停顿时间较长，且当前片段已经形成完整语义，则分割
                elif pause_duration > max_pause_duration and (ends_with_sentence or has_natural_break):
                    should_split = True
                
                if should_split:
                    # 保存当前片段并开始新片段
                    results.append(current_segment)
                    current_segment = {
                        "start": segment.start,
                        "end": segment.end,
                        "text": text
                    }
                else:
                    # 合并片段
                    current_segment["end"] = segment.end
                    # 确保文本之间有空格
                    if current_text and text and not current_text.endswith(' ') and not text.startswith(' '):
                        current_segment["text"] = current_text + " " + text
                    else:
                        current_segment["text"] = current_text + text
        
        # 添加最后一个片段
        if current_segment is not None:
            # 如果最后一个片段太短，尝试与上一个片段合并
            if len(results) > 0 and len(current_segment["text"]) < 20:
                last_segment = results[-1]
                last_segment["end"] = current_segment["end"]
                last_segment["text"] += " " + current_segment["text"]
            else:
                results.append(current_segment)
        
        # 后处理：清理文本格式
        for segment in results:
            # 移除多余的空格
            segment["text"] = " ".join(segment["text"].split())
            # 确保句子结束有标点
            if not any(segment["text"].rstrip().endswith(end) for end in sentence_endings):
                segment["text"] = segment["text"].rstrip() + "."
        
        logger.info(f"Transcription completed, generated {len(results)} segments")
        return results
        
    except Exception as e:
        logger.error(f"Transcription failed: {str(e)}")
        raise

@app.post("/diarize/")
async def diarize_audio(file: UploadFile = File(...)):
    """说话人识别接口"""
    start_time = datetime.now()
    logger.info(f"Received speaker recognition request: {file.filename}")
    
    try:
        # Generate unique filename (using timestamp)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_extension = os.path.splitext(file.filename)[1] if file.filename else ".wav"
        saved_filename = f"{timestamp}{file_extension}"
        file_path = os.path.join(UPLOAD_DIR, saved_filename)
        
        # Save uploaded audio file
        logger.info(f"Saving audio file: {saved_filename}")
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        file_size_mb = len(content)/1024/1024
        logger.info(f"Audio file saved successfully, size: {file_size_mb:.2f}MB")
        
        # Perform speaker recognition
        segments = process_diarization(file_path)
        
        # Clean up temporary file
        try:
            os.remove(file_path)
            logger.info(f"Temporary file cleaned: {saved_filename}")
        except Exception as e:
            logger.warning(f"Failed to clean temporary file: {str(e)}")
        
        return {
            "segments": segments,
            "saved_file": saved_filename
        }
        
    except Exception as e:
        logger.error(f"Processing failed: {str(e)}")
        # Ensure temporary file cleanup
        try:
            if 'file_path' in locals():
                os.remove(file_path)
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Speaker recognition processing failed: {str(e)}")

@app.post("/transcribe/")
async def transcribe_audio(file: UploadFile = File(...)):
    """音频转录接口"""
    start_time = datetime.now()
    logger.info(f"Received transcription request: {file.filename}")
    
    try:
        # Generate unique filename (using timestamp)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_extension = os.path.splitext(file.filename)[1] if file.filename else ".wav"
        saved_filename = f"{timestamp}{file_extension}"
        file_path = os.path.join(UPLOAD_DIR, saved_filename)
        
        # Save uploaded audio file
        logger.info(f"Saving audio file: {saved_filename}")
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        file_size_mb = len(content)/1024/1024
        logger.info(f"Audio file saved successfully, size: {file_size_mb:.2f}MB")
        
        # Perform audio transcription
        segments = process_transcription(file_path)
        
        # Clean up temporary file
        try:
            os.remove(file_path)
            logger.info(f"Temporary file cleaned: {saved_filename}")
        except Exception as e:
            logger.warning(f"Failed to clean temporary file: {str(e)}")
        
        return {
            "segments": segments,
            "saved_file": saved_filename
        }
        
    except Exception as e:
        logger.error(f"Processing failed: {str(e)}")
        # Ensure temporary file cleanup
        try:
            if 'file_path' in locals():
                os.remove(file_path)
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Transcription processing failed: {str(e)}")

if __name__ == "__main__":
    logger.info("Starting STT server...")
    uvicorn.run(app, host="0.0.0.0", port=8001)
