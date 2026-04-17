#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TOOL_DIR="${PROJECT_ROOT}/tools/tool_component_match_review"

if [ ! -d "${TOOL_DIR}" ]; then
    echo "未找到 tool_component_match_review 工具目录：${TOOL_DIR}"
    read -r -p "按回车键退出..."
    exit 1
fi

echo "正在启动构件匹配结果人工修订工具..."
echo "工具目录：${TOOL_DIR}"
echo

bash "${TOOL_DIR}/start.sh"
EXIT_CODE=$?

echo
if [ "${EXIT_CODE}" -eq 0 ]; then
    echo "工具已退出。"
else
    echo "启动失败，退出码：${EXIT_CODE}"
fi

read -r -p "按回车键退出..."
exit "${EXIT_CODE}"
