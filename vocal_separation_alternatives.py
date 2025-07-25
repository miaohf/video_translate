#!/usr/bin/env python3
"""
多种人声分离方案实现
"""

import os
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Tuple, Optional, Dict, Any
import json

logger = logging.getLogger(__name__)

class VocalSeparationManager:
    """人声分离管理器 - 支持多种分离方案"""
    
    def __init__(self):
        self.available_methods = self._detect_available_methods()
        logger.info(f"🎵 可用的人声分离方法: {list(self.available_methods.keys())}")
    
    def _detect_available_methods(self) -> Dict[str, bool]:
        """检测可用的分离方法"""
        methods = {}
        
        # 检测Demucs
        try:
            import demucs
            methods["demucs"] = True
            logger.info("✅ Demucs可用")
        except ImportError:
            methods["demucs"] = False
            logger.info("❌ Demucs不可用")
        
        # 检测Open-Unmix
        try:
            import openunmix
            methods["openunmix"] = True
            logger.info("✅ Open-Unmix可用")
        except ImportError:
            methods["openunmix"] = False
            logger.info("❌ Open-Unmix不可用")
        
        # 检测FFmpeg
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
            methods["ffmpeg"] = True
            logger.info("✅ FFmpeg可用")
        except (subprocess.CalledProcessError, FileNotFoundError):
            methods["ffmpeg"] = False
            logger.info("❌ FFmpeg不可用")
        
        return methods
    
    def separate_vocals(self, input_file: str, method: str = "auto", 
                       output_dir: str = None, **kwargs) -> Dict[str, str]:
        """
        分离人声
        
        Args:
            input_file: 输入音频文件
            method: 分离方法 (auto, demucs, openunmix, ffmpeg)
            output_dir: 输出目录
            **kwargs: 其他参数
            
        Returns:
            Dict[str, str]: 包含分离结果文件路径的字典
        """
        if not os.path.exists(input_file):
            raise FileNotFoundError(f"输入文件不存在: {input_file}")
        
        # 自动选择最佳方法
        if method == "auto":
            method = self._select_best_method()
        
        if method not in self.available_methods or not self.available_methods[method]:
            raise ValueError(f"方法 {method} 不可用")
        
        logger.info(f"🎵 使用 {method} 进行人声分离")
        
        if method == "demucs":
            return self._separate_with_demucs(input_file, output_dir, **kwargs)
        elif method == "openunmix":
            return self._separate_with_openunmix(input_file, output_dir, **kwargs)
        elif method == "ffmpeg":
            return self._separate_with_ffmpeg(input_file, output_dir, **kwargs)
        else:
            raise ValueError(f"不支持的方法: {method}")
    
    def _select_best_method(self) -> str:
        """自动选择最佳分离方法"""
        # 优先级: Demucs > Open-Unmix > FFmpeg
        if self.available_methods.get("demucs"):
            return "demucs"
        elif self.available_methods.get("openunmix"):
            return "openunmix"
        elif self.available_methods.get("ffmpeg"):
            return "ffmpeg"
        else:
            raise RuntimeError("没有可用的分离方法")
    
    def _separate_with_demucs(self, input_file: str, output_dir: str = None, **kwargs) -> Dict[str, str]:
        """使用Demucs分离"""
        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="demucs_")
        
        model = kwargs.get("model", "htdemucs")
        device = kwargs.get("device", "cpu")
        
        try:
            cmd = [
                "demucs",
                "--model", model,
                "--device", device,
                "--out", output_dir,
                "--two-stems", "vocals",
                input_file
            ]
            
            logger.info(f"🚀 执行Demucs: {' '.join(cmd)}")
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                raise RuntimeError(f"Demucs分离失败: {result.stderr}")
            
            # 查找输出文件
            input_name = Path(input_file).stem
            model_dir = os.path.join(output_dir, model, input_name)
            
            vocals_file = os.path.join(model_dir, "vocals.wav")
            no_vocals_file = os.path.join(model_dir, "no_vocals.wav")
            
            return {
                "vocals": vocals_file,
                "background": no_vocals_file,
                "method": "demucs",
                "model": model
            }
            
        except Exception as e:
            logger.error(f"❌ Demucs分离失败: {str(e)}")
            raise
    
    def _separate_with_openunmix(self, input_file: str, output_dir: str = None, **kwargs) -> Dict[str, str]:
        """使用Open-Unmix分离"""
        # Open-Unmix实现较复杂，这里提供基础框架
        logger.info("Open-Unmix分离功能待实现")
        raise NotImplementedError("Open-Unmix分离功能待实现")
    
    def _separate_with_ffmpeg(self, input_file: str, output_dir: str = None, **kwargs) -> Dict[str, str]:
        """使用FFmpeg进行基础分离"""
        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="ffmpeg_")
        
        os.makedirs(output_dir, exist_ok=True)
        
        input_name = Path(input_file).stem
        vocals_file = os.path.join(output_dir, f"{input_name}_vocals.wav")
        background_file = os.path.join(output_dir, f"{input_name}_background.wav")
        
        try:
            # 使用FFmpeg进行简单的频谱分离
            # 这是一个基础实现，效果不如深度学习方法
            
            # 提取人声 (高频部分)
            cmd_vocals = [
                "ffmpeg", "-i", input_file,
                "-af", "highpass=f=200,lowpass=f=3000",
                "-y", vocals_file
            ]
            
            # 提取背景音乐 (低频部分)
            cmd_background = [
                "ffmpeg", "-i", input_file,
                "-af", "lowpass=f=200",
                "-y", background_file
            ]
            
            logger.info("🚀 使用FFmpeg进行基础分离")
            
            # 执行分离
            subprocess.run(cmd_vocals, capture_output=True, check=True)
            subprocess.run(cmd_background, capture_output=True, check=True)
            
            return {
                "vocals": vocals_file,
                "background": background_file,
                "method": "ffmpeg",
                "note": "基础频谱分离，效果有限"
            }
            
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ FFmpeg分离失败: {str(e)}")
            raise
    
    def install_method(self, method: str) -> bool:
        """安装指定的分离方法"""
        installers = {
            "demucs": self._install_demucs,
            "openunmix": self._install_openunmix
        }
        
        if method not in installers:
            logger.error(f"❌ 不支持安装方法: {method}")
            return False
        
        return installers[method]()
    
    def _install_demucs(self) -> bool:
        """安装Demucs"""
        try:
            logger.info("🔧 安装Demucs...")
            subprocess.run(["pip", "install", "demucs"], check=True)
            logger.info("✅ Demucs安装成功")
            self.available_methods["demucs"] = True
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Demucs安装失败: {str(e)}")
            return False
    
    def _install_openunmix(self) -> bool:
        """安装Open-Unmix"""
        try:
            logger.info("🔧 安装Open-Unmix...")
            subprocess.run(["pip", "install", "openunmix"], check=True)
            logger.info("✅ Open-Unmix安装成功")
            self.available_methods["openunmix"] = True
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Open-Unmix安装失败: {str(e)}")
            return False


def create_separation_config():
    """创建分离配置文件"""
    config = {
        "preferred_method": "demucs",
        "fallback_method": "ffmpeg",
        "demucs": {
            "model": "htdemucs",
            "device": "cpu",
            "two_stems": True
        },
        "ffmpeg": {
            "vocals_filter": "highpass=f=200,lowpass=f=3000",
            "background_filter": "lowpass=f=200"
        },
        "output": {
            "format": "wav",
            "sample_rate": 44100,
            "channels": 2
        }
    }
    
    with open("vocal_separation_config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    logger.info("✅ 分离配置文件已创建: vocal_separation_config.json")


# 使用示例
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # 创建分离管理器
    manager = VocalSeparationManager()
    
    # 创建配置文件
    create_separation_config()
    
    print("🎵 人声分离管理器初始化完成")
    print(f"可用方法: {list(manager.available_methods.keys())}")
    
    # 如果需要安装Demucs
    if not manager.available_methods.get("demucs"):
        print("是否安装Demucs? (y/n)")
        # 这里可以添加用户交互逻辑 