from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence

from pipeline_v2.model_runtime import DEFAULT_OPENAI_MODEL, DEFAULT_REASONING_EFFORT
from pipeline_v2.step2_engine.api import (
    build_synonym_library,
    ensure_all_components_present,
    merge_window_mappings,
    normalize_mapping,
    normalize_result_payload,
    normalize_optional_text,
)


BILL_CHAPTER_PATTERN = re.compile(r"^附录\s*[A-Z]", re.IGNORECASE)
STEP2_VALIDATION_FALLBACK_MODEL = DEFAULT_OPENAI_MODEL
STEP2_VALIDATION_MIN_DEVIATION_SCORE = 0.6
STEP2_VALIDATION_STATUS_WEIGHTS = {
    "matched": 0.0,
    "candidate_only": 0.45,
    "conflict": 0.75,
    "unmatched": 1.0,
}
STEP2_CHAPTER_MATCH_TYPE_WEIGHTS = {
    "chapter_heading": 6.0,
    "exact": 5.5,
    "exact_match": 5.5,
    "exact_name_overlap": 5.5,
    "exact_keyword_match": 5.0,
    "direct_match": 5.0,
    "partial_match": 4.0,
    "broader_category_match": 3.0,
    "chapter_semantic": 2.5,
    "semantic_match": 2.0,
    "candidate_only": 1.0,
    "unmatched": 0.0,
    "none": 0.0,
}
STEP2_CHAPTER_REVIEW_STATUS_WEIGHTS = {
    "auto_accepted": 3.0,
    "auto": 2.5,
    "suggested": 2.0,
    "unreviewed": 1.0,
    "needs_review": 0.5,
    "needs_manual_review": 0.5,
    "pending": 0.0,
    "pending_review": 0.0,
}
STEP2_CHAPTER_AUTO_RESOLVE_SCORE_GAP = 120.0


def load_json_or_jsonl(path: str | Path) -> Any:
    source = Path(path)
    if source.suffix.lower() == ".jsonl":
        items: List[Any] = []
        with source.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if line:
                    items.append(json.loads(line))
        return items
    return json.loads(source.read_text(encoding="utf-8"))


def normalize_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def is_bill_chapter_title(chapter_title: str) -> bool:
    return bool(BILL_CHAPTER_PATTERN.match(str(chapter_title or "").strip()))


def resolve_standard_document_name(step1_source_path: str | Path) -> str:
    source_path = normalize_path(step1_source_path)
    if source_path.name == "chapter_index.json" and source_path.parent.name == "chapter_regions":
        return source_path.parent.parent.name
    if source_path.parent.name == "chapter_regions":
        return source_path.parent.parent.name
    if source_path.is_dir() and source_path.name == "chapter_regions":
        return source_path.parent.name
    if source_path.is_dir():
        return source_path.name
    return source_path.stem


def resolve_chapter_index_path(step1_source_path: str | Path) -> Path:
    source_path = normalize_path(step1_source_path)
    if source_path.is_file():
        if source_path.name == "chapter_index.json":
            return source_path
        raise FileNotFoundError(f"Step2 V2 需要 chapter_index.json，而不是单章文件：{source_path}")

    direct_index = source_path / "chapter_index.json"
    if direct_index.exists():
        return direct_index

    nested_index = source_path / "chapter_regions" / "chapter_index.json"
    if nested_index.exists():
        return nested_index

    raise FileNotFoundError(f"未能识别 Step1 chapter_index.json：{source_path}")


def resolve_chapter_path(index_path: Path, chapter_item: Dict[str, Any]) -> Path:
    candidates = [
        chapter_item.get("relative_path"),
        chapter_item.get("file_name"),
        chapter_item.get("file_path"),
    ]
    for candidate in candidates:
        candidate_text = str(candidate or "").strip()
        if not candidate_text:
            continue
        candidate_path = Path(candidate_text)
        if candidate_path.is_absolute():
            if candidate_path.exists():
                return candidate_path
            continue
        if candidate_text.startswith("chapter_regions/"):
            candidate_path = index_path.parent.parent / candidate_path
        else:
            candidate_path = index_path.parent / candidate_path
        if candidate_path.exists():
            return candidate_path.resolve()
    raise FileNotFoundError(f"章节索引缺少可用路径：{chapter_item}")


def load_all_bill_chapters(step1_source_path: str | Path) -> List[Dict[str, Any]]:
    index_path = resolve_chapter_index_path(step1_source_path)
    payload = load_json_or_jsonl(index_path)
    if not isinstance(payload, dict) or not isinstance(payload.get("chapters"), list):
        raise ValueError(f"chapter_index.json 格式不正确：{index_path}")

    chapters: List[Dict[str, Any]] = []
    for chapter_item in payload["chapters"]:
        if not isinstance(chapter_item, dict):
            continue
        chapter_title = str(chapter_item.get("title", "")).strip()
        if chapter_title and not is_bill_chapter_title(chapter_title):
            continue
        chapter_path = resolve_chapter_path(index_path, chapter_item)
        chapter_payload = load_json_or_jsonl(chapter_path)
        if not isinstance(chapter_payload, dict) or not isinstance(chapter_payload.get("regions"), list):
            raise ValueError(f"章节文件格式不正确：{chapter_path}")
        chapter_meta = chapter_payload.get("chapter", {}) if isinstance(chapter_payload.get("chapter"), dict) else {}
        chapters.append(
            {
                "title": chapter_title or str(chapter_meta.get("title", "")).strip() or chapter_path.stem,
                "path": str(chapter_path),
                "relative_path": str(chapter_item.get("relative_path", "") or ""),
                "chapter": chapter_meta,
                "regions": chapter_payload["regions"],
                "source_path": str(chapter_path),
            }
        )

    if not chapters:
        raise FileNotFoundError(f"chapter_index.json 中未找到可用的清单章节：{index_path}")
    return chapters


def load_components(components_path: str | Path) -> List[Dict[str, Any]]:
    payload = load_json_or_jsonl(components_path)
    if isinstance(payload, dict):
        if isinstance(payload.get("components"), list):
            payload = payload["components"]
        else:
            raise ValueError("components.json 必须是数组或包含 components 数组。")
    if not isinstance(payload, list):
        raise ValueError("components.json 必须是数组。")
    return [item for item in payload if isinstance(item, dict)]


def get_component_name(component: Dict[str, Any]) -> str:
    return str(component.get("component_type", "") or component.get("source_component_name", "")).strip()


def summarize_component(component: Dict[str, Any]) -> Dict[str, Any]:
    properties = component.get("properties", {}) if isinstance(component.get("properties"), dict) else {}
    attributes = properties.get("attributes", []) if isinstance(properties.get("attributes"), list) else []
    calculations = properties.get("calculations", []) if isinstance(properties.get("calculations"), list) else []
    return {
        "component_name": get_component_name(component),
        "attribute_count": len(attributes),
        "calculation_count": len(calculations),
        "attributes": [
            {
                "name": str(attribute.get("name", "")).strip(),
                "code": str(attribute.get("code", "")).strip(),
                "values": [str(value).strip() for value in attribute.get("values", []) if str(value).strip()],
            }
            for attribute in attributes
            if isinstance(attribute, dict)
        ],
        "calculations": [
            {
                "name": str(calculation.get("name", "")).strip(),
                "code": str(calculation.get("code", "")).strip(),
                "unit": str(calculation.get("unit", "")).strip(),
            }
            for calculation in calculations
            if isinstance(calculation, dict)
        ],
    }


