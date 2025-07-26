import os
import io
import time
import json
import torch
import torchaudio
import logging
import soundfile as sf
import re
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from typing import List, Generator, Optional
import platform
from pathlib import Path
from datetime import datetime

from indextts.infer import IndexTTS

# 配置日志
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("indextts-api")

# 创建FastAPI应用
app = FastAPI()

# 定义请求模型
class TextToSpeechRequest(BaseModel):
    text: str
    prompt_speech_path: Optional[str] = None
    speaker: Optional[str] = None
    temperature: float = 0.8
    top_k: int = 30
    top_p: float = 0.8
    seed: int = 421
    max_text_tokens_per_sentence: int = 100
    sentences_bucket_max_size: int = 4
    max_mel_tokens: int = 600
    num_beams: int = 3
    length_penalty: float = 0.0
    repetition_penalty: float = 10.0

# 新增流式处理请求模型
class StreamTTSRequest(BaseModel):
    text: str
    prompt_speech_path: Optional[str] = None
    speaker: Optional[str] = None
    temperature: float = 0.8
    top_k: int = 30
    top_p: float = 0.8
    seed: int = 421
    max_text_tokens_per_sentence: int = 100
    sentences_bucket_max_size: int = 4
    max_mel_tokens: int = 600
    num_beams: int = 3
    length_penalty: float = 0.0
    repetition_penalty: float = 10.0
    max_segment_length: int = 100  # 最大分段长度

