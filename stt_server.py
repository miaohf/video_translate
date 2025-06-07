from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from faster_whisper import WhisperModel
import uvicorn
from tempfile import NamedTemporaryFile
import os
from datetime import datetime
import logging
from tqdm import tqdm
import asyncio
from typing import Optional
import signal
from contextlib import contextmanager
import time

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("stt-server")

app = FastAPI()

# 创建保存音频文件的目录
UPLOAD_DIR = "audio_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 设置超时时间（秒）
PROCESSING_TIMEOUT = 300  # 5分钟

@contextmanager
def timeout(seconds):
    def signal_handler(signum, frame):
        raise TimeoutError(f"处理超时（{seconds}秒）")
    
    # 设置信号处理器
    signal.signal(signal.SIGALRM, signal_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        # 取消警报
        signal.alarm(0)

# 加载 faster-whisper 模型
logger.info("正在加载 Whisper 模型...")
try:
    model = WhisperModel(
        "small",
        device="cuda",  # 使用 GPU，如果用 CPU 则设为 "cpu"
        compute_type="float16"  # 可选 "float32", "float16", "int8"
    )
    logger.info("Whisper 模型加载完成！")
except Exception as e:
    logger.error(f"模型加载失败: {str(e)}")
    raise

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录所有请求的中间件"""
    start_time = time.time()
    logger.info(f"收到请求: {request.method} {request.url}")
    
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        logger.info(f"请求处理完成: {request.method} {request.url} - 耗时: {process_time:.2f}秒")
        return response
    except Exception as e:
        logger.error(f"请求处理失败: {request.method} {request.url} - 错误: {str(e)}")
        raise

@app.post("/transcribe/")
async def transcribe_audio(file: UploadFile = File(...)):
    start_time = datetime.now()
    logger.info(f"收到转录请求: {file.filename}")
    
    try:
        # 生成唯一文件名（使用时间戳）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_extension = os.path.splitext(file.filename)[1] if file.filename else ".wav"
        saved_filename = f"{timestamp}{file_extension}"
        file_path = os.path.join(UPLOAD_DIR, saved_filename)
        
        # 保存上传的音频文件到永久位置
        logger.info(f"正在保存音频文件: {saved_filename}")
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        file_size_mb = len(content)/1024/1024
        logger.info(f"音频文件保存完成，大小: {file_size_mb:.2f}MB")
        
        # # 检查文件大小
        # if file_size_mb > 100:  # 如果文件大于100MB
        #     logger.error(f"文件过大: {file_size_mb:.2f}MB > 100MB")
        #     raise HTTPException(status_code=400, detail="音频文件过大，请确保文件小于100MB")
        
        # 使用 faster-whisper 进行转录
        logger.info("开始转录音频...")
        
        try:
            with timeout(PROCESSING_TIMEOUT):
                logger.info("开始模型推理...")
                segments, info = model.transcribe(
                    file_path,
                    beam_size=5,  # 降低 beam size 以提高速度
                    vad_filter=True,
                    vad_parameters=dict(
                        min_silence_duration_ms=1000,
                        speech_pad_ms=200
                    ),
                    condition_on_previous_text=True,
                    no_speech_threshold=0.6,
                    compression_ratio_threshold=2.4,
                    log_prob_threshold=-1.0,
                    initial_prompt="This is a speech or conversation that may contain numbers, dates, and years.",
                )
                logger.info("模型推理完成")
        except TimeoutError as e:
            logger.error(f"转录处理超时: {str(e)}")
            raise HTTPException(status_code=408, detail="转录处理超时，请尝试使用较短的音频文件")
        
        # 将字幕段转换为列表并合并断句
        logger.info("正在处理转录结果...")
        subtitles = []
        current_text = ""
        current_start = None
        current_end = None
        
        # 使用 tqdm 显示进度
        segments_list = list(segments)
        logger.info(f"开始处理 {len(segments_list)} 个音频段")
        
        for segment in tqdm(segments_list, desc="处理字幕段"):
            text = segment.text.strip()
            if not text:
                continue
                
            # 如果是新的句子开始
            if not current_text:
                current_text = text
                current_start = segment.start
                current_end = segment.end
            else:
                # 如果当前文本以标点符号结束，保存当前句子
                if current_text[-1] in ['.', '!', '?', '。', '！', '？']:
                    subtitles.append({
                        "text": current_text,
                        "start": current_start,
                        "end": current_end
                    })
                    current_text = text
                    current_start = segment.start
                    current_end = segment.end
                else:
                    # 继续当前句子
                    current_text += " " + text
                    current_end = segment.end
        
        # 添加最后一个句子
        if current_text:
            subtitles.append({
                "text": current_text,
                "start": current_start,
                "end": current_end
            })
        
        # 计算处理时间
        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()
        
        logger.info(f"转录完成:")
        logger.info(f"- 处理时间: {processing_time:.2f}秒")
        logger.info(f"- 生成字幕数: {len(subtitles)}")
        logger.info(f"- 音频时长: {info.duration:.2f}秒")
        logger.info(f"- 检测到的语言: {info.language} (置信度: {info.language_probability:.2f})")
        
        # 清理临时文件
        try:
            os.remove(file_path)
            logger.info(f"临时文件已清理: {saved_filename}")
        except Exception as e:
            logger.warning(f"清理临时文件失败: {str(e)}")
        
        return {
            "subtitles": subtitles,
            "saved_file": saved_filename,
            "processing_time": processing_time,
            "audio_duration": info.duration,
            "language": info.language,
            "language_probability": info.language_probability
        }
        
    except Exception as e:
        logger.error(f"处理失败: {str(e)}")
        # 确保清理临时文件
        try:
            if 'file_path' in locals():
                os.remove(file_path)
        except:
            pass
        raise HTTPException(status_code=500, detail=f"转录处理失败: {str(e)}")

if __name__ == "__main__":
    logger.info("启动 STT 服务器...")
    uvicorn.run(app, host="0.0.0.0", port=8001)