def summarize_chapter(chapter: Dict[str, Any]) -> Dict[str, Any]:
    regions = chapter.get("regions", []) if isinstance(chapter.get("regions"), list) else []
    region_count = len(regions)
    table_count = sum(len(region.get("tables", [])) for region in regions if isinstance(region, dict))
    return {
        "title": chapter.get("title", ""),
        "path": chapter.get("path", ""),
        "region_count": region_count,
        "table_count": table_count,
    }


def build_components_text(components: Sequence[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for index, component in enumerate(components, start=1):
        summary = summarize_component(component)
        lines.append(f"{index}. 构件名: {summary['component_name']}")
        if summary["attributes"]:
            lines.append("   项目特征:")
            for attribute in summary["attributes"]:
                values = " | ".join(attribute["values"]) if attribute["values"] else "无"
                label = f"{attribute['name']}[{attribute['code']}]" if attribute["code"] else attribute["name"]
                lines.append(f"   - {label}: {values}")
        if summary["calculations"]:
            lines.append("   计算项目:")
            for calculation in summary["calculations"]:
                unit = f" ({calculation['unit']})" if calculation["unit"] else ""
                label = f"{calculation['name']}[{calculation['code']}]" if calculation["code"] else calculation["name"]
                lines.append(f"   - {label}{unit}")
        lines.append("")
    return "\n".join(lines).strip()


def build_chapters_text(chapters: Sequence[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for index, chapter in enumerate(chapters, start=1):
        summary = summarize_chapter(chapter)
        lines.append(f"{index}. 章节: {summary['title']}")
        lines.append(f"   来源: {summary['path']}")
        lines.append(f"   区域数: {summary['region_count']}; 表格数: {summary['table_count']}")
        for region in chapter.get("regions", [])[:6]:
            if not isinstance(region, dict):
                continue
            path_text = str(region.get("path_text", "") or region.get("title", "")).strip()
            if path_text:
                lines.append(f"   - {path_text}")
        lines.append("")
    return "\n".join(lines).strip()


def build_step2_prompt_text(
    components: Sequence[Dict[str, Any]],
    chapters: Sequence[Dict[str, Any]],
    standard_document: str,
) -> str:
    return "\n".join(
        [
            f"标准文档: {standard_document}",
            "任务: 你是构件预匹配助手，请根据构件库和全部章节，输出构件名称、候选标准名、同义词库和证据。",
            "要求:",
            "1. 只输出合法 JSON。",
            "2. 不要引用未提供内容。",
            "3. 不要使用 file_data 或 input_file。",
            "4. 顶层必须返回对象，且只能包含 meta 与 mappings 两个主要字段。",
            "5. mappings 必须覆盖当前批次内每一个构件，不能遗漏。",
            "6. mappings 每项固定字段为："
            "source_component_name, source_aliases, selected_standard_name, standard_aliases, "
            "candidate_standard_names, match_type, match_status, confidence, review_status, "
            "evidence_paths, evidence_texts, reasoning, manual_notes。",
            "7. 只能使用上述英文字段名，不要改成中文键名。",
            "8. 若无法确定唯一标准名，也要返回该构件；候选过多用 candidate_only，完全不匹配用 unmatched。",
            "",
            "【components.txt】",
            build_components_text(components),
            "",
            "【chapters.txt】",
            build_chapters_text(chapters),
        ]
    )


def build_openai_request_payload(
    prompt_text: str,
    model: str = DEFAULT_OPENAI_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> Dict[str, Any]:
    return {
        "model": model,
        "input": prompt_text,
        "reasoning": {"effort": reasoning_effort},
        "text": {"format": {"type": "json_object"}},
    }


def extract_json_text(raw_text: str) -> str:
    stripped = str(raw_text or "").strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return stripped
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return stripped[first_brace:last_brace + 1]
    raise ValueError("模型输出中未找到可解析的 JSON。")


def call_openai_plaintext_model(
    *,
    prompt_text: str,
    model: str,
    reasoning_effort: str,
    max_output_tokens: int = 8000,
    request_timeout_seconds: float = 120.0,
    connection_retries: int = 5,
    provider_mode: str | None = None,
) -> str:
    from pipeline_v2.step2_engine.api import call_openai_model

    return call_openai_model(
        model=model,
        reasoning_effort=reasoning_effort,
        max_output_tokens=max_output_tokens,
        request_timeout_seconds=request_timeout_seconds,
        connection_retries=connection_retries,
        provider_mode=provider_mode,
        prompt_text=prompt_text,
        instructions_text=None,
        input_items=None,
        phase="step2_v2_plaintext_request",
        retry_log_path=None,
        log_context=None,
    )


def sanitize_path_segment(text: str) -> str:
    sanitized = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", str(text or "").strip(), flags=re.UNICODE)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized[:80] or "untitled"


def chunk_components(components: Sequence[Dict[str, Any]], batch_size: int) -> List[List[Dict[str, Any]]]:
    normalized_batch_size = max(1, int(batch_size or 1))
    return [list(components[index:index + normalized_batch_size]) for index in range(0, len(components), normalized_batch_size)]


def deduplicate_strings(values: Sequence[Any]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for value in values:
        text = normalize_optional_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def is_step2_lite_validation_candidate(model: str) -> bool:
    normalized_model = str(model or "").strip().lower()
    return "gemini" in normalized_model and "lite" in normalized_model


def summarize_step2_batch_quality(
    mappings: Sequence[Dict[str, Any]],
    expected_component_names: Sequence[str],
) -> Dict[str, Any]:
    expected_names = deduplicate_strings(expected_component_names)
    mapping_by_source: Dict[str, Dict[str, Any]] = {}
    for item in mappings:
        if not isinstance(item, dict):
            continue
        source_name = normalize_optional_text(item.get("source_component_name", ""))
        if source_name and source_name not in mapping_by_source:
            mapping_by_source[source_name] = item

    matched_count = 0
    candidate_only_count = 0
    conflict_count = 0
    unmatched_count = 0
    missing_count = 0
    deviation_points = 0.0
    missing_components: List[str] = []

    for component_name in expected_names:
        mapping = mapping_by_source.get(component_name)
        if mapping is None:
            missing_count += 1
            deviation_points += 1.0
            missing_components.append(component_name)
            continue

        match_status = str(mapping.get("match_status", "")).strip() or "unmatched"
        if match_status == "matched":
            matched_count += 1
        elif match_status == "candidate_only":
            candidate_only_count += 1
        elif match_status == "conflict":
            conflict_count += 1
        else:
            unmatched_count += 1
            match_status = "unmatched"

        deviation_points += STEP2_VALIDATION_STATUS_WEIGHTS.get(match_status, 1.0)

    expected_count = len(expected_names)
    unresolved_count = missing_count + candidate_only_count + conflict_count + unmatched_count
    deviation_score = (deviation_points / expected_count) if expected_count else 0.0

    return {
        "expected_count": expected_count,
        "returned_component_count": len(mapping_by_source),
        "matched_count": matched_count,
        "candidate_only_count": candidate_only_count,
        "conflict_count": conflict_count,
        "unmatched_count": unmatched_count,
        "missing_count": missing_count,
        "unresolved_count": unresolved_count,
        "missing_components": missing_components,
        "deviation_score": round(deviation_score, 4),
    }


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _chapter_match_type_weight(match_type: Any) -> float:
    return STEP2_CHAPTER_MATCH_TYPE_WEIGHTS.get(str(match_type or "").strip().lower(), 0.0)


def _chapter_review_status_weight(review_status: Any) -> float:
    return STEP2_CHAPTER_REVIEW_STATUS_WEIGHTS.get(str(review_status or "").strip().lower(), 0.0)


def _chapter_merge_candidate_score(item: Dict[str, Any]) -> float:
    selected_name = normalize_optional_text(item.get("selected_standard_name", ""))
    match_status = str(item.get("match_status", "")).strip().lower()
    confidence = max(0.0, min(1.0, _to_float(item.get("confidence", 0.0))))
    evidence_count = len(item.get("evidence_paths", []) or []) + len(item.get("evidence_texts", []) or [])
    return (
        (4000.0 if selected_name else 0.0)
        + ({
            "matched": 400.0,
            "candidate_only": 200.0,
            "conflict": 100.0,
            "unmatched": 0.0,
        }.get(match_status, 0.0))
        + (_chapter_match_type_weight(item.get("match_type", "")) * 100.0)
        + (confidence * 100.0)
        + (_chapter_review_status_weight(item.get("review_status", "")) * 10.0)
        + min(float(evidence_count), 20.0)
    )


def _resolve_chapter_level_conflict(
    merged_mapping: Dict[str, Any],
    candidates: Sequence[Dict[str, Any]],
) -> Dict[str, Any] | None:
    selected_candidates = [
        item for item in candidates if normalize_optional_text(item.get("selected_standard_name", ""))
    ]
    if len(selected_candidates) < 2:
        return None

    ranked_candidates = sorted(
        selected_candidates,
        key=lambda item: (
            _chapter_merge_candidate_score(item),
            _to_float(item.get("confidence", 0.0)),
            len(item.get("evidence_paths", []) or []),
            len(item.get("evidence_texts", []) or []),
        ),
        reverse=True,
    )
    best = ranked_candidates[0]
    runner_up = ranked_candidates[1]
    best_score = _chapter_merge_candidate_score(best)
    runner_up_score = _chapter_merge_candidate_score(runner_up)
    best_type_weight = _chapter_match_type_weight(best.get("match_type", ""))
    runner_up_type_weight = _chapter_match_type_weight(runner_up.get("match_type", ""))
    best_confidence = _to_float(best.get("confidence", 0.0))
    runner_up_confidence = _to_float(runner_up.get("confidence", 0.0))

    should_auto_resolve = (
        (best_score - runner_up_score) >= STEP2_CHAPTER_AUTO_RESOLVE_SCORE_GAP
        or (best_type_weight - runner_up_type_weight) >= 2.0
        or (best_confidence >= 0.9 and runner_up_confidence <= 0.5 and best_type_weight >= runner_up_type_weight)
    )
    if not should_auto_resolve:
        return None

    best_selected_name = normalize_optional_text(best.get("selected_standard_name", ""))
    runner_up_selected_name = normalize_optional_text(runner_up.get("selected_standard_name", ""))
    resolution_note = (
        f" 跨章节合并时检测到多个标准名，已自动保留更强匹配“{best_selected_name}”，"
        f"并降级保留“{runner_up_selected_name}”为候选。"
    )
    resolved_record = {
        "source_component_name": merged_mapping.get("source_component_name", ""),
        "source_aliases": merged_mapping.get("source_aliases", []),
        "selected_standard_name": best_selected_name,
        "standard_aliases": deduplicate_strings(
            [best_selected_name] + list(best.get("standard_aliases", []) or [])
        ),
        "candidate_standard_names": merged_mapping.get("candidate_standard_names", []),
        "match_type": str(best.get("match_type", "")).strip(),
        "match_status": "matched",
        "confidence": max(
            _to_float(merged_mapping.get("confidence", 0.0)),
            max(_to_float(item.get("confidence", 0.0)) for item in selected_candidates),
        ),
        "review_status": str(best.get("review_status", "")).strip() or "pending",
        "evidence_paths": merged_mapping.get("evidence_paths", []),
        "evidence_texts": merged_mapping.get("evidence_texts", []),
        "reasoning": f"{str(best.get('reasoning', '')).strip()}{resolution_note}".strip(),
        "manual_notes": str(best.get("manual_notes", "")).strip() or str(merged_mapping.get("manual_notes", "")).strip(),
    }
    return normalize_mapping(resolved_record)


def merge_chapter_serial_mappings(
    group_payloads: Sequence[Dict[str, Any]],
    expected_component_names: Sequence[str],
) -> Dict[str, Any]:
    merged_payload = merge_window_mappings(
        group_payloads=group_payloads,
        expected_component_names=expected_component_names,
    )

    grouped_candidates: Dict[str, List[Dict[str, Any]]] = {}
    for payload in group_payloads:
        for item in payload.get("mappings", []):
            if not isinstance(item, dict):
                continue
            source_name = normalize_optional_text(item.get("source_component_name", ""))
            if source_name:
                grouped_candidates.setdefault(source_name, []).append(item)

    auto_resolved_conflict_count = 0
    resolved_mappings: List[Dict[str, Any]] = []
    for item in merged_payload.get("mappings", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("match_status", "")).strip() != "conflict":
            resolved_mappings.append(item)
            continue

        source_name = normalize_optional_text(item.get("source_component_name", ""))
        resolved = _resolve_chapter_level_conflict(item, grouped_candidates.get(source_name, []))
        if resolved is None:
            resolved_mappings.append(item)
            continue

        auto_resolved_conflict_count += 1
        resolved_mappings.append(resolved)

    merged_payload["mappings"] = ensure_all_components_present(resolved_mappings, expected_component_names)
    merged_payload.setdefault("meta", {})
    merged_payload["meta"]["auto_resolved_conflict_count"] = auto_resolved_conflict_count
    return merged_payload


def plan_step2_validation_fallback(
    *,
    primary_model: str,
    validation_fallback_model: str | None,
    min_deviation_score: float,
    mappings: Sequence[Dict[str, Any]],
    expected_component_names: Sequence[str],
) -> Dict[str, Any]:
    normalized_fallback_model = normalize_optional_text(validation_fallback_model or "")
    summary = summarize_step2_batch_quality(mappings, expected_component_names)
    if not summary["expected_count"]:
        return {"triggered": False, "reason": "", "summary": summary, "validation_model": normalized_fallback_model}

    if not is_step2_lite_validation_candidate(primary_model):
        return {"triggered": False, "reason": "", "summary": summary, "validation_model": normalized_fallback_model}

    if not normalized_fallback_model or normalized_fallback_model == str(primary_model or "").strip():
        return {"triggered": False, "reason": "", "summary": summary, "validation_model": normalized_fallback_model}

    high_deviation = summary["deviation_score"] >= float(min_deviation_score)
    zero_match_high_risk = summary["matched_count"] <= 0 and summary["unresolved_count"] > 0
    triggered = high_deviation or zero_match_high_risk
    if not triggered:
        return {"triggered": False, "reason": "", "summary": summary, "validation_model": normalized_fallback_model}

    reasons: List[str] = []
    if high_deviation:
        reasons.append(
            f"deviation_score={summary['deviation_score']:.2f} >= {float(min_deviation_score):.2f}"
        )
    if zero_match_high_risk:
        reasons.append("matched_count=0")

    return {
        "triggered": True,
        "reason": "; ".join(reasons),
        "summary": summary,
        "validation_model": normalized_fallback_model,
    }


def slice_sequence(items: Sequence[Any], start_index: int = 1, limit: int | None = None) -> List[Any]:
    normalized_start_index = max(1, int(start_index or 1))
    sliced = list(items[normalized_start_index - 1:])
    if limit is not None:
        normalized_limit = max(0, int(limit))
        sliced = sliced[:normalized_limit]
    return sliced


def select_indexed_items(
    items: Sequence[Any],
    start_index: int = 1,
    limit: int | None = None,
) -> List[tuple[int, Any]]:
    normalized_start_index = max(1, int(start_index or 1))
    normalized_limit = None if limit is None else max(0, int(limit))
    selected: List[tuple[int, Any]] = []
    for absolute_index, item in enumerate(items, start=1):
        if absolute_index < normalized_start_index:
            continue
        if normalized_limit is not None and len(selected) >= normalized_limit:
            break
        selected.append((absolute_index, item))
    return selected


def validate_resumed_batch_payload(
    payload: Dict[str, Any],
    *,
    expected_component_names: Sequence[str],
    chapter_title: str,
    chapter_index: int,
    component_batch_index: int,
) -> str | None:
    mappings = payload.get("mappings")
    if not isinstance(mappings, list):
        return "已有批次结果缺少 mappings 数组。"

    actual_component_names = deduplicate_strings(
        item.get("source_component_name", "")
        for item in mappings
        if isinstance(item, dict)
    )
    if set(actual_component_names) != set(expected_component_names):
        return (
            "已有批次结果中的构件集合与当前批次不一致。"
            f" expected={list(expected_component_names)} actual={actual_component_names}"
        )

    meta = payload.get("meta", {}) if isinstance(payload.get("meta"), dict) else {}
    existing_chapter_title = str(meta.get("chapter_title", "")).strip()
    if existing_chapter_title and existing_chapter_title != chapter_title:
        return f"已有批次结果 chapter_title 不匹配：{existing_chapter_title} != {chapter_title}"

    existing_chapter_index = str(meta.get("chapter_index", "")).strip()
    if existing_chapter_index and existing_chapter_index != str(chapter_index):
        return f"已有批次结果 chapter_index 不匹配：{existing_chapter_index} != {chapter_index}"

    existing_batch_index = str(meta.get("component_batch_index", "")).strip()
    if existing_batch_index and existing_batch_index != str(component_batch_index):
        return f"已有批次结果 component_batch_index 不匹配：{existing_batch_index} != {component_batch_index}"

    return None


def coerce_model_payload(raw_payload: Dict[str, Any], standard_document: str) -> Dict[str, Any]:
    if isinstance(raw_payload.get("mappings"), list):
        return raw_payload

    results = raw_payload.get("results")
    if not isinstance(results, list):
        return raw_payload

    mappings: List[Dict[str, Any]] = []
    for entry in results:
        if not isinstance(entry, dict):
            continue

        source_component_name = str(
            entry.get("source_component_name", "")
            or entry.get("component_name", "")
            or entry.get("构件名称", "")
        ).strip()
        source_component_name = normalize_optional_text(source_component_name)
        candidate_standard_names = deduplicate_strings(
            entry.get("candidate_standard_names", [])
            or entry.get("candidate_names", [])
            or entry.get("候选标准名", [])
            or []
        )
        selected_standard_name = normalize_optional_text(
            entry.get("selected_standard_name", "")
            or entry.get("standard_name", "")
            or entry.get("canonical_name", "")
            or ""
        )
        if not selected_standard_name and len(candidate_standard_names) == 1:
            selected_standard_name = candidate_standard_names[0]
        if selected_standard_name and selected_standard_name not in candidate_standard_names:
            candidate_standard_names = [selected_standard_name] + candidate_standard_names

        evidence = (
            entry.get("evidence", {})
            if isinstance(entry.get("evidence"), dict)
            else entry.get("证据", {})
            if isinstance(entry.get("证据"), dict)
            else {}
        )
        evidence_paths = deduplicate_strings(
            (evidence.get("chapters", []) if isinstance(evidence.get("chapters"), list) else [])
            + (evidence.get("章节证据", []) if isinstance(evidence.get("章节证据"), list) else [])
        )
        evidence_texts = deduplicate_strings(
            list(evidence.get("component", []) if isinstance(evidence.get("component"), list) else [])
            + list(evidence.get("构件证据", []) if isinstance(evidence.get("构件证据"), list) else [])
            + list(evidence.get("章节证据", []) if isinstance(evidence.get("章节证据"), list) else [])
            + ([str(evidence.get("reason", "")).strip()] if str(evidence.get("reason", "")).strip() else [])
            + ([str(evidence.get("match_conclusion", "")).strip()] if str(evidence.get("match_conclusion", "")).strip() else [])
            + ([str(evidence.get("结论", "")).strip()] if str(evidence.get("结论", "")).strip() else [])
        )
        source_aliases = deduplicate_strings(
            [source_component_name] + list(entry.get("synonym_library", []) or []) + list(entry.get("同义词库", []) or [])
        )
        reasoning = str(
            entry.get("reasoning", "")
            or evidence.get("reason", "")
            or evidence.get("match_conclusion", "")
            or evidence.get("结论", "")
        ).strip()

        if selected_standard_name:
            match_status = "matched"
            confidence = 0.7
            review_status = "suggested"
        elif candidate_standard_names:
            match_status = "candidate_only"
            confidence = 0.35
            review_status = "pending"
        else:
            match_status = "unmatched"
            confidence = 0.0
            review_status = "pending"

        mappings.append(
            {
                "source_component_name": source_component_name,
                "source_aliases": source_aliases or ([source_component_name] if source_component_name else []),
                "selected_standard_name": selected_standard_name,
                "standard_aliases": [selected_standard_name] if selected_standard_name else [],
                "candidate_standard_names": candidate_standard_names,
                "match_type": "chapter_serial_precheck",
                "match_status": match_status,
                "confidence": confidence,
                "review_status": review_status,
                "evidence_paths": evidence_paths,
                "evidence_texts": evidence_texts,
                "reasoning": reasoning,
                "manual_notes": "",
            }
        )

    return {
        "meta": {
            "task_name": "component_standard_name_matching",
            "standard_document": str(raw_payload.get("document", "")).strip() or standard_document,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "review_stage": "pre_parse",
        },
        "mappings": mappings,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _parse_chapter_dir_name(chapter_dir: Path) -> tuple[int, str]:
    match = re.match(r"^chapter_(\d{3})_(.+)$", chapter_dir.name)
    if not match:
        return (0, chapter_dir.name)
    return (int(match.group(1)), match.group(2).replace("_", " "))


def _parse_batch_index_from_path(batch_result_path: Path) -> int:
    match = re.search(r"batch_(\d{3})_result\.json$", batch_result_path.name)
    if not match:
        return 0
    return int(match.group(1))


def _backup_existing_file(path: Path) -> str:
    if not path.exists():
        return ""

    backup_path = path.with_name(f"{path.name}.pre_synthesize.bak")
    if not backup_path.exists():
        backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return str(backup_path)


def synthesize_existing_step2_outputs(
    output_dir: str | Path,
    *,
    components_path: str | Path | None = None,
    step1_source_path: str | Path | None = None,
    backup_existing: bool = True,
) -> Dict[str, Any]:
    output_path = normalize_path(output_dir)
    if not output_path.exists():
        raise FileNotFoundError(f"未找到 Step2 输出目录：{output_path}")

    execute_manifest_path = output_path / "execute_manifest.json"
    execute_manifest = load_json_or_jsonl(execute_manifest_path) if execute_manifest_path.exists() else {}
    if not isinstance(execute_manifest, dict):
        execute_manifest = {}

    run_summary_path = output_path / "run_summary.json"
    original_run_summary = load_json_or_jsonl(run_summary_path) if run_summary_path.exists() else {}
    if not isinstance(original_run_summary, dict):
        original_run_summary = {}

    resolved_components_path = (
        normalize_path(components_path)
        if components_path
        else normalize_path(execute_manifest["components_path"])
        if execute_manifest.get("components_path")
        else None
    )
    resolved_step1_source_path = (
        normalize_path(step1_source_path)
        if step1_source_path
        else normalize_path(execute_manifest["step1_source_path"])
        if execute_manifest.get("step1_source_path")
        else None
    )

    standard_document = str(execute_manifest.get("standard_document", "")).strip()
    if not standard_document and resolved_step1_source_path is not None:
        standard_document = resolve_standard_document_name(resolved_step1_source_path)
    if not standard_document:
        standard_document = output_path.name

    components: List[Dict[str, Any]] = []
    all_component_names: List[str] = []
    if resolved_components_path and resolved_components_path.exists():
        components = load_components(resolved_components_path)
        all_component_names = deduplicate_strings(get_component_name(component) for component in components)

    expected_chapter_count = 0
    if resolved_step1_source_path and resolved_step1_source_path.exists():
        try:
            expected_chapter_count = len(load_all_bill_chapters(resolved_step1_source_path))
        except Exception:
            expected_chapter_count = 0
    if not expected_chapter_count:
        try:
            expected_chapter_count = int(execute_manifest.get("chapter_count") or 0)
        except (TypeError, ValueError):
            expected_chapter_count = 0

    chapter_dirs = sorted(
        [path for path in output_path.iterdir() if path.is_dir() and path.name.startswith("chapter_")],
        key=lambda item: _parse_chapter_dir_name(item)[0],
    )

    chapter_results: List[Dict[str, Any]] = []
    chapter_run_index: List[Dict[str, Any]] = []

    for chapter_dir in chapter_dirs:
        chapter_index, parsed_chapter_title = _parse_chapter_dir_name(chapter_dir)
        chapter_result_path = chapter_dir / "chapter_result.json"
        batch_result_paths = sorted(
            chapter_dir.glob("batch_*_result.json"),
            key=_parse_batch_index_from_path,
        )

        chapter_payload: Dict[str, Any] | None = None
        chapter_title = parsed_chapter_title
        chapter_source_path = ""

        if chapter_result_path.exists():
            raw_chapter_payload = load_json_or_jsonl(chapter_result_path)
            if isinstance(raw_chapter_payload, dict):
                chapter_payload = normalize_result_payload(coerce_model_payload(raw_chapter_payload, standard_document))
        elif batch_result_paths:
            batch_payloads: List[Dict[str, Any]] = []
            inferred_component_names: List[str] = []

            for batch_result_path in batch_result_paths:
                raw_batch_payload = load_json_or_jsonl(batch_result_path)
                if not isinstance(raw_batch_payload, dict):
                    continue

                batch_payload = normalize_result_payload(coerce_model_payload(raw_batch_payload, standard_document))
                batch_index = _parse_batch_index_from_path(batch_result_path)
                batch_manifest_path = chapter_dir / f"batch_{batch_index:03d}_manifest.json"
                batch_manifest = load_json_or_jsonl(batch_manifest_path) if batch_manifest_path.exists() else {}
                if not isinstance(batch_manifest, dict):
                    batch_manifest = {}

                expected_names = deduplicate_strings(batch_manifest.get("component_names", []))
                if not expected_names:
                    expected_names = deduplicate_strings(
                        item.get("source_component_name", "")
                        for item in batch_payload.get("mappings", [])
                        if isinstance(item, dict)
                    )
                inferred_component_names.extend(expected_names)
                batch_payload["mappings"] = ensure_all_components_present(batch_payload.get("mappings", []), expected_names)
                batch_payload.setdefault("meta", {})
                batch_payload["meta"].update(
                    {
                        "standard_document": standard_document,
                        "chapter_title": str(batch_manifest.get("chapter_title", "")).strip() or chapter_title,
                        "chapter_index": int(batch_manifest.get("chapter_index") or chapter_index or 0),
                        "component_batch_index": int(batch_manifest.get("component_batch_index") or batch_index or 0),
                        "total_component_batches": int(
                            batch_manifest.get("total_component_batches")
                            or execute_manifest.get("total_component_batch_count_per_chapter")
                            or 0
                        ),
                    }
                )

                chapter_title = str(batch_manifest.get("chapter_title", "")).strip() or chapter_title
                chapter_source_path = str(batch_manifest.get("chapter_source_path", "")).strip() or chapter_source_path
                batch_payloads.append(batch_payload)

            if batch_payloads:
                chapter_expected_names = all_component_names or deduplicate_strings(inferred_component_names)
                chapter_payload = merge_window_mappings(
                    group_payloads=batch_payloads,
                    expected_component_names=chapter_expected_names,
                )

        if chapter_payload is None:
            continue

        chapter_meta = chapter_payload.setdefault("meta", {})
        chapter_title = str(chapter_meta.get("chapter_title", "")).strip() or chapter_title
        chapter_source_path = str(chapter_meta.get("chapter_source_path", "")).strip() or chapter_source_path
        chapter_index = int(chapter_meta.get("chapter_index") or chapter_index or 0)

        chapter_component_names = all_component_names or deduplicate_strings(
            item.get("source_component_name", "")
            for item in chapter_payload.get("mappings", [])
            if isinstance(item, dict)
        )
        if not all_component_names:
            all_component_names = list(chapter_component_names)

        chapter_payload["mappings"] = ensure_all_components_present(
            chapter_payload.get("mappings", []),
            chapter_component_names,
        )
        chapter_meta.update(
            {
                "standard_document": standard_document,
                "chapter_title": chapter_title,
                "chapter_index": chapter_index,
                "merged_component_batch_count": max(
                    1,
                    len(batch_result_paths) if batch_result_paths else int(chapter_meta.get("merged_component_batch_count") or 1),
                ),
                "total_component_batch_count": int(
                    execute_manifest.get("total_component_batch_count_per_chapter")
                    or chapter_meta.get("total_component_batch_count")
                    or len(batch_result_paths)
                    or 1
                ),
                "merge_strategy": str(chapter_meta.get("merge_strategy", "")).strip() or "component_batch_merge_recovered",
            }
        )

        write_json(chapter_result_path, chapter_payload)
        chapter_results.append(chapter_payload)
        chapter_run_index.append(
            {
                "chapter_index": chapter_index,
                "chapter_title": chapter_title,
                "chapter_source_path": chapter_source_path,
                "chapter_output_dir": str(chapter_dir),
                "component_batch_count": int(chapter_meta.get("merged_component_batch_count") or 0),
                "chapter_result_path": str(chapter_result_path),
            }
        )

    if not chapter_results:
        raise RuntimeError(
            f"未在 {output_path} 下找到可恢复的 chapter_result.json 或 batch_*_result.json，无法合成 Step2 主结果。"
        )

    result_payload = merge_chapter_serial_mappings(
        group_payloads=chapter_results,
        expected_component_names=all_component_names,
    )
    result_payload.setdefault("meta", {})
    result_payload["meta"].update(
        {
            "task_name": "component_standard_name_matching",
            "standard_document": standard_document,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "merged_chapter_count": len(chapter_results),
            "merge_strategy": "chapter_serial_merge_recovered",
            "components_per_chapter_batch": execute_manifest.get("components_per_chapter_batch"),
            "selected_component_batches_per_chapter": execute_manifest.get("component_batch_count_per_chapter"),
            "total_component_batches_per_chapter": execute_manifest.get("total_component_batch_count_per_chapter"),
        }
    )

    synonym_library = build_synonym_library(result_payload["mappings"], result_payload["meta"])
    recovered_status = "completed_from_existing" if expected_chapter_count and len(chapter_results) >= expected_chapter_count else "partial_from_existing"

    backup_paths: Dict[str, str] = {}
    if backup_existing:
        for name in ("component_matching_result.json", "result.json", "synonym_library.json", "run_summary.json"):
            backup_path = _backup_existing_file(output_path / name)
            if backup_path:
                backup_paths[name] = backup_path

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    run_summary = {
        "task_name": "step2_v2_synthesize_existing",
        "generated_at": now,
        "standard_document": standard_document,
        "components_path": str(resolved_components_path) if resolved_components_path else "",
        "step1_source_path": str(resolved_step1_source_path) if resolved_step1_source_path else "",
        "output_dir": str(output_path),
        "status": recovered_status,
        "recovered_from_status": str(original_run_summary.get("status", "")).strip(),
        "recovered_chapter_count": len(chapter_results),
        "expected_chapter_count": expected_chapter_count,
        "component_count": len(all_component_names),
        "matched_count": sum(1 for item in result_payload["mappings"] if item.get("match_status") == "matched"),
        "candidate_only_count": sum(1 for item in result_payload["mappings"] if item.get("match_status") == "candidate_only"),
        "conflict_count": sum(1 for item in result_payload["mappings"] if item.get("match_status") == "conflict"),
        "pending_review_count": sum(1 for item in result_payload["mappings"] if item.get("review_status") == "pending"),
        "synonym_component_count": len(synonym_library.get("synonym_library", [])),
        "matched_synonym_component_count": sum(
            1 for item in synonym_library.get("synonym_library", []) if str(item.get("selected_standard_name", "")).strip()
        ),
        "synonym_canonical_count": len(synonym_library.get("synonym_library", [])),
        "step3_ready": True,
        "backup_paths": backup_paths,
        "source_error": str(original_run_summary.get("error", "")).strip(),
        "completed_at": now,
    }

    write_json(output_path / "chapter_run_index.json", {"chapters": chapter_run_index})
    write_json(output_path / "result.json", result_payload)
    write_json(output_path / "component_matching_result.json", result_payload)
    write_json(output_path / "synonym_library.json", synonym_library)
    write_json(output_path / "run_summary.json", run_summary)

    return {
        "result_payload": result_payload,
        "run_summary": run_summary,
        "synonym_library": synonym_library,
        "output_dir": str(output_path),
    }


def batch_result_path_for(output_path: Path, chapter_index: int, chapter_title: str, batch_index: int) -> Path:
    chapter_dir = output_path / f"chapter_{chapter_index:03d}_{sanitize_path_segment(chapter_title)}"
    return chapter_dir / f"batch_{batch_index:03d}_result.json"


def prepare(
    components_path: str | Path,
    step1_source_path: str | Path,
    output_dir: str | Path,
    *,
    model: str = DEFAULT_OPENAI_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    component_batch_size: int | None = None,
    components_per_chapter_batch: int = 5,
    start_chapter_index: int = 1,
    chapter_limit: int | None = None,
    start_component_batch_index: int = 1,
    component_batch_limit: int | None = None,
) -> Dict[str, Any]:
    if component_batch_size is not None:
        components_per_chapter_batch = component_batch_size

    components = load_components(components_path)
    all_chapters = load_all_bill_chapters(step1_source_path)
    selected_chapters = select_indexed_items(all_chapters, start_chapter_index, chapter_limit)
    chapters = [chapter for _, chapter in selected_chapters]
    standard_document = resolve_standard_document_name(step1_source_path)
    prompt_text = build_step2_prompt_text(components, chapters, standard_document)
    request_payload = build_openai_request_payload(prompt_text, model=model, reasoning_effort=reasoning_effort)
    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    all_component_batches = chunk_components(components, components_per_chapter_batch)
    selected_component_batches = select_indexed_items(
        all_component_batches,
        start_component_batch_index,
        component_batch_limit,
    )
    component_batches = [batch for _, batch in selected_component_batches]
    manifest = {
        "task_name": "step2_v2_prepare",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "standard_document": standard_document,
        "components_path": str(normalize_path(components_path)),
        "step1_source_path": str(normalize_path(step1_source_path)),
        "output_dir": str(output_path),
        "component_count": len(components),
        "chapter_count": len(chapters),
        "total_chapter_count": len(all_chapters),
        "chapter_titles": [chapter["title"] for chapter in chapters],
        "components_per_chapter_batch": components_per_chapter_batch,
        "component_batch_count_per_chapter": len(component_batches),
        "total_component_batch_count_per_chapter": len(all_component_batches),
        "start_chapter_index": start_chapter_index,
        "chapter_limit": chapter_limit,
        "start_component_batch_index": start_component_batch_index,
        "component_batch_limit": component_batch_limit,
        "model": model,
        "reasoning_effort": reasoning_effort,
    }

    write_json(output_path / "prepare_manifest.json", manifest)
    write_text(output_path / "prepare_prompt.txt", prompt_text)
    write_json(output_path / "prepare_request.json", request_payload)

    return {
        "manifest": manifest,
        "prompt_text": prompt_text,
        "request_payload": request_payload,
        "chapters": chapters,
        "components": [summarize_component(component) for component in components],
        "output_dir": str(output_path),
    }


def execute(
    components_path: str | Path,
    step1_source_path: str | Path,
    output_dir: str | Path,
    *,
    model: str = DEFAULT_OPENAI_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    openai_api_key: str | None = None,
    openai_base_url: str | None = None,
    validation_openai_api_key: str | None = None,
    validation_openai_base_url: str | None = None,
    provider_mode: str | None = None,
    validation_provider_mode: str | None = None,
    component_batch_size: int | None = None,
    max_component_payload_chars: int | None = None,
    max_prompt_chars: int | None = None,
    target_region_chars: int | None = None,
    max_regions_per_batch: int | None = None,
    max_region_text_chars: int | None = None,
    max_table_text_chars: int | None = None,
    max_table_rows: int | None = None,
    only_regions_with_tables: bool = False,
    tpm_budget: int | None = None,
    prepare_only: bool = False,
    resume_existing: bool = True,
    max_output_tokens: int = 8000,
    request_timeout_seconds: float = 120.0,
    connection_retries: int = 5,
    validation_fallback_model: str | None = STEP2_VALIDATION_FALLBACK_MODEL,
    validation_min_deviation_score: float = STEP2_VALIDATION_MIN_DEVIATION_SCORE,
    components_per_chapter_batch: int = 5,
    start_chapter_index: int = 1,
    chapter_limit: int | None = None,
    start_component_batch_index: int = 1,
    component_batch_limit: int | None = None,
) -> Dict[str, Any]:
    if component_batch_size is not None:
        components_per_chapter_batch = component_batch_size

    components = load_components(components_path)
    if not components:
        raise ValueError("Step2 V2 至少需要一个构件类型。")

    all_chapters = load_all_bill_chapters(step1_source_path)
    selected_chapters = select_indexed_items(all_chapters, start_chapter_index, chapter_limit)
    standard_document = resolve_standard_document_name(step1_source_path)
    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    all_component_batches = chunk_components(components, components_per_chapter_batch)
    selected_component_batches = select_indexed_items(
        all_component_batches,
        start_component_batch_index,
        component_batch_limit,
    )
    previous_environment = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
        "OPENAI_BASE_URL": os.getenv("OPENAI_BASE_URL"),
    }
    effective_provider_mode = str(provider_mode or "").strip().lower()
    if effective_provider_mode == "codex":
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("OPENAI_BASE_URL", None)
    else:
        if openai_api_key:
            os.environ["OPENAI_API_KEY"] = str(openai_api_key)
        if openai_base_url:
            os.environ["OPENAI_BASE_URL"] = str(openai_base_url)
    chapters = [chapter for _, chapter in selected_chapters]
    all_component_names = [get_component_name(component) for component in components]
    pending_request_count = sum(
        1
        for chapter_index, chapter in selected_chapters
        for batch_index, _ in selected_component_batches
        if not resume_existing or not batch_result_path_for(output_path, chapter_index, chapter["title"], batch_index).exists()
    )
    if prepare_only:
        startup_check: Dict[str, Any] = {"status": "skipped", "reason": "prepare_only=true"}
    elif pending_request_count <= 0:
        startup_check = {"status": "skipped", "reason": "all_batches_resumed"}
    else:
        from pipeline_v2.step2_engine.api import run_openai_startup_check

        startup_check = run_openai_startup_check(
            model=model,
            request_timeout_seconds=request_timeout_seconds,
            connection_retries=connection_retries,
            output_path=output_path,
            provider_mode=provider_mode,
        )

    execute_manifest = {
        "task_name": "step2_v2_execute",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "standard_document": standard_document,
        "components_path": str(normalize_path(components_path)),
        "step1_source_path": str(normalize_path(step1_source_path)),
        "output_dir": str(output_path),
        "component_count": len(components),
        "chapter_count": len(chapters),
        "total_chapter_count": len(all_chapters),
        "components_per_chapter_batch": components_per_chapter_batch,
        "component_batch_count_per_chapter": len(selected_component_batches),
        "total_component_batch_count_per_chapter": len(all_component_batches),
        "start_chapter_index": start_chapter_index,
        "chapter_limit": chapter_limit,
        "start_component_batch_index": start_component_batch_index,
        "component_batch_limit": component_batch_limit,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "prepare_only": prepare_only,
        "resume_existing": resume_existing,
        "max_component_payload_chars": max_component_payload_chars,
        "max_prompt_chars": max_prompt_chars,
        "target_region_chars": target_region_chars,
        "max_regions_per_batch": max_regions_per_batch,
        "max_region_text_chars": max_region_text_chars,
        "max_table_text_chars": max_table_text_chars,
        "max_table_rows": max_table_rows,
        "only_regions_with_tables": only_regions_with_tables,
        "tpm_budget": tpm_budget,
        "max_output_tokens": max_output_tokens,
        "request_timeout_seconds": request_timeout_seconds,
        "connection_retries": connection_retries,
        "validation_fallback_model": normalize_optional_text(validation_fallback_model or ""),
        "validation_min_deviation_score": validation_min_deviation_score,
        "provider_mode": normalize_optional_text(provider_mode or ""),
        "validation_provider_mode": normalize_optional_text(validation_provider_mode or ""),
        "startup_connectivity_check": startup_check,
        "pending_request_count": pending_request_count,
    }
    write_json(output_path / "execute_manifest.json", execute_manifest)

    chapter_results: List[Dict[str, Any]] = []
    chapter_run_index: List[Dict[str, Any]] = []
    model_outputs: List[str] = []
    total_requests = 0

    try:
        for chapter_index, chapter in selected_chapters:
            chapter_dir = output_path / f"chapter_{chapter_index:03d}_{sanitize_path_segment(chapter['title'])}"
            chapter_dir.mkdir(parents=True, exist_ok=True)

            batch_payloads: List[Dict[str, Any]] = []
            for batch_position, (batch_index, batch_components) in enumerate(selected_component_batches, start=1):
                prompt_text = build_step2_prompt_text(batch_components, [chapter], standard_document)
                request_payload = build_openai_request_payload(prompt_text, model=model, reasoning_effort=reasoning_effort)
                expected_names = [get_component_name(component) for component in batch_components]
                batch_manifest = {
                    "chapter_index": chapter_index,
                    "chapter_title": chapter["title"],
                    "chapter_source_path": chapter["source_path"],
                    "component_batch_index": batch_index,
                    "selected_component_batch_position": batch_position,
                    "selected_component_batch_count": len(selected_component_batches),
                    "total_component_batches": len(all_component_batches),
                    "component_count": len(batch_components),
                    "component_names": expected_names,
                    "prompt_chars": len(prompt_text),
                    "model": model,
                    "reasoning_effort": reasoning_effort,
                    "max_output_tokens": max_output_tokens,
                    "request_timeout_seconds": request_timeout_seconds,
                    "connection_retries": connection_retries,
                    "validation_fallback_model": normalize_optional_text(validation_fallback_model or ""),
                    "validation_min_deviation_score": validation_min_deviation_score,
                }

                write_json(chapter_dir / f"batch_{batch_index:03d}_manifest.json", batch_manifest)
                write_text(chapter_dir / f"batch_{batch_index:03d}_prompt.txt", prompt_text)
                write_json(chapter_dir / f"batch_{batch_index:03d}_request.json", request_payload)

                batch_result_path = chapter_dir / f"batch_{batch_index:03d}_result.json"
                batch_model_output_path = chapter_dir / f"batch_{batch_index:03d}_model_output.txt"
                if resume_existing and batch_result_path.exists():
                    existing_payload = load_json_or_jsonl(batch_result_path)
                    if not isinstance(existing_payload, dict):
                        raise ValueError(f"已存在的批次结果格式不正确：{batch_result_path}")
                    normalized_existing_payload = normalize_result_payload(
                        coerce_model_payload(existing_payload, standard_document)
                    )
                    resume_error = validate_resumed_batch_payload(
                        normalized_existing_payload,
                        expected_component_names=expected_names,
                        chapter_title=chapter["title"],
                        chapter_index=chapter_index,
                        component_batch_index=batch_index,
                    )
                    if resume_error is None:
                        parsed_payload = normalized_existing_payload
                        parsed_payload["mappings"] = ensure_all_components_present(parsed_payload["mappings"], expected_names)
                        parsed_payload.setdefault("meta", {})
                        parsed_payload["meta"].update(
                            {
                                "standard_document": standard_document,
                                "chapter_title": chapter["title"],
                                "chapter_index": chapter_index,
                                "component_batch_index": batch_index,
                                "total_component_batches": len(all_component_batches),
                            }
                        )
                        write_json(batch_result_path, parsed_payload)
                        if batch_model_output_path.exists():
                            model_outputs.append(
                                "\n".join(
                                    [
                                        f"=== 章节 {chapter_index}: {chapter['title']} / 构件批次 {batch_index} (resumed) ===",
                                        batch_model_output_path.read_text(encoding="utf-8"),
                                    ]
                                )
                            )
                    else:
                        parsed_payload = {}
                elif prepare_only:
                    continue
                else:
                    parsed_payload = {}

                if not parsed_payload and prepare_only:
                    continue

                if not parsed_payload:
                    response_text = call_openai_plaintext_model(
                        prompt_text=prompt_text,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        max_output_tokens=max_output_tokens,
                        request_timeout_seconds=request_timeout_seconds,
                        connection_retries=connection_retries,
                        provider_mode=provider_mode,
                    )
                    total_requests += 1
                    model_outputs.append(
                        "\n".join(
                            [
                                f"=== 章节 {chapter_index}: {chapter['title']} / 构件批次 {batch_index} ===",
                                response_text,
                            ]
                        )
                    )
                    write_text(batch_model_output_path, response_text)

                    raw_payload = json.loads(extract_json_text(response_text))
                    primary_payload = normalize_result_payload(coerce_model_payload(raw_payload, standard_document))
                    validation_plan = plan_step2_validation_fallback(
                        primary_model=model,
                        validation_fallback_model=validation_fallback_model,
                        min_deviation_score=validation_min_deviation_score,
                        mappings=primary_payload.get("mappings", []),
                        expected_component_names=expected_names,
                    )
                    validation_failed = False
                    validation_error = ""
                    final_quality_summary = validation_plan["summary"]
                    if validation_plan["triggered"]:
                        validation_model = validation_plan["validation_model"]
                        validation_model_output_path = chapter_dir / f"batch_{batch_index:03d}_validation_model_output.txt"
                        validation_request_path = chapter_dir / f"batch_{batch_index:03d}_validation_request.json"
                        validation_request_payload = build_openai_request_payload(
                            prompt_text,
                            model=validation_model,
                            reasoning_effort=reasoning_effort,
                        )
                        write_json(validation_request_path, validation_request_payload)
                        validation_previous_environment = {
                            "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
                            "OPENAI_BASE_URL": os.getenv("OPENAI_BASE_URL"),
                        }
                        effective_validation_provider_mode = str(validation_provider_mode or provider_mode or "").strip().lower()
                        if effective_validation_provider_mode == "codex":
                            os.environ.pop("OPENAI_API_KEY", None)
                            os.environ.pop("OPENAI_BASE_URL", None)
                        else:
                            if validation_openai_api_key:
                                os.environ["OPENAI_API_KEY"] = str(validation_openai_api_key)
                            if validation_openai_base_url:
                                os.environ["OPENAI_BASE_URL"] = str(validation_openai_base_url)
                        try:
                            validation_response_text = call_openai_plaintext_model(
                                prompt_text=prompt_text,
                                model=validation_model,
                                reasoning_effort=reasoning_effort,
                                max_output_tokens=max_output_tokens,
                                request_timeout_seconds=request_timeout_seconds,
                                connection_retries=connection_retries,
                                provider_mode=validation_provider_mode or provider_mode,
                            )
                            total_requests += 1
                            model_outputs.append(
                                "\n".join(
                                    [
                                        (
                                            f"=== 章节 {chapter_index}: {chapter['title']} / 构件批次 {batch_index}"
                                            f" / 复核模型 {validation_model} ==="
                                        ),
                                        validation_response_text,
                                    ]
                                )
                            )
                            write_text(validation_model_output_path, validation_response_text)
                            validation_raw_payload = json.loads(extract_json_text(validation_response_text))
                            parsed_payload = normalize_result_payload(
                                coerce_model_payload(validation_raw_payload, standard_document)
                            )
                            final_quality_summary = summarize_step2_batch_quality(
                                parsed_payload.get("mappings", []),
                                expected_names,
                            )
                        except Exception as exc:
                            validation_failed = True
                            validation_error = str(exc).strip()
                            parsed_payload = primary_payload
                        finally:
                            for env_key, env_value in validation_previous_environment.items():
                                if env_value is None:
                                    os.environ.pop(env_key, None)
                                else:
                                    os.environ[env_key] = env_value
                    else:
                        parsed_payload = primary_payload

                    parsed_payload["mappings"] = ensure_all_components_present(parsed_payload["mappings"], expected_names)
                    parsed_payload.setdefault("meta", {})
                    parsed_payload["meta"].update(
                        {
                            "standard_document": standard_document,
                            "chapter_title": chapter["title"],
                            "chapter_index": chapter_index,
                            "component_batch_index": batch_index,
                            "total_component_batches": len(all_component_batches),
                            "validation_triggered": validation_plan["triggered"],
                            "validation_reason": validation_plan["reason"],
                            "validation_primary_model": model,
                            "validation_fallback_model": validation_plan["validation_model"],
                            "validation_failed": validation_failed,
                            "validation_error": validation_error,
                            "validation_primary_summary": validation_plan["summary"],
                            "validation_final_summary": final_quality_summary,
                        }
                    )
                    write_json(batch_result_path, parsed_payload)

                if "mappings" not in parsed_payload:
                    raise ValueError(f"批次结果缺少 mappings 字段：{batch_result_path}")
                batch_payloads.append(parsed_payload)

            if prepare_only:
                chapter_run_index.append(
                    {
                        "chapter_index": chapter_index,
                        "chapter_title": chapter["title"],
                        "chapter_source_path": chapter["source_path"],
                        "chapter_output_dir": str(chapter_dir),
                        "component_batch_count": len(selected_component_batches),
                        "chapter_result_path": "",
                    }
                )
                continue

            chapter_payload = merge_window_mappings(
                group_payloads=batch_payloads,
                expected_component_names=all_component_names,
            )
            chapter_payload.setdefault("meta", {})
            chapter_payload["meta"].update(
                {
                    "standard_document": standard_document,
                    "chapter_title": chapter["title"],
                    "chapter_index": chapter_index,
                    "merged_component_batch_count": len(batch_payloads),
                    "total_component_batch_count": len(all_component_batches),
                    "merge_strategy": "component_batch_merge",
                }
            )
            write_json(chapter_dir / "chapter_result.json", chapter_payload)
            chapter_results.append(chapter_payload)
            chapter_run_index.append(
                {
                    "chapter_index": chapter_index,
                        "chapter_title": chapter["title"],
                        "chapter_source_path": chapter["source_path"],
                        "chapter_output_dir": str(chapter_dir),
                        "component_batch_count": len(batch_payloads),
                        "chapter_result_path": str(chapter_dir / "chapter_result.json"),
                }
            )

        if prepare_only:
            run_summary = {
                **execute_manifest,
                "status": "prepared_only",
                "total_requests": total_requests,
                "prepared_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "next_step": "去掉 --prepare-only 后继续运行，脚本会逐章逐批调用模型并生成最终 Step2 结果。",
            }
            write_json(output_path / "chapter_run_index.json", {"chapters": chapter_run_index})
            write_json(output_path / "run_summary.json", run_summary)
            return {
                "manifest": execute_manifest,
                "result_payload": {},
                "run_summary": run_summary,
                "output_dir": str(output_path),
            }

        result_payload = merge_chapter_serial_mappings(
            group_payloads=chapter_results,
            expected_component_names=all_component_names,
        )
        result_payload.setdefault("meta", {})
        result_payload["meta"].update(
            {
                "task_name": "component_standard_name_matching",
                "standard_document": standard_document,
                "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "merged_chapter_count": len(chapter_results),
                "merge_strategy": "chapter_serial_merge",
                "components_per_chapter_batch": components_per_chapter_batch,
                "selected_component_batches_per_chapter": len(selected_component_batches),
                "total_component_batches_per_chapter": len(all_component_batches),
            }
        )

        synonym_library = build_synonym_library(result_payload["mappings"], result_payload["meta"])
        run_summary = {
            **execute_manifest,
            "status": "completed",
            "total_requests": total_requests,
            "merged_chapter_count": len(chapter_results),
            "matched_count": sum(1 for item in result_payload["mappings"] if item.get("match_status") == "matched"),
            "candidate_only_count": sum(1 for item in result_payload["mappings"] if item.get("match_status") == "candidate_only"),
            "conflict_count": sum(1 for item in result_payload["mappings"] if item.get("match_status") == "conflict"),
            "pending_review_count": sum(1 for item in result_payload["mappings"] if item.get("review_status") == "pending"),
            "synonym_component_count": len(synonym_library.get("synonym_library", [])),
            "matched_synonym_component_count": sum(
                1 for item in synonym_library.get("synonym_library", []) if str(item.get("selected_standard_name", "")).strip()
            ),
            "synonym_canonical_count": len(synonym_library.get("synonym_library", [])),
            "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }

        write_json(output_path / "chapter_run_index.json", {"chapters": chapter_run_index})
        write_text(output_path / "model_output.txt", "\n\n".join(model_outputs))
        write_json(output_path / "result.json", result_payload)
        write_json(output_path / "component_matching_result.json", result_payload)
        write_json(output_path / "synonym_library.json", synonym_library)
        write_json(output_path / "run_summary.json", run_summary)
        return {
            "manifest": execute_manifest,
            "result_payload": result_payload,
            "run_summary": run_summary,
            "output_dir": str(output_path),
        }
    except Exception as exc:
        error_payload = {
            **execute_manifest,
            "status": "failed",
            "total_requests": total_requests,
            "error": str(exc),
            "failed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        write_text(output_path / "error.txt", str(exc))
        write_json(output_path / "run_summary.json", error_payload)
        raise
    finally:
        for env_key, env_value in previous_environment.items():
            if env_value is None:
                os.environ.pop(env_key, None)
            else:
                os.environ[env_key] = env_value
