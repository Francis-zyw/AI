from __future__ import annotations

import argparse
import configparser
import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence

from pipeline_v2.step3_engine.api import (
    build_component_source_table,
    build_feature_expression_items,
    build_feature_expression_text_from_items,
    call_openai_model,
    clean_feature_text,
    dedupe_preserve_order,
    extract_json_text,
    load_json_or_jsonl,
    merge_runtime_value,
    normalize_feature_expression_items,
    normalize_text,
    normalize_unit,
    parse_optional_bool,
    parse_optional_int,
    resolve_path_from_config,
    select_best_calculation,
    strip_affixes,
    summarize_source_entry_for_prompt,
    write_json,
    write_text,
)


FEATURE_SPLIT_RE = re.compile(r"[、,，;；/]+")
DEFAULT_MODEL = "gpt-5.4"
DEFAULT_CONFIG_NAME = "step4_runtime_config.ini"
DEFAULT_MAX_ITEMS_PER_BATCH = 20
FINAL_JSON_NAME = "step4_direct_match_result.json"
LOCAL_JSON_NAME = "step4_local_direct_match_result.json"
LOCAL_RESULT_JSON_NAME = LOCAL_JSON_NAME
RUN_SUMMARY_NAME = "run_summary.json"
FROM_STEP3_JSON_NAME = "step4_from_step3_result.json"
FROM_STEP3_MARKDOWN_NAME = "step4_from_step3_result.md"


@dataclass(frozen=True)
class DirectMatchCatalog:
    source_table: List[Dict[str, Any]]
    source_by_name: Dict[str, Dict[str, Any]]


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def get_default_config_path() -> Path:
    return Path(__file__).with_name(DEFAULT_CONFIG_NAME)


def get_default_components_path() -> Path:
    root = get_project_root()
    json_path = root / "data" / "input" / "components.json"
    if json_path.exists():
        return json_path
    jsonl_path = root / "data" / "input" / "components.jsonl"
    if jsonl_path.exists():
        return jsonl_path
    raise FileNotFoundError("未找到默认构件库，请检查 data/input/components.json 或 components.jsonl。")


def sanitize_path_segment(text: str) -> str:
    sanitized = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", str(text or "").strip(), flags=re.UNICODE)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized[:80] or "untitled"


def get_default_output_dir(component_type: str) -> Path:
    return get_project_root() / "data" / "output" / "step4" / sanitize_path_segment(component_type)


def _build_row_id(index: int) -> str:
    return f"S4-{int(index):04d}"


def load_runtime_config(config_path: str | Path | None) -> Dict[str, Any]:
    if not config_path:
        return {}

    resolved_path = Path(config_path)
    if not resolved_path.exists():
        raise FileNotFoundError(f"未找到 Step 4 配置文件：{resolved_path}")

    import configparser

    parser = configparser.ConfigParser()
    parser.read(resolved_path, encoding="utf-8")

    return {
        "config_path": str(resolved_path),
        "components_path": resolve_path_from_config(
            parser.get("paths", "components", fallback=""),
            resolved_path,
            must_exist=True,
        ),
        "synonym_library_path": resolve_path_from_config(
            parser.get("paths", "synonym_library", fallback=""),
            resolved_path,
            must_exist=True,
        ),
        "output_dir": resolve_path_from_config(
            parser.get("paths", "output", fallback=""),
            resolved_path,
            must_exist=False,
        ),
        "model": str(parser.get("model", "model", fallback="")).strip() or None,
        "reasoning_effort": str(parser.get("model", "reasoning_effort", fallback="")).strip() or None,
        "openai_api_key": str(parser.get("model", "openai_api_key", fallback="")).strip() or None,
        "openai_base_url": str(parser.get("model", "openai_base_url", fallback="")).strip() or None,
        "component_type": str(
            parser.get(
                "run",
                "component_type",
                fallback=parser.get("match", "component_type", fallback=""),
            )
        ).strip()
        or None,
        "max_items_per_batch": parse_optional_int(parser.get("run", "max_items_per_batch", fallback="")),
        "prepare_only": parse_optional_bool(parser.get("run", "prepare_only", fallback="")),
        "local_only": parse_optional_bool(parser.get("run", "local_only", fallback="")),
    }


