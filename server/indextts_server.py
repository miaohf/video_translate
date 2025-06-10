import os
import io
import re
import time
import json
import torch
import torchaudio
import sentencepiece as spm
import logging
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from omegaconf import OmegaConf
from torch.nn.utils.rnn import pad_sequence
from typing import List, Generator, Optional
import tempfile

from indextts.BigVGAN.models import BigVGAN as Generator
from indextts.gpt.model import UnifiedVoice
from indextts.utils.checkpoint import load_checkpoint
from indextts.utils.feature_extractors import MelSpectrogramFeatures
from indextts.utils.common import tokenize_by_CJK_char
from indextts.vqvae.xtts_dvae import DiscreteVAE
from indextts.utils.front import TextNormalizer

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
    prompt_text: Optional[str] = None
    speaker: Optional[str] = None  # 兼容indextts_api的speaker参数
    gender: Optional[str] = None
    pitch: Optional[str] = None
    speed: Optional[str] = None
    temperature: float = 0.8
    top_k: int = 50
    top_p: float = 0.95
    seed: int = 421

# 新增流式处理请求模型
class StreamTTSRequest(BaseModel):
    text: str
    prompt_speech_path: Optional[str] = None
    prompt_text: Optional[str] = None
    speaker: Optional[str] = None  # 兼容indextts_api的speaker参数
    gender: Optional[str] = None
    pitch: Optional[str] = None
    speed: Optional[str] = None
    temperature: float = 0.8
    top_k: int = 50
    top_p: float = 0.95
    seed: int = 421
    max_segment_length: int = 100  # 最大分段长度

