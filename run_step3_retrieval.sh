#!/bin/bash
#
# Step3 检索增强版运行脚本
# 用法: ./run_step3_retrieval.sh <step1_json_path> <local_result_json_path> [output_dir]
#

set -e

# 默认配置
PROJECT_ROOT="/Users/zhangkaiye/AI数据/AI智能提量/智能提量处理流程/智能提量工具"
DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/data/output/step3/run-$(date +%Y%m%d)-retrieval"
MODEL="gpt-4o"
BATCH_SIZE=20
STANDARD_DOCUMENT="GB50500-2024"

# 解析参数
STEP1_JSON="${1:-}"
LOCAL_JSON="${2:-}"
OUTPUT_DIR="${3:-${DEFAULT_OUTPUT_DIR}}"

# 检查必需参数
if [ -z "${STEP1_JSON}" ] || [ -z "${LOCAL_JSON}" ]; then
    echo "用法: $0 <step1_json_path> <local_result_json_path> [output_dir]"
    echo ""
    echo "示例:"
    echo "  $0 data/output/step1/run-20260327/structured_bill_items.json data/output/step3/run-20260330/local_rule_result.json"
    exit 1
fi

# 检查文件是否存在
if [ ! -f "${STEP1_JSON}" ]; then
    echo "错误: Step1 JSON 文件不存在: ${STEP1_JSON}"
    exit 1
fi

if [ ! -f "${LOCAL_JSON}" ]; then
    echo "错误: Local Result JSON 文件不存在: ${LOCAL_JSON}"
    exit 1
fi

# 创建输出目录
mkdir -p "${OUTPUT_DIR}"

echo "========================================"
echo "Step3 检索增强版"
echo "========================================"
echo "Step1 JSON: ${STEP1_JSON}"
echo "Local JSON: ${LOCAL_JSON}"
echo "Output Dir: ${OUTPUT_DIR}"
echo "Model: ${MODEL}"
echo "Batch Size: ${BATCH_SIZE}"
echo "Standard: ${STANDARD_DOCUMENT}"
echo "========================================"
echo ""

# 运行检索增强版 Step3
cd "${PROJECT_ROOT}"

python3 -m pipeline_v2.step3_engine.step3_retrieval_api \
    --step1 "${STEP1_JSON}" \
    --local "${LOCAL_JSON}" \
    --output "${OUTPUT_DIR}" \
    --standard "${STANDARD_DOCUMENT}" \
    --model "${MODEL}" \
    --batch-size "${BATCH_SIZE}"

echo ""
echo "========================================"
echo "完成！"
echo "输出目录: ${OUTPUT_DIR}"
echo "========================================"
