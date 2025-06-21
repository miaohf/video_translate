#!/usr/bin/env python3
"""
YouTube 视频下载脚本
使用 yt-dlp 进行下载，支持交互式分辨率选择和文件名标准化
"""

import sys
import subprocess
import re
from pathlib import Path

def sanitize_filename(filename: str, max_length: int = 100) -> str:
    """
    标准化文件名
    
    参数:
        filename: 原始文件名
        max_length: 最大长度
        
    返回:
        标准化后的文件名
    """
    # 移除或替换特殊字符
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)  # Windows不允许的字符
    filename = re.sub(r'[^\w\s\-_.\u4e00-\u9fff]', '', filename)  # 保留中文、字母、数字、空格、连字符、下划线、点号
    
    # 替换多个空格为单个空格
    filename = re.sub(r'\s+', ' ', filename)
    
    # 替换空格为下划线
    filename = filename.replace(' ', '_')
    
    # 移除开头和结尾的特殊字符
    filename = filename.strip('_-.')
    
    # 限制长度
    if len(filename) > max_length:
        filename = filename[:max_length].rstrip('_-.')
    
    # 确保文件名不为空
    if not filename:
        filename = "video"
    
    return filename

def get_video_info(url: str):
    """
    获取视频基本信息
    """
    try:
        cmd = ["yt-dlp", "--print", "title,duration,uploader", "--no-playlist", url]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            if len(lines) >= 3:
                return {
                    'title': lines[0],
                    'duration': lines[1],
                    'uploader': lines[2]
                }
        
    except Exception as e:
        print(f"⚠️  Cannot get video info: {str(e)}")
    
    return None

def get_available_formats(url: str):
    """
    获取视频的所有可用格式
    """
    try:
        cmd = ["yt-dlp", "--list-formats", "--no-playlist", url]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            formats = []
            
            for line in lines:
                # 解析格式行，寻找视频格式
                if 'mp4' in line and ('x' in line or 'p' in line):
                    # 使用正则表达式提取信息
                    parts = line.split()
                    if len(parts) >= 3:
                        format_id = parts[0]
                        ext = parts[1] if len(parts) > 1 else 'mp4'
                        
                        # 提取分辨率信息
                        resolution_match = re.search(r'(\d+)x(\d+)', line)
                        quality_match = re.search(r'(\d+)p', line)
                        
                        height = None
                        resolution = "Unknown"
                        quality_label = ""
                        
                        if resolution_match:
                            width, height = resolution_match.groups()
                            height = int(height)
                            resolution = f"{width}x{height}"
                            quality_label = f"{height}p"
                        elif quality_match:
                            height = int(quality_match.group(1))
                            resolution = f"{height}p"
                            quality_label = f"{height}p"
                        
                        # 提取文件大小
                        size_match = re.search(r'(\d+\.?\d*)(MiB|GiB|KiB)', line)
                        filesize = size_match.group(0) if size_match else "Unknown"
                        
                        # 提取编码信息
                        codec_match = re.search(r'(avc1|vp9|av01|h264)', line.lower())
                        codec = codec_match.group(1).upper() if codec_match else "Unknown"
                        
                        if height:  # 只添加有分辨率信息的格式
                            formats.append({
                                'format_id': format_id,
                                'ext': ext,
                                'resolution': resolution,
                                'height': height,
                                'quality_label': quality_label,
                                'filesize': filesize,
                                'codec': codec,
                                'raw_line': line.strip()
                            })
            
            # 按分辨率排序（从高到低）
            formats.sort(key=lambda x: x['height'], reverse=True)
            return formats
            
    except Exception as e:
        print(f"⚠️  Cannot get format info: {str(e)}")
    
    return []

def display_formats_and_choose(formats):
    """
    显示可用格式并让用户选择
    """
    if not formats:
        print("❌ No video formats available")
        return None, None
    
    print("\n🎯 Available video formats:")
    print("=" * 75)
    print(f"{'No.':<4} {'Resolution':<12} {'Codec':<8} {'Size':<12} {'Format ID':<12}")
    print("-" * 75)
    
    # 去重显示主要格式（每个分辨率只显示最好的一个）
    seen_heights = set()
    display_formats = []
    
    for fmt in formats:
        height = fmt['height']
        if height not in seen_heights:
            seen_heights.add(height)
            display_formats.append(fmt)
    
    for i, fmt in enumerate(display_formats, 1):
        print(f"{i:<4} {fmt['resolution']:<12} {fmt['codec']:<8} {fmt['filesize']:<12} {fmt['format_id']:<12}")
    
    print("-" * 75)
    print("0    Best quality (auto select)")
    print("-" * 75)
    
    while True:
        try:
            choice = input("\nPlease select format number (0 for best quality): ").strip()
            
            if choice == '0':
                return 'best', 'best'
            
            choice_num = int(choice)
            if 1 <= choice_num <= len(display_formats):
                selected_format = display_formats[choice_num - 1]
                print(f"✅ Selected: {selected_format['resolution']} ({selected_format['codec']})")
                return selected_format['format_id'], selected_format['quality_label']
            else:
                print(f"❌ Please enter a number between 0 and {len(display_formats)}")
                
        except ValueError:
            print("❌ Please enter a valid number")
        except KeyboardInterrupt:
            print("\n🚫 Download cancelled")
            return None, None

