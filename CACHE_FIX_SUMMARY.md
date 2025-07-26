# 缓存目录修复总结

## 🐛 问题描述

用户发现缓存目录包含了时间戳，导致每次请求都创建新的目录，永远找不到缓存文件：

```
当前缓存目录: temp/266_20250726_163114
应该改成: temp/266
```

## 🔍 问题分析

### 问题根源：

1. **文件上传时**：文件名包含时间戳
   ```
   266_20250726_163114.mp3
   ```

2. **缓存检查时**：使用 `Path(video_file_path).stem` 获取文件名
   ```
   video_name = "266_20250726_163114"
   ```

3. **缓存目录**：变成了带时间戳的目录
   ```
   temp/266_20250726_163114/
   ```

4. **结果**：每次请求都创建新的缓存目录，永远找不到缓存文件

## ✅ 解决方案

### 1. 修改缓存目录逻辑

在 `TranslationTaskService` 中区分处理上传文件和本地文件：

```python
# 对于上传的文件，使用video_id作为缓存目录名
if "uploads" in video_file_path:
    # 上传的文件，使用video_id作为缓存目录
    cache_dir = str(video_id)
    file_hash = get_file_hash(str(video_id))
else:
    # 本地文件，使用原始文件名
    video_name = Path(video_file_path).stem
    cache_dir = video_name
    file_hash = get_file_hash(video_name)
```

### 2. 统一缓存检查逻辑

在 `_check_cache_files` 方法中使用 `video_id` 作为缓存目录：

```python
def _check_cache_files(self, video_name: str, file_hash: str, video_id: int) -> Optional[dict]:
    # 使用video_id作为缓存目录名，而不是带时间戳的文件名
    cache_dir = str(video_id)
    
    # 检查所有必要的缓存文件
    cache_files = {
        "subtitle_json": os.path.join(settings.TEMP_DIR, cache_dir, f"{file_hash}_subtitles.json"),
        "translated_subtitle_json": os.path.join(settings.TEMP_DIR, cache_dir, f"{file_hash}_subtitles_zh.json"),
        # ... 其他文件
    }
```

### 3. 更新翻译服务

确保翻译服务使用相同的缓存目录逻辑：

```python
# 设置路径 - 使用video_name作为缓存目录（可能是video_id或原始文件名）
temp_dir = os.path.join("temp", video_name)
```

## 📊 修复效果

### 修复前：
```
文件路径: /path/to/temp/uploads/266_20250726_163114.mp3
缓存目录: temp/266_20250726_163114/
结果: 每次都是新目录，永远找不到缓存
```

### 修复后：
```
文件路径: /path/to/temp/uploads/266_20250726_163114.mp3
视频ID: 266
缓存目录: temp/266/
结果: 固定目录，可以正确找到缓存文件
```

## 🧪 测试验证

通过测试脚本验证修复效果：

```
📋 测试场景: 上传文件场景
   文件路径: /path/to/temp/uploads/266_20250726_163114.mp3
   视频ID: 266
   计算缓存目录: 266
   期望缓存目录: 266
   ✅ 结果: 正确
```

## 🎯 缓存文件结构

修复后的缓存文件结构：

```
temp/
├── 266/                                    # 使用video_id作为目录名
│   ├── f7664060cc52bc6f3d62_subtitles.json
│   ├── f7664060cc52bc6f3d62_subtitles_zh.json
│   └── f7664060cc52bc6f3d62_subtitles_zh.srt
└── sample/                                 # 本地文件使用原始文件名
    ├── 5e8ff9bf55ba3508199d_subtitles.json
    └── ...

output/
├── 266_f7664060cc52bc6f3d62_subtitles_zh.json
├── 266_f7664060cc52bc6f3d62_translated_audio.wav
└── ...
```

## 🚀 优化效果

1. **缓存命中**：相同 `video_id` 的请求可以正确找到缓存
2. **性能提升**：避免重复的翻译处理
3. **存储效率**：避免创建大量无用的缓存目录
4. **用户体验**：相同视频的重复请求立即返回结果

## 📝 注意事项

1. **向后兼容**：支持旧版本的缓存文件格式
2. **错误处理**：缓存文件损坏时自动重新处理
3. **目录清理**：定期清理过期的缓存目录

现在缓存机制可以正常工作，相同视频的重复请求会立即返回缓存结果！🎉 