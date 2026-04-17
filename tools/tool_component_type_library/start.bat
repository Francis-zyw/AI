@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ==========================================
echo      构件类型管理工具 v1.2.2
echo ==========================================
echo.

REM 切换到脚本所在目录（关键修复，防止从其他目录运行失败）
cd /d "%~dp0"

REM 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到Python，请先安装Python 3.8+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 检查app.py
if not exist "app.py" (
    echo [错误] 未找到 app.py，请确保与本脚本同目录
    pause
    exit /b 1
)

echo [1/3] 检查虚拟环境...

REM 🔧 优化1：同时检查目录和python.exe是否存在（防止目录损坏）
if not exist "venv\Scripts\python.exe" (
    echo 创建虚拟环境...
    python -m venv venv
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo ✓ 虚拟环境创建完成
) else (
    echo ✓ 虚拟环境已存在，跳过创建
)

echo [2/3] 检查依赖...

REM 激活虚拟环境
call venv\Scripts\activate

REM 🔧 优化2：检查关键依赖是否已安装，避免每次都执行 pip install
python -c "import streamlit, pandas, openpyxl, xlrd" >nul 2>&1
if errorlevel 1 (
    echo 首次安装依赖（使用清华镜像加速）...
    python -m pip install --upgrade pip -q -i https://pypi.tuna.tsinghua.edu.cn/simple
    python -m pip install streamlit pandas openpyxl xlrd -q -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
    echo ✓ 依赖安装完成
) else (
    echo ✓ 所有依赖已安装，跳过安装步骤
)

echo [3/3] 启动应用...
echo ==========================================
echo  🚀 应用启动中...
echo  🌐 浏览器访问: http://localhost:8501
echo  ⏹️  按 Ctrl+C 停止服务
echo ==========================================
echo.

python -m streamlit run app.py

REM 🔧 优化3：如果应用异常退出，暂停显示错误信息
if errorlevel 1 (
    echo.
    echo [提示] 应用已停止或发生错误
    pause
)
