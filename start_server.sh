#!/bin/bash

# 启动 DeepSeek 数据助手服务器（统一使用 conda 环境 teach_llm）

echo "🚀 启动 DeepSeek 数据助手..."
echo ""

# 检查是否在正确的目录
if [ ! -d "backend" ]; then
    echo "❌ 错误：请在项目根目录运行此脚本"
    exit 1
fi

PYTHON="$HOME/opt/anaconda3/envs/teach_llm/bin/python"

if [ ! -x "$PYTHON" ]; then
    echo "❌ 错误：未找到 conda 环境 teach_llm"
    echo "   请先创建并安装依赖："
    echo "   conda create -n teach_llm python=3.13"
    echo "   conda run -n teach_llm pip install -r backend/requirements.txt"
    exit 1
fi

echo "📦 使用 conda 环境 teach_llm ($PYTHON)"
echo ""
echo "🌐 启动服务器在 http://localhost:8000"
echo "📁 上传功能已启用 - 支持点击和拖拽上传 CSV 文件"
echo ""
echo "按 Ctrl+C 停止服务器"
echo ""

exec "$PYTHON" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
