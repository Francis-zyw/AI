#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "$0" )" && pwd )"
cd "$SCRIPT_DIR"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "=========================================="
echo "      构件匹配结果人工修订工具"
echo "=========================================="
echo ""

if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到 Python3"
    exit 1
fi

if [ ! -f "app.py" ]; then
    echo "[错误] 未找到 app.py"
    exit 1
fi

echo "[1/3] 检查 Python 环境..."

PYTHON_EXE=""
if [ -x "${PROJECT_ROOT}/分析工具/venv/bin/python" ]; then
    PYTHON_EXE="${PROJECT_ROOT}/分析工具/venv/bin/python"
    echo "✓ 已复用主项目虚拟环境: ${PYTHON_EXE}"
elif [ -x "${PROJECT_ROOT}/分析工具/venv/bin/python3" ]; then
    PYTHON_EXE="${PROJECT_ROOT}/分析工具/venv/bin/python3"
    echo "✓ 已复用主项目虚拟环境: ${PYTHON_EXE}"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_EXE="python3"
    echo "✓ 未找到主项目虚拟环境，改用系统 python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_EXE="python"
    echo "✓ 未找到主项目虚拟环境，改用系统 python"
else
    echo "[错误] 未找到可用的 Python 解释器"
    exit 1
fi

echo "[2/3] 检查依赖..."

if "${PYTHON_EXE}" -c "import streamlit, pandas" 2>/dev/null; then
    echo "✓ 所有依赖已安装，跳过安装步骤"
else
    echo "安装依赖（首次运行或依赖缺失）..."
    "${PYTHON_EXE}" -m pip install --upgrade pip -q -i https://pypi.tuna.tsinghua.edu.cn/simple || {
        echo "[错误] pip 升级失败"
        exit 1
    }
    "${PYTHON_EXE}" -m pip install streamlit pandas -q -i https://pypi.tuna.tsinghua.edu.cn/simple || {
        echo "[错误] 依赖安装失败"
        exit 1
    }
    echo "✓ 依赖安装完成"
fi

echo "[3/3] 启动应用..."
echo "=========================================="
echo "  🚀 应用启动中..."
echo "  🌐 浏览器访问: http://localhost:8502"
echo "  ⏹️  按 Ctrl+C 停止"
echo "=========================================="

"${PYTHON_EXE}" -m streamlit run app.py --server.port 8502
