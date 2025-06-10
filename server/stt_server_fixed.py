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

    # 加载 Whisper 模型 - 先用CPU确保稳定性
    logger.info("Loading Whisper model...")
    try:
        whisper_model = WhisperModel(
            "large-v3",  # 使用large-v3获得更好效果
            device=device,  # 使用GPU
            compute_type="float16" if device == "cuda" else "float32"
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
        
        # Use Whisper for transcription - 禁用VAD避免段错误
        segments, info = whisper_model.transcribe(
            audio_path,
            language="en",  # Force English language
            task="transcribe",  # Transcription task
            beam_size=1,  # 减少beam_size避免内存问题
            vad_filter=False,  # 禁用VAD避免段错误
            condition_on_previous_text=False  # 禁用条件生成
        )
        
        logger.info(f"Detected language: {info.language} (probability: {info.language_probability:.2f})")
        logger.info(f"Audio duration: {info.duration:.2f} seconds")
        
        # Convert generator to list to check if empty
        segments_list = list(segments)
        logger.info(f"Generated {len(segments_list)} raw segments")
        
        if not segments_list:
            logger.warning("No segments detected by Whisper")
            return []
        
        # Process results - 添加智能合并逻辑
        results = []
        current_segment = None
        
        # 合并参数
        max_segment_duration = 30.0  # 最大片段时长（秒）
        max_pause_duration = 2.0     # 最大停顿时长（秒）
        max_chars_per_segment = 300  # 每个片段最大字符数
        min_segment_duration = 0.5   # 最小片段时长（秒）
        
        # 句子结束标记
        sentence_endings = ['.', '!', '?']
        # 自然断句标记
        natural_breaks = [',', ';', ':', ' - ', ' and ', ' but ', ' or ', ' so ']
        
        for segment in segments_list:
            text = segment.text.strip()
            if not text or len(text) < 3:  # 跳过空文本或过短文本
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
                should_merge = (
                    current_duration < max_segment_duration and  # 当前片段不能太长
                    pause_duration < max_pause_duration and      # 停顿时间不能太长
                    len(current_text + " " + text) <= max_chars_per_segment and  # 合并后字符数不超限
                    not (ends_with_sentence and pause_duration > 0.8) and  # 句子结束且有明显停顿时不合并
                    not (len(current_text) > 150 and has_natural_break and pause_duration > 0.5)  # 长句子在自然断句处分割
                )
                
                if should_merge:
                    # 合并片段
                    current_segment["end"] = segment.end
                    # 智能添加标点
                    if current_text and text:
                        if current_text[-1] in '.!?':
                            current_segment["text"] = current_text + " " + text
                        elif current_text[-1] in ',;:':
                            current_segment["text"] = current_text + " " + text
                        elif text[0].isupper() and not current_text.endswith(' '):
                            current_segment["text"] = current_text + ". " + text
                        else:
                            current_segment["text"] = current_text + " " + text
                    else:
                        current_segment["text"] = current_text + " " + text
                else:
                    # 保存当前片段并开始新片段
                    if current_segment["end"] - current_segment["start"] >= min_segment_duration:
                        # 确保片段以适当的标点结束
                        if not any(current_segment["text"].rstrip().endswith(end) for end in sentence_endings):
                            if any(current_segment["text"].rstrip().endswith(mark.strip()) for mark in natural_breaks):
                                current_segment["text"] = current_segment["text"].rstrip() + "."
                            else:
                                current_segment["text"] = current_segment["text"].rstrip() + "."
                        
                        results.append(current_segment)
                    
                    # 开始新片段
                    current_segment = {
                        "start": segment.start,
                        "end": segment.end,
                        "text": text
                    }
        
        # 添加最后一个片段
        if current_segment and current_segment["end"] - current_segment["start"] >= min_segment_duration:
            # 确保最后一个片段以适当的标点结束
            if not any(current_segment["text"].rstrip().endswith(end) for end in sentence_endings):
                current_segment["text"] = current_segment["text"].rstrip() + "."
            results.append(current_segment)
        
        logger.info(f"Final processed segments: {len(results)} (merged from {len(segments_list)} raw segments)")
        for i, seg in enumerate(results):
            logger.debug(f"Result {i+1}: {seg['start']:.2f}-{seg['end']:.2f} ({seg['end']-seg['start']:.1f}s): '{seg['text'][:100]}{'...' if len(seg['text']) > 100 else ''}'")
        
        return results
        
    except Exception as e:
        logger.error(f"Transcription failed: {str(e)}")
        raise

def merge_speaker_segments(segments: List[Dict]) -> List[Dict]:
    """
    合并同一说话人的连续字幕片段
    
    Args:
        segments: 包含speaker信息的字幕片段列表
        
    Returns:
        合并后的字幕片段列表
    """
    if not segments:
        return []
    
    logger.info(f"Merging speaker segments: {len(segments)} input segments")
    
    merged = []
    current_merged = None
    
    # 合并参数
    max_merged_duration = 60.0   # 最大合并片段时长（秒）
    max_gap_duration = 3.0       # 最大间隔时长（秒）
    max_chars_per_merged = 500   # 每个合并片段最大字符数
    
    for segment in segments:
        if not segment.get("text", "").strip():
            continue
            
        current_speaker = segment.get("speaker", "UNKNOWN")
        current_text = segment["text"].strip()
        current_start = segment["start"]
        current_end = segment["end"]
        
        if current_merged is None:
            # 开始新的合并片段
            current_merged = {
                "start": current_start,
                "end": current_end,
                "text": current_text,
                "speaker": current_speaker
            }
        else:
            # 检查是否可以与当前合并片段合并
            same_speaker = current_merged["speaker"] == current_speaker
            gap_duration = current_start - current_merged["end"]
            merged_duration = current_end - current_merged["start"]
            merged_text_length = len(current_merged["text"] + " " + current_text)
            
            should_merge = (
                same_speaker and
                gap_duration <= max_gap_duration and
                merged_duration <= max_merged_duration and
                merged_text_length <= max_chars_per_merged
            )
            
            if should_merge:
                # 合并到当前片段
                current_merged["end"] = current_end
                # 智能连接文本
                merged_text = current_merged["text"]
                if merged_text and current_text:
                    # 检查是否需要添加标点
                    if merged_text[-1] in '.!?':
                        current_merged["text"] = merged_text + " " + current_text
                    elif merged_text[-1] in ',;:':
                        current_merged["text"] = merged_text + " " + current_text
                    elif not merged_text.endswith(' ') and current_text[0].isupper():
                        # 如果下一句开头是大写字母，可能是新句子
                        if gap_duration > 1.0:  # 如果间隔较长，添加句号
                            current_merged["text"] = merged_text + ". " + current_text
                        else:
                            current_merged["text"] = merged_text + " " + current_text
                    else:
                        current_merged["text"] = merged_text + " " + current_text
                else:
                    current_merged["text"] = merged_text + " " + current_text
            else:
                # 不能合并，保存当前合并片段并开始新的
                merged.append(current_merged)
                current_merged = {
                    "start": current_start,
                    "end": current_end,
                    "text": current_text,
                    "speaker": current_speaker
                }
    
    # 添加最后一个合并片段
    if current_merged:
        merged.append(current_merged)
    
    logger.info(f"Merged speaker segments: {len(segments)} -> {len(merged)} segments")
    
    # 打印合并统计
    for i, seg in enumerate(merged):
        duration = seg["end"] - seg["start"]
        char_count = len(seg["text"])
        logger.debug(f"Merged {i+1}: {seg['speaker']} ({duration:.1f}s, {char_count} chars): '{seg['text'][:80]}{'...' if char_count > 80 else ''}'")
    
    return merged

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

@app.post("/transcribe_with_speakers/")
async def transcribe_with_speakers(transcription_segments: List[Dict]):
    """
    对已有的转录片段进行说话人信息合并
    
    Args:
        transcription_segments: 包含speaker信息的转录片段列表
        
    Returns:
        合并后的转录结果
    """
    try:
        logger.info(f"Received transcription segments for speaker merging: {len(transcription_segments)} segments")
        
        # 使用说话人合并功能
        merged_segments = merge_speaker_segments(transcription_segments)
        
        response = {
            "status": "success",
            "segments": merged_segments,
            "total_segments": len(merged_segments),
            "original_segments": len(transcription_segments)
        }
        
        logger.info(f"Speaker merging completed: {len(transcription_segments)} -> {len(merged_segments)} segments")
        return response
        
    except Exception as e:
        logger.error(f"Speaker merging failed: {str(e)}")
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