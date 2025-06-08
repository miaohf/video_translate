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