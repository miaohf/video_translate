import os
import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config import settings
from routes import translation_routes, health_routes

# 配置日志 - 使用 config 中的统一配置
from config import settings
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format=settings.LOG_FORMAT,
    force=True  # 强制覆盖已有配置
)
logger = logging.getLogger(__name__)

# 创建FastAPI应用
app = FastAPI(
    title="Video Translation API",
    description="API for video translation service",
    version="1.0.0"
)

# 挂载静态文件服务（用于提供翻译后的视频文件）
os.makedirs(settings.OUTPUT_DIR, exist_ok=True)
app.mount("/files", StaticFiles(directory=settings.OUTPUT_DIR), name="files")

# 注册路由
app.include_router(translation_routes.router)
app.include_router(health_routes.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT) 