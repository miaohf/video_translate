import os
import json
import hashlib
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_file_hash(text: str, length: int = 20) -> str:
    """
    生成文本的短哈希值
    
    参数:
        text: 要哈希的文本
        length: 哈希值长度
        
    返回:
        哈希值字符串
    """
    return hashlib.md5(text.encode()).hexdigest()[:length]

def format_time(seconds: float) -> str:
    """
    将秒数格式化为SRT时间格式
    
    参数:
        seconds: 秒数
        
    返回:
        格式化的时间字符串 (HH:MM:SS,mmm)
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60
    milliseconds = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{int(seconds):02d},{milliseconds:03d}"