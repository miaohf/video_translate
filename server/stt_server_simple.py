import os
import torch
import logging
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pyannote.audio import Pipeline
from faster_whisper import WhisperModel
import torchaudio
import gc
from dotenv import load_dotenv
import uvicorn
from contextlib import asynccontextmanager, contextmanager
from typing import List, Dict
import signal

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
PROCESSING_TIMEOUT = 300  # 5分钟

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

    # 加载 Whisper 模型 - 先用CPU和small模型确保稳定性
    logger.info("Loading Whisper model...")
    try:
        whisper_model = WhisperModel(
            "small",  # 先使用small模型
            device="cpu",  # 先使用CPU模式
            compute_type="int8"  # 使用int8量化
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
        
        # 进行说话人识别
        logger.info("Starting speaker diarization...")
        logger.info("Preprocessing audio...")
        
        # 预处理音频
        processed_audio_path = preprocess_audio(temp_audio_path)
        
        # 进行说话人识别
        logger.info("Starting speaker diarization...")
        diarization = pipeline(processed_audio_path)
        
        # 处理识别结果
        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append({
                "start": turn.start,
                "end": turn.end,
                "speaker": f"SPEAKER_{speaker.split('_')[-1]}"
            })
        
        # 清理临时文件
        if os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)
        if os.path.exists(processed_audio_path):
            os.remove(processed_audio_path)
            
        # 清理 GPU 内存
        if device == "cuda":
            torch.cuda.empty_cache()
            gc.collect()
        
        logger.info(f"Identified {len(set(s['speaker'] for s in segments))} unique speakers")
        logger.info(f"Generated {len(segments)} speaker segments")
        
        return {"segments": segments}
        
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
        segments, info = whisper_model.transcribe(
            audio_path,
            language="en",  # Force English language
            task="transcribe",  # Transcription task
            beam_size=5,  # Use beam search
            vad_filter=True  # Use voice activity detection
        )
        
        logger.info(f"Detected language: {info.language} (probability: {info.language_probability:.2f})")
        logger.info(f"Audio duration: {info.duration:.2f} seconds")
        
        # Convert generator to list to check if empty
        segments_list = list(segments)
        logger.info(f"Generated {len(segments_list)} raw segments")
        
        if not segments_list:
            logger.warning("No segments detected by Whisper")
            return []
        
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
        
        for segment in segments_list:
            text = segment.text.strip()
            if not text:  # 跳过空文本
                continue
                
            logger.debug(f"Processing segment: {segment.start:.2f}-{segment.end:.2f}: '{text}'")
                
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
                
                # 合并条件：
                # 1. 当前片段时长小于最大时长
                # 2. 停顿时间小于最大停顿时长
                # 3. 当前文本长度小于最大字符数
                # 4. 不在句子结束处
                # 5. 不在自然断句处
                if (current_duration < max_segment_duration and
                    pause_duration < max_pause_duration and
                    len(current_text) < max_chars_per_segment and
                    not ends_with_sentence and
                    not has_natural_break):
                    # 合并片段
                    current_segment["end"] = segment.end
                    current_segment["text"] += " " + text
                else:
                    # 保存当前片段
                    if current_segment["end"] - current_segment["start"] >= min_segment_duration:
                        results.append(current_segment)
                    # 开始新片段
                    current_segment = {
                        "start": segment.start,
                        "end": segment.end,
                        "text": text
                    }
        
        # 添加最后一个片段
        if current_segment and current_segment["end"] - current_segment["start"] >= min_segment_duration:
            results.append(current_segment)
        
        logger.info(f"Final processed segments: {len(results)}")
        for i, seg in enumerate(results):
            logger.debug(f"Result {i+1}: {seg['start']:.2f}-{seg['end']:.2f}: '{seg['text']}'")
        
        return results
        
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
            
            # 确保返回正确的格式
            response = {
                "status": "success", 
                "segments": segments,  # 修改为segments而不是results
                "total_segments": len(segments)
            }
            
            logger.info(f"Returning {len(segments)} segments")
            return response
            
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

def preprocess_audio(audio_path: str) -> str:
    """
    预处理音频文件，确保格式正确
    
    参数:
        audio_path: 输入音频文件路径
        
    返回:
        处理后的音频文件路径
    """
    try:
        # 读取音频文件
        waveform, sample_rate = torchaudio.load(audio_path)
        
        # 如果是立体声，转换为单声道
        if waveform.shape[0] > 1:
            waveform = torch.mean(waveform, dim=0, keepdim=True)
        
        # 如果采样率不是 16kHz，进行重采样
        if sample_rate != 16000:
            resampler = torchaudio.transforms.Resample(sample_rate, 16000)
            waveform = resampler(waveform)
            sample_rate = 16000
        
        # 保存处理后的音频
        output_path = audio_path.replace(".mp3", "_processed.wav")
        torchaudio.save(output_path, waveform, sample_rate)
        
        return output_path
    except Exception as e:
        logger.error(f"Audio preprocessing failed: {str(e)}")
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

    signal.signal(signal.SIGALRM, signal_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001) 