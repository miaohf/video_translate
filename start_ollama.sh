#!/bin/bash

# 停止现有的 Ollama 服务
pkill ollama

# 等待服务完全停止
sleep 2

# 设置环境变量
export OLLAMA_GPU_LAYERS=35
export OLLAMA_NUM_GPU=1

# 启动 Ollama 服务
ollama serve &

# 等待服务启动
sleep 5

# 拉取模型（如果还没有）
ollama pull llama2

echo "Ollama service started with GPU acceleration" 