from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Sequence

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


def build_bill_item_key(item: Dict[str, Any], ordinal: int) -> str:
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
            }
        )
    return normalized


def load_component_context(
    components_path: str | Path,
    synonym_library_path: str | Path | None = None,
) -> Dict[str, Any]:
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


def match_bill_items_to_component(
    bill_items: Sequence[Dict[str, Any]],
    component_type: str,
    components_path: str | Path,
    synonym_library_path: str | Path | None = None,
) -> Dict[str, Any]:
    normalized_items = normalize_bill_items(bill_items)
    component_context = load_component_context(components_path, synonym_library_path=synonym_library_path)
    source_entry = resolve_component_entry(component_type, component_context)

    results: List[Dict[str, Any]] = []
    for item in normalized_items:
        feature_expression_items = build_feature_expression_items(item["project_features"], source_entry)
        calculation = select_best_calculation(source_entry, item)
        matched = source_entry is not None
        results.append(
            {
                "result_id": item["row_id"].replace("BI-", "FM-"),
                "row_id": item["row_id"],
                "project_code": item["project_code"],
                "project_name": item["project_name"],
                "project_features_raw": item["project_features"],
                "measurement_unit": calculation.get("measurement_unit", item["measurement_unit"]),
                "quantity_rule": item["quantity_rule"],
                "work_content": item["work_content"],
                "specified_component_type": component_type,
                "resolved_component_name": source_entry.get("component_name", "") if source_entry else "",
                "feature_expression_items": feature_expression_items,
                "feature_expression_text": build_feature_expression_text(feature_expression_items),
                "calculation_item_name": calculation.get("calculation_item_name", ""),
                "calculation_item_code": calculation.get("calculation_item_code", ""),
                "calculation_basis": calculation.get("calculation_basis", ""),
                "match_status": "matched" if matched else "unmatched",
                "review_status": "suggested" if matched else "pending",
                "reasoning": (
                    f"按指定构件类型“{component_type}”直接匹配项目特征与计算项目。"
                    if matched
                    else f"未在构件库中找到指定构件类型“{component_type}”。"
                ),
            }
        )

    return {
        "meta": {
            "task_name": "step3_forced_component_match",
            "specified_component_type": component_type,
            "components_path": str(Path(components_path).resolve()),
            "synonym_library_path": str(Path(synonym_library_path).resolve()) if synonym_library_path else "",
            "total_items": len(normalized_items),
        },
        "rows": results,
    }