# 初始化模型（全局变量，避免重复加载）
class IndexTTSModel:
    def __init__(self, model_dir='checkpoints', device=None):
        # 确定设备
        if device is not None:
            self.device = device
        elif platform.system() == "Darwin" and torch.backends.mps.is_available():
            # macOS with MPS support (Apple Silicon)
            self.device = torch.device("mps")
            logger.info(f"Using MPS device: {self.device}")
        elif torch.cuda.is_available():
            # System with CUDA support
            self.device = torch.device("cuda:0")
            logger.info(f"Using CUDA device: {self.device}")
        else:
            # Fall back to CPU
            self.device = torch.device("cpu")
            logger.info("GPU acceleration not available, using CPU")
        
        self.model_dir = model_dir
        
        # 初始化IndexTTS模型
        logger.info(f"Initializing IndexTTS model from {model_dir}")
        self.tts_model = IndexTTS(
            cfg_path=os.path.join(model_dir, "config.yaml"),
            model_dir=model_dir,
            is_fp16=True,
            device=str(self.device),
            use_cuda_kernel=True
        )
        logger.info("IndexTTS model initialized")
        
        # 获取采样率
        self.sampling_rate = 24000  # IndexTTS固定采样率
        logger.info(f"Model sample rate: {self.sampling_rate}")
        
        # 确保输出目录存在
        os.makedirs("outputs", exist_ok=True)
        
        # 音频提示文件目录
        self.prompt_dir = "assets/speakers"
        if not os.path.exists(self.prompt_dir):
            os.makedirs(self.prompt_dir, exist_ok=True)
            logger.info(f"Created prompt directory: {self.prompt_dir}")
        
    def generate_speech(self, text, prompt_speech_path=None, speaker=None,
                       temperature=0.8, top_k=30, top_p=0.8, seed=421,
                       max_text_tokens_per_sentence=100, sentences_bucket_max_size=4,
                       max_mel_tokens=600, num_beams=3, length_penalty=0.0,
                       repetition_penalty=10.0):
        """生成语音"""
        logger.info(f"Generating speech for text: {text[:50]}...")
        
        # 设置随机种子
        torch.manual_seed(seed)
        
        try:
            # 处理speaker参数(优先使用prompt_speech_path)
            if speaker and not prompt_speech_path:
                prompt_speech_path = self.find_prompt_by_speaker(speaker)
                logger.info(f"Using speaker audio prompt: {prompt_speech_path}")
            
            # 验证参数
            if not prompt_speech_path:
                raise ValueError("必须提供prompt_speech_path或speaker参数")
            
            # 处理音频提示路径
            if prompt_speech_path:
                # 统一处理路径
                if not os.path.isabs(prompt_speech_path):
                    # 提取纯文件名（移除可能的路径前缀）
                    filename = os.path.basename(prompt_speech_path)
                    prompt_speech_path = os.path.join(self.prompt_dir, filename)
                
                # 检查文件是否存在
                if not os.path.exists(prompt_speech_path):
                    logger.warning(f"Prompt audio file not found: {prompt_speech_path}")
                    raise ValueError(f"提示音频文件不存在: {prompt_speech_path}")
            
            # 分割文本
            segments = split_text(text, max_length=100)  # 使用较小的max_length以确保安全
            logger.info(f"Text split into {len(segments)} segments")
            
            # 存储所有生成的音频段
            all_wav_data = []
            sample_rate = None
            
            # 为每个段落生成语音
            for i, segment in enumerate(segments):
                logger.info(f"Generating segment {i+1}/{len(segments)}: {segment[:30]}...")
                segment_seed = seed + i  # 为每段使用不同的种子
                
                with torch.no_grad():
                    wav = self.tts_model.infer_fast(
                        audio_prompt=prompt_speech_path,
                        text=segment,
                        output_path=None,
                        verbose=False,
                        max_text_tokens_per_sentence=max_text_tokens_per_sentence,
                        sentences_bucket_max_size=sentences_bucket_max_size,
                        temperature=temperature,
                        top_k=top_k,
                        top_p=top_p,
                        num_beams=num_beams,
                        length_penalty=length_penalty,
                        repetition_penalty=repetition_penalty,
                        max_mel_tokens=max_mel_tokens
                    )
                
                # 获取采样率和音频数据
                segment_sample_rate, segment_wav_data = wav
                if sample_rate is None:
                    sample_rate = segment_sample_rate
                
                # 确保音频数据是torch张量
                if isinstance(segment_wav_data, torch.Tensor):
                    all_wav_data.append(segment_wav_data)
                else:
                    # 如果是numpy数组，转换为torch张量
                    all_wav_data.append(torch.from_numpy(segment_wav_data))
            
            # 合并所有音频段
            if len(all_wav_data) > 1:
                # 使用torch.cat合并音频数据
                combined_wav = torch.cat(all_wav_data, dim=0)
                logger.info(f"Combined {len(all_wav_data)} audio segments")
            else:
                combined_wav = all_wav_data[0]
            
            logger.info(f"Generated audio of length: {len(combined_wav)/sample_rate:.2f} seconds")
            return combined_wav, sample_rate
        
        except Exception as e:
            logger.error(f"Error generating speech: {e}", exc_info=True)
            raise ValueError(f"Failed to generate speech: {str(e)}")
    
    def find_prompt_by_speaker(self, speaker_name):
        """查找音频提示文件"""
        if not os.path.exists(self.prompt_dir) or not os.listdir(self.prompt_dir):
            raise FileNotFoundError(f"提示音频目录不存在或为空: {self.prompt_dir}")
        
        # 按优先级搜索：精确匹配 > 部分匹配 > 任意音频文件
        # 1. 精确匹配
        for ext in ['.wav', '.mp3']:
            exact_match = os.path.join(self.prompt_dir, f"{speaker_name}{ext}")
            if os.path.exists(exact_match):
                logger.info(f"找到精确匹配的提示音频: {exact_match}")
                return exact_match
        
        # 2. 部分匹配 - 查找文件名包含speaker_name的文件
        partial_matches = []
        for file in os.listdir(self.prompt_dir):
            if file.endswith(('.wav', '.mp3')) and speaker_name.lower() in file.lower():
                partial_matches.append(file)
        
        if partial_matches:
            # 使用第一个匹配项
            matched_file = partial_matches[0]
            prompt_path = os.path.join(self.prompt_dir, matched_file)
            logger.warning(f"未找到精确匹配'{speaker_name}'的音频，使用部分匹配: {matched_file}")
            return prompt_path
        
        # 3. 任意音频文件
        audio_files = [f for f in os.listdir(self.prompt_dir) if f.endswith(('.wav', '.mp3'))]
        if audio_files:
            # 按字母顺序排序，保证结果一致性
            audio_files.sort()
            prompt_path = os.path.join(self.prompt_dir, audio_files[0])
            logger.warning(f"未找到与'{speaker_name}'相关的音频，使用默认音频: {audio_files[0]}")
            return prompt_path
        
        # 如果没有找到任何音频文件
        raise FileNotFoundError(f"未找到任何可用的提示音频文件，请检查{self.prompt_dir}目录")
    
    def split_text_by_punctuation(self, text):
        """按标点符号分割文本"""
        punctuation = ["!", "?", ".", ";", "！", "？", "。", "；"]
        pattern = r"(?<=[{0}])\s*".format("".join(punctuation))
        sentences = [i for i in re.split(pattern, text) if i.strip() != ""]
        return sentences
    
    def generate_speech_segment(self, text_segment, prompt_speech_path=None, speaker=None,
                              temperature=0.8, top_k=30, top_p=0.8, seed=421,
                              max_text_tokens_per_sentence=100, sentences_bucket_max_size=4,
                              max_mel_tokens=600, num_beams=3, length_penalty=0.0,
                              repetition_penalty=10.0):
        """为流式API生成单个段落的音频"""
        logger.debug(f"Generating segment: {text_segment[:30]}...")
        
        try:
            # 生成语音
            wav_data, sample_rate = self.generate_speech(
                text=text_segment,
                prompt_speech_path=prompt_speech_path,
                speaker=speaker,
                temperature=temperature,
                top_k=top_k,
                top_p=top_p,
                seed=seed,
                max_text_tokens_per_sentence=max_text_tokens_per_sentence,
                sentences_bucket_max_size=sentences_bucket_max_size,
                max_mel_tokens=max_mel_tokens,
                num_beams=num_beams,
                length_penalty=length_penalty,
                repetition_penalty=repetition_penalty
            )
            
            # 创建包含音频数据和采样率的字典
            audio_data = {
                "text": text_segment,
                "audio": wav_data.tolist(),
                "sample_rate": sample_rate
            }
            
            return audio_data
        except Exception as e:
            logger.error(f"Error generating segment: {e}", exc_info=True)
            raise