# 初始化模型（全局变量，避免重复加载）
class IndexTTSModel:
    def __init__(self, cfg_path='checkpoints/config.yaml', model_dir='checkpoints', is_fp16=True, device=None):
        if device is not None:
            self.device = device
            self.is_fp16 = False if device == 'cpu' else is_fp16
        elif torch.cuda.is_available():
            self.device = 'cuda:0'
            self.is_fp16 = is_fp16
        elif torch.mps.is_available():
            self.device = 'mps'
            self.is_fp16 = is_fp16
        else:
            self.device = 'cpu'
            self.is_fp16 = False
            logger.info(">> Be patient, it may take a while to run in CPU mode.")

        self.cfg = OmegaConf.load(cfg_path)
        self.model_dir = model_dir
        self.dtype = torch.float16 if self.is_fp16 else None
        self.stop_mel_token = self.cfg.gpt.stop_mel_token

        # 加载模型组件
        self._load_dvae()
        self._load_gpt()
        self._load_bigvgan()
        
        # 加载文本处理工具
        self.bpe_path = os.path.join(self.model_dir, self.cfg.dataset['bpe_model'])
        self.normalizer = TextNormalizer()
        self.normalizer.load()
        logger.info(">> TextNormalizer loaded")
        
        # 初始化分词器
        self.tokenizer = spm.SentencePieceProcessor()
        self.tokenizer.load(self.bpe_path)
        
        # 预定义参数
        self.sampling_rate = 24000
        self.max_mel_tokens = 600
        self.autoregressive_batch_size = 1
        self.length_penalty = 0.0
        self.num_beams = 3
        
        # 音频提示文件目录
        self.prompt_dir = "assets/speakers"
        if not os.path.exists(self.prompt_dir):
            os.makedirs(self.prompt_dir, exist_ok=True)
            logger.info(f"Created prompt directory: {self.prompt_dir}")
        
        # 存储处理过的音频提示缓存
        self.prompt_cache = {}
        
        logger.info(f"Model initialized with device: {self.device}, fp16: {self.is_fp16}")
    
    def _load_dvae(self):
        self.dvae = DiscreteVAE(**self.cfg.vqvae)
        self.dvae_path = os.path.join(self.model_dir, self.cfg.dvae_checkpoint)
        load_checkpoint(self.dvae, self.dvae_path)
        self.dvae = self.dvae.to(self.device)
        if self.is_fp16:
            self.dvae.eval().half()
        else:
            self.dvae.eval()
        logger.info(">> vqvae weights restored from: " + self.dvae_path)
    
    def _load_gpt(self):
        self.gpt = UnifiedVoice(**self.cfg.gpt)
        self.gpt_path = os.path.join(self.model_dir, self.cfg.gpt_checkpoint)
        load_checkpoint(self.gpt, self.gpt_path)
        self.gpt = self.gpt.to(self.device)
        if self.is_fp16:
            self.gpt.eval().half()
        else:
            self.gpt.eval()
        logger.info(">> GPT weights restored from: " + self.gpt_path)
        if self.is_fp16:
            self.gpt.post_init_gpt2_config(use_deepspeed=True, kv_cache=True, half=True)
        else:
            self.gpt.post_init_gpt2_config(use_deepspeed=False, kv_cache=False, half=False)
    
    def _load_bigvgan(self):
        self.bigvgan = Generator(self.cfg.bigvgan)
        self.bigvgan_path = os.path.join(self.model_dir, self.cfg.bigvgan_checkpoint)
        vocoder_dict = torch.load(self.bigvgan_path, map_location='cpu')
        self.bigvgan.load_state_dict(vocoder_dict['generator'])
        self.bigvgan = self.bigvgan.to(self.device)
        self.bigvgan.eval()
        logger.info(">> bigvgan weights restored from: " + self.bigvgan_path)
    
    def preprocess_text(self, text):
        return self.normalizer.normalize(text)
    
    def remove_long_silence(self, codes: torch.Tensor, silent_token=52, max_consecutive=30):
        code_lens = []
        codes_list = []
        device = codes.device
        dtype = codes.dtype
        isfix = False
        for i in range(0, codes.shape[0]):
            code = codes[i]
            if self.stop_mel_token not in code:
                code_lens.append(len(code))
                len_ = len(code)
            else:
                len_ = (code == self.stop_mel_token).nonzero(as_tuple=False)[0] + 1
                len_ = len_ - 2

            count = torch.sum(code == silent_token).item()
            if count > max_consecutive:
                code = code.cpu().tolist()
                ncode = []
                n = 0
                for k in range(0, len_):
                    if code[k] != silent_token:
                        ncode.append(code[k])
                        n = 0
                    elif code[k] == silent_token and n < 10:
                        ncode.append(code[k])
                        n += 1
                len_ = len(ncode)
                ncode = torch.LongTensor(ncode)
                codes_list.append(ncode.to(device, dtype=dtype))
                isfix = True
            else:
                codes_list.append(codes[i])
            code_lens.append(len_)

        codes = pad_sequence(codes_list, batch_first=True) if isfix else codes[:, :-2]
        code_lens = torch.LongTensor(code_lens).to(device, dtype=dtype)
        return codes, code_lens
    
    def process_audio_prompt(self, speaker_name):
        """处理音频提示文件，兼容indextts_api的speaker参数"""
        # 如果已经处理过，直接返回缓存
        if speaker_name in self.prompt_cache:
            logger.info(f"Using cached audio prompt for speaker: {speaker_name}")
            return self.prompt_cache[speaker_name]
        
        # 确保提示目录存在
        if not os.path.exists(self.prompt_dir):
            os.makedirs(self.prompt_dir, exist_ok=True)
            logger.info(f"Created prompt directory: {self.prompt_dir}")
        
        # 按优先级搜索：精确匹配 > 部分匹配 > 任意音频文件
        # 1. 精确匹配
        for ext in ['.wav', '.mp3']:
            exact_match = os.path.join(self.prompt_dir, f"{speaker_name}{ext}")
            if os.path.exists(exact_match):
                logger.info(f"找到精确匹配的提示音频: {exact_match}")
                prompt_path = exact_match
                break
        else:
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
            else:
                # 3. 任意音频文件
                audio_files = [f for f in os.listdir(self.prompt_dir) if f.endswith(('.wav', '.mp3'))]
                if audio_files:
                    # 按字母顺序排序，保证结果一致性
                    audio_files.sort()
                    prompt_path = os.path.join(self.prompt_dir, audio_files[0])
                    logger.warning(f"未找到与'{speaker_name}'相关的音频，使用默认音频: {audio_files[0]}")
                else:
                    raise FileNotFoundError(f"未找到任何可用的提示音频文件，请检查{self.prompt_dir}目录")
        
        # 记录使用的提示文件
        logger.info(f"Using audio prompt: {prompt_path}")
        
        # 加载和处理音频
        try:
            audio, sr = torchaudio.load(prompt_path)
            audio = torch.mean(audio, dim=0, keepdim=True)
            if audio.shape[0] > 1:
                audio = audio[0].unsqueeze(0)
            
            # 调整音频长度，防止超出位置编码的最大长度
            max_samples = 5 * self.sampling_rate
            if audio.shape[1] > max_samples:
                logger.warning(f"Audio prompt too long ({audio.shape[1]/self.sampling_rate:.2f}s), trimming to 5s")
                audio = audio[:, :max_samples]
            
            # 重采样到目标采样率
            audio = torchaudio.transforms.Resample(sr, self.sampling_rate)(audio)
            
            # 提取mel特征
            cond_mel = MelSpectrogramFeatures()(audio).to(self.device)
            logger.info(f"Processed audio prompt shape: {cond_mel.shape}")
            
            # 缓存结果以备后用
            self.prompt_cache[speaker_name] = cond_mel
            
            return cond_mel
        except Exception as e:
            logger.error(f"Error processing audio file {prompt_path}: {e}", exc_info=True)
            raise ValueError(f"Failed to process audio file: {str(e)}")
    
    def split_text_by_punctuation(self, text):
        punctuation = ["!", "?", ".", ";", "！", "？", "。", "；"]
        pattern = r"(?<=[{0}])\s*".format("".join(punctuation))
        sentences = [i for i in re.split(pattern, text) if i.strip() != ""]
        return sentences
    
    def generate_speech(self, text, prompt_speech_path=None, prompt_text=None, 
                       speaker=None, gender=None, pitch=None, speed=None, 
                       temperature=0.8, top_k=50, top_p=0.95, seed=421):
        """生成语音"""
        logger.info(f"Generating speech for text: {text[:50]}...")
        
        # 设置随机种子
        torch.manual_seed(seed)
        
        try:
            # 处理speaker参数(优先使用prompt_speech_path)
            if speaker and not prompt_speech_path:
                auto_conditioning = self.process_audio_prompt(speaker)
                logger.info(f"Using speaker audio prompt: {speaker}")
            elif prompt_speech_path:
                # 统一处理路径
                if not os.path.isabs(prompt_speech_path):
                    # 提取纯文件名（移除可能的路径前缀）
                    filename = os.path.basename(prompt_speech_path)
                    prompt_speech_path = os.path.join(self.prompt_dir, filename)
                
                # 检查文件是否存在
                if not os.path.exists(prompt_speech_path):
                    logger.warning(f"Prompt audio file not found: {prompt_speech_path}")
                    raise ValueError(f"提示音频文件不存在: {prompt_speech_path}")
                
                # 加载音频提示
                audio, sr = torchaudio.load(prompt_speech_path)
                audio = torch.mean(audio, dim=0, keepdim=True)
                if audio.shape[0] > 1:
                    audio = audio[0].unsqueeze(0)
                
                # 调整音频长度
                max_samples = 5 * self.sampling_rate
                if audio.shape[1] > max_samples:
                    logger.warning(f"Audio prompt too long ({audio.shape[1]/self.sampling_rate:.2f}s), trimming to 5s")
                    audio = audio[:, :max_samples]
                
                # 重采样到目标采样率
                audio = torchaudio.transforms.Resample(sr, self.sampling_rate)(audio)
                
                # 提取mel特征
                auto_conditioning = MelSpectrogramFeatures()(audio).to(self.device)
            else:
                raise ValueError("必须提供speaker参数或prompt_speech_path参数中的至少一个")
            
            # 分割文本为句子
            sentences = self.split_text_by_punctuation(text)
            logger.info(f"Text split into {len(sentences)} sentences")
            
            wavs = []
            
            for idx, sent in enumerate(sentences):
                logger.debug(f"Processing sentence {idx+1}/{len(sentences)}: {sent[:30]}...")
                # 处理文本
                cleand_text = tokenize_by_CJK_char(sent)
                text_tokens = torch.IntTensor(self.tokenizer.encode(cleand_text)).unsqueeze(0).to(self.device)
                
                try:
                    with torch.no_grad():
                        with torch.amp.autocast(self.device, enabled=self.dtype is not None, dtype=self.dtype):
                            # 生成mel编码
                            logger.debug(f"Starting inference_speech for text: {sent[:30]}...")
                            codes = self.gpt.inference_speech(
                                auto_conditioning, 
                                text_tokens,
                                cond_mel_lengths=torch.tensor([auto_conditioning.shape[-1]], device=text_tokens.device),
                                do_sample=True,
                                top_p=top_p,
                                top_k=top_k,
                                temperature=temperature,
                                num_return_sequences=self.autoregressive_batch_size,
                                length_penalty=self.length_penalty,
                                num_beams=self.num_beams,
                                repetition_penalty=10.0,
                                max_generate_length=self.max_mel_tokens
                            )
                            logger.debug(f"Finished inference_speech, codes shape: {codes.shape}")
                            
                            # 处理生成的编码
                            code_lens = torch.tensor([codes.shape[-1]], device=codes.device, dtype=codes.dtype)
                            codes, code_lens = self.remove_long_silence(codes, silent_token=52, max_consecutive=30)
                            
                            # 生成音频波形
                            logger.debug(f"Starting waveform generation...")
                            with torch.amp.autocast(self.device, enabled=self.dtype is not None, dtype=self.dtype):
                                latent = self.gpt(
                                    auto_conditioning, 
                                    text_tokens,
                                    torch.tensor([text_tokens.shape[-1]], device=text_tokens.device), 
                                    codes,
                                    code_lens*self.gpt.mel_length_compression,
                                    cond_mel_lengths=torch.tensor([auto_conditioning.shape[-1]], device=text_tokens.device),
                                    return_latent=True, 
                                    clip_inputs=False
                                )
                                latent = latent.transpose(1, 2)
                                wav, _ = self.bigvgan(latent.transpose(1, 2), auto_conditioning.transpose(1, 2))
                                wav = wav.squeeze(1).cpu()
                            logger.debug(f"Finished waveform generation, wav shape: {wav.shape}")
                            
                            # 标准化波形
                            wav = 32767 * wav
                            torch.clip(wav, -32767.0, 32767.0)
                            wavs.append(wav)
                except Exception as e:
                    logger.error(f"Error processing sentence {idx+1}: {e}", exc_info=True)
                    # 如果处理单个句子失败，继续处理下一个
                    continue
            
            if not wavs:
                raise ValueError("Failed to generate any audio")
                
            # 合并所有音频片段
            wav = torch.cat(wavs, dim=1)
            logger.info(f"Generated audio of length: {wav.shape[1]/self.sampling_rate:.2f} seconds")
            return wav, self.sampling_rate
            
        except Exception as e:
            logger.error(f"Error generating speech: {e}", exc_info=True)
            raise ValueError(f"Failed to generate speech: {str(e)}")

    def generate_speech_segment(self, text_segment, prompt_speech_path=None, prompt_text=None,
                               speaker=None, gender=None, pitch=None, speed=None, 
                               temperature=0.8, top_k=50, top_p=0.95, seed=421):
        """为流式API生成单个段落的音频"""
        logger.debug(f"Generating segment: {text_segment[:30]}...")
        
        try:
            # 生成语音
            wav, sample_rate = self.generate_speech(
                text=text_segment,
                prompt_speech_path=prompt_speech_path,
                prompt_text=prompt_text,
                speaker=speaker,
                gender=gender,
                pitch=pitch,
                speed=speed,
                temperature=temperature,
                top_k=top_k,
                top_p=top_p,
                seed=seed
            )
            
            # 将张量转换为列表
            if isinstance(wav, torch.Tensor):
                audio_array = wav.cpu().numpy().tolist()
            else:
                # 已经是numpy数组
                audio_array = wav.tolist()
            
            # 创建包含音频数据和采样率的字典
            audio_data = {
                "text": text_segment,
                "audio": audio_array,
                "sample_rate": sample_rate
            }
            
            return audio_data
        except Exception as e:
            logger.error(f"Error generating segment: {e}", exc_info=True)
            raise