def resolve_runtime_options(args: Any) -> Dict[str, Any]:
    explicit_config_path = Path(args.config).expanduser() if getattr(args, "config", None) else None
    default_config_path = get_default_config_path()

    if explicit_config_path is not None:
        config_values = load_runtime_config(explicit_config_path)
        config_path_text = str(explicit_config_path)
    elif default_config_path.exists():
        config_values = load_runtime_config(default_config_path)
        config_path_text = str(default_config_path)
    else:
        config_values = {}
        config_path_text = ""

    prepare_only = bool(merge_runtime_value(args.prepare_only, config_values.get("prepare_only"), False))
    local_only = bool(merge_runtime_value(args.local_only, config_values.get("local_only"), False))
    if args.prepare_only is True and args.local_only is None:
        local_only = False

    component_type = str(
        merge_runtime_value(getattr(args, "component_type", None), config_values.get("component_type"), "")
        or ""
    ).strip()
    default_components_path = str(get_default_components_path())
    output_dir = merge_runtime_value(args.output, config_values.get("output_dir"), None)
    if not output_dir and component_type:
        output_dir = str(get_default_output_dir(component_type))

    return {
        "config_path": config_path_text,
        "component_type": component_type,
        "components_path": merge_runtime_value(args.components, config_values.get("components_path"), default_components_path),
        "synonym_library_path": merge_runtime_value(args.synonym_library, config_values.get("synonym_library_path"), None),
        "output_dir": output_dir,
        "model": merge_runtime_value(args.model, config_values.get("model"), DEFAULT_MODEL),
        "reasoning_effort": merge_runtime_value(args.reasoning_effort, config_values.get("reasoning_effort"), "medium"),
        "max_items_per_batch": merge_runtime_value(
            args.max_items_per_batch,
            config_values.get("max_items_per_batch"),
            DEFAULT_MAX_ITEMS_PER_BATCH,
        ),
        "prepare_only": prepare_only,
        "local_only": local_only,
        "openai_api_key": merge_runtime_value(getattr(args, "openai_api_key", None), config_values.get("openai_api_key"), None),
        "openai_base_url": merge_runtime_value(getattr(args, "openai_base_url", None), config_values.get("openai_base_url"), None),
    }


def apply_runtime_environment(runtime_options: Dict[str, Any]) -> Dict[str, str | None]:
    previous = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
        "OPENAI_BASE_URL": os.getenv("OPENAI_BASE_URL"),
    }
    effective_api_key = runtime_options.get("openai_api_key") or os.getenv("OPENAI_API_KEY")
    effective_base_url = runtime_options.get("openai_base_url") or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    if effective_api_key:
        os.environ["OPENAI_API_KEY"] = str(effective_api_key)
    if effective_base_url:
        os.environ["OPENAI_BASE_URL"] = str(effective_base_url)
    return previous


