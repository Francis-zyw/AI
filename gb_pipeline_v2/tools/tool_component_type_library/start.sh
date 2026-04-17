#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "$0" )" && pwd )"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "      构件类型管理工具 v1.2.2"
echo "=========================================="
echo ""

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到Python3"
    exit 1
fi

# 检查app.py
if [ ! -f "app.py" ]; then
    echo "[错误] 未找到 app.py，请确保与本脚本同目录"
    exit 1
fi

echo "[1/3] 检查虚拟环境..."

# 检查 venv 模块是否存在
if ! python3 -c "import venv" 2>/dev/null; then
    echo "[错误] Python 缺少 venv 模块"
    exit 1
fi

# 🔧 优化1：虚拟环境已存在时跳过创建
if [ ! -d "venv" ] || [ ! -f "venv/bin/python" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv || {
        echo "[错误] 创建虚拟环境失败"
        exit 1
    }
    echo "✓ 虚拟环境创建完成"
else
    echo "✓ 虚拟环境已存在，跳过创建"
fi

echo "[2/3] 检查依赖..."

# 激活虚拟环境
. venv/bin/activate

# 🔧 优化2：检查关键依赖是否已安装，避免每次都执行 pip install
if python -c "import streamlit, pandas, openpyxl" 2>/dev/null; then
    echo "✓ 所有依赖已安装，跳过安装步骤"
else
    echo "安装依赖（首次运行或依赖缺失）..."
    python -m pip install --upgrade pip -q -i https://pypi.tuna.tsinghua.edu.cn/simple
    python -m pip install streamlit pandas openpyxl xlrd -q -i https://pypi.tuna.tsinghua.edu.cn/simple
    echo "✓ 依赖安装完成"
fi

echo "[3/3] 启动应用..."
echo "=========================================="
echo "  🚀 应用启动中..."
echo "  🌐 浏览器访问: http://localhost:8501"
echo "  ⏹️  按 Ctrl+C 停止"
echo "=========================================="

python -m streamlit run app.py
