#!/bin/bash

# 切换到项目目录
cd /home/miaohf/Documents/mycode/video_translate

# 激活虚拟环境
source .venv/bin/activate

# 启动API服务器
python start_api_server_prod.py 