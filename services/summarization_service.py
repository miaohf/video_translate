import logging
import json
import os
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path

from services.translation_service import TranslationService
from config import settings

logger = logging.getLogger(__name__)

class SummarizationService:
    """内容总结服务"""
    
    def __init__(self):
        self.translation_service = TranslationService()
    
    async def generate_content_summary(self, subtitles: List[Dict[str, Any]], video_name: str, video_id: int) -> Dict[str, Any]:
        """生成视频内容总结（基于原始语音字幕）"""
        try:
            logger.info(f"📝 开始为视频 {video_name} (ID: {video_id}) 生成内容总结")
            
            # 提取所有字幕文本（使用原始语音字幕）
            all_texts = []
            for subtitle in subtitles:
                # 优先使用原始文本，如果没有则使用翻译后的文本
                text = subtitle.get('original_text', subtitle.get('text', '')).strip()
                if text:
                    all_texts.append(text)
            
            if not all_texts:
                logger.warning(f"⚠️ 没有找到可总结的文本内容")
                return {
                    "success": False,
                    "error": "没有找到可总结的文本内容",
                    "summary": None
                }
            
            # 合并所有文本
            full_text = " ".join(all_texts)
            logger.info(f"📄 提取到 {len(all_texts)} 条原始字幕，总长度: {len(full_text)} 字符")
            
            # 生成总结提示词
            summary_prompt = self._create_summary_prompt(full_text, video_name)
            
            # 调用翻译服务进行总结
            summary_result = await self._generate_summary_with_llm(summary_prompt)
            
            if summary_result:
                # 保存总结结果
                summary_data = {
                    "video_id": video_id,
                    "video_name": video_name,
                    "summary": summary_result,
                    "generated_at": datetime.now().isoformat(),
                    "subtitle_count": len(all_texts),
                    "total_text_length": len(full_text),
                    "source_language": "original_audio",  # 标记为基于原始音频
                    "summary_language": "zh"  # 总结输出语言
                }
                
                # 保存到文件
                summary_file_path = self._save_summary(summary_data, video_id)
                
                logger.info(f"✅ 内容总结生成完成: {summary_file_path}")
                
                return {
                    "success": True,
                    "summary": summary_result,
                    "summary_file_path": summary_file_path,
                    "metadata": {
                        "subtitle_count": len(all_texts),
                        "total_text_length": len(full_text),
                        "generated_at": summary_data["generated_at"],
                        "source_language": summary_data["source_language"],
                        "summary_language": summary_data["summary_language"]
                    }
                }
            else:
                logger.error(f"❌ 总结生成失败")
                return {
                    "success": False,
                    "error": "总结生成失败",
                    "summary": None
                }
                
        except Exception as e:
            logger.error(f"❌ 生成内容总结时发生错误: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "summary": None
            }
    
    def _create_summary_prompt(self, text: str, video_name: str) -> str:
        """创建总结提示词"""
        prompt = f"""请对以下视频内容进行详细总结。这是一个名为"{video_name}"的视频的字幕内容。

要求：
1. 提取主要内容要点
2. 识别关键主题和概念
3. 总结主要观点和结论
4. 保持客观准确的描述
5. 使用中文输出
6. 总结长度控制在500-800字之间

视频字幕内容：
{text}

请提供详细的内容总结："""
        
        return prompt
    
    async def _generate_summary_with_llm(self, prompt: str) -> Optional[str]:
        """使用LLM生成总结"""
        try:
            # 使用翻译服务的LLM进行总结
            if hasattr(self.translation_service, 'llm') and self.translation_service.llm:
                # 直接使用LLM
                response = await self.translation_service.llm.ainvoke(prompt)
                return response.strip()
            else:
                # 使用翻译服务的API调用
                summary_text = await self.translation_service.translate_single_subtitle(prompt)
                return summary_text
                
        except Exception as e:
            logger.error(f"❌ LLM总结生成失败: {str(e)}")
            return None
    
    def _save_summary(self, summary_data: Dict[str, Any], video_id: int) -> str:
        """保存总结结果到文件"""
        try:
            # 创建总结目录
            summary_dir = os.path.join(settings.OUTPUT_DIR, "summaries")
            os.makedirs(summary_dir, exist_ok=True)
            
            # 生成文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            summary_filename = f"summary_{video_id}_{timestamp}.json"
            summary_file_path = os.path.join(summary_dir, summary_filename)
            
            # 保存JSON文件
            with open(summary_file_path, "w", encoding="utf-8") as f:
                json.dump(summary_data, f, ensure_ascii=False, indent=2)
            
            # 同时保存纯文本版本
            text_filename = f"summary_{video_id}_{timestamp}.txt"
            text_file_path = os.path.join(summary_dir, text_filename)
            
            with open(text_file_path, "w", encoding="utf-8") as f:
                f.write(f"视频ID: {video_id}\n")
                f.write(f"视频名称: {summary_data['video_name']}\n")
                f.write(f"生成时间: {summary_data['generated_at']}\n")
                f.write(f"字幕数量: {summary_data['subtitle_count']}\n")
                f.write(f"总文本长度: {summary_data['total_text_length']}\n")
                f.write("\n" + "="*50 + "\n")
                f.write("内容总结:\n")
                f.write("="*50 + "\n\n")
                f.write(summary_data['summary'])
            
            logger.info(f"💾 总结已保存: {summary_file_path}")
            return summary_file_path
            
        except Exception as e:
            logger.error(f"❌ 保存总结文件失败: {str(e)}")
            raise
    
    def get_summary_file_url(self, video_id: int) -> Optional[str]:
        """获取总结文件的URL"""
        try:
            summary_dir = os.path.join(settings.OUTPUT_DIR, "summaries")
            
            # 查找最新的总结文件
            summary_files = []
            for filename in os.listdir(summary_dir):
                if filename.startswith(f"summary_{video_id}_") and filename.endswith(".json"):
                    file_path = os.path.join(summary_dir, filename)
                    summary_files.append((file_path, os.path.getmtime(file_path)))
            
            if summary_files:
                # 按修改时间排序，取最新的
                latest_file = max(summary_files, key=lambda x: x[1])[0]
                filename = os.path.basename(latest_file)
                return f"{settings.API_BASE_URL}/files/summaries/{filename}"
            
            return None
            
        except Exception as e:
            logger.error(f"❌ 获取总结文件URL失败: {str(e)}")
            return None

# 创建全局实例
summarization_service = SummarizationService() 