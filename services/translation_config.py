"""
翻译服务配置文件
"""

class TranslationConfig:
    """翻译服务配置类"""
    
    # 批处理配置
    DEFAULT_BATCH_SIZE = 3  # 默认批处理大小（针对大模型优化）
    MIN_BATCH_SIZE = 1      # 最小批处理大小
    MAX_BATCH_SIZE = 10     # 最大批处理大小
    
    # 重试配置
    MAX_RETRIES = 3         # 最大重试次数（减少重试避免浪费时间）
    BASE_RETRY_DELAY = 1.0  # 基础重试延迟（秒）
    MAX_RETRY_DELAY = 30.0  # 最大重试延迟（秒）
    
    # API配置
    REQUEST_TIMEOUT = 180   # 请求超时时间（秒）- 增加到3分钟
    BATCH_DELAY = 0.5       # 批次间延迟（秒）
    
    # 翻译质量检查配置
    MIN_LENGTH_RATIO = 0.3  # 最小长度比例
    MAX_LENGTH_RATIO = 3.0  # 最大长度比例
    QUALITY_THRESHOLD = 0.5 # 质量阈值（失败比例超过此值时重试）
    
    # 模型参数配置
    MODEL_TEMPERATURE = 0.1    # 模型温度
    MODEL_TOP_P = 0.95        # Top-p采样
    MODEL_TOP_K = 50          # Top-k采样
    MODEL_NUM_CTX = 2048      # 上下文长度（减小以提高速度）
    MODEL_REPEAT_PENALTY = 1.1 # 重复惩罚
    
    # 进度保存配置
    PROGRESS_SAVE_INTERVAL = 9  # 每处理多少条字幕保存一次进度（batch_size * 3）
    
    @classmethod
    def get_model_options(cls):
        """获取模型选项"""
        return {
            "temperature": cls.MODEL_TEMPERATURE,
            "top_p": cls.MODEL_TOP_P,
            "top_k": cls.MODEL_TOP_K,
            "num_ctx": cls.MODEL_NUM_CTX,
            "repeat_penalty": cls.MODEL_REPEAT_PENALTY
        }
    
    @classmethod
    def validate_batch_size(cls, batch_size: int) -> int:
        """验证并调整批处理大小"""
        if batch_size < cls.MIN_BATCH_SIZE:
            return cls.MIN_BATCH_SIZE
        elif batch_size > cls.MAX_BATCH_SIZE:
            return cls.MAX_BATCH_SIZE
        return batch_size 