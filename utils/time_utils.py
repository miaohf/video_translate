"""时间转换工具模块"""

def srt_time_to_seconds(time_str: str) -> float:
    """
    将 SRT 时间格式转换为秒
    
    参数:
        time_str: SRT 格式的时间字符串 (HH:MM:SS,mmm)
        
    返回:
        秒数
    """
    hours, minutes, seconds = time_str.replace(',', '.').split(':')
    return float(hours) * 3600 + float(minutes) * 60 + float(seconds) 