#!/usr/bin/env python3
"""
安装Demucs人声分离工具
"""

import subprocess
import sys
import os

def install_demucs():
    """安装Demucs"""
    print("🔧 开始安装Demucs...")
    
    try:
        # 首先卸载可能冲突的numpy版本
        print("📦 检查numpy版本...")
        result = subprocess.run([sys.executable, "-m", "pip", "list"], 
                              capture_output=True, text=True)
        
        if "numpy" in result.stdout:
            print("🔄 卸载当前numpy版本...")
            subprocess.run([sys.executable, "-m", "pip", "uninstall", "numpy", "-y"], 
                         check=True)
        
        # 安装兼容的numpy版本
        print("📦 安装兼容的numpy版本...")
        subprocess.run([sys.executable, "-m", "pip", "install", "numpy==1.18.5"], 
                      check=True)
        
        # 安装Demucs
        print("📦 安装Demucs...")
        subprocess.run([sys.executable, "-m", "pip", "install", "demucs"], 
                      check=True)
        
        print("✅ Demucs安装成功!")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ 安装失败: {str(e)}")
        return False

def test_demucs():
    """测试Demucs是否正常工作"""
    print("🧪 测试Demucs...")
    
    try:
        import demucs
        print(f"✅ Demucs导入成功，版本: {demucs.__version__}")
        
        # 测试命令行工具
        result = subprocess.run(["demucs", "--help"], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ Demucs命令行工具可用")
            return True
        else:
            print("❌ Demucs命令行工具不可用")
            return False
            
    except ImportError as e:
        print(f"❌ Demucs导入失败: {str(e)}")
        return False

def main():
    """主函数"""
    print("🎵 Demucs人声分离工具安装程序")
    print("=" * 50)
    
    # 检查Python版本
    if sys.version_info < (3, 7):
        print("❌ 需要Python 3.7或更高版本")
        return
    
    print(f"🐍 Python版本: {sys.version}")
    
    # 安装Demucs
    if install_demucs():
        # 测试安装
        if test_demucs():
            print("\n🎉 Demucs安装和测试完成!")
            print("\n📖 使用示例:")
            print("  demucs --help                    # 查看帮助")
            print("  demucs input.wav                 # 分离音频")
            print("  demucs --two-stems vocals input.wav  # 只分离人声和伴奏")
        else:
            print("❌ Demucs测试失败")
    else:
        print("❌ Demucs安装失败")

if __name__ == "__main__":
    main() 