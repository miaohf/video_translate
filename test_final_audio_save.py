#!/usr/bin/env python3
"""
测试最终音频保存功能的脚本
"""

import os
import glob
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_final_audio_save():
    """测试最终音频保存功能"""
    try:
        logger.info("🔍 检查项目根目录中的音频文件...")
        
        # 查找所有的最终音频文件
        patterns = [
            "*_final_audio_*.wav",
            "*final_audio*.wav",
            "*.wav"
        ]
        
        all_audio_files = []
        for pattern in patterns:
            files = glob.glob(pattern)
            all_audio_files.extend(files)
        
        # 去重
        all_audio_files = list(set(all_audio_files))
        
        if all_audio_files:
            logger.info(f"📄 发现 {len(all_audio_files)} 个音频文件:")
            for i, file_path in enumerate(sorted(all_audio_files), 1):
                if os.path.exists(file_path):
                    file_size = os.path.getsize(file_path) / (1024 * 1024)  # MB
                    
                    # 获取音频信息
                    try:
                        from pydub import AudioSegment
                        audio = AudioSegment.from_file(file_path)
                        duration = audio.duration_seconds
                        logger.info(f"   {i}. {file_path}")
                        logger.info(f"      大小: {file_size:.2f} MB, 时长: {duration:.2f}s")
                    except Exception as e:
                        logger.info(f"   {i}. {file_path}")
                        logger.info(f"      大小: {file_size:.2f} MB, (无法读取音频信息: {str(e)})")
                else:
                    logger.warning(f"   {i}. {file_path} (文件不存在)")
        else:
            logger.info("📂 项目根目录中没有找到音频文件")
        
        # 检查temp目录中的音频文件
        logger.info(f"\n🔍 检查temp目录中的音频文件...")
        temp_audio_files = []
        
        if os.path.exists("temp"):
            for root, dirs, files in os.walk("temp"):
                for file in files:
                    if file.endswith(('.wav', '.mp3')):
                        temp_audio_files.append(os.path.join(root, file))
        
        if temp_audio_files:
            logger.info(f"📄 在temp目录中发现 {len(temp_audio_files)} 个音频文件:")
            for i, file_path in enumerate(sorted(temp_audio_files), 1):
                if os.path.exists(file_path):
                    file_size = os.path.getsize(file_path) / (1024 * 1024)  # MB
                    logger.info(f"   {i}. {file_path} ({file_size:.2f} MB)")
        else:
            logger.info("📂 temp目录中没有找到音频文件")
        
        # 总结
        total_files = len(all_audio_files) + len(temp_audio_files)
        logger.info(f"\n📊 总结: 共发现 {total_files} 个音频文件")
        logger.info(f"   项目根目录: {len(all_audio_files)} 个")
        logger.info(f"   temp目录: {len(temp_audio_files)} 个")
        
    except Exception as e:
        logger.error(f"测试失败: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_final_audio_save() 