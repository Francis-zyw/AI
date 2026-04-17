@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "TOOL_DIR=%PROJECT_ROOT%\tools\tool_component_match_review"

if not exist "%TOOL_DIR%" (
    echo 未找到 tool_component_match_review 工具目录：%TOOL_DIR%
    pause
    exit /b 1
)

cd /d "%TOOL_DIR%"

echo ==========================================
echo       构件匹配结果人工修订工具
echo ==========================================
echo.

set "PYTHON_EXE="
if exist "%PROJECT_ROOT%\分析工具\venv\Scripts\python.exe" (
    set "PYTHON_EXE=%PROJECT_ROOT%\分析工具\venv\Scripts\python.exe"
    echo [1/3] 已复用主项目虚拟环境：%PYTHON_EXE%
)

if not defined PYTHON_EXE (
    if exist "%PROJECT_ROOT%\分析工具\venv\Scripts\python3.exe" (
        set "PYTHON_EXE=%PROJECT_ROOT%\分析工具\venv\Scripts\python3.exe"
        echo [1/3] 已复用主项目虚拟环境：%PYTHON_EXE%
    )
)

if not defined PYTHON_EXE (
    where py >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_EXE=py -3"
        echo [1/3] 未找到主项目虚拟环境，改用 py -3
    )
)

if not defined PYTHON_EXE (
    where python3 >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_EXE=python3"
        echo [1/3] 未找到主项目虚拟环境，改用 python3
    )
)

if not defined PYTHON_EXE (
    where python >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_EXE=python"
        echo [1/3] 未找到主项目虚拟环境，改用 python
    )
)

if not defined PYTHON_EXE (
    echo 未找到可用的 Python，请先安装 Python 3。
    pause
    exit /b 1
)

echo [2/3] 检查依赖...
call %PYTHON_EXE% -c "import streamlit, pandas" >nul 2>nul
if errorlevel 1 (
    echo 安装依赖（首次运行或依赖缺失）...
    call %PYTHON_EXE% -m pip install --upgrade pip -q -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo pip 升级失败。
        pause
        exit /b 1
    )
    call %PYTHON_EXE% -m pip install streamlit pandas -q -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo 依赖安装失败。
        pause
        exit /b 1
    )
    echo ✓ 依赖安装完成
) else (
    echo ✓ 所有依赖已安装，跳过安装步骤
)

echo [3/3] 启动应用...
echo ==========================================
echo   应用启动中...
echo   浏览器访问: http://localhost:8502
echo   按 Ctrl+C 停止
echo ==========================================

call %PYTHON_EXE% -m streamlit run app.py --server.port 8502
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
    echo 工具已退出。
) else (
    echo 运行失败，退出码：%EXIT_CODE%
)

pause
exit /b %EXIT_CODE%
