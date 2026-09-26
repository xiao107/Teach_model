#!/bin/bash

# 启动 DeepSeek 数据助手服务器
# 环境选择优先级：conda 环境 teach_llm > 项目虚拟环境 .venv > 系统 python3
# Windows 用户请使用 start_server.bat

echo "🚀 启动 DeepSeek 数据助手..."
echo ""

# 检查是否在正确的目录
if [ ! -d "backend" ]; then
    echo "❌ 错误：请在项目根目录运行此脚本"
    exit 1
fi

# 1) conda 环境 teach_llm（任意安装位置）
CONDA_PY="$(command -v conda >/dev/null 2>&1 && conda run -n teach_llm python -c 'import sys; print(sys.executable)' 2>/dev/null)"
[ -z "$CONDA_PY" ] && for p in \
    "$HOME/opt/anaconda3/envs/teach_llm/bin/python" \
    "$HOME/opt/miniconda3/envs/teach_llm/bin/python" \
    "$HOME/anaconda3/envs/teach_llm/bin/python" \
    "$HOME/miniconda3/envs/teach_llm/bin/python"; do
    [ -x "$p" ] && CONDA_PY="$p" && break
done

if [ -x "$CONDA_PY" ]; then
    PYTHON="$CONDA_PY"
    echo "📦 使用 conda 环境 teach_llm ($PYTHON)"
elif [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
    echo "📦 使用项目虚拟环境 ($PYTHON)"
else
    # 2) 自动创建 .venv 并安装依赖
    echo "🔧 未检测到 conda 环境 teach_llm / .venv，正在创建虚拟环境 .venv ..."
    PYTHON_BIN="$(command -v python3 || command -v python)"
    if [ -z "$PYTHON_BIN" ]; then
        echo "❌ 错误：未找到 Python，请先安装 Python 3.11+ 或 conda"
        exit 1
    fi
    "$PYTHON_BIN" -m venv .venv || { echo "❌ 虚拟环境创建失败"; exit 1; }
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt || { echo "❌ 依赖安装失败，请检查网络"; exit 1; }
    PYTHON=".venv/bin/python"
    echo "📦 已创建并使用虚拟环境 ($PYTHON)"
fi

# .env 检查
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    echo "⚠️  未检测到 .env，已从 .env.example 生成模板，请填入 DEEPSEEK_API_KEY 后重新运行"
    cp .env.example .env
    exit 1
fi

echo ""
echo "🌐 启动服务器在 http://localhost:8000"
echo "📁 上传功能已启用 - 支持点击和拖拽上传 CSV 文件"
echo ""
echo "按 Ctrl+C 停止服务器"
echo ""

exec "$PYTHON" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
