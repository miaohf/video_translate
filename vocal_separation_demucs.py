#!/usr/bin/env python3
"""
基于Demucs的人声分离模块
"""

import os
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

class DemucsVocalSeparator:
    """基于Demucs的人声分离器"""
    
    def __init__(self, model: str = "htdemucs", device: str = "cpu"):
        """
        初始化Demucs分离器
        
        Args:
            model: 使用的模型 (htdemucs, mdx, demucs, demucs_extra, demucs_quantized)
            device: 设备类型 (cpu, cuda)
        """
        self.model = model
        self.device = device
        self._check_demucs_installation()
    
    def _check_demucs_installation(self):
        """检查Demucs是否已安装"""
        try:
            import demucs
            logger.info(f"✅ Demucs已安装，版本: {demucs.__version__}")
        except ImportError:
            logger.error("❌ Demucs未安装，请运行: pip install demucs")
            raise ImportError("Demucs未安装")
    
    def separate_vocals(self, input_file: str, output_dir: str = None) -> Tuple[str, str]:
        """
        分离人声和背景音乐
        
        Args:
            input_file: 输入音频文件路径
            output_dir: 输出目录，如果为None则使用临时目录
            
        Returns:
            Tuple[str, str]: (人声文件路径, 背景音乐文件路径)
        """
        if not os.path.exists(input_file):
            raise FileNotFoundError(f"输入文件不存在: {input_file}")
        
        # 设置输出目录
        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="demucs_")
        
        os.makedirs(output_dir, exist_ok=True)
        
        logger.info(f"🎵 开始人声分离: {input_file}")
        logger.info(f"📁 输出目录: {output_dir}")
        logger.info(f"🤖 使用模型: {self.model}")
        
        try:
            # 构建Demucs命令
            cmd = [
                "demucs",
                "--model", self.model,
                "--device", self.device,
                "--out", output_dir,
                "--two-stems", "vocals",  # 只分离人声和伴奏
                input_file
            ]
            
            logger.info(f"🚀 执行命令: {' '.join(cmd)}")
            
            # 执行分离
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5分钟超时
            )
            
            if result.returncode != 0:
                logger.error(f"❌ Demucs分离失败: {result.stderr}")
                raise RuntimeError(f"Demucs分离失败: {result.stderr}")
            
            logger.info(f"✅ Demucs分离完成: {result.stdout}")
            
            # 查找输出文件
            input_name = Path(input_file).stem
            model_dir = os.path.join(output_dir, self.model, input_name)
            
            vocals_file = os.path.join(model_dir, "vocals.wav")
            no_vocals_file = os.path.join(model_dir, "no_vocals.wav")
            
            if not os.path.exists(vocals_file):
                raise FileNotFoundError(f"人声文件未生成: {vocals_file}")
            
            if not os.path.exists(no_vocals_file):
                raise FileNotFoundError(f"背景音乐文件未生成: {no_vocals_file}")
            
            logger.info(f"🎤 人声文件: {vocals_file}")
            logger.info(f"🎼 背景音乐文件: {no_vocals_file}")
            
            return vocals_file, no_vocals_file
            
        except subprocess.TimeoutExpired:
            logger.error("❌ Demucs分离超时")
            raise RuntimeError("Demucs分离超时")
        except Exception as e:
            logger.error(f"❌ Demucs分离异常: {str(e)}")
            raise
    
    def separate_four_stems(self, input_file: str, output_dir: str = None) -> dict:
        """
        分离为四个音轨 (人声、鼓、贝斯、其他)
        
        Args:
            input_file: 输入音频文件路径
            output_dir: 输出目录
            
        Returns:
            dict: 包含各音轨文件路径的字典
        """
        if not os.path.exists(input_file):
            raise FileNotFoundError(f"输入文件不存在: {input_file}")
        
        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="demucs_")
        
        os.makedirs(output_dir, exist_ok=True)
        
        logger.info(f"🎵 开始四轨分离: {input_file}")
        
        try:
            # 构建Demucs命令 (四轨分离)
            cmd = [
                "demucs",
                "--model", self.model,
                "--device", self.device,
                "--out", output_dir,
                input_file
            ]
            
            logger.info(f"🚀 执行命令: {' '.join(cmd)}")
            
            # 执行分离
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600  # 10分钟超时
            )
            
            if result.returncode != 0:
                logger.error(f"❌ Demucs四轨分离失败: {result.stderr}")
                raise RuntimeError(f"Demucs四轨分离失败: {result.stderr}")
            
            # 查找输出文件
            input_name = Path(input_file).stem
            model_dir = os.path.join(output_dir, self.model, input_name)
            
            stems = {}
            for stem in ["vocals", "drums", "bass", "other"]:
                stem_file = os.path.join(model_dir, f"{stem}.wav")
                if os.path.exists(stem_file):
                    stems[stem] = stem_file
                else:
                    logger.warning(f"⚠️ {stem}音轨文件未找到: {stem_file}")
            
            logger.info(f"✅ 四轨分离完成: {list(stems.keys())}")
            return stems
            
        except Exception as e:
            logger.error(f"❌ Demucs四轨分离异常: {str(e)}")
            raise
    
    def get_available_models(self) -> list:
        """获取可用的模型列表"""
        try:
            result = subprocess.run(
                ["demucs", "--list-models"],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                models = result.stdout.strip().split('\n')
                return [model.strip() for model in models if model.strip()]
            else:
                logger.warning("无法获取模型列表")
                return ["htdemucs", "mdx", "demucs", "demucs_extra"]
                
        except Exception as e:
            logger.warning(f"获取模型列表失败: {str(e)}")
            return ["htdemucs", "mdx", "demucs", "demucs_extra"]


class OpenUnmixSeparator:
    """基于Open-Unmix的人声分离器"""
    
    def __init__(self):
        self._check_installation()
    
    def _check_installation(self):
        """检查Open-Unmix是否已安装"""
        try:
            import openunmix
            logger.info("✅ Open-Unmix已安装")
        except ImportError:
            logger.error("❌ Open-Unmix未安装，请运行: pip install openunmix")
            raise ImportError("Open-Unmix未安装")
    
    def separate_vocals(self, input_file: str, output_dir: str = None) -> Tuple[str, str]:
        """使用Open-Unmix分离人声"""
        # 这里可以实现Open-Unmix的分离逻辑
        # 由于Open-Unmix的API比较复杂，这里只是示例
        logger.info("Open-Unmix分离功能待实现")
        raise NotImplementedError("Open-Unmix分离功能待实现")


def install_demucs():
    """安装Demucs"""
    try:
        logger.info("🔧 开始安装Demucs...")
        subprocess.run(["pip", "install", "demucs"], check=True)
        logger.info("✅ Demucs安装成功")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Demucs安装失败: {str(e)}")
        return False


def install_openunmix():
    """安装Open-Unmix"""
    try:
        logger.info("🔧 开始安装Open-Unmix...")
        subprocess.run(["pip", "install", "openunmix"], check=True)
        logger.info("✅ Open-Unmix安装成功")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Open-Unmix安装失败: {str(e)}")
        return False


# 使用示例
if __name__ == "__main__":
    # 设置日志
    logging.basicConfig(level=logging.INFO)
    
    # 测试Demucs
    try:
        separator = DemucsVocalSeparator()
        print("✅ Demucs分离器初始化成功")
        
        # 获取可用模型
        models = separator.get_available_models()
        print(f"📋 可用模型: {models}")
        
    except ImportError:
        print("❌ Demucs未安装")
        install_demucs() 