def download_video_with_format(url: str, format_id: str, quality_label: str, output_dir: str = "./downloads"):
    """
    使用指定格式下载视频，并标准化文件名
    """
    try:
        # 确保输出目录存在
        Path(output_dir).mkdir(exist_ok=True)
        
        # 获取视频标题用于文件名
        video_info = get_video_info(url)
        title = video_info['title'] if video_info else "video"
        
        # 标准化文件名
        clean_title = sanitize_filename(title)
        
        # 添加质量标签到文件名
        if quality_label and quality_label != 'best':
            filename_template = f"{clean_title}_{quality_label}.%(ext)s"
        else:
            filename_template = f"{clean_title}.%(ext)s"
        
        print(f"\n🎬 Starting video download...")
        print(f"📁 Output directory: {output_dir}")
        print(f"🎯 Format: {format_id}")
        print(f"📝 Filename template: {filename_template}")
        print("-" * 50)
        
        # 构建下载命令
        if format_id == 'best':
            format_selector = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best"
        else:
            # 选择指定的视频格式，并自动选择最佳音频
            format_selector = f"{format_id}+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
        
        cmd = [
            "yt-dlp",
            "--format", format_selector,
            "--output", f"{output_dir}/{filename_template}",
            "--no-playlist",
            "--merge-output-format", "mp4",  # 确保输出格式为mp4
            "--embed-subs",  # 嵌入字幕（如果有）
            "--write-auto-sub",  # 下载自动生成的字幕
            "--sub-lang", "en",  # 字幕语言
            "--concurrent-fragments", "4",  # 启用分段下载，4个并发连接
            "--fragment-retries", "10",  # 分段重试次数
            url
        ]
        
        print("🔄 Downloading...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ Download completed successfully!")
            
            # 显示下载的文件信息
            if result.stdout:
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    if "[download]" in line and "100%" in line:
                        print(f"📄 {line}")
            
            # 显示最终文件名
            expected_filename = filename_template.replace(".%(ext)s", ".mp4")
            print(f"💾 Final filename: {expected_filename}")
            
            return True
        else:
            print(f"❌ Download failed!")
            if result.stderr:
                print(f"Error details: {result.stderr}")
            return False
            
    except FileNotFoundError:
        print("❌ yt-dlp not installed or not in PATH")
        print("Please run: pip install yt-dlp")
        return False
    except Exception as e:
        print(f"❌ Download error: {str(e)}")
        return False

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("YouTube Video Downloader with Interactive Format Selection")
        print("=" * 60)
        print("Features:")
        print("  ✨ Interactive format selection")
        print("  📝 Automatic filename standardization")
        print("  🏷️  Quality labels in filenames")
        print("  📁 Custom output directory")
        print()
        print("Usage:")
        print("  python yt_download.py <YouTube_URL> [output_dir]")
        print()
        print("Examples:")
        print("  python yt_download.py 'https://www.youtube.com/watch?v=GvvA12oTQ94'")
        print("  python yt_download.py 'https://www.youtube.com/watch?v=GvvA12oTQ94' ./videos")
        print()
        print("Filename format:")
        print("  Standard: video_title.mp4")
        print("  With quality: video_title_1080p.mp4")
        return
    
    url = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "./downloads"
    
    # 获取视频信息
    print("📋 Getting video information...")
    video_info = get_video_info(url)
    
    if video_info:
        print(f"📺 Title: {video_info['title']}")
        print(f"📝 Standardized: {sanitize_filename(video_info['title'])}")
        print(f"⏱️  Duration: {video_info['duration']} seconds")
        print(f"👤 Uploader: {video_info['uploader']}")
    
    # 获取可用格式
    print("\n🔍 Analyzing available formats...")
    formats = get_available_formats(url)
    
    if not formats:
        print("❌ Cannot get format information. Downloading with best quality...")
        success = download_video_with_format(url, 'best', 'best', output_dir)
    else:
        # 显示格式并让用户选择
        selected_format, quality_label = display_formats_and_choose(formats)
        
        if selected_format:
            success = download_video_with_format(url, selected_format, quality_label, output_dir)
        else:
            print("🚫 Download cancelled")
            return
    
    if success:
        print("🎉 Video download completed!")
    else:
        print("💥 Video download failed")
        print()
        print("Suggested solutions:")
        print("1. Check network connection")
        print("2. Verify the video URL is valid")
        print("3. Try updating yt-dlp: pip install --upgrade yt-dlp")

if __name__ == "__main__":
    main()