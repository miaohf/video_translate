"""
翻译服务配置文件
"""

class TranslationConfig:
    """翻译服务配置类"""
    
    # ========== 批量翻译配置 ==========
    ENABLE_BATCH_TRANSLATION = True   # 启用批量翻译模式
    BATCH_TRANSLATION_SIZE = 10       # 每批翻译的字幕数量（自适应会根据成功率调整）
    BATCH_TRANSLATION_MAX_TOKENS = 16384  # 批量翻译最大输出token
    USE_STRUCTURED_OUTPUT = True      # 使用 Pydantic 结构化 JSON 输出（提高解析成功率）
    
    # ========== 三步翻译法配置 ==========
    ENABLE_THREE_STEP_TRANSLATION = True  # 启用三步翻译法
    TRANSLATION_MODE = "contextual_three_step"  # 翻译模式: "contextual_direct", "contextual_three_step"
    
    # ========== 上下文管理配置 ==========
    CONTEXT_WINDOW_SIZE = 8     # 上下文窗口大小（保留前N条翻译）
    
    # ========== API 配置 ==========
    REQUEST_TIMEOUT = 180   # 请求超时时间（秒）
    BATCH_DELAY = 0.1       # 请求间延迟（秒）
    
    # ========== 模型参数配置 ==========
    MODEL_TEMPERATURE = 0.1    # 模型温度
    MODEL_TOP_P = 0.95         # Top-p采样
    MODEL_TOP_K = 40           # Top-k采样
    MODEL_REPEAT_PENALTY = 1.1 # 重复惩罚
    MODEL_MAX_TOKENS = 2048    # 最大生成token数
    
    # ========== 调试日志配置 ==========
    DEBUG_LOG_PROMPTS = True       # 打印详细的请求提示词
    DEBUG_LOG_RESPONSES = True     # 打印详细的响应内容
    DEBUG_LOG_MAX_LENGTH = 0       # 日志内容最大长度（0 = 不截断，显示完整内容）
    DEBUG_LOG_USE_COLOR = True     # 使用颜色区分不同类型的日志