# 初始化模型
logger.info("Initializing IndexTTS model...")
model = IndexTTSModel(model_dir="checkpoints")
logger.info("Model initialization complete")

# 文本分段函数
def split_text(text: str, max_length: int = 100) -> List[str]:
    # 如果文本长度小于max_length，直接返回
    if len(text) <= max_length:
        return [text]
    
    # 定义分隔符优先级（从高到低）
    separators = ['. ', '! ', '? ', '; ', ', ', ' ', '。', '！', '？', '；', '，']
    
    segments = []
    while len(text) > max_length:
        # 尝试在max_length位置附近找到合适的分割点
        segment_end = -1
        
        # 按优先级尝试不同的分隔符
        for sep in separators:
            # 在允许范围内寻找最后一个分隔符
            pos = text[:max_length].rfind(sep)
            if pos > 0:  # 找到了分隔符
                segment_end = pos + len(sep)
                break
        
        # 如果没找到任何分隔符，就在词边界处分割
        if segment_end == -1:
            # 寻找最后一个空格
            pos = text[:max_length].rfind(' ')
            if pos > 0:
                segment_end = pos + 1
            else:
                # 实在没有合适位置，就在max_length处强制分割
                segment_end = max_length
        
        # 添加分段并更新剩余文本
        segments.append(text[:segment_end].strip())
        text = text[segment_end:].strip()
    
    # 添加最后一段
    if text:
        segments.append(text)
    
    return segments

@app.post("/tts")
async def generate_speech(request: Request):
    try:
        # 记录请求内容
        body = await request.json()
        logger.info(f"Received /tts request: {body}")
        
        # 解析请求
        try:
            req = TextToSpeechRequest(**body)
            logger.debug(f"Parsed request: {req}")
        except Exception as e:
            logger.error(f"Request parsing error: {e}")
            raise HTTPException(status_code=422, detail=f"Invalid request format: {str(e)}")
        
        # 验证请求参数
        if not req.prompt_speech_path and not req.speaker:
            error_message = "必须提供prompt_speech_path或speaker参数"
            logger.error(f"Parameter validation error: {error_message}")
            raise HTTPException(status_code=400, detail=error_message)
        
        # 生成语音
        try:
            wav_data, sample_rate = model.generate_speech(
                text=req.text,
                prompt_speech_path=req.prompt_speech_path,
                speaker=req.speaker,
                temperature=req.temperature,
                top_k=req.top_k,
                top_p=req.top_p,
                seed=req.seed,
                max_text_tokens_per_sentence=req.max_text_tokens_per_sentence,
                sentences_bucket_max_size=req.sentences_bucket_max_size,
                max_mel_tokens=req.max_mel_tokens,
                num_beams=req.num_beams,
                length_penalty=req.length_penalty,
                repetition_penalty=req.repetition_penalty
            )
        except ValueError as e:
            logger.error(f"Speech generation error: {e}")
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Speech generation error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error generating speech: {str(e)}")
        
        # 将音频数据写入内存缓冲区
        buffer = io.BytesIO()
        sf.write(buffer, wav_data, sample_rate, format="wav")
        buffer.seek(0)
        
        # 返回音频数据
        logger.info("Successfully generated speech, returning response")
        return Response(
            content=buffer.read(),
            media_type="audio/wav"
        )
    
    except HTTPException:
        # 重新抛出HTTP异常
        raise
    except Exception as e:
        # 打印详细错误信息
        logger.error(f"Unexpected error in /tts endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tts_stream")
async def stream_tts(request: Request):
    try:
        # 记录请求内容
        body = await request.json()
        logger.info(f"Received /tts_stream request: {body}")
        
        # 解析请求
        try:
            req = StreamTTSRequest(**body)
            logger.debug(f"Parsed stream request: {req}")
        except Exception as e:
            logger.error(f"Stream request parsing error: {e}")
            raise HTTPException(status_code=422, detail=f"Invalid request format: {str(e)}")
        
        # 验证请求参数
        if not req.prompt_speech_path and not req.speaker:
            error_message = "必须提供prompt_speech_path或speaker参数"
            logger.error(f"Parameter validation error: {error_message}")
            raise HTTPException(status_code=400, detail=error_message)
        
        # 分割文本
        segments = split_text(req.text, req.max_segment_length)
        logger.info(f"Text split into {len(segments)} segments for streaming")
        
        async def generate_stream():
            for i, segment in enumerate(segments):
                logger.debug(f"Generating segment {i+1}/{len(segments)}")
                # 生成此段的音频
                segment_seed = req.seed + i  # 为每段使用不同的种子以增加变化
                
                try:
                    audio_data = model.generate_speech_segment(
                        text_segment=segment, 
                        prompt_speech_path=req.prompt_speech_path,
                        speaker=req.speaker,
                        temperature=req.temperature,
                        top_k=req.top_k,
                        top_p=req.top_p,
                        seed=segment_seed,
                        max_text_tokens_per_sentence=req.max_text_tokens_per_sentence,
                        sentences_bucket_max_size=req.sentences_bucket_max_size,
                        max_mel_tokens=req.max_mel_tokens,
                        num_beams=req.num_beams,
                        length_penalty=req.length_penalty,
                        repetition_penalty=req.repetition_penalty
                    )
                    
                    # 添加段落索引信息
                    audio_data["segment_index"] = i
                    audio_data["total_segments"] = len(segments)
                    
                    # 将字典转换为JSON并发送
                    yield json.dumps(audio_data) + "\n"
                except Exception as e:
                    logger.error(f"Error generating segment {i}: {e}", exc_info=True)
                    error_data = {
                        "error": str(e),
                        "segment_index": i,
                        "total_segments": len(segments),
                        "text": segment
                    }
                    yield json.dumps(error_data) + "\n"
        
        # 使用StreamingResponse返回流式响应
        logger.info("Starting streaming response")
        return StreamingResponse(
            generate_stream(),
            media_type="application/x-ndjson"  # 使用换行分隔的JSON格式
        )
    
    except HTTPException:
        # 重新抛出HTTP异常
        raise
    except Exception as e:
        # 打印详细错误信息
        logger.error(f"Unexpected error in /tts_stream endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload_audio")
async def upload_audio(file: UploadFile = File(...)):
    """
    上传音频文件到 assets 目录
    
    参数:
        file: 上传的音频文件（支持 wav 和 mp3 格式）
        
    返回:
        上传结果信息
    """
    try:
        # 检查文件扩展名
        if not file.filename.lower().endswith(('.wav', '.mp3')):
            raise HTTPException(status_code=400, detail="只支持 WAV 和 MP3 格式的音频文件")
        
        # 确保 assets 目录存在
        os.makedirs(model.prompt_dir, exist_ok=True)
        
        # 构建保存路径
        save_path = os.path.join(model.prompt_dir, file.filename)
        
        # 保存文件
        content = await file.read()
        with open(save_path, "wb") as f:
            f.write(content)
        
        logger.info(f"成功保存音频文件: {save_path}")
        
        return {
            "status": "success",
            "message": "音频文件上传成功",
            "file_path": save_path
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"上传音频文件失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"上传音频文件失败: {str(e)}")

# 如果直接运行此文件
if __name__ == "__main__":
    import uvicorn
    logger.info("Starting IndexTTS API server")
    uvicorn.run(app, host="0.0.0.0", port=8002)

# 示例请求:
# curl -X POST "http://localhost:8002/tts" \
#      -H "Content-Type: application/json" \
#      -d '{"text": "你好，这是一个测试。", "prompt_speech_path": "prompt.wav"}'

# curl -X POST "http://localhost:8002/tts" \
#      -H "Content-Type: application/json" \
#      -d '{"text": "你好，这是一个测试。", "speaker": "Scarlett"}' \
#      --output output.wav 