"""
翻译服务配置文件
"""

class TranslationConfig:
    """翻译服务配置类"""
    
    # 批处理配置
    DEFAULT_BATCH_SIZE = 1  # 默认批处理大小（单条处理）
    MIN_BATCH_SIZE = 1      # 最小批处理大小
    MAX_BATCH_SIZE = 1      # 最大批处理大小（单条处理）
    
    # 流式翻译配置
    ENABLE_STREAMING = True  # 启用流式翻译
    STREAM_CHUNK_TIMEOUT = 5.0  # 流式块超时时间（秒）
    
    # 上下文管理配置
    CONTEXT_WINDOW_SIZE = 8     # 上下文窗口大小（保留前N条翻译）
    TERMINOLOGY_DICT_SIZE = 100 # 术语词典最大条目数
    ENABLE_CONTEXT = True       # 启用上下文翻译
    
    # 自适应批次配置（单条模式下禁用）
    ENABLE_ADAPTIVE_BATCH = False   # 禁用自适应批次大小（单条模式）
    MIN_RESPONSE_TIME = 5.0         # 最小响应时间阈值（秒）
    MAX_RESPONSE_TIME = 30.0        # 最大响应时间阈值（秒）
    MIN_SUCCESS_RATE = 0.8          # 最小成功率阈值
    
    # 重试配置
    MAX_RETRIES = 3         # 最大重试次数（减少重试避免浪费时间）
    BASE_RETRY_DELAY = 1.0  # 基础重试延迟（秒）
    MAX_RETRY_DELAY = 30.0  # 最大重试延迟（秒）
    
    # API配置
    REQUEST_TIMEOUT = 180   # 请求超时时间（秒）- 增加到3分钟
    BATCH_DELAY = 0.1       # 单条间延迟（秒）- 减少延迟提高效率
    
    # 翻译质量检查配置
    MIN_LENGTH_RATIO = 0.3  # 最小长度比例
    MAX_LENGTH_RATIO = 3.0  # 最大长度比例
    QUALITY_THRESHOLD = 0.5 # 质量阈值（失败比例超过此值时重试）
    
    # 模型参数配置（针对流式优化）
    MODEL_TEMPERATURE = 0.1    # 模型温度
    MODEL_TOP_P = 0.95        # Top-p采样
    MODEL_TOP_K = 40          # Top-k采样（流式处理可以略降低）
    MODEL_NUM_CTX = 4096      # 上下文长度（增加以支持更多上下文）
    MODEL_REPEAT_PENALTY = 1.1 # 重复惩罚
    MODEL_MAX_TOKENS = 2048    # 最大生成token数（统一参数名，内部自动转换为对应API格式）
    
    # 进度保存配置
    PROGRESS_SAVE_INTERVAL = 10  # 每处理多少条字幕保存一次进度（单条模式）
    
    # ========== 三步翻译法配置 ==========
    
    # 三步翻译法开关
    ENABLE_THREE_STEP_TRANSLATION = True  # 启用三步翻译法
    ENABLE_REFLECTION_OPTIMIZATION = True # 启用反思优化
    
    # 三步翻译法参数
    THREE_STEP_BATCH_SIZE = 1  # 三步翻译法的批次大小（单条处理）
    REFLECTION_QUALITY_THRESHOLD = 0.7  # 反思优化的质量阈值
    MAX_REFLECTION_ATTEMPTS = 2  # 最大反思优化次数
    
    # 质量评分权重
    ACCURACY_WEIGHT = 0.25      # 准确性权重
    NATURALNESS_WEIGHT = 0.25   # 自然度权重
    FLUENCY_WEIGHT = 0.2        # 流畅度权重
    CONSISTENCY_WEIGHT = 0.2    # 一致性权重
    CONCISENESS_WEIGHT = 0.1    # 简洁度权重
    
    # 翻译模式选择（上下文模式始终启用）
    TRANSLATION_MODE = "contextual_three_step"  # 翻译模式: "contextual_direct", "contextual_three_step"
    
    # 三步翻译法超时配置
    THREE_STEP_TIMEOUT = 120    # 三步翻译超时时间（秒）
    REFLECTION_TIMEOUT = 60     # 反思优化超时时间（秒）
    
    # 去重配置
    ENABLE_DEDUPLICATION = True  # 启用去重功能
    DEDUPLICATION_LOG_LEVEL = "info"  # 去重日志级别: "debug", "info", "warning"
    
    @classmethod
    def get_model_options(cls):
        """获取模型选项"""
        return {
            "temperature": cls.MODEL_TEMPERATURE,
            "top_p": cls.MODEL_TOP_P,
            "top_k": cls.MODEL_TOP_K,
            "num_ctx": cls.MODEL_NUM_CTX,
            "repeat_penalty": cls.MODEL_REPEAT_PENALTY,
            "max_tokens": cls.MODEL_MAX_TOKENS
        }
    
    @classmethod
    def get_streaming_options(cls):
        """获取流式处理的优化模型选项"""
        options = cls.get_model_options()
        # 流式处理优化参数
        options.update({
            "top_k": 30,  # 降低采样范围以提高一致性
            "repeat_penalty": 1.05,  # 略微降低重复惩罚
        })
        return options
    
    @classmethod
    def get_three_step_options(cls):
        """获取三步翻译法的模型选项"""
        options = cls.get_model_options()
        # 三步翻译法优化参数
        options.update({
            "temperature": 0.15,  # 略微提高创造性
            "top_p": 0.9,        # 降低采样范围以提高质量
            "top_k": 30,         # 降低采样范围
        })
        return options
    
    @classmethod
    def validate_batch_size(cls, batch_size: int) -> int:
        """验证并调整批处理大小"""
        if batch_size < cls.MIN_BATCH_SIZE:
            return cls.MIN_BATCH_SIZE
        elif batch_size > cls.MAX_BATCH_SIZE:
            return cls.MAX_BATCH_SIZE
        return batch_size 