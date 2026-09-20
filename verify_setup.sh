#!/bin/bash

echo "🔍 验证项目设置"
echo "================================"

# 检查 conda 环境 teach_llm
PYTHON="$HOME/opt/anaconda3/envs/teach_llm/bin/python"

echo -n "✓ 检查 conda 环境 teach_llm... "
if [ -x "$PYTHON" ]; then
    echo "存在 ($($PYTHON --version))"
else
    echo "❌ 未找到"
    echo "  请先创建: conda create -n teach_llm python=3.13"
    exit 1
fi

# 检查依赖
echo -n "✓ 检查核心依赖... "
missing=$("$PYTHON" -c "
import importlib.util
mods = ['fastapi', 'uvicorn', 'dotenv', 'sklearn', 'pandas', 'httpx', 'pydot', 'multipart', 'numpy', 'tabulate']
print(','.join(m for m in mods if importlib.util.find_spec(m) is None))
" 2>/dev/null)
if [ -z "$missing" ]; then
    echo "完整"
else
    echo "❌ 缺少: $missing"
    echo "  请执行: conda run -n teach_llm pip install -r backend/requirements.txt"
fi

# 检查.env文件
echo -n "✓ 检查.env文件... "
if [ -f ".env" ]; then
    echo "存在"
    if grep -q "DEEPSEEK_API_KEY" .env; then
        echo "  ✓ 包含API密钥配置"
    else
        echo "  ⚠️  缺少API密钥配置"
    fi
else
    echo "❌ 不存在"
    echo "  请创建.env文件并添加DEEPSEEK_API_KEY"
fi

# 检查核心文件
echo ""
echo "📁 检查核心文件"
echo "--------------------------------"

files=(
    "backend/main.py"
    "backend/agent.py"
    "backend/prompts.py"
    "backend/llm_client.py"
    "backend/state.py"
    "backend/actions.py"
    "backend/charts.py"
    "backend/sessions.py"
    "backend/data_loader.py"
    "frontend/index.html"
    "frontend/app.js"
    "frontend/style.css"
)

for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        echo "✓ $file"
    else
        echo "❌ $file (缺失)"
    fi
done

# 运行测试
echo ""
echo "🧪 运行集成测试"
echo "--------------------------------"
"$PYTHON" test_integration.py

# 总结
echo ""
echo "================================"
echo "✅ 验证完成！"
echo ""
echo "下一步："
echo "1. 确保.env文件包含有效的API密钥"
echo "2. 运行: bash start_server.sh"
echo "3. 访问: http://localhost:8000"
