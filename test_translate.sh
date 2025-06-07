#!/bin/bash

# 测试翻译接口
curl -X POST http://localhost:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3:14b",
    "prompt": "直接输出以下英文的中文翻译：In 2022, I met representatives of the Kremlin for a secret talk in Moscow.",
    "options": {
      "temperature": 0.2
    },
    "stream": false
  }'

echo -e "\n\n测试第二条："
curl -X POST http://localhost:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3:14b",
    "prompt": "直接输出以下英文的中文翻译：They asked how to deal with crazy politicians who lost the ground of reality.",
    "options": {
      "temperature": 0.2
    },
    "stream": false
  }' 