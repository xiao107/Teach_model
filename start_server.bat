@echo off
chcp 65001 >nul
REM Teach_model 启动脚本（Windows）

echo 🚀 启动 DeepSeek 数据助手...
echo.

REM 检查是否在正确的目录
if not exist "backend" (
    echo ❌ 错误：请在项目根目录运行此脚本
    exit /b 1
)

REM 优先使用项目虚拟环境 .venv，其次使用系统 Python
set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

echo 📦 使用 Python: %PYTHON%
echo.

REM 首次运行：自动创建虚拟环境并安装依赖
if not exist ".venv\Scripts\python.exe" (
    echo 🔧 未检测到虚拟环境，正在创建 .venv ...
    python -m venv .venv || goto :fail
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
)

if not exist ".env" (
    if exist ".env.example" (
        echo ⚠️  未检测到 .env，已从 .env.example 生成模板，请填入 DEEPSEEK_API_KEY 后重新运行
        copy .env.example .env >nul
        pause
        exit /b 1
    )
)

echo 🌐 启动服务器在 http://localhost:8000
echo 按 Ctrl+C 停止服务器
echo.
"%PYTHON%" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
goto :eof

:fail
echo ❌ 环境安装失败，请检查网络后重试
pause
