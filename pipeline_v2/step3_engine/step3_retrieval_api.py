"""
Step3 Retrieval-Augmented API
基于知识库检索增强的 Step3 处理流程
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence

# 确保项目根目录在路径中
PROJECT_ROOT = Path("/Users/zhangkaiye/AI数据/AI智能提量/智能提量处理流程/智能提量工具").resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline_v2.step3_engine.api import (
    load_json_or_jsonl,
    write_json,
    load_prompt_template,
    call_openai_model,
    normalize_model_result_payload,
    merge_model_row_with_local,
    build_step3_html_report,
    DEFAULT_CONFIG_NAME,
    DEFAULT_MODEL,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_CONNECTION_RETRIES,
    FINAL_JSON_NAME,
    STEP3_READY_STEP2_STATUSES,
)
from pipeline_v2.step3_engine.retrieval_context import (
    build_retrieval_context_batch,
    format_retrieval_context_for_prompt,
)
from pipeline_v2.model_runtime import load_step_model_config

# 检索增强版专用配置
RETRIEVAL_PROMPT_TEMPLATE_NAME = "prompt_template_retrieval_v1.txt"
RETRIEVAL_KNOWLEDGE_DB_PATH = "/Users/zhangkaiye/AI数据/知识库中心/projects/智能提量工具/project_knowledge_v1/knowledge.db"


def load_retrieval_prompt_template() -> str:
    """加载检索增强版 prompt 模板"""
    template_path = Path(__file__).with_name(RETRIEVAL_PROMPT_TEMPLATE_NAME)
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    
    # 如果找不到专用模板，使用默认模板
    return load_prompt_template()


def build_retrieval_prompt_text(
    batch_step1_rows: Sequence[Dict[str, Any]],
    local_batch_rows: Sequence[Dict[str, Any]],
    retrieval_context_by_row_id: Dict[str, Dict[str, Any]],
    standard_document: str,
    batch_index: int,
    total_batches: int,
) -> str:
    """
    构建检索增强版 Prompt 文本
    
    Args:
        batch_step1_rows: Step1 清单行批次
        local_batch_rows: 本地规则结果批次
        retrieval_context_by_row_id: 按 row_id 索引的检索上下文
        standard_document: 标准文档名称
        batch_index: 当前批次索引
        total_batches: 总批次数
    
    Returns:
        完整的 Prompt 文本
    """
    template = load_retrieval_prompt_template()
    
    # 为每行构建格式化的检索上下文
    retrieval_contexts = []
    for row in batch_step1_rows:
        row_id = row.get("row_id", "")
        context = retrieval_context_by_row_id.get(row_id, {})
        retrieval_contexts.append({
            "row_id": row_id,
            "formatted_context": format_retrieval_context_for_prompt(context),
            "raw_hits": context,
        })
    
    replacements = {
        "${STANDARD_DOCUMENT}": standard_document,
        "${STEP1_BATCH_ROWS_JSON}": json.dumps(batch_step1_rows, ensure_ascii=False, indent=2),
        "${LOCAL_RULE_RESULT_JSON}": json.dumps(local_batch_rows, ensure_ascii=False, indent=2),
        "${RETRIEVAL_CONTEXT_JSON}": json.dumps(retrieval_contexts, ensure_ascii=False, indent=2),
    }
    
    prompt_text = template
    for placeholder, value in replacements.items():
        prompt_text = prompt_text.replace(placeholder, value)
    
    batch_header = (
        f"当前批次信息:\n"
        f"- standard_document: {standard_document}\n"
        f"- batch_index: {batch_index}\n"
        f"- total_batches: {total_batches}\n"
        f"- current_batch_row_count: {len(batch_step1_rows)}\n"
        f"- retrieval_augmented: true\n"
        f"- knowledge_db: {RETRIEVAL_KNOWLEDGE_DB_PATH}\n\n"
    )
    return batch_header + prompt_text


def run_step3_retrieval_batch(
    batch_step1_rows: Sequence[Dict[str, Any]],
    local_rows_by_row_id: Dict[str, List[Dict[str, Any]]],
    standard_document: str,
    output_path: Path,
    batch_index: int,
    total_batches: int,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    retries: int = DEFAULT_CONNECTION_RETRIES,
    knowledge_db_path: str = RETRIEVAL_KNOWLEDGE_DB_PATH,
) -> Dict[str, Any]:
    """
    运行单批次的检索增强 Step3 处理
    
    Args:
        batch_step1_rows: Step1 清单行批次
        local_rows_by_row_id: 按 row_id 索引的本地规则结果
        standard_document: 标准文档名称
        output_path: 输出路径
        batch_index: 当前批次索引
        total_batches: 总批次数
        model: 模型名称
        api_key: API 密钥
        base_url: API 基础 URL
        timeout: 请求超时时间
        retries: 重试次数
        knowledge_db_path: 知识库数据库路径
    
    Returns:
        模型处理结果
    """
    # 构建本地规则批次
    local_batch_rows: List[Dict[str, Any]] = []
    for row in batch_step1_rows:
        row_id = row.get("row_id", "")
        local_rows = local_rows_by_row_id.get(row_id, [])
        if local_rows:
            local_batch_rows.append(local_rows[0])
    
    # 构建检索上下文
    print(f"[Batch {batch_index}/{total_batches}] Building retrieval context...")
    retrieval_context_by_row_id = build_retrieval_context_batch(
        knowledge_db_path=knowledge_db_path,
        step1_rows=batch_step1_rows,
        local_rows_by_row_id=local_rows_by_row_id,
    )
    
    # 构建 Prompt
    prompt_text = build_retrieval_prompt_text(
        batch_step1_rows=batch_step1_rows,
        local_batch_rows=local_batch_rows,
        retrieval_context_by_row_id=retrieval_context_by_row_id,
        standard_document=standard_document,
        batch_index=batch_index,
        total_batches=total_batches,
    )
    
    # 保存 prompt 用于调试
    prompt_debug_path = output_path / f"batch_{batch_index:04d}_prompt.txt"
    prompt_debug_path.write_text(prompt_text, encoding="utf-8")
    
    # 调用模型
    print(f"[Batch {batch_index}/{total_batches}] Calling model: {model}")
    response = call_openai_model(
        prompt_text=prompt_text,
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        retries=retries,
        output_path=output_path,
    )
    
    # 解析结果
    result_payload = response.get("parsed_json", {})
    if not result_payload:
        print(f"[Batch {batch_index}/{total_batches}] Warning: No JSON parsed from response")
        return {"rows": [], "raw_response": response.get("raw_response", "")}
    
    # 规范化结果
    normalized = normalize_model_result_payload(result_payload)
    
    # 保存批次结果
    batch_result_path = output_path / f"batch_{batch_index:04d}_result.json"
    write_json(batch_result_path, normalized)
    
    return normalized


def run_step3_retrieval(
    step1_json_path: str | Path,
    local_result_json_path: str | Path,
    output_dir: str | Path,
    standard_document: str = "",
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    retries: int = DEFAULT_CONNECTION_RETRIES,
    batch_size: int = 20,
    knowledge_db_path: str = RETRIEVAL_KNOWLEDGE_DB_PATH,
) -> Dict[str, Any]:
    """
    运行完整的检索增强 Step3 流程
    
    Args:
        step1_json_path: Step1 结果 JSON 路径
        local_result_json_path: 本地规则结果 JSON 路径
        output_dir: 输出目录
        standard_document: 标准文档名称
        model: 模型名称
        api_key: API 密钥
        base_url: API 基础 URL
        timeout: 请求超时时间
        retries: 重试次数
        batch_size: 每批处理的行数
        knowledge_db_path: 知识库数据库路径
    
    Returns:
        完整处理结果
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 加载输入数据
    print(f"Loading Step1 data from: {step1_json_path}")
    step1_data = load_json_or_jsonl(Path(step1_json_path))
    step1_rows = step1_data.get("rows", []) if isinstance(step1_data, dict) else step1_data
    
    print(f"Loading local rule results from: {local_result_json_path}")
    local_data = load_json_or_jsonl(Path(local_result_json_path))
    local_rows = local_data.get("rows", []) if isinstance(local_data, dict) else local_data
    
    # 构建本地规则结果索引
    local_rows_by_row_id: Dict[str, List[Dict[str, Any]]] = {}
    for row in local_rows:
        row_id = row.get("row_id", "")
        if row_id:
            local_rows_by_row_id.setdefault(row_id, []).append(row)
    
    # 计算批次
    total_rows = len(step1_rows)
    total_batches = (total_rows + batch_size - 1) // batch_size
    
    print(f"Total rows: {total_rows}, Batch size: {batch_size}, Total batches: {total_batches}")
    print(f"Knowledge DB: {knowledge_db_path}")
    print(f"Model: {model}")
    
    # 检查知识库是否存在
    if not Path(knowledge_db_path).exists():
        raise FileNotFoundError(f"Knowledge database not found: {knowledge_db_path}")
    
    # 逐批处理
    all_result_rows: List[Dict[str, Any]] = []
    
    for batch_index in range(1, total_batches + 1):
        start_idx = (batch_index - 1) * batch_size
        end_idx = min(start_idx + batch_size, total_rows)
        batch_rows = step1_rows[start_idx:end_idx]
        
        print(f"\n{'='*60}")
        print(f"Processing batch {batch_index}/{total_batches} (rows {start_idx+1}-{end_idx})")
        print(f"{'='*60}")
        
        batch_result = run_step3_retrieval_batch(
            batch_step1_rows=batch_rows,
            local_rows_by_row_id=local_rows_by_row_id,
            standard_document=standard_document,
            output_path=output_path,
            batch_index=batch_index,
            total_batches=total_batches,
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            retries=retries,
            knowledge_db_path=knowledge_db_path,
        )
        
        batch_rows_result = batch_result.get("rows", [])
        all_result_rows.extend(batch_rows_result)
        
        print(f"Batch {batch_index} completed: {len(batch_rows_result)} rows")
    
    # 合并最终结果
    final_result = {
        "meta": {
            "task_name": "project_component_feature_calc_matching",
            "standard_document": standard_document,
            "generated_at": datetime.now().astimezone().isoformat(),
            "review_stage": "retrieval_model_refine",
            "retrieval_augmented": True,
            "knowledge_db": knowledge_db_path,
            "model": model,
            "total_rows": total_rows,
            "total_batches": total_batches,
        },
        "rows": all_result_rows,
    }
    
    # 保存最终结果
    final_json_path = output_path / FINAL_JSON_NAME
    write_json(final_json_path, final_result)
    print(f"\nFinal result saved to: {final_json_path}")
    
    # 生成 HTML 报告
    try:
        html_report_path = output_path / "project_component_feature_calc_matching_result.html"
        build_step3_html_report(
            input_json_path=final_json_path,
            output_html_path=html_report_path,
        )
        print(f"HTML report saved to: {html_report_path}")
    except Exception as e:
        print(f"Warning: Failed to generate HTML report: {e}")
    
    return final_result


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description="Step3 Retrieval-Augmented Processing")
    parser.add_argument("--step1", required=True, help="Path to Step1 result JSON")
    parser.add_argument("--local", required=True, help="Path to local rule result JSON")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--standard", default="", help="Standard document name")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model name")
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY"), help="API key")
    parser.add_argument("--base-url", default=os.getenv("OPENAI_BASE_URL"), help="Base URL")
    parser.add_argument("--timeout", type=float, default=DEFAULT_REQUEST_TIMEOUT_SECONDS, help="Request timeout")
    parser.add_argument("--retries", type=int, default=DEFAULT_CONNECTION_RETRIES, help="Connection retries")
    parser.add_argument("--batch-size", type=int, default=20, help="Batch size")
    parser.add_argument("--knowledge-db", default=RETRIEVAL_KNOWLEDGE_DB_PATH, help="Knowledge database path")
    
    args = parser.parse_args()
    
    # 加载模型配置
    step_model_cfg = load_step_model_config("step3")
    model = args.model or step_model_cfg.get("model") or DEFAULT_MODEL
    api_key = args.api_key or step_model_cfg.get("openai_api_key") or os.getenv("OPENAI_API_KEY")
    base_url = args.base_url or step_model_cfg.get("openai_base_url") or os.getenv("OPENAI_BASE_URL")
    
    result = run_step3_retrieval(
        step1_json_path=args.step1,
        local_result_json_path=args.local,
        output_dir=args.output,
        standard_document=args.standard,
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=args.timeout,
        retries=args.retries,
        batch_size=args.batch_size,
        knowledge_db_path=args.knowledge_db,
    )
    
    print(f"\nCompleted: {len(result.get('rows', []))} rows processed")


if __name__ == "__main__":
    main()
