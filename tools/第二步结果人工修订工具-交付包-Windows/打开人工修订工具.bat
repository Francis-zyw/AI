@echo off
setlocal enableextensions
chcp 65001 >nul

set "SCRIPT_DIR=%~dp0"
set "TOOL_HTML=%SCRIPT_DIR%第二步结果人工修订工具.html"
set "INPUT_DIR=%SCRIPT_DIR%待修订输入"
set "AUTO_HTML=%SCRIPT_DIR%第二步结果人工修订工具_自动打开.html"

if not exist "%TOOL_HTML%" (
    echo 未找到工具页面：
    echo %TOOL_HTML%
    pause
    exit /b 1
)

set "HAS_AUTO_FILE=0"
if exist "%INPUT_DIR%\step2_manual_review_package.json" set "HAS_AUTO_FILE=1"
if exist "%INPUT_DIR%\component_matching_result.json" set "HAS_AUTO_FILE=1"

if "%HAS_AUTO_FILE%"=="0" (
    echo 正在打开人工修订工具...
    echo 待修订输入文件夹中没有检测到可自动挂接的 JSON 文件，将以空白工具打开。
    start "" "%TOOL_HTML%"
    exit /b 0
)

echo 正在生成自动挂接版本，请稍候...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "$toolHtml = [System.IO.Path]::GetFullPath($env:TOOL_HTML);" ^
  "$inputDir = [System.IO.Path]::GetFullPath($env:INPUT_DIR);" ^
  "$autoHtml = [System.IO.Path]::GetFullPath($env:AUTO_HTML);" ^
  "$html = Get-Content -LiteralPath $toolHtml -Raw -Encoding UTF8;" ^
  "$payload = [ordered]@{ sourceNames = [ordered]@{ component=''; synonym=''; summary=''; package='' } };" ^
  "function Add-JsonFile([string]$payloadKey, [string]$sourceNameKey, [string]$filePath, [string]$displayName) { if (Test-Path -LiteralPath $filePath) { $raw = Get-Content -LiteralPath $filePath -Raw -Encoding UTF8; if (-not [string]::IsNullOrWhiteSpace($raw)) { $payload[$payloadKey + 'Base64'] = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($raw)); $payload.sourceNames[$sourceNameKey] = $displayName; return $true } } return $false }" ^
  "$hasPackage = Add-JsonFile 'reviewPackage' 'package' ([System.IO.Path]::Combine($inputDir, 'step2_manual_review_package.json')) 'step2_manual_review_package.json';" ^
  "if (-not $hasPackage) { $null = Add-JsonFile 'component' 'component' ([System.IO.Path]::Combine($inputDir, 'component_matching_result.json')) 'component_matching_result.json'; $null = Add-JsonFile 'synonym' 'synonym' ([System.IO.Path]::Combine($inputDir, 'synonym_library.json')) 'synonym_library.json'; $null = Add-JsonFile 'summary' 'summary' ([System.IO.Path]::Combine($inputDir, 'run_summary.json')) 'run_summary.json'; }" ^
  "$json = $payload | ConvertTo-Json -Depth 6 -Compress;" ^
  "$inject = '<script>window.__AUTO_LOAD_PAYLOAD__ = ' + $json + ';</script>';" ^
  "$finalHtml = $html -replace '</body>', ($inject + [Environment]::NewLine + '</body>');" ^
  "[System.IO.File]::WriteAllText($autoHtml, $finalHtml, [System.Text.UTF8Encoding]::new($false));"

if errorlevel 1 (
    echo 自动挂接页生成失败，将直接打开原始工具页面。
    start "" "%TOOL_HTML%"
    exit /b 0
)

echo 已自动挂接待修订输入中的 JSON 文件。
start "" "%AUTO_HTML%"
exit /b 0
