"""
翻译服务配置文件
"""

class TranslationConfig:
    """翻译服务配置"""
    
    # 批处理配置
    DEFAULT_BATCH_SIZE = 3
    MIN_BATCH_SIZE = 1
    MAX_BATCH_SIZE = 10
    BATCH_DELAY = 0.5  # 批次间延迟（秒）
    
    # 进度保存配置
    PROGRESS_SAVE_INTERVAL = 3  # 每处理多少条字幕保存一次进度
    
    # 重试配置
    MAX_RETRIES = 3
    BASE_RETRY_DELAY = 1.0  # 秒
    MAX_RETRY_DELAY = 10.0  # 秒
    
    # 质量检查配置
    QUALITY_THRESHOLD = 0.5  # 质量阈值（失败比例超过此值时重试）
    # 注意：已移除长度比例检查，因为中英文长度差异较大，过于严苛
    
    # 请求配置
    REQUEST_TIMEOUT = 300  # 5分钟超时
    
    # 整体翻译配置
    MAX_WHOLE_CONTENT_LENGTH = 8000  # 整体翻译的最大字符长度
    LARGE_BATCH_SIZE = 20  # 大批次处理的大小
    
    @staticmethod
    def validate_batch_size(batch_size: int) -> int:
        """验证并调整批处理大小"""
        if batch_size < TranslationConfig.MIN_BATCH_SIZE:
            return TranslationConfig.MIN_BATCH_SIZE
        elif batch_size > TranslationConfig.MAX_BATCH_SIZE:
            return TranslationConfig.MAX_BATCH_SIZE
        return batch_size
    
    @staticmethod
    def get_model_options() -> dict:
        """获取模型选项"""
        return {
            "temperature": 0.3,
            "top_k": 40,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
            "num_ctx": 8192,
            "num_predict": 4096
        } 