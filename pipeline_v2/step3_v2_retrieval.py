"""
Step3 V2 Retrieval-Augmented Module
检索增强版的 Step3 处理模块，集成知识库检索功能
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Sequence

# 导出原有的工具函数
from pipeline_v2.step3_engine.api import (
    build_alias_index,
    build_component_source_table,
    build_feature_expression_items,
    build_feature_expression_text,
    clean_project_name,
    load_json_or_jsonl,
    normalize_unit,
    select_best_calculation,
)

# 导出检索增强版 API
from pipeline_v2.step3_engine.step3_retrieval_api import (
    run_step3_retrieval,
    run_step3_retrieval_batch,
    build_retrieval_prompt_text,
    load_retrieval_prompt_template,
    RETRIEVAL_PROMPT_TEMPLATE_NAME,
    RETRIEVAL_KNOWLEDGE_DB_PATH,
)

# 导出检索上下文构建器
from pipeline_v2.step3_engine.retrieval_context import (
    build_retrieval_context_batch,
    build_retrieval_context_for_row,
    format_retrieval_context_for_prompt,
    query_knowledge_entries,
    query_wiki_pages,
    build_step1_entry_hits,
    build_step2_entry_hits,
    build_component_wiki_hits,
    build_chapter_wiki_hits,
    build_component_catalog_hits,
    build_database_principles,
)


def build_bill_item_key(item: Dict[str, Any], ordinal: int) -> str:
    """构建清单行唯一标识"""
    digest_source = "|".join(
        [
            str(item.get("project_code", "")).strip(),
            str(item.get("project_name", "")).strip(),
            str(item.get("project_features", "")).strip(),
            str(item.get("measurement_unit", "")).strip(),
            str(item.get("quantity_rule", "")).strip(),
            str(item.get("work_content", "")).strip(),
            str(ordinal),
        ]
    )
    digest = hashlib.md5(digest_source.encode("utf-8")).hexdigest()[:12]
    return f"BI-{ordinal:04d}-{digest}"


def normalize_bill_items(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """规范化清单行数据"""
    normalized: List[Dict[str, Any]] = []
    for ordinal, raw in enumerate(items, start=1):
        normalized.append(
            {
                "row_id": build_bill_item_key(raw, ordinal),
                "project_code": str(raw.get("project_code", "")).strip(),
                "project_name": clean_project_name(raw.get("project_name", "")),
                "project_features": str(raw.get("project_features", "")).strip(),
                "measurement_unit": normalize_unit(str(raw.get("measurement_unit", "")).strip()),
                "quantity_rule": str(raw.get("quantity_rule", "")).strip(),
                "work_content": str(raw.get("work_content", "")).strip(),
                "component_type": str(raw.get("component_type", "")).strip(),
                "section_path": str(raw.get("section_path", "")).strip(),
                "table_title": str(raw.get("table_title", "")).strip(),
                "chapter_root": str(raw.get("chapter_root", "")).strip(),
                "chapter_title": str(raw.get("chapter_title", "")).strip(),
            }
        )
    return normalized


def load_component_context(
    components_path: str | Path,
    synonym_library_path: str | Path | None = None,
) -> Dict[str, Any]:
    """加载构件上下文"""
    components_payload = load_json_or_jsonl(Path(components_path))
    synonym_payload = load_json_or_jsonl(Path(synonym_library_path)) if synonym_library_path else {}
    source_table = build_component_source_table(components_payload, synonym_payload)
    alias_index = build_alias_index(source_table, synonym_payload)
    source_table_by_name = {entry["component_name"]: entry for entry in source_table}
    return {
        "source_table": source_table,
        "source_table_by_name": source_table_by_name,
        "alias_index": alias_index,
        "synonym_payload": synonym_payload,
    }


def resolve_component_entry(
    component_type: str,
    component_context: Dict[str, Any],
) -> Dict[str, Any] | None:
    """解析构件条目"""
    source_table_by_name = component_context["source_table_by_name"]
    if component_type in source_table_by_name:
        return source_table_by_name[component_type]

    alias_index = component_context["alias_index"]
    candidates = alias_index.get(component_type, [])
    if not candidates:
        from pipeline_v2.step3_engine.api import normalize_text, strip_affixes

        normalized = normalize_text(component_type)
        stripped = normalize_text(strip_affixes(component_type))
        candidates = alias_index.get(normalized, []) + alias_index.get(stripped, [])
    for name in candidates:
        if name in source_table_by_name:
            return source_table_by_name[name]
    return None


__all__ = [
    # 基础工具函数
    "build_bill_item_key",
    "normalize_bill_items",
    "load_component_context",
    "resolve_component_entry",
    # 检索增强版 API
    "run_step3_retrieval",
    "run_step3_retrieval_batch",
    "build_retrieval_prompt_text",
    "load_retrieval_prompt_template",
    "RETRIEVAL_PROMPT_TEMPLATE_NAME",
    "RETRIEVAL_KNOWLEDGE_DB_PATH",
    # 检索上下文构建器
    "build_retrieval_context_batch",
    "build_retrieval_context_for_row",
    "format_retrieval_context_for_prompt",
    "query_knowledge_entries",
    "query_wiki_pages",
    "build_step1_entry_hits",
    "build_step2_entry_hits",
    "build_component_wiki_hits",
    "build_chapter_wiki_hits",
    "build_component_catalog_hits",
    "build_database_principles",
]
