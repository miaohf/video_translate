"""
配置管理模块
"""

import os
from typing import Optional
from pathlib import Path
import logging

# 尝试导入 python-dotenv
try:
    from dotenv import load_dotenv
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False

logger = logging.getLogger(__name__)

class Config:
    """配置管理类"""
    
    def __init__(self, env_file: Optional[str] = None):
        """
        初始化配置管理器
        
        Args:
            env_file: 环境变量文件路径，默认为 .env 或 config.env
        """
        self._load_env_file(env_file)
        self._setup_logging()
    
    def _load_env_file(self, env_file: Optional[str] = None):
        """加载环境变量文件"""
        if not DOTENV_AVAILABLE:
            logger.warning("python-dotenv 未安装，跳过环境变量文件加载")
            return
        
        # 寻找环境变量文件
        env_files = []
        if env_file:
            env_files.append(env_file)
        
        # 按优先级顺序检查文件
        for filename in ['.env', 'config.env', '.env.local']:
            if Path(filename).exists():
                env_files.append(filename)
        
        # 加载找到的第一个文件
        for file_path in env_files:
            if Path(file_path).exists():
                load_dotenv(file_path)
                logger.info(f"已加载环境变量文件: {file_path}")
                break
        else:
            logger.info("未找到环境变量文件，使用默认配置")
    
    def _setup_logging(self):
        """设置日志配置"""
        log_level = getattr(logging, self.log_level.upper())
        logging.basicConfig(
            level=log_level,
            format=self.log_format
        )
    
    def get(self, key: str, default: str = None) -> str:
        """获取配置项"""
        return os.getenv(key, default)
    
    def get_int(self, key: str, default: int = None) -> int:
        """获取整数配置项"""
        value = os.getenv(key)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            logger.warning(f"配置项 {key} 的值 '{value}' 不是有效整数，使用默认值 {default}")
            return default
    
    def get_float(self, key: str, default: float = None) -> float:
        """获取浮点数配置项"""
        value = os.getenv(key)
        if value is None:
            return default
        try:
            return float(value)
        except ValueError:
            logger.warning(f"配置项 {key} 的值 '{value}' 不是有效浮点数，使用默认值 {default}")
            return default
    
    def get_bool(self, key: str, default: bool = False) -> bool:
        """获取布尔配置项"""
        value = os.getenv(key)
        if value is None:
            return default
        return value.lower() in ('true', '1', 'yes', 'on')
    
    # API服务器配置
    @property
    def api_host(self) -> str:
        return self.get('API_HOST', '0.0.0.0')
    
    @property
    def api_port(self) -> int:
        return self.get_int('API_PORT', 8001)
    
    @property
    def api_workers(self) -> int:
        return self.get_int('API_WORKERS', 1)
    
    @property
    def api_base_url(self) -> str:
        return self.get('API_BASE_URL', f'http://localhost:{self.api_port}')
    
    # 翻译服务配置
    @property
    def stt_server_url(self) -> str:
        return self.get('STT_SERVER_URL', 'http://localhost:8001')
    
    @property
    def tts_server_url(self) -> str:
        return self.get('TTS_SERVER_URL', 'http://localhost:8002')
    
    # 任务配置
    @property
    def default_estimated_duration(self) -> int:
        return self.get_int('DEFAULT_ESTIMATED_DURATION', 1800)
    
    @property
    def task_check_interval(self) -> int:
        return self.get_int('TASK_CHECK_INTERVAL', 10)
    
    # 文件路径配置
    @property
    def temp_dir(self) -> str:
        return self.get('TEMP_DIR', 'temp')
    
    @property
    def output_dir(self) -> str:
        return self.get('OUTPUT_DIR', 'output')
    
    # 日志配置
    @property
    def log_level(self) -> str:
        return self.get('LOG_LEVEL', 'INFO')
    
    @property
    def log_format(self) -> str:
        return self.get('LOG_FORMAT', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # 音频处理配置
    @property
    def fade_duration(self) -> int:
        return self.get_int('FADE_DURATION', 150)
    
    @property
    def background_min_volume(self) -> float:
        return self.get_float('BACKGROUND_MIN_VOLUME', 0.05)
    
    # TTS配置
    @property
    def tts_temperature(self) -> float:
        return self.get_float('TTS_TEMPERATURE', 0.8)
    
    @property
    def tts_top_k(self) -> int:
        return self.get_int('TTS_TOP_K', 50)
    
    @property
    def tts_top_p(self) -> float:
        return self.get_float('TTS_TOP_P', 0.95)
    
    @property
    def tts_seed_base(self) -> int:
        return self.get_int('TTS_SEED_BASE', 421)

# 创建全局配置实例
config = Config()

# 为了向后兼容，导出一些常用的配置
def get_config():
    """获取配置实例"""
    return config

# 向后兼容的配置访问方式
STT_SERVER_URL = config.stt_server_url
TTS_SERVER_URL = config.tts_server_url 