# 初始化模型
logger.info("Initializing IndexTTS model...")
model = IndexTTSModel(cfg_path="checkpoints/config.yaml", model_dir="checkpoints", is_fp16=True)
logger.info("Model initialization complete")

# 确保输出目录存在
os.makedirs("outputs", exist_ok=True)

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
        
        # 生成语音
        try:
            wav, sample_rate = model.generate_speech(
                text=req.text,
                prompt_speech_path=req.prompt_speech_path,
                prompt_text=req.prompt_text,
                speaker=req.speaker,
                gender=req.gender,
                pitch=req.pitch,
                speed=req.speed,
                temperature=req.temperature,
                top_k=req.top_k,
                top_p=req.top_p,
                seed=req.seed
            )
        except Exception as e:
            logger.error(f"Speech generation error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error generating speech: {str(e)}")
        
        # 将音频数据写入内存缓冲区
        buffer = io.BytesIO()
        torchaudio.save(buffer, wav.type(torch.int16), sample_rate, format="wav")
        buffer.seek(0)
        
        # 返回音频数据
        logger.info("Successfully generated speech, returning response")
        return Response(
            content=buffer.read(),
            media_type="audio/wav"
        )
    
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
        
        # 预处理文本
        normalized_text = model.preprocess_text(req.text)
        
        # 分割文本
        segments = split_text(normalized_text, req.max_segment_length)
        logger.info(f"Text split into {len(segments)} segments for streaming")
        
        async def generate_stream():
            for i, segment in enumerate(segments):
                logger.debug(f"Generating segment {i+1}/{len(segments)}")
                # 生成此段的音频
                segment_seed = req.seed + i  # 为每段使用不同的种子以增加变化
                
                try:
                    audio_data = model.generate_speech_segment(
                        text_segment=segment, 
                        speaker=req.speaker,
                        top_p=0.8,  # 使用默认值
                        top_k=30,
                        temperature=1.0,
                        repetition_penalty=10.0,
                        seed=segment_seed,
                        language=req.language
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
    
    except Exception as e:
        # 打印详细错误信息
        logger.error(f"Unexpected error in /tts_stream endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload_audio")
async def upload_audio(file: UploadFile = File(...)):
    """
    上传音频文件到 assets/speakers 目录
    
    参数:
        file: 上传的音频文件（支持 mp3 格式）
        
    返回:
        上传结果信息
    """
    try:
        # 检查文件扩展名
        if not file.filename.lower().endswith('.mp3'):
            raise HTTPException(status_code=400, detail="只支持 MP3 格式的音频文件")
        
        # 确保 assets/speakers 目录存在
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
    uvicorn.run(app, host="0.0.0.0", port=8000)


# curl -X POST "http://localhost:8001/generate_speech" \
#      -H "Content-Type: application/json" \
#      -d '{"text": "Hello, world!", "speaker": "Scarlett"}'


# curl -X POST "http://localhost:8001/generate_speech" \
#      -H "Content-Type: application/json" \
#      -d '{"text": "Hello, world!", "speaker": "Scarlett"}' \
#      --output output.wav