def restore_runtime_environment(previous: Dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _normalize_component_key(text: str) -> str:
    return normalize_text(str(text or ""))


def _normalize_bill_item(bill_item: Dict[str, Any]) -> Dict[str, Any]:
    project_features = _normalize_feature_source_text(str(bill_item.get("project_features", "") or ""))
    quantity_rule = clean_feature_text(str(bill_item.get("quantity_rule", "") or ""))
    work_content = clean_feature_text(str(bill_item.get("work_content", "") or ""))
    if not quantity_rule and work_content:
        quantity_rule = work_content

    return {
        "row_id": str(bill_item.get("row_id", "")).strip(),
        "project_code": str(bill_item.get("project_code", "")).strip(),
        "project_name": str(bill_item.get("project_name", "")).strip(),
        "project_features": project_features,
        "measurement_unit": str(bill_item.get("measurement_unit", "")).strip(),
        "quantity_rule": quantity_rule,
        "work_content": work_content,
        "component_type": str(bill_item.get("component_type", "")).strip(),
    }


def _normalize_feature_source_text(text: str) -> str:
    value = str(text or "")
    value = value.replace("\u3000", " ")
    value = value.replace("．", ".").replace("：", ":")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n+", "\n", value)
    return value.strip()


def _explode_atomic_features(project_features: str) -> str:
    cleaned = _normalize_feature_source_text(project_features)
    if not cleaned:
        return ""

    atomic_lines: List[str] = []
    next_order = 1
    for fragment in cleaned.splitlines():
        raw_fragment = fragment.strip()
        if not raw_fragment:
            continue

        match = re.match(r"^\s*(\d+)\s*[.\-]?\s*(.+?)\s*$", raw_fragment)
        if match:
            raw_fragment = match.group(2).strip()

        parts = [part.strip(" ：:。.;；,，") for part in FEATURE_SPLIT_RE.split(raw_fragment) if part.strip(" ：:。.;；,，")]
        if len(parts) <= 1:
            atomic_lines.append(f"{next_order}.{raw_fragment}")
            next_order += 1
            continue

        for part in parts:
            atomic_lines.append(f"{next_order}.{part}")
            next_order += 1

    return "\n".join(atomic_lines)


def build_direct_match_catalog(
    components_payload: Sequence[Dict[str, Any]],
    synonym_library_payload: Any | None = None,
) -> DirectMatchCatalog:
    source_table = build_component_source_table(components_payload, synonym_library_payload or {})
    source_by_name = {entry["component_name"]: entry for entry in source_table}
    return DirectMatchCatalog(source_table=source_table, source_by_name=source_by_name)


def resolve_component_source_entry(
    component_type: str,
    catalog: DirectMatchCatalog,
) -> Dict[str, Any] | None:
    if not component_type:
        return None

    normalized_key = _normalize_component_key(component_type)
    stripped_key = _normalize_component_key(strip_affixes(component_type))

    for entry in catalog.source_table:
        candidate_names = dedupe_preserve_order(
            [entry.get("component_name", "")] + list(entry.get("query_names", [])) + list(entry.get("aliases", []))
        )
        for candidate_name in candidate_names:
            candidate_key = _normalize_component_key(candidate_name)
            stripped_candidate_key = _normalize_component_key(strip_affixes(candidate_name))
            if candidate_key == normalized_key or candidate_key == stripped_key:
                return entry
            if stripped_candidate_key and (stripped_candidate_key == normalized_key or stripped_candidate_key == stripped_key):
                return entry

    return catalog.source_by_name.get(component_type)


def _build_direct_match_row(
    normalized_bill_item: Dict[str, Any],
    catalog: DirectMatchCatalog,
    *,
    row_id: str,
) -> Dict[str, Any]:
    source_entry = resolve_component_source_entry(normalized_bill_item["component_type"], catalog)
    feature_text = _explode_atomic_features(normalized_bill_item["project_features"])
    feature_expression_items = build_feature_expression_items(feature_text, source_entry, chapter_feature_hints=None)
    calculation = select_best_calculation(source_entry, normalized_bill_item)

    if not source_entry:
        match_status = "unmatched"
        reasoning = f"未找到指定构件类型 `{normalized_bill_item['component_type']}` 对应的构件库记录。"
        review_status = "pending"
        confidence = 0.0
    else:
        matched_count = sum(1 for item in feature_expression_items if item.get("matched"))
        if matched_count == len(feature_expression_items) and calculation.get("calculation_item_code"):
            match_status = "matched"
        elif matched_count:
            match_status = "candidate_only"
        else:
            match_status = "unmatched"
        reasoning = f"按指定构件类型 `{source_entry.get('component_name', '')}` 直接匹配特征表达式与计算项目。"
        review_status = "suggested" if match_status == "matched" else "pending"
        confidence = 0.9 if match_status == "matched" else 0.55 if match_status == "candidate_only" else 0.1

    return {
        "row_id": row_id,
        "project_code": normalized_bill_item["project_code"],
        "project_name": normalized_bill_item["project_name"],
        "component_type": normalized_bill_item["component_type"],
        "source_component_name": source_entry.get("component_name", "") if source_entry else "",
        "project_features_raw": normalized_bill_item["project_features"],
        "feature_expression_items": feature_expression_items,
        "feature_expression_text": build_feature_expression_text_from_items(feature_expression_items),
        "quantity_rule": normalized_bill_item["quantity_rule"],
        "work_content": normalized_bill_item["work_content"],
        "quantity_component": source_entry.get("component_name", "") if source_entry else "",
        "resolved_component_name": source_entry.get("component_name", "") if source_entry else "",
        "calculation_item_name": calculation.get("calculation_item_name", ""),
        "calculation_item_code": calculation.get("calculation_item_code", ""),
        "measurement_unit": calculation.get("measurement_unit", normalized_bill_item["measurement_unit"]),
        "match_status": match_status,
        "review_status": review_status,
        "confidence": confidence,
        "reasoning": reasoning,
        "manual_notes": "",
    }


def direct_match_bill_item(
    bill_item: Dict[str, Any],
    components_payload: Sequence[Dict[str, Any]],
    synonym_library_payload: Any | None = None,
) -> Dict[str, Any]:
    normalized_bill_item = _normalize_bill_item(bill_item)
    catalog = build_direct_match_catalog(components_payload, synonym_library_payload)
    return _build_direct_match_row(
        normalized_bill_item,
        catalog,
        row_id=normalized_bill_item.get("row_id", "") or _build_row_id(1),
    )


def direct_match_bill_items(
    bill_items: Sequence[Dict[str, Any]],
    components_payload: Sequence[Dict[str, Any]],
    synonym_library_payload: Any | None = None,
) -> List[Dict[str, Any]]:
    catalog = build_direct_match_catalog(components_payload, synonym_library_payload)
    results: List[Dict[str, Any]] = []
    for index, bill_item in enumerate(bill_items, start=1):
        normalized_bill_item = _normalize_bill_item(bill_item)
        results.append(
            _build_direct_match_row(
                normalized_bill_item,
                catalog,
                row_id=normalized_bill_item.get("row_id", "") or _build_row_id(index),
            )
        )
    return results


def build_result_statistics(rows: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    return {
        "total_items": len(rows),
        "matched_rows": sum(1 for item in rows if item.get("match_status") == "matched"),
        "candidate_only_rows": sum(1 for item in rows if item.get("match_status") == "candidate_only"),
        "unmatched_rows": sum(1 for item in rows if item.get("match_status") == "unmatched"),
    }


def build_local_direct_match_payload(
    bill_items: Sequence[Dict[str, Any]],
    components_payload: Sequence[Dict[str, Any]],
    synonym_library_payload: Any | None,
    component_type: str,
) -> Dict[str, Any]:
    rows = direct_match_bill_items(bill_items, components_payload, synonym_library_payload)
    normalized_rows: List[Dict[str, Any]] = []
    for row in rows:
        normalized_rows.append(
            {
                "row_id": row.get("row_id", ""),
                "project_code": row.get("project_code", ""),
                "project_name": row.get("project_name", ""),
                "component_type": row.get("component_type", ""),
                "source_component_name": row.get("source_component_name", ""),
                "project_features_raw": row.get("project_features_raw", ""),
                "feature_expression_items": normalize_feature_expression_items(row.get("feature_expression_items")),
                "feature_expression_text": str(row.get("feature_expression_text", "")).strip(),
                "quantity_rule": row.get("quantity_rule", ""),
                "work_content": row.get("work_content", ""),
                "quantity_component": row.get("quantity_component", ""),
                "resolved_component_name": row.get("resolved_component_name", ""),
                "calculation_item_name": row.get("calculation_item_name", ""),
                "calculation_item_code": row.get("calculation_item_code", ""),
                "measurement_unit": normalize_unit(str(row.get("measurement_unit", "")).strip()),
                "match_status": row.get("match_status", "unmatched"),
                "match_basis": "direct_rule",
                "confidence": float(row.get("confidence", 0.0) or 0.0),
                "review_status": row.get("review_status", "pending"),
                "reasoning": row.get("reasoning", ""),
                "manual_notes": row.get("manual_notes", ""),
            }
        )

    return {
        "meta": {
            "task_name": "step4_direct_match",
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "specified_component_type": component_type,
            "generation_mode": "local_direct",
        },
        "statistics": build_result_statistics(normalized_rows),
        "rows": normalized_rows,
    }


def chunk_list(items: Sequence[Any], batch_size: int) -> List[List[Any]]:
    if batch_size <= 0:
        return [list(items)]
    return [list(items[index:index + batch_size]) for index in range(0, len(items), batch_size)]


def build_prompt_batch_payload(
    local_batch_rows: Sequence[Dict[str, Any]],
    source_entry: Dict[str, Any] | None,
) -> List[Dict[str, Any]]:
    source_summary = summarize_source_entry_for_prompt(source_entry) if source_entry else {}
    return [{"local_row": row, "source_component": source_summary} for row in local_batch_rows]


def build_prompt_text(
    local_batch_rows: Sequence[Dict[str, Any]],
    batch_payload: Sequence[Dict[str, Any]],
    component_type: str,
    batch_index: int,
    total_batches: int,
) -> str:
    instructions = [
        "你是 Step4 构件直匹配复核助手。",
        f"固定构件类型: {component_type}",
        "任务: 基于本地直匹配结果和指定构件类型的属性/计算项目，复核并修正项目特征表达式与计算项目。",
        "限制:",
        "1. 不要改动 row_id、project_code、project_name、component_type。",
        "2. 不要把 source_component_name / quantity_component / resolved_component_name 改成别的构件类型。",
        "3. 只输出合法 JSON，顶层必须包含 meta 和 rows。",
        "4. rows 必须覆盖当前批次每一行，不能遗漏。",
        "5. rows 允许修改的核心字段为：feature_expression_items, feature_expression_text, calculation_item_name, calculation_item_code, measurement_unit, match_status, confidence, review_status, reasoning, manual_notes。",
        "6. 如果本地结果已经合理，可以直接保留。",
        "7. feature_expression_items 每项字段固定为：order, raw_text, label, attribute_name, attribute_code, value_expression, expression, matched。",
        "",
        f"当前批次信息: batch_index={batch_index}, total_batches={total_batches}, current_batch_item_count={len(local_batch_rows)}",
        "",
        "【LOCAL_DIRECT_MATCH_ROWS】",
        json.dumps(local_batch_rows, ensure_ascii=False, indent=2),
        "",
        "【ROW_SOURCE_COMPONENT_CONTEXT】",
        json.dumps(batch_payload, ensure_ascii=False, indent=2),
    ]
    return "\n".join(instructions)


def normalize_model_result_row(record: Dict[str, Any]) -> Dict[str, Any]:
    provided_fields = set(record.keys())
    confidence = record.get("confidence", 0.0)
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = 0.0

    feature_expression_items = normalize_feature_expression_items(record.get("feature_expression_items"))
    feature_expression_text = str(record.get("feature_expression_text", "")).strip()
    if not feature_expression_text:
        feature_expression_text = build_feature_expression_text_from_items(feature_expression_items)

    return {
        "_provided_fields": sorted(provided_fields),
        "row_id": str(record.get("row_id", "")).strip(),
        "project_code": str(record.get("project_code", "")).strip(),
        "project_name": str(record.get("project_name", "")).strip(),
        "component_type": str(record.get("component_type", "")).strip(),
        "source_component_name": str(record.get("source_component_name", "")).strip(),
        "project_features_raw": str(record.get("project_features_raw", "")).strip(),
        "feature_expression_items": feature_expression_items,
        "feature_expression_text": feature_expression_text,
        "quantity_rule": str(record.get("quantity_rule", "")).strip(),
        "work_content": str(record.get("work_content", "")).strip(),
        "quantity_component": str(record.get("quantity_component", "")).strip(),
        "resolved_component_name": str(record.get("resolved_component_name", "")).strip(),
        "calculation_item_name": str(record.get("calculation_item_name", "")).strip(),
        "calculation_item_code": str(record.get("calculation_item_code", "")).strip(),
        "measurement_unit": normalize_unit(str(record.get("measurement_unit", "")).strip()),
        "match_status": str(record.get("match_status", "")).strip() or "unmatched",
        "match_basis": str(record.get("match_basis", "")).strip() or "model_refine",
        "confidence": max(0.0, min(1.0, confidence_value)),
        "review_status": str(record.get("review_status", "")).strip() or "pending",
        "reasoning": str(record.get("reasoning", "")).strip(),
        "manual_notes": str(record.get("manual_notes", "") or record.get("notes", "")).strip(),
    }


def normalize_model_result_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    if not isinstance(meta, dict):
        meta = {}
    if not isinstance(rows, list):
        raise ValueError("模型输出中的 rows 字段必须为数组。")

    return {
        "meta": {
            "task_name": str(meta.get("task_name", "step4_direct_match")),
            "generated_at": str(meta.get("generated_at", datetime.now().astimezone().isoformat(timespec="seconds"))),
            "review_stage": str(meta.get("review_stage", "model_refine")),
        },
        "rows": [normalize_model_result_row(item) for item in rows if isinstance(item, dict)],
    }


def merge_model_row_with_local(model_row: Dict[str, Any], local_row: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(local_row)
    provided_fields = set(model_row.get("_provided_fields", []))
    for key, value in model_row.items():
        if key.startswith("_"):
            continue
        if provided_fields and key not in provided_fields and key != "row_id":
            continue
        if key == "feature_expression_items":
            merged[key] = value
            continue
        if isinstance(value, str):
            if value.strip():
                merged[key] = value.strip()
            continue
        if value not in (None, [], {}):
            merged[key] = value

    merged["confidence"] = max(0.0, min(1.0, float(merged.get("confidence", 0.0) or 0.0)))
    merged["feature_expression_items"] = normalize_feature_expression_items(merged.get("feature_expression_items"))
    merged["feature_expression_text"] = (
        str(merged.get("feature_expression_text", "")).strip()
        or build_feature_expression_text_from_items(merged["feature_expression_items"])
    )
    merged["measurement_unit"] = normalize_unit(str(merged.get("measurement_unit", "")).strip())
    merged["review_status"] = str(merged.get("review_status", "")).strip() or "pending"
    merged["match_basis"] = str(merged.get("match_basis", "")).strip() or "model_refine"
    return merged


def ensure_all_rows_present(
    model_rows: Sequence[Dict[str, Any]],
    local_rows: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    local_by_row_id = {row["row_id"]: row for row in local_rows}
    model_by_row_id = {
        row["row_id"]: row
        for row in model_rows
        if str(row.get("row_id", "")).strip()
    }
    merged_rows: List[Dict[str, Any]] = []
    for local_row in local_rows:
        row_id = local_row["row_id"]
        if row_id in model_by_row_id:
            merged_rows.append(merge_model_row_with_local(model_by_row_id[row_id], local_row))
        else:
            merged_rows.append(dict(local_row))
    return merged_rows


def build_result_markdown(rows: Sequence[Dict[str, Any]]) -> str:
    lines = [
        "| 项目编码 | 项目名称 | 指定构件 | 项目特征表达式 | 计算项目 | 单位 | 匹配状态 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {project_code} | {project_name} | {quantity_component} | {feature_expression_text} | {calculation_item_code} | {measurement_unit} | {match_status} |".format(
                project_code=row.get("project_code", ""),
                project_name=row.get("project_name", ""),
                quantity_component=row.get("quantity_component", ""),
                feature_expression_text=str(row.get("feature_expression_text", "")).replace("|", "\\|"),
                calculation_item_code=row.get("calculation_item_code", ""),
                measurement_unit=row.get("measurement_unit", ""),
                match_status=row.get("match_status", ""),
            )
        )
    return "\n".join(lines) + "\n"


def resolve_step3_component_type(row: Dict[str, Any], fallback_component_type: str | None = None) -> str:
    if fallback_component_type:
        return str(fallback_component_type).strip()

    for key in ("quantity_component", "resolved_component_name", "source_component_name", "component_type"):
        value = str(row.get(key, "")).strip()
        if value:
            return value
    return ""


def normalize_step3_row_to_step4_item(
    row: Dict[str, Any],
    *,
    component_type: str | None = None,
) -> Dict[str, Any]:
    return {
        "row_id": str(row.get("row_id", "")).strip(),
        "project_code": str(row.get("project_code", "")).strip(),
        "project_name": str(row.get("project_name", "")).strip(),
        "project_features": str(row.get("project_features_raw", "") or row.get("project_features", "")).strip(),
        "measurement_unit": str(row.get("measurement_unit", "")).strip(),
        "quantity_rule": str(row.get("quantity_rule", "")).strip(),
        "work_content": str(row.get("work_content", "") or row.get("notes", "")).strip(),
        "component_type": resolve_step3_component_type(row, fallback_component_type=component_type),
    }


def load_step3_groups_for_step4(
    step3_result_path: str | Path,
    *,
    component_type: str | None = None,
) -> Dict[str, Any]:
    payload = load_json_or_jsonl(Path(step3_result_path))
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        rows = payload["rows"]
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ValueError("Step3 结果必须是包含 rows 数组的 JSON，或直接是结果数组。")

    grouped_items: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    row_order: List[str] = []
    skipped_missing_component = 0
    skipped_unmatched = 0

    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue

        resolved_component_type = resolve_step3_component_type(row, fallback_component_type=component_type)
        match_status = str(row.get("match_status", "")).strip()
        if not resolved_component_type:
            skipped_missing_component += 1
            continue
        if not component_type and match_status not in {"matched", "candidate_only"}:
            skipped_unmatched += 1
            continue

        item = normalize_step3_row_to_step4_item(row, component_type=resolved_component_type)
        row_id = item.get("row_id", "") or f"S3STEP4-{index:04d}"
        item["row_id"] = row_id
        grouped_items[resolved_component_type].append(item)
        row_order.append(row_id)

    return {
        "grouped_items": dict(grouped_items),
        "row_order": row_order,
        "skipped_missing_component": skipped_missing_component,
        "skipped_unmatched": skipped_unmatched,
        "total_source_rows": len(rows),
    }


def get_default_from_step3_output_dir(step3_result_path: str | Path) -> Path:
    source_path = Path(step3_result_path)
    document_name = source_path.parent.name or source_path.stem
    return get_project_root() / "data" / "output" / "step4" / f"from_step3_{sanitize_path_segment(document_name)}"


def run_step4_from_step3_result_pipeline(
    *,
    step3_result_path: str | Path,
    component_type: str | None = None,
    components_path: str | Path | None = None,
    synonym_library_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str | None = "medium",
    max_items_per_batch: int = DEFAULT_MAX_ITEMS_PER_BATCH,
    prepare_only: bool = False,
    local_only: bool = False,
    config_path: str | Path | None = None,
) -> Dict[str, Any]:
    step3_source = Path(step3_result_path).expanduser().resolve()
    grouped_payload = load_step3_groups_for_step4(step3_source, component_type=component_type)
    grouped_items = grouped_payload["grouped_items"]
    if not grouped_items:
        raise ValueError("Step3 结果里没有可用于 Step4 的已定构件行。")

    components_file = Path(components_path) if components_path else get_default_components_path()
    synonym_file = Path(synonym_library_path) if synonym_library_path else None
    output_path = Path(output_dir) if output_dir else get_default_from_step3_output_dir(step3_source)

    component_results: List[Dict[str, Any]] = []
    model_requests = 0
    merged_rows: List[Dict[str, Any]] = []

    for resolved_component_type, bill_items in grouped_items.items():
        component_output_dir = output_path / sanitize_path_segment(resolved_component_type)
        result = run_step4_direct_match_pipeline(
            bill_items=bill_items,
            component_type=resolved_component_type,
            components_path=components_file,
            synonym_library_path=synonym_file,
            output_dir=component_output_dir,
            model=model,
            reasoning_effort=reasoning_effort,
            max_items_per_batch=max_items_per_batch,
            prepare_only=prepare_only,
            local_only=local_only,
        )
        payload = dict(result["payload"])
        summary = dict(result["summary"])
        merged_rows.extend(payload.get("rows", []))
        model_requests += int(summary.get("model_requests", 0) or 0)
        component_results.append(
            {
                "component_type": resolved_component_type,
                "item_count": len(bill_items),
                "output_dir": str(component_output_dir),
                "status": summary.get("status", ""),
            }
        )

    row_order_index = {row_id: index for index, row_id in enumerate(grouped_payload["row_order"])}
    merged_rows.sort(key=lambda row: row_order_index.get(str(row.get("row_id", "")).strip(), len(row_order_index)))

    final_payload = {
        "meta": {
            "task_name": "step4_from_step3_direct_match",
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "step3_result_path": str(step3_source),
            "components_path": str(components_file),
            "synonym_library_path": str(synonym_file) if synonym_file else "",
            "output_dir": str(output_path),
            "generation_mode": "prepare_only" if prepare_only else "local_direct" if local_only else "model_refine",
            "config_path": str(config_path) if config_path else "",
        },
        "statistics": build_result_statistics(merged_rows),
        "rows": merged_rows,
        "component_groups": component_results,
    }
    summary = {
        "status": "prepared_only" if prepare_only else "completed_local_only" if local_only else "completed",
        "step3_result_path": str(step3_source),
        "components_path": str(components_file),
        "synonym_library_path": str(synonym_file) if synonym_file else "",
        "output_dir": str(output_path),
        "specified_component_type": str(component_type or "").strip(),
        "component_group_count": len(component_results),
        "selected_item_count": len(merged_rows),
        "total_source_rows": grouped_payload["total_source_rows"],
        "skipped_rows_without_component_type": grouped_payload["skipped_missing_component"],
        "skipped_rows_without_match": grouped_payload["skipped_unmatched"],
        "model": model,
        "reasoning_effort": reasoning_effort,
        "model_requests": model_requests,
        **final_payload["statistics"],
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }

    write_json(output_path / FROM_STEP3_JSON_NAME, final_payload)
    write_text(output_path / FROM_STEP3_MARKDOWN_NAME, build_result_markdown(final_payload["rows"]))
    write_json(output_path / RUN_SUMMARY_NAME, summary)

    return {
        "result_payload": final_payload,
        "run_summary": summary,
    }


def run_step4_direct_match_pipeline(
    *,
    bill_items: Sequence[Dict[str, Any]],
    component_type: str,
    components_path: str | Path | None = None,
    synonym_library_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str | None = "medium",
    max_items_per_batch: int = DEFAULT_MAX_ITEMS_PER_BATCH,
    prepare_only: bool = False,
    local_only: bool = False,
) -> Dict[str, Any]:
    normalized_component_type = str(component_type or "").strip()
    if not normalized_component_type:
        raise ValueError("Step4 必须提供 component_type。")

    components_file = Path(components_path) if components_path else get_default_components_path()
    synonym_file = Path(synonym_library_path) if synonym_library_path else None
    output_path = Path(output_dir) if output_dir else get_default_output_dir(normalized_component_type)

    normalized_bill_items = [dict(item, component_type=normalized_component_type) for item in bill_items if isinstance(item, dict)]
    components_payload = load_json_or_jsonl(components_file)
    synonym_payload = load_json_or_jsonl(synonym_file) if synonym_file else {}
    catalog = build_direct_match_catalog(components_payload, synonym_payload)
    source_entry = resolve_component_source_entry(normalized_component_type, catalog)

    local_payload = build_local_direct_match_payload(
        bill_items=normalized_bill_items,
        components_payload=components_payload,
        synonym_library_payload=synonym_payload,
        component_type=normalized_component_type,
    )
    local_payload["meta"].update(
        {
            "components_path": str(components_file),
            "synonym_library_path": str(synonym_file) if synonym_file else "",
            "output_dir": str(output_path),
        }
    )

    write_json(output_path / LOCAL_JSON_NAME, local_payload)

    if local_only:
        final_payload = {
            "meta": {
                **local_payload["meta"],
                "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "generation_mode": "local_direct",
            },
            "statistics": dict(local_payload["statistics"]),
            "rows": list(local_payload["rows"]),
        }
        summary = {
            "status": "completed_local_only",
            "specified_component_type": normalized_component_type,
            "components_path": str(components_file),
            "synonym_library_path": str(synonym_file) if synonym_file else "",
            "output_dir": str(output_path),
            **final_payload["statistics"],
            "model_requests": 0,
            "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        write_json(output_path / FINAL_JSON_NAME, final_payload)
        write_text(output_path / "step4_direct_match_result.md", build_result_markdown(final_payload["rows"]))
        write_json(output_path / RUN_SUMMARY_NAME, summary)
        return {"payload": final_payload, "summary": summary}

    local_rows = list(local_payload["rows"])
    row_batches = chunk_list(local_rows, max_items_per_batch)
    total_batches = len(row_batches)
    batch_results: List[Dict[str, Any]] = []
    summary_path = output_path / RUN_SUMMARY_NAME

    for batch_number, local_batch_rows in enumerate(row_batches, start=1):
        prompt_batch_payload = build_prompt_batch_payload(local_batch_rows=local_batch_rows, source_entry=source_entry)
        prompt_text = build_prompt_text(
            local_batch_rows=local_batch_rows,
            batch_payload=prompt_batch_payload,
            component_type=normalized_component_type,
            batch_index=batch_number,
            total_batches=total_batches,
        )
        write_json(output_path / f"batch_{batch_number:03d}_prompt_input.json", prompt_batch_payload)
        write_text(output_path / f"batch_{batch_number:03d}_prompt.txt", prompt_text)

        if prepare_only:
            continue

        try:
            raw_response_text = call_openai_model(
                prompt_text=prompt_text,
                model=model,
                reasoning_effort=reasoning_effort,
            )
            write_text(output_path / f"batch_{batch_number:03d}_model_output.txt", raw_response_text)

            parsed_payload = normalize_model_result_payload(json.loads(extract_json_text(raw_response_text)))
            parsed_rows = ensure_all_rows_present(parsed_payload["rows"], local_batch_rows)
            batch_payload = {
                "meta": parsed_payload["meta"],
                "statistics": build_result_statistics(parsed_rows),
                "rows": parsed_rows,
            }
            write_json(output_path / f"batch_{batch_number:03d}_result.json", batch_payload)
            batch_results.append(batch_payload)
        except Exception as exc:
            error_payload = {
                "status": "failed",
                "specified_component_type": normalized_component_type,
                "components_path": str(components_file),
                "synonym_library_path": str(synonym_file) if synonym_file else "",
                "output_dir": str(output_path),
                "model": model,
                "reasoning_effort": reasoning_effort,
                "failed_batch": batch_number,
                "total_batches": total_batches,
                "error": str(exc),
                "failed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            write_text(output_path / f"batch_{batch_number:03d}_error.txt", str(exc))
            write_json(summary_path, error_payload)
            raise

    if prepare_only:
        summary = {
            "status": "prepared_only",
            "specified_component_type": normalized_component_type,
            "components_path": str(components_file),
            "synonym_library_path": str(synonym_file) if synonym_file else "",
            "output_dir": str(output_path),
            "model": model,
            "reasoning_effort": reasoning_effort,
            "total_items": len(local_rows),
            "total_batches": total_batches,
            "model_requests": 0,
            "prepared_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "next_step": "去掉 --prepare-only 重新运行，脚本才会实际调用模型并生成最终结果。",
            "expected_missing_files": [
                "batch_001_model_output.txt",
                "batch_001_result.json",
                FINAL_JSON_NAME,
            ],
        }
        write_json(summary_path, summary)
        prepared_payload = {
            "meta": {
                **local_payload["meta"],
                "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "generation_mode": "prepare_only",
            },
            "statistics": dict(local_payload["statistics"]),
            "rows": list(local_payload["rows"]),
        }
        return {"payload": prepared_payload, "summary": summary}

    merged_rows: List[Dict[str, Any]] = []
    for item in batch_results:
        merged_rows.extend(item["rows"])
    final_rows = ensure_all_rows_present(merged_rows, local_rows)
    final_payload = {
        "meta": {
            "task_name": "step4_direct_match",
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "specified_component_type": normalized_component_type,
            "components_path": str(components_file),
            "synonym_library_path": str(synonym_file) if synonym_file else "",
            "output_dir": str(output_path),
            "generation_mode": "model_refine",
        },
        "statistics": build_result_statistics(final_rows),
        "rows": final_rows,
    }
    summary = {
        "status": "completed",
        "specified_component_type": normalized_component_type,
        "components_path": str(components_file),
        "synonym_library_path": str(synonym_file) if synonym_file else "",
        "output_dir": str(output_path),
        "model": model,
        "reasoning_effort": reasoning_effort,
        "total_batches": total_batches,
        "model_requests": len(batch_results),
        **final_payload["statistics"],
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    write_json(output_path / FINAL_JSON_NAME, final_payload)
    write_text(output_path / "step4_direct_match_result.md", build_result_markdown(final_rows))
    write_json(summary_path, summary)
    return {"payload": final_payload, "summary": summary}


def run_step4_pipeline(
    *,
    bill_items: Sequence[Dict[str, Any]],
    component_type: str,
    components_path: str | Path | None = None,
    synonym_library_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str | None = "medium",
    max_items_per_batch: int = DEFAULT_MAX_ITEMS_PER_BATCH,
    prepare_only: bool = False,
    local_only: bool = False,
    config_path: str | Path | None = None,
) -> Dict[str, Any]:
    result = run_step4_direct_match_pipeline(
        bill_items=bill_items,
        component_type=component_type,
        components_path=components_path,
        synonym_library_path=synonym_library_path,
        output_dir=output_dir,
        model=model,
        reasoning_effort=reasoning_effort,
        max_items_per_batch=max_items_per_batch,
        prepare_only=prepare_only,
        local_only=local_only,
    )
    payload = dict(result["payload"])
    payload.setdefault("meta", {})
    if config_path:
        payload["meta"]["config_path"] = str(config_path)
    return {
        "result_payload": payload,
        "run_summary": dict(result["summary"]),
    }
