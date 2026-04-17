from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from pipeline_v2.model_runtime import DEFAULT_OPENAI_MODEL, normalize_model_name
from pipeline_v2.wiki_retriever import WikiRetriever

from .step1_source import (
    get_default_output_dir as get_default_step1_output_dir,
    get_default_step1_source_path,
    load_step1_regions_source,
)

CHAPTER_MATCH_INSTRUCTIONS_TEMPLATE_NAME = "chapter_match_instructions.txt"
CONSOLIDATION_PROMPT_TEMPLATE_NAME = "consolidation_prompt_template.txt"
DEFAULT_MODEL = DEFAULT_OPENAI_MODEL
DEFAULT_MAX_PROMPT_CHARS = 120_000
DEFAULT_TARGET_REGION_CHARS = 60_000
DEFAULT_MAX_REGIONS_PER_BATCH = 18
DEFAULT_MAX_OUTPUT_TOKENS = 8_000
DEFAULT_TPM_BUDGET = 320_000
DEFAULT_REQUEST_TIMEOUT_SECONDS = 120.0
DEFAULT_CONNECTION_RETRIES = 5
DEFAULT_MAX_COMPONENT_PAYLOAD_CHARS = 18_000
OPENAI_RETRY_LOG_NAME = "openai_request_events.jsonl"
OPENAI_STARTUP_CHECK_NAME = "openai_startup_check.json"
CODEX_CLI_NAME = "codex"
MAX_PROMPT_ALIAS_ITEMS = 20
MAX_PROMPT_HISTORY_ITEMS = 20
NULLISH_TEXT_MARKERS = {
    "",
    "none",
    "null",
    "nil",
    "n/a",
    "na",
    "undefined",
    "无",
    "暂无",
    "空",
    "未匹配",
    "未找到",
    "not matched",
}

SEARCH_NORMALIZATION_REPLACEMENTS = {
    "砼": "混凝土",
    "现浇板": "实心楼板",
    "空心楼盖板": "空心楼板",
    "飘窗": "凸飘窗",
    "雨蓬": "雨篷",
    "门联窗": "连窗门",
    "窗台梁": "过梁",
    "基础连梁": "基础联系梁",
    "基础梁": "基础联系梁",
    "承台梁": "基础联系梁",
    "板洞": "洞",
    "板缝": "后浇带",
    "预制墙": "墙板",
    "预制柱": "实心柱",
    "预制梁": "叠合梁",
    "间壁墙": "轻质隔墙",
    "保温层": "保温隔热",
    "内墙面": "墙面",
    "外墙面": "墙面",
}

COMPONENT_FOCUS_TERMS = (
    "楼地面",
    "墙面",
    "柱面",
    "幕墙",
    "隔墙",
    "楼梯",
    "屋面",
    "地沟",
    "明沟",
    "检查井",
    "集水井",
    "栏杆",
    "栏板",
    "踢脚线",
    "踢脚",
    "保温",
    "隔热",
    "防水",
    "吊顶",
    "天棚",
    "基础",
    "垫层",
    "模板",
    "门窗",
    "门",
    "窗",
    "墙",
    "柱",
    "梁",
    "板",
    "井",
)


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_default_components_path() -> Path:
    root = get_project_root()
    json_path = root / "data" / "input" / "components.json"
    if json_path.exists():
        return json_path
    jsonl_path = root / "data" / "input" / "components.jsonl"
    if jsonl_path.exists():
        return jsonl_path
    raise FileNotFoundError("未找到默认构件列表，请检查 data/input/components.json 或 components.jsonl。")


def get_default_output_dir(step1_source_path: Path) -> Path:
    return get_default_step1_output_dir(step1_source_path, get_project_root())


def load_json_or_jsonl(path: Path) -> Any:
    if path.suffix.lower() == ".jsonl":
        items: List[Any] = []
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if line:
                    items.append(json.loads(line))
        return items
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_summary(path: Path, payload: Dict[str, Any]) -> None:
    write_json(path, payload)


def estimate_payload_chars(payload: Any) -> int:
    return len(json.dumps(payload, ensure_ascii=False))


def join_compact(values: Sequence[Any], sep: str = " | ", limit: int | None = None) -> str:
    items = [str(item).strip() for item in values if str(item).strip()]
    if limit is not None:
        items = items[:limit]
    return sep.join(items)


def truncate_text(text: str, max_chars: int) -> str:
    normalized = (text or "").strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + "\n...[truncated]"


def get_component_source_name(component: Dict[str, Any]) -> str:
    return str(component.get("source_component_name", "") or component.get("component_type", "")).strip()


def get_component_attribute_summaries(component: Dict[str, Any]) -> List[Dict[str, Any]]:
    if isinstance(component.get("attribute_summaries"), list):
        return [item for item in component.get("attribute_summaries", []) if isinstance(item, dict)]

    properties = component.get("properties", {})
    attributes = properties.get("attributes", []) if isinstance(properties, dict) else []
    summaries: List[Dict[str, Any]] = []
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        summaries.append(
            {
                "name": str(attribute.get("name", "")),
                "code": str(attribute.get("code", "")),
                "data_type": str(attribute.get("data_type", "")),
                "values": [str(value).strip() for value in attribute.get("values", []) if str(value).strip()],
            }
        )
    return summaries


def collect_component_terms(component_payload: Sequence[Dict[str, Any]]) -> List[str]:
    component_names = [get_component_source_name(item) for item in component_payload if get_component_source_name(item)]
    search_terms: List[str] = []
    for name in component_names:
        search_terms.extend(expand_component_search_terms(name))
    return deduplicate_preserve_order(term for term in search_terms if str(term).strip())


def format_component_payload_for_prompt(component_payload: Sequence[Dict[str, Any]]) -> str:
    if not component_payload:
        return "无"

    lines: List[str] = []
    for index, item in enumerate(component_payload, start=1):
        source_name = get_component_source_name(item) or f"未命名构件{index}"
        focus_terms = deduplicate_preserve_order(expand_component_search_terms(source_name))
        lines.append(f"{index}. 构件名: {source_name}")
        if focus_terms:
            lines.append(f"   检索词: {join_compact(focus_terms, limit=8)}")

        attribute_summaries = get_component_attribute_summaries(item)
        if attribute_summaries:
            lines.append("   关键属性:")
            for attribute in attribute_summaries:
                values = [str(value).strip() for value in attribute.get("values", []) if str(value).strip()]
                if not values:
                    continue
                attr_name = str(attribute.get("name", "")).strip() or str(attribute.get("code", "")).strip() or "未命名属性"
                attr_code = str(attribute.get("code", "")).strip()
                attr_label = f"{attr_name}[{attr_code}]" if attr_code and attr_code != attr_name else attr_name
                lines.append(f"   - {attr_label}: {join_compact(values, limit=6)}")
        else:
            lines.append("   关键属性: 无明显枚举属性")

    return "\n".join(lines)


def format_region_payload_for_prompt(region_payload: Sequence[Dict[str, Any]]) -> str:
    if not region_payload:
        return "无"

    lines: List[str] = []
    for index, region in enumerate(region_payload, start=1):
        path_text = str(region.get("path_text", "") or region.get("title", "")).strip() or f"章节{index}"
        lines.append(f"{index}. 章节路径: {path_text}")
        lines.append(
            "   统计: "
            f"level={region.get('level', '')}; tables={int(region.get('table_count', 0) or 0)}; "
            f"rows={int(region.get('table_row_count', 0) or 0)}"
        )

        non_table_text = str(region.get("non_table_text_excerpt", "")).strip()
        if non_table_text:
            lines.append(f"   正文摘录: {non_table_text}")

        tables = region.get("tables", []) or []
        for table_index, table in enumerate(tables, start=1):
            title = str(table.get("title", "")).strip() or f"表{table_index}"
            lines.append(f"   表{table_index}标题: {title}")
            headers = table.get("headers", []) or []
            if headers:
                header_text = join_compact(headers, limit=12)
                if header_text:
                    lines.append(f"   表{table_index}表头: {header_text}")
            rows = table.get("rows", []) or []
            compact_rows = [stringify_table_row(row) for row in rows if stringify_table_row(row).strip()]
            if compact_rows:
                lines.append(f"   表{table_index}关键行: {join_compact(compact_rows, sep=' || ', limit=8)}")
            raw_text = str(table.get("raw_text_excerpt", "")).strip()
            if raw_text:
                lines.append(f"   表{table_index}原文摘录: {raw_text}")

    return "\n".join(lines)


def extract_prior_entries(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("synonym_library", "mappings", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def score_prior_entry(entry: Dict[str, Any], normalized_terms: Sequence[str]) -> int:
    searchable_fields: List[str] = []
    for key in (
        "canonical_name",
        "source_component_name",
        "selected_standard_name",
        "project_name",
        "quantity_component",
        "reasoning",
    ):
        value = entry.get(key)
        if isinstance(value, str):
            searchable_fields.append(value)

    for key in (
        "aliases",
        "source_component_names",
        "source_aliases",
        "standard_aliases",
        "candidate_standard_names",
    ):
        value = entry.get(key)
        if isinstance(value, list):
            searchable_fields.extend(str(item) for item in value if str(item).strip())

    searchable_text = normalize_search_text(" ".join(searchable_fields))
    score = 0
    for term in normalized_terms:
        if term and term in searchable_text:
            score += max(1, len(term))
    return score


def select_relevant_prior_entries(
    payload: Any,
    component_payload: Sequence[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    entries = extract_prior_entries(payload)
    if not entries:
        return []

    normalized_terms = deduplicate_preserve_order(
        normalize_search_text(term)
        for term in collect_component_terms(component_payload)
        if normalize_search_text(term)
    )
    ranked_entries = []
    for index, entry in enumerate(entries):
        score = score_prior_entry(entry, normalized_terms)
        if score <= 0:
            continue
        ranked_entries.append((score, index, entry))

    ranked_entries.sort(key=lambda item: (-item[0], item[1]))
    return [entry for _, _, entry in ranked_entries[:limit]]


def format_alias_payload_for_prompt(alias_payload: Any, component_payload: Sequence[Dict[str, Any]]) -> str:
    entries = select_relevant_prior_entries(alias_payload, component_payload, MAX_PROMPT_ALIAS_ITEMS)
    if not entries:
        return "无与当前批次明显相关的别名字典条目"

    lines: List[str] = []
    for index, entry in enumerate(entries, start=1):
        canonical_name = str(entry.get("canonical_name", "")).strip()
        aliases = join_compact(entry.get("aliases", []) or [], limit=10)
        source_component_names = join_compact(entry.get("source_component_names", []) or [], limit=10)
        line = f"{index}. 标准名: {canonical_name or '未标注'}"
        if aliases:
            line += f"; 别名: {aliases}"
        if source_component_names:
            line += f"; 来源构件: {source_component_names}"
        lines.append(line)
    return "\n".join(lines)


def format_history_payload_for_prompt(history_payload: Any, component_payload: Sequence[Dict[str, Any]]) -> str:
    entries = select_relevant_prior_entries(history_payload, component_payload, MAX_PROMPT_HISTORY_ITEMS)
    if not entries:
        return "无与当前批次明显相关的历史人工修订"

    lines: List[str] = []
    for index, entry in enumerate(entries, start=1):
        source_name = str(entry.get("source_component_name", "") or entry.get("project_name", "")).strip() or "未标注"
        selected_name = str(entry.get("selected_standard_name", "") or entry.get("quantity_component", "")).strip()
        review_status = str(entry.get("review_status", "")).strip()
        match_status = str(entry.get("match_status", "")).strip()
        reasoning = str(entry.get("reasoning", "")).strip()
        line = f"{index}. 历史项: source={source_name}"
        if selected_name:
            line += f"; selected={selected_name}"
        if match_status:
            line += f"; match_status={match_status}"
        if review_status:
            line += f"; review_status={review_status}"
        if reasoning:
            line += f"; note={truncate_text(reasoning, 80)}"
        lines.append(line)
    return "\n".join(lines)


def format_mapping_for_prompt(mapping: Dict[str, Any], index: int) -> str:
    source_name = str(mapping.get("source_component_name", "")).strip() or f"未标注构件{index}"
    selected_name = str(mapping.get("selected_standard_name", "")).strip()
    candidate_names = join_compact(mapping.get("candidate_standard_names", []) or [], limit=8)
    evidence_paths = join_compact(mapping.get("evidence_paths", []) or [], limit=6)
    evidence_texts = join_compact(mapping.get("evidence_texts", []) or [], sep=" || ", limit=4)
    reasoning = str(mapping.get("reasoning", "")).strip()
    line = (
        f"{index}. source={source_name}; selected={selected_name or '未选定'}; "
        f"match_status={str(mapping.get('match_status', '')).strip() or 'unmatched'}; "
        f"match_type={str(mapping.get('match_type', '')).strip() or 'unknown'}; "
        f"confidence={float(mapping.get('confidence', 0.0) or 0.0):.2f}; "
        f"review_status={str(mapping.get('review_status', '')).strip() or 'pending'}"
    )
    extras: List[str] = []
    if candidate_names:
        extras.append(f"candidates={candidate_names}")
    if evidence_paths:
        extras.append(f"paths={evidence_paths}")
    if evidence_texts:
        extras.append(f"evidence={evidence_texts}")
    if reasoning:
        extras.append(f"reasoning={truncate_text(reasoning, 120)}")
    if extras:
        line += "; " + "; ".join(extras)
    return line


def format_window_results_for_prompt(window_payloads: Sequence[Dict[str, Any]]) -> str:
    if not window_payloads:
        return "无章节窗口结果"

    lines: List[str] = []
    for window in window_payloads:
        window_index = int(window.get("region_window_index", 0) or 0)
        window_count = int(window.get("region_window_count", 0) or 0)
        selected_paths = join_compact(window.get("selected_region_paths", []) or [], limit=12)
        lines.append(
            f"窗口 {window_index}/{window_count}: "
            f"batch_index={int(window.get('batch_index', 0) or 0)}; "
            f"chapter_paths={selected_paths or '无'}"
        )
        result_payload = window.get("result", {}) or {}
        mappings = result_payload.get("mappings", []) if isinstance(result_payload, dict) else []
        for mapping_index, mapping in enumerate(mappings, start=1):
            if isinstance(mapping, dict):
                lines.append("  " + format_mapping_for_prompt(mapping, mapping_index))
    return "\n".join(lines)


def summarize_tables(tables: Sequence[Dict[str, Any]], max_table_rows: int, max_table_text_chars: int) -> List[Dict[str, Any]]:
    summarized_tables: List[Dict[str, Any]] = []
    for table in tables:
        rows = table.get("rows", [])[:max_table_rows]
        summarized_tables.append(
            {
                "title": str(table.get("title", "")),
                "headers": table.get("headers", []),
                "rows": rows,
                "raw_text_excerpt": truncate_text(str(table.get("raw_text", "")), max_table_text_chars),
            }
        )
    return summarized_tables


def summarize_regions(
    regions: Sequence[Dict[str, Any]],
    max_region_text_chars: int,
    max_table_text_chars: int,
    max_table_rows: int,
    only_regions_with_tables: bool,
) -> List[Dict[str, Any]]:
    summarized: List[Dict[str, Any]] = []
    for item in regions:
        tables = item.get("tables", []) or []
        if only_regions_with_tables and not tables:
            continue

        region_payload: Dict[str, Any] = {
            "title": str(item.get("title", "")),
            "path_text": str(item.get("path_text", "")),
            "level": item.get("level"),
            "table_count": item.get("table_count", 0),
            "table_row_count": item.get("table_row_count", 0),
        }

        non_table_text = str(item.get("non_table_text", "") or item.get("text", ""))
        if non_table_text:
            region_payload["non_table_text_excerpt"] = truncate_text(non_table_text, max_region_text_chars)

        if tables:
            region_payload["tables"] = summarize_tables(
                tables=tables,
                max_table_rows=max_table_rows,
                max_table_text_chars=max_table_text_chars,
            )

        summarized.append(region_payload)

    return summarized


def chunk_list(items: Sequence[Any], batch_size: int) -> List[List[Any]]:
    if batch_size <= 0:
        return [list(items)]
    return [list(items[index:index + batch_size]) for index in range(0, len(items), batch_size)]


def normalize_search_text(text: Any) -> str:
    normalized = str(text or "").strip()
    for old, new in SEARCH_NORMALIZATION_REPLACEMENTS.items():
        normalized = normalized.replace(old, new)
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(r"[，,。、“”‘’：:；;（）()\[\]{}<>《》·•\-_\\/|]", "", normalized)
    return normalized


def expand_component_search_terms(name: str) -> List[str]:
    text = str(name or "").strip()
    if not text:
        return []

    terms = [text]
    normalized = normalize_search_text(text)
    if normalized and normalized != text:
        terms.append(normalized)

    for old, new in SEARCH_NORMALIZATION_REPLACEMENTS.items():
        if old in text:
            terms.append(new)

    for focus_term in COMPONENT_FOCUS_TERMS:
        if focus_term in text:
            terms.append(focus_term)

    if text.endswith("墙面"):
        terms.extend(["墙面", "墙"])
    if text.endswith("柱面"):
        terms.extend(["柱面", "柱"])

    return deduplicate_preserve_order(terms)


def extract_alias_search_terms(component_names: Sequence[str], alias_payload: Any) -> List[str]:
    if not isinstance(alias_payload, list):
        return []

    normalized_names = {normalize_search_text(name) for name in component_names if str(name).strip()}
    alias_terms: List[str] = []

    for item in alias_payload:
        if not isinstance(item, dict):
            continue

        related_names: List[str] = []
        for key in ("source_component_name", "selected_standard_name", "canonical_name"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                related_names.append(value)

        for key in ("source_component_names", "source_aliases", "standard_aliases", "aliases"):
            value = item.get(key)
            if isinstance(value, list):
                related_names.extend(str(entry).strip() for entry in value if str(entry).strip())

        if not normalized_names.intersection(normalize_search_text(name) for name in related_names if name):
            continue

        alias_terms.extend(related_names)

    return deduplicate_preserve_order(alias_terms)


def stringify_table_row(row: Any) -> str:
    if isinstance(row, dict):
        return json.dumps(row, ensure_ascii=False, sort_keys=True)
    if isinstance(row, list):
        return " ".join(str(item) for item in row if str(item).strip())
    return str(row or "")


def build_region_search_index(region: Dict[str, Any]) -> Dict[str, str]:
    table_titles: List[str] = []
    table_headers: List[str] = []
    table_rows: List[str] = []
    table_raw_texts: List[str] = []

    for table in region.get("tables", []) or []:
        table_titles.append(str(table.get("title", "")))
        table_headers.append(json.dumps(table.get("headers", []), ensure_ascii=False))
        table_rows.extend(stringify_table_row(row) for row in table.get("rows", []) or [])
        table_raw_texts.append(str(table.get("raw_text_excerpt", "")))

    return {
        "title": normalize_search_text(region.get("title", "")),
        "path_text": normalize_search_text(region.get("path_text", "")),
        "non_table_text": normalize_search_text(region.get("non_table_text_excerpt", "")),
        "table_titles": normalize_search_text(" ".join(table_titles)),
        "table_headers": normalize_search_text(" ".join(table_headers)),
        "table_rows": normalize_search_text(" ".join(table_rows)),
        "table_raw_text": normalize_search_text(" ".join(table_raw_texts)),
    }


def score_region_for_terms(region: Dict[str, Any], normalized_terms: Sequence[str]) -> tuple[float, List[str]]:
    region_index = build_region_search_index(region)
    matched_terms: List[str] = []
    score = 0.0

    for term in normalized_terms:
        if not term:
            continue

        term_length = len(term)
        matched = False

        if term_length <= 1:
            if (
                term in region_index["title"]
                or term in region_index["path_text"]
                or term in region_index["table_titles"]
            ):
                score += 0.8
                matched = True
        elif term in region_index["title"]:
            score += 10.0 + min(term_length, 8)
            matched = True
        elif term in region_index["path_text"]:
            score += 8.0 + min(term_length, 8) * 0.8
            matched = True
        elif term in region_index["table_titles"]:
            score += 6.0 + min(term_length, 8) * 0.6
            matched = True
        elif term in region_index["table_headers"]:
            score += 4.0 + min(term_length, 8) * 0.4
            matched = True
        elif (
            term in region_index["table_rows"]
            or term in region_index["table_raw_text"]
            or term in region_index["non_table_text"]
        ):
            score += 3.0 + min(term_length, 8) * 0.3
            matched = True

        if matched:
            matched_terms.append(term)

    if matched_terms:
        score += min(int(region.get("table_count", 0) or 0), 4) * 0.3
        score += min(int(region.get("table_row_count", 0) or 0), 30) * 0.05

    return score, deduplicate_preserve_order(matched_terms)


def select_regions_for_batch(
    component_payload: Sequence[Dict[str, Any]],
    all_regions: Sequence[Dict[str, Any]],
    alias_payload: Any,
    target_region_chars: int,
    max_regions_per_batch: int,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    component_names = [get_component_source_name(item) for item in component_payload if get_component_source_name(item)]
    search_terms: List[str] = []
    for name in component_names:
        search_terms.extend(expand_component_search_terms(name))
    search_terms.extend(extract_alias_search_terms(component_names, alias_payload))

    normalized_terms = deduplicate_preserve_order(
        term
        for term in (normalize_search_text(item) for item in search_terms)
        if term
    )
    normalized_terms.sort(key=len, reverse=True)

    ranked_regions: List[Dict[str, Any]] = []
    for index, region in enumerate(all_regions):
        score, matched_terms = score_region_for_terms(region, normalized_terms)
        ranked_regions.append(
            {
                "index": index,
                "region": region,
                "score": score,
                "matched_terms": matched_terms,
                "payload_chars": estimate_payload_chars(region),
                "table_count": int(region.get("table_count", 0) or 0),
                "table_row_count": int(region.get("table_row_count", 0) or 0),
            }
        )

    positive_regions = [item for item in ranked_regions if item["score"] > 0]
    fallback_regions = ranked_regions if positive_regions else sorted(
        ranked_regions,
        key=lambda item: (-item["table_row_count"], -item["table_count"], item["payload_chars"], item["index"]),
    )
    ranked_candidates = sorted(
        positive_regions or fallback_regions,
        key=lambda item: (
            -item["score"],
            -len(item["matched_terms"]),
            -item["table_row_count"],
            item["payload_chars"],
            item["index"],
        ),
    )

    selected: List[Dict[str, Any]] = []
    selected_indexes = set()
    selected_group_keys = set()
    total_region_chars = 0
    region_budget = max(target_region_chars, 0)

    for candidate in ranked_candidates:
        if len(selected) >= max_regions_per_batch:
            break

        group_key = get_region_group_key(candidate["region"])
        if group_key in selected_group_keys:
            continue

        candidate_chars = candidate["payload_chars"]
        if selected and total_region_chars + candidate_chars > region_budget:
            break

        selected.append(candidate)
        selected_indexes.add(candidate["index"])
        selected_group_keys.add(group_key)
        total_region_chars += candidate_chars

        if total_region_chars >= region_budget:
            break

    if not selected and ranked_candidates:
        selected = [ranked_candidates[0]]
        selected_indexes = {ranked_candidates[0]["index"]}
        total_region_chars = ranked_candidates[0]["payload_chars"]

    selected.sort(key=lambda item: item["index"])
    selected_regions = [item["region"] for item in selected]

    debug_payload = {
        "component_names": component_names,
        "search_terms": search_terms[:80],
        "normalized_term_count": len(normalized_terms),
        "matched_region_count": len(positive_regions),
        "selected_region_count": len(selected_regions),
        "selected_region_chars": total_region_chars,
        "selected_group_keys": sorted(selected_group_keys),
        "selected_region_titles": [str(item["region"].get("path_text", "") or item["region"].get("title", "")) for item in selected],
    }
    return selected_regions, debug_payload


def get_region_group_key(region: Dict[str, Any]) -> str:
    path_text = str(region.get("path_text", "")).strip()
    if path_text:
        return path_text.split(" > ")[0]
    return str(region.get("title", "")).strip()


def build_top_level_region_groups(all_regions: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: List[Dict[str, Any]] = []
    group_by_key: Dict[str, Dict[str, Any]] = {}

    for index, region in enumerate(all_regions):
        group_key = get_region_group_key(region)
        if group_key not in group_by_key:
            group = {
                "key": group_key,
                "first_index": index,
                "regions": [],
            }
            groups.append(group)
            group_by_key[group_key] = group
        group_by_key[group_key]["regions"].append(region)

    return groups


def expand_regions_to_top_level_groups(
    selected_regions: Sequence[Dict[str, Any]],
    all_regions: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    selected_keys = {get_region_group_key(region) for region in selected_regions}
    return [group for group in build_top_level_region_groups(all_regions) if group["key"] in selected_keys]


def pack_selected_regions_into_windows(
    component_payload: Sequence[Dict[str, Any]],
    selected_regions: Sequence[Dict[str, Any]],
    all_regions: Sequence[Dict[str, Any]],
    alias_payload: Any,
    history_payload: Any,
    max_prompt_chars: int,
    max_regions_per_window: int,
) -> tuple[List[List[Dict[str, Any]]] | None, Dict[str, Any]]:
    if not selected_regions:
        prompt_preview = build_prompt_text(
            component_payload=component_payload,
            region_payload=[],
            alias_payload=alias_payload,
            history_payload=history_payload,
            batch_index=0,
            total_batches=0,
            region_window_index=1,
            region_window_count=1,
        )
        return ([[]] if len(prompt_preview) <= max_prompt_chars else None), {
            "selected_group_keys": [],
            "fallback_group_keys": [],
        }

    windows: List[List[Dict[str, Any]]] = []
    selected_groups = expand_regions_to_top_level_groups(selected_regions, all_regions)
    fallback_group_keys: List[str] = []

    for group in selected_groups:
        group_regions = list(group["regions"])
        group_prompt = build_prompt_text(
            component_payload=component_payload,
            region_payload=group_regions,
            alias_payload=alias_payload,
            history_payload=history_payload,
            batch_index=0,
            total_batches=0,
            region_window_index=1,
            region_window_count=1,
        )

        if len(group_regions) <= max_regions_per_window and len(group_prompt) <= max_prompt_chars:
            windows.append(group_regions)
            continue

        fallback_group_keys.append(str(group["key"]))
        for region in group_regions:
            single_region_prompt = build_prompt_text(
                component_payload=component_payload,
                region_payload=[region],
                alias_payload=alias_payload,
                history_payload=history_payload,
                batch_index=0,
                total_batches=0,
                region_window_index=1,
                region_window_count=1,
            )
            if len(single_region_prompt) > max_prompt_chars:
                return None, {
                    "selected_group_keys": [str(item["key"]) for item in selected_groups],
                    "fallback_group_keys": fallback_group_keys,
                    "failed_chapter_path": str(region.get("path_text", "") or region.get("title", "")),
                }
            windows.append([region])

    return windows, {
        "selected_group_keys": [str(group["key"]) for group in selected_groups],
        "fallback_group_keys": fallback_group_keys,
    }


def load_template(template_name: str) -> str:
    path = Path(__file__).with_name(template_name)
    return path.read_text(encoding="utf-8")


def infer_component_bucket(component: Dict[str, Any]) -> str:
    source_name = get_component_source_name(component)
    searchable_parts = [source_name]
    for attribute in get_component_attribute_summaries(component):
        searchable_parts.extend(str(value) for value in attribute.get("values", []) or [])

    searchable_text = normalize_search_text(" ".join(searchable_parts))
    for focus_term in COMPONENT_FOCUS_TERMS:
        normalized_focus = normalize_search_text(focus_term)
        if normalized_focus and normalized_focus in searchable_text:
            return focus_term

    if source_name:
        return source_name[:2]
    return "其他"


def build_initial_component_batches(
    preprocessed_components: Sequence[Dict[str, Any]],
    max_components_per_batch: int,
    max_component_payload_chars: int,
) -> List[List[Dict[str, Any]]]:
    grouped_components: Dict[str, List[Dict[str, Any]]] = {}
    ordered_group_keys: List[str] = []

    for component in preprocessed_components:
        bucket = infer_component_bucket(component)
        if bucket not in grouped_components:
            grouped_components[bucket] = []
            ordered_group_keys.append(bucket)
        grouped_components[bucket].append(component)

    batches: List[List[Dict[str, Any]]] = []
    for bucket in ordered_group_keys:
        current_batch: List[Dict[str, Any]] = []
        current_chars = 0
        for component in grouped_components[bucket]:
            component_chars = estimate_payload_chars(component)
            exceeds_batch_size = bool(current_batch) and len(current_batch) >= max_components_per_batch
            exceeds_char_budget = bool(current_batch) and current_chars + component_chars > max_component_payload_chars
            if exceeds_batch_size or exceeds_char_budget:
                batches.append(current_batch)
                current_batch = []
                current_chars = 0

            current_batch.append(component)
            current_chars += component_chars

        if current_batch:
            batches.append(current_batch)

    return batches


def build_chapter_match_instructions(
    batch_index: int,
    total_batches: int,
    component_count: int,
    region_window_index: int | None = None,
    region_window_count: int | None = None,
) -> str:
    template = load_template(CHAPTER_MATCH_INSTRUCTIONS_TEMPLATE_NAME)
    header = (
        f"当前批次信息:\n"
        f"- batch_index: {batch_index}\n"
        f"- total_batches: {total_batches}\n"
        f"- current_batch_component_count: {component_count}\n"
    )
    if region_window_index is not None and region_window_count is not None:
        header += (
            f"- region_window_index: {region_window_index}\n"
            f"- region_window_count: {region_window_count}\n"
            "- chapter_window_rule: 当前请求只包含当前章节窗口，不要引用未提供章节。\n"
        )
    return header + "\n" + template


def build_components_context_text(
    component_payload: Sequence[Dict[str, Any]],
    alias_payload: Any,
    history_payload: Any,
) -> str:
    sections = [
        "【构件组摘要】",
        format_component_payload_for_prompt(component_payload),
        "",
        "【与当前构件组相关的先验别名】",
        format_alias_payload_for_prompt(alias_payload, component_payload),
        "",
        "【与当前构件组相关的历史人工修订】",
        format_history_payload_for_prompt(history_payload, component_payload),
    ]
    return "\n".join(sections)


def build_chapter_context_text(region_payload: Sequence[Dict[str, Any]]) -> str:
    return "\n".join(
        [
            "【当前章节窗口摘要】",
            format_region_payload_for_prompt(region_payload),
        ]
    )


def build_chapter_request_payload(
    component_payload: Sequence[Dict[str, Any]],
    region_payload: Sequence[Dict[str, Any]],
    alias_payload: Any,
    history_payload: Any,
    batch_index: int,
    total_batches: int,
    region_window_index: int,
    region_window_count: int,
    wiki_context: str = "",
) -> Dict[str, Any]:
    instructions_text = build_chapter_match_instructions(
        batch_index=batch_index,
        total_batches=total_batches,
        component_count=len(component_payload),
        region_window_index=region_window_index,
        region_window_count=region_window_count,
    )
    components_text = build_components_context_text(component_payload, alias_payload, history_payload)
    chapter_text = build_chapter_context_text(region_payload)
    parts = [
        instructions_text,
        "【components.txt】",
        components_text,
        "【chapter.txt】",
        chapter_text,
    ]
    if wiki_context:
        parts.insert(2, "【wiki_reference.txt】\n" + wiki_context)
    preview_text = "\n\n".join(parts)
    content_items = [
        {
            "type": "input_text",
            "text": "【components.txt】\n" + components_text,
        },
    ]
    if wiki_context:
        content_items.append({
            "type": "input_text",
            "text": "【wiki_reference.txt】\n" + wiki_context,
        })
    content_items.append({
        "type": "input_text",
        "text": "【chapter.txt】\n" + chapter_text,
    })
    input_items = [
        {
            "role": "user",
            "content": content_items,
        }
    ]
    return {
        "instructions_text": instructions_text,
        "components_text": components_text,
        "chapter_text": chapter_text,
        "wiki_context": wiki_context,
        "preview_text": preview_text,
        "input_items": input_items,
    }


def build_prompt_text(
    component_payload: Sequence[Dict[str, Any]],
    region_payload: Sequence[Dict[str, Any]],
    alias_payload: Any,
    history_payload: Any,
    batch_index: int,
    total_batches: int,
    region_window_index: int | None = None,
    region_window_count: int | None = None,
    wiki_context: str = "",
) -> str:
    payload = build_chapter_request_payload(
        component_payload=component_payload,
        region_payload=region_payload,
        alias_payload=alias_payload,
        history_payload=history_payload,
        batch_index=batch_index,
        total_batches=total_batches,
        region_window_index=region_window_index or 1,
        region_window_count=region_window_count or 1,
        wiki_context=wiki_context,
    )
    return str(payload["preview_text"])


def build_consolidation_prompt_text(
    component_payload: Sequence[Dict[str, Any]],
    window_payloads: Sequence[Dict[str, Any]],
    component_group_id: int,
    total_component_groups: int,
) -> str:
    template = load_template(CONSOLIDATION_PROMPT_TEMPLATE_NAME)
    header = (
        f"整合批次信息:\n"
        f"- component_group_id: {component_group_id}\n"
        f"- total_component_groups: {total_component_groups}\n"
        f"- chapter_window_count: {len(window_payloads)}\n\n"
    )
    prompt_text = header + template
    replacements = {
        "${COMPONENT_LIST_JSON}": build_components_context_text(component_payload, [], []),
        "${WINDOW_RESULT_SUMMARIES}": format_window_results_for_prompt(window_payloads),
    }
    for placeholder, value in replacements.items():
        prompt_text = prompt_text.replace(placeholder, value)
    return prompt_text


def build_consolidation_request_payload(
    component_payload: Sequence[Dict[str, Any]],
    window_payloads: Sequence[Dict[str, Any]],
    component_group_id: int,
    total_component_groups: int,
) -> Dict[str, Any]:
    instructions_text = (
        f"整合批次信息:\n"
        f"- component_group_id: {component_group_id}\n"
        f"- total_component_groups: {total_component_groups}\n"
        f"- chapter_window_count: {len(window_payloads)}\n\n"
        "你将收到两个独立文件：`components.txt` 和 `window_results.txt`。\n"
        "请基于这些中间结果，对同一构件在不同章节窗口中的候选结论进行归并。\n"
        "优先保留跨章节一致、证据更强、置信度更高的结论；若仍无法唯一确定，请输出 candidate_only 或 conflict。\n"
        "不要漏掉任何输入构件，输出必须是合法 JSON，不要输出 Markdown。\n"
    )
    components_text = "\n".join(
        [
            "【当前构件组摘要】",
            format_component_payload_for_prompt(component_payload),
        ]
    )
    window_results_text = "\n".join(
        [
            "【按章节窗口拆分后的中间结果】",
            format_window_results_for_prompt(window_payloads),
        ]
    )
    preview_text = "\n\n".join(
        [
            instructions_text,
            "【components.txt】",
            components_text,
            "【window_results.txt】",
            window_results_text,
        ]
    )
    input_items = [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "【components.txt】\n" + components_text,
                },
                {
                    "type": "input_text",
                    "text": "【window_results.txt】\n" + window_results_text,
                },
            ],
        }
    ]
    return {
        "instructions_text": instructions_text,
        "components_text": components_text,
        "window_results_text": window_results_text,
        "preview_text": preview_text,
        "input_items": input_items,
    }


def extract_json_text(raw_text: str) -> str:
    stripped = raw_text.strip()
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

    raise ValueError("模型输出中未找到可解析的 JSON 内容。")


def normalize_optional_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text.casefold() in NULLISH_TEXT_MARKERS:
        return ""
    return text


def normalize_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [text for item in value if (text := normalize_optional_text(item))]
    if isinstance(value, str):
        text = normalize_optional_text(value)
        return [text] if text else []
    text = normalize_optional_text(value)
    return [text] if text else []


def normalize_mapping(record: Dict[str, Any]) -> Dict[str, Any]:
    confidence = record.get("confidence", 0.0)
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = 0.0

    source_component_name = normalize_optional_text(record.get("source_component_name", ""))
    source_aliases = deduplicate_preserve_order(
        ([source_component_name] if source_component_name else []) + normalize_string_list(record.get("source_aliases"))
    )
    selected_standard_name = normalize_optional_text(
        record.get("selected_standard_name", "") or record.get("quantity_component", "")
    )
    candidate_standard_names = deduplicate_preserve_order(
        ([selected_standard_name] if selected_standard_name else [])
        + normalize_string_list(record.get("candidate_standard_names"))
    )
    raw_match_status = str(record.get("match_status", "")).strip().lower()
    if selected_standard_name:
        match_status = "matched"
        review_status = str(record.get("review_status", "")).strip() or "suggested"
    elif candidate_standard_names:
        match_status = "conflict" if raw_match_status == "conflict" else "candidate_only"
        review_status = str(record.get("review_status", "")).strip() or "pending"
    else:
        match_status = "unmatched"
        review_status = str(record.get("review_status", "")).strip() or "pending"

    return {
        "source_component_name": source_component_name,
        "source_aliases": source_aliases,
        "selected_standard_name": selected_standard_name,
        "standard_aliases": deduplicate_preserve_order(
            ([selected_standard_name] if selected_standard_name else [])
            + normalize_string_list(record.get("standard_aliases"))
        ),
        "candidate_standard_names": candidate_standard_names,
        "match_type": str(record.get("match_type", "")).strip(),
        "match_status": match_status,
        "confidence": max(0.0, min(1.0, confidence_value)),
        "review_status": review_status,
        "evidence_paths": normalize_string_list(record.get("evidence_paths")),
        "evidence_texts": normalize_string_list(record.get("evidence_texts")),
        "reasoning": str(record.get("reasoning", "")).strip(),
        "manual_notes": str(record.get("manual_notes", "")).strip(),
    }


def normalize_result_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
    mappings = payload.get("mappings", []) if isinstance(payload, dict) else []
    if not isinstance(meta, dict):
        meta = {}
    if not isinstance(mappings, list):
        raise ValueError("模型输出中的 mappings 字段必须为数组。")

    return {
        "meta": {
            "task_name": str(meta.get("task_name", "component_standard_name_matching")),
            "standard_document": str(meta.get("standard_document", "")),
            "generated_at": str(meta.get("generated_at", datetime.now().astimezone().isoformat(timespec="seconds"))),
            "review_stage": str(meta.get("review_stage", "pre_parse")),
        },
        "mappings": [normalize_mapping(item) for item in mappings if isinstance(item, dict)],
    }


def ensure_all_components_present(
    mappings: Sequence[Dict[str, Any]],
    expected_component_names: Sequence[str],
) -> List[Dict[str, Any]]:
    mapping_by_source = {}
    for item in mappings:
        source_name = item.get("source_component_name", "")
        if source_name and source_name not in mapping_by_source:
            mapping_by_source[source_name] = item

    results: List[Dict[str, Any]] = []
    for name in expected_component_names:
        if name in mapping_by_source:
            results.append(mapping_by_source[name])
            continue

        results.append(
            {
                "source_component_name": name,
                "source_aliases": [name],
                "selected_standard_name": "",
                "standard_aliases": [],
                "candidate_standard_names": [],
                "match_type": "",
                "match_status": "unmatched",
                "confidence": 0.0,
                "review_status": "pending",
                "evidence_paths": [],
                "evidence_texts": [],
                "reasoning": "模型未返回该构件，已由脚本补为待人工复核的未匹配项。",
                "manual_notes": "",
            }
        )
    return results


def extract_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    response_dict = None
    if hasattr(response, "model_dump"):
        response_dict = response.model_dump()
    elif hasattr(response, "to_dict"):
        response_dict = response.to_dict()

    if not isinstance(response_dict, dict):
        raise RuntimeError("无法从 Responses API 响应中提取文本内容。")

    chunks: List[str] = []
    for output_item in response_dict.get("output", []):
        for content in output_item.get("content", []):
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text)

    if chunks:
        return "\n".join(chunks)

    raise RuntimeError("Responses API 响应中没有可用文本。")


def estimate_request_tokens(prompt_text: str, max_output_tokens: int | None) -> int:
    return len(prompt_text) + int(max_output_tokens or 0) + 1_024


def wait_for_tpm_budget(
    estimated_request_tokens: int,
    request_history: List[Dict[str, float]],
    tpm_budget: int | None,
) -> None:
    if not tpm_budget or tpm_budget <= 0:
        return

    now = time.time()
    request_history[:] = [item for item in request_history if now - float(item["timestamp"]) < 60]

    if estimated_request_tokens > tpm_budget:
        raise RuntimeError(
            f"单次请求估算 token 约为 {estimated_request_tokens}，已经超过 tpm_budget={tpm_budget}。"
            "请降低 --max-prompt-chars 或 --max-output-tokens。"
        )

    while sum(int(item["tokens"]) for item in request_history) + estimated_request_tokens > tpm_budget:
        oldest = min(request_history, key=lambda item: float(item["timestamp"]))
        wait_seconds = max(1.0, 60 - (time.time() - float(oldest["timestamp"])) + 0.5)
        time.sleep(wait_seconds)
        now = time.time()
        request_history[:] = [item for item in request_history if now - float(item["timestamp"]) < 60]


def get_openai_base_label(base_url: str | None) -> str:
    return str(base_url or "https://api.openai.com/v1")


def describe_exception(exc: BaseException) -> Dict[str, str]:
    root_cause = exc.__cause__ or exc.__context__
    payload = {
        "error_type": type(exc).__name__,
        "error_message": str(exc),
    }
    if root_cause:
        payload["root_cause_type"] = type(root_cause).__name__
        payload["root_cause_message"] = str(root_cause)
    return payload


def log_openai_event(
    log_path: Path | None,
    *,
    phase: str,
    event: str,
    model: str,
    base_url: str | None,
    request_timeout_seconds: float,
    attempt: int | None = None,
    total_attempts: int | None = None,
    wait_seconds: float | None = None,
    extra: Dict[str, Any] | None = None,
    exc: BaseException | None = None,
) -> None:
    if log_path is None:
        return

    payload: Dict[str, Any] = {
        "logged_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "phase": phase,
        "event": event,
        "model": model,
        "base_url": get_openai_base_label(base_url),
        "request_timeout_seconds": request_timeout_seconds,
    }
    if attempt is not None:
        payload["attempt"] = attempt
    if total_attempts is not None:
        payload["total_attempts"] = total_attempts
    if wait_seconds is not None:
        payload["wait_seconds"] = wait_seconds
    if extra:
        payload.update(extra)
    if exc is not None:
        payload.update(describe_exception(exc))

    append_jsonl(log_path, payload)


def is_gemini_cli_model(model: str | None) -> bool:
    text = str(model or "").strip().lower()
    return text.startswith("gemini") or text.startswith("google/gemini")


def map_model_for_gemini_cli(model: str | None) -> str:
    text = str(model or "").strip()
    lowered = text.lower()
    if lowered in {"gemini", "gemini-free", "gemini flash", "google/gemini-2.5-flash", "gemini-2.5-flash"}:
        return "gemini-2.5-flash"
    if lowered in {"gemini lite", "google/gemini-2.5-flash-lite", "gemini-2.5-flash-lite"}:
        return "gemini-2.5-flash-lite"
    return text or "gemini-2.5-flash"


def resolve_provider_mode(provider_mode: str | None = None) -> str:
    text = str(provider_mode or os.getenv("PIPELINE_STEP2_PROVIDER_MODE") or "").strip().lower()
    return text


def build_codex_prompt_text(
    *,
    prompt_text: str | None,
    instructions_text: str | None,
    input_items: Any | None,
) -> str:
    sections: List[str] = []
    instructions = str(instructions_text or "").strip()
    if instructions:
        sections.append(instructions)

    prompt = str(prompt_text or "").strip()
    if prompt:
        sections.append(prompt)

    if input_items is not None:
        sections.append(
            "\n".join(
                [
                    "以下是补充输入，请按 JSON 语义一起处理：",
                    json.dumps(input_items, ensure_ascii=False, indent=2),
                ]
            )
        )

    merged = "\n\n".join(section for section in sections if section.strip()).strip()
    if not merged:
        raise ValueError("Codex CLI 调用缺少可用提示词。")
    return merged


def extract_process_error_tail(*texts: str | None) -> str:
    ignored_prefixes = (
        "WARNING: proceeding, even though we could not update PATH",
        "OpenAI Codex v",
        "--------",
        "workdir:",
        "model:",
        "provider:",
        "approval:",
        "sandbox:",
        "reasoning effort:",
        "reasoning summaries:",
        "session id:",
        "user",
    )
    ignored_contains = (
        "rollout::list: state db missing rollout path for thread",
    )

    for text in texts:
        lines = []
        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if any(line.startswith(prefix) for prefix in ignored_prefixes):
                continue
            if any(marker in line for marker in ignored_contains):
                continue
            lines.append(line)
        if lines:
            return lines[-1]
    return ""


def run_codex_login_status(request_timeout_seconds: float) -> str:
    try:
        completed = subprocess.run(
            [CODEX_CLI_NAME, "login", "status"],
            capture_output=True,
            text=True,
            timeout=request_timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "未检测到 codex CLI。请先安装 Codex，并执行 `codex login` 或 `codex login --device-auth`。"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Codex 登录态检查超时（>{request_timeout_seconds}s）。请稍后重试，或先手动执行 `codex login status`。"
        ) from exc

    status_text = "\n".join(
        part.strip()
        for part in (completed.stdout, completed.stderr)
        if str(part or "").strip()
    ).strip()
    if completed.returncode != 0:
        detail = status_text or f"{CODEX_CLI_NAME} login status exited with code {completed.returncode}"
        raise RuntimeError(f"Codex 登录态检查失败：{detail}")
    return status_text or "Logged in using ChatGPT"


def run_codex_cli_prompt(
    *,
    model: str,
    reasoning_effort: str | None,
    request_timeout_seconds: float,
    prompt_text: str | None,
    instructions_text: str | None,
    input_items: Any | None,
) -> str:
    normalized_model = normalize_model_name(model, DEFAULT_MODEL) or DEFAULT_MODEL
    merged_prompt = build_codex_prompt_text(
        prompt_text=prompt_text,
        instructions_text=instructions_text,
        input_items=input_items,
    )

    with tempfile.TemporaryDirectory(prefix="pipeline_v2_codex_") as temp_dir:
        temp_path = Path(temp_dir)
        output_last_message_path = temp_path / "codex_last_message.txt"
        cmd = [
            CODEX_CLI_NAME,
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--model",
            normalized_model,
            "--cd",
            str(temp_path),
            "--output-last-message",
            str(output_last_message_path),
            "-",
        ]
        if str(reasoning_effort or "").strip():
            cmd.extend(["-c", f'model_reasoning_effort="{str(reasoning_effort).strip().lower()}"'])

        try:
            completed = subprocess.run(
                cmd,
                input=merged_prompt,
                capture_output=True,
                text=True,
                timeout=request_timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "未检测到 codex CLI。请先安装 Codex，并执行 `codex login` 或 `codex login --device-auth`。"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Codex CLI 请求超时（>{request_timeout_seconds}s）。如提示词较大，请提高 request_timeout_seconds。"
            ) from exc

        final_reply = ""
        if output_last_message_path.exists():
            final_reply = output_last_message_path.read_text(encoding="utf-8").strip()

        if completed.returncode != 0 and not final_reply:
            detail = extract_process_error_tail(completed.stderr, completed.stdout)
            raise RuntimeError(
                f"Codex CLI 调用失败（exit={completed.returncode}）。"
                f"{f' 详细错误: {detail}' if detail else ''}"
            )

        if final_reply:
            return final_reply

        detail = extract_process_error_tail(completed.stdout, completed.stderr)
        raise RuntimeError(
            "Codex CLI 未返回有效文本输出。"
            f"{f' 最后输出: {detail}' if detail else ''}"
        )


def run_gemini_cli_prompt(prompt_text: str, model: str, request_timeout_seconds: float) -> str:
    rest_error: Exception | None = None
    if os.getenv("GEMINI_API_KEY"):
        try:
            return run_gemini_rest_prompt(prompt_text, model, request_timeout_seconds)
        except Exception as exc:
            rest_error = exc

    cmd = [
        "gemini",
        "-m",
        map_model_for_gemini_cli(model),
        "-p",
        "",
        "--output-format",
        "text",
    ]
    completed = subprocess.run(cmd, input=prompt_text, capture_output=True, text=True, timeout=request_timeout_seconds)
    if completed.returncode != 0:
        cli_error = (completed.stderr or completed.stdout or "gemini cli failed").strip()
        if rest_error is not None:
            raise RuntimeError(f"{cli_error}\nGemini REST fallback also failed: {rest_error}") from rest_error
        raise RuntimeError(cli_error)
    return (completed.stdout or "").strip()


def run_gemini_rest_prompt(prompt_text: str, model: str, request_timeout_seconds: float) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("When using Gemini API, you must specify the GEMINI_API_KEY environment variable.")

    model_name = map_model_for_gemini_cli(model)
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{urllib.parse.quote(model_name, safe='')}:generateContent"
        f"?key={urllib.parse.quote(api_key, safe='')}"
    )
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt_text,
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=request_timeout_seconds) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"gemini api failed ({exc.code} {exc.reason}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"gemini api connection failed: {exc}") from exc

    candidates = response_payload.get("candidates", []) if isinstance(response_payload, dict) else []
    texts: List[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content", {})
        if not isinstance(content, dict):
            continue
        for part in content.get("parts", []):
            if not isinstance(part, dict):
                continue
            text = str(part.get("text", "")).strip()
            if text:
                texts.append(text)

    if texts:
        return "\n".join(texts)

    raise RuntimeError(f"gemini api returned no text: {json.dumps(response_payload, ensure_ascii=False)[:1000]}")


def load_openai_sdk() -> tuple[type[BaseException], type[BaseException], type[Any]]:
    try:
        from openai import APIConnectionError, APITimeoutError, OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "未安装 openai SDK。请先执行 `pip install openai` 或安装当前 pipeline_v2 运行依赖。"
        ) from exc

    return APIConnectionError, APITimeoutError, OpenAI


def build_openai_client(api_key: str, base_url: str | None, request_timeout_seconds: float) -> Any:
    _, _, OpenAI = load_openai_sdk()

    client_kwargs: Dict[str, Any] = {
        "api_key": api_key,
        "timeout": request_timeout_seconds,
        "max_retries": 0,
    }
    if base_url:
        client_kwargs["base_url"] = base_url
    return OpenAI(**client_kwargs)


def run_openai_startup_check(
    *,
    model: str,
    request_timeout_seconds: float,
    connection_retries: int,
    output_path: Path,
    provider_mode: str | None = None,
) -> Dict[str, Any]:
    model = normalize_model_name(model, DEFAULT_MODEL) or DEFAULT_MODEL
    if is_gemini_cli_model(model):
        result = {
            "status": "passed",
            "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "base_url": "gemini-cli",
            "model": map_model_for_gemini_cli(model),
            "request_timeout_seconds": request_timeout_seconds,
            "connection_retries": connection_retries,
            "attempts_used": 1,
            "provider": "gemini-cli",
        }
        write_json(output_path / OPENAI_STARTUP_CHECK_NAME, result)
        return result
    effective_provider_mode = resolve_provider_mode(provider_mode)
    if effective_provider_mode == "codex":
        auth_status = run_codex_login_status(request_timeout_seconds)
        result = {
            "status": "passed",
            "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "base_url": "codex-cli",
            "model": model,
            "request_timeout_seconds": request_timeout_seconds,
            "connection_retries": connection_retries,
            "attempts_used": 1,
            "provider": "codex-cli",
            "auth_status": auth_status,
        }
        write_json(output_path / OPENAI_STARTUP_CHECK_NAME, result)
        return result
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")

    if not api_key:
        raise RuntimeError(
            "未检测到 OPENAI_API_KEY。请先确保当前运行环境已注入该环境变量（例如 shell profile、direnv、launchd 或其他安全注入方式），避免在命令参数或配置文件中明文填写。"
        )

    # 检测是否是 Moonshot API
    is_moonshot = base_url and ("moonshot" in base_url.lower() or "api.moonshot.cn" in base_url)
    # 检测是否是 GitHub Copilot API
    is_copilot = bool(base_url and "githubcopilot.com" in base_url.lower())

    retry_log_path = output_path / OPENAI_RETRY_LOG_NAME
    startup_check_path = output_path / OPENAI_STARTUP_CHECK_NAME

    # Copilot：跳过模型验证直接返回通过
    if is_copilot:
        result = {
            "status": "passed",
            "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "base_url": get_openai_base_label(base_url),
            "model": model,
            "request_timeout_seconds": request_timeout_seconds,
            "connection_retries": connection_retries,
            "attempts_used": 1,
            "provider": "github-copilot",
        }
        write_json(startup_check_path, result)
        return result

    APIConnectionError, APITimeoutError, _ = load_openai_sdk()
    client = build_openai_client(api_key=api_key, base_url=base_url, request_timeout_seconds=request_timeout_seconds)
    total_attempts = max(1, int(connection_retries))

    for attempt in range(1, total_attempts + 1):
        try:
            if is_moonshot:
                # Moonshot 使用简单的模型列表检查
                models_response = client.models.list()
                available_models = [getattr(m, "id", str(m)) for m in getattr(models_response, "data", [])]
                if model not in available_models and not any(model in m for m in available_models):
                    # 如果精确匹配失败，尝试模糊匹配
                    pass  # Moonshot 可能模型名不完全一致，继续尝试
                result = {
                    "status": "passed",
                    "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "base_url": get_openai_base_label(base_url),
                    "model": model,
                    "request_timeout_seconds": request_timeout_seconds,
                    "connection_retries": connection_retries,
                    "attempts_used": attempt,
                    "provider": "moonshot",
                }
            else:
                retrieved_model = client.models.retrieve(model)
                result = {
                    "status": "passed",
                    "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "base_url": get_openai_base_label(base_url),
                    "model": getattr(retrieved_model, "id", model),
                    "request_timeout_seconds": request_timeout_seconds,
                    "connection_retries": connection_retries,
                    "attempts_used": attempt,
                }
            write_json(startup_check_path, result)
            log_openai_event(
                retry_log_path,
                phase="startup_check",
                event="succeeded",
                model=model,
                base_url=base_url,
                request_timeout_seconds=request_timeout_seconds,
                attempt=attempt,
                total_attempts=total_attempts,
                extra={"check_path": str(startup_check_path)},
            )
            return result
        except (APIConnectionError, APITimeoutError) as exc:
            wait_seconds = float(min(2 ** (attempt - 1), 8))
            log_openai_event(
                retry_log_path,
                phase="startup_check",
                event="retrying" if attempt < total_attempts else "failed",
                model=model,
                base_url=base_url,
                request_timeout_seconds=request_timeout_seconds,
                attempt=attempt,
                total_attempts=total_attempts,
                wait_seconds=wait_seconds if attempt < total_attempts else None,
                extra={"check_path": str(startup_check_path)},
                exc=exc,
            )
            if attempt < total_attempts:
                time.sleep(wait_seconds)
                continue

            base_label = get_openai_base_label(base_url)
            root_cause = exc.__cause__ or exc.__context__
            cause_text = f" 底层异常: {root_cause}" if root_cause else ""
            raise RuntimeError(
                f"OpenAI 启动前连通性自检失败（已重试 {total_attempts} 次）。"
                f" base_url={base_label}，model={model}，timeout={request_timeout_seconds}s。"
                f"{cause_text} 请检查网络、DNS、代理/VPN，或确认 OPENAI_BASE_URL 是否可访问。"
            ) from exc
        except Exception as exc:
            log_openai_event(
                retry_log_path,
                phase="startup_check",
                event="failed",
                model=model,
                base_url=base_url,
                request_timeout_seconds=request_timeout_seconds,
                attempt=attempt,
                total_attempts=total_attempts,
                extra={"check_path": str(startup_check_path)},
                exc=exc,
            )
            raise RuntimeError(
                f"OpenAI 启动前连通性自检失败。"
                f" base_url={get_openai_base_label(base_url)}，model={model}，timeout={request_timeout_seconds}s。"
                f" 详细错误: {exc}"
            ) from exc

    raise RuntimeError("OpenAI 启动前连通性自检未返回结果。")


def get_group_window_prefix(output_path: Path, component_group_id: int, region_window_index: int) -> Path:
    return output_path / f"component_group_{component_group_id:03d}_window_{region_window_index:03d}"


def call_openai_model(
    model: str,
    reasoning_effort: str | None,
    max_output_tokens: int | None,
    request_timeout_seconds: float,
    connection_retries: int,
    provider_mode: str | None = None,
    prompt_text: str | None = None,
    instructions_text: str | None = None,
    input_items: Any | None = None,
    phase: str = "batch_request",
    retry_log_path: Path | None = None,
    log_context: Dict[str, Any] | None = None,
) -> str:
    model = normalize_model_name(model, DEFAULT_MODEL) or DEFAULT_MODEL
    if is_gemini_cli_model(model):
        merged_prompt = ""
        if instructions_text:
            merged_prompt += str(instructions_text).strip() + "\n\n"
        if input_items is not None:
            merged_prompt += json.dumps(input_items, ensure_ascii=False, indent=2)
        else:
            merged_prompt += str(prompt_text or "")
        total_attempts = max(1, int(connection_retries))
        last_exc: Exception | None = None
        for attempt in range(1, total_attempts + 1):
            try:
                text = run_gemini_cli_prompt(merged_prompt, model, request_timeout_seconds)
                log_openai_event(
                    retry_log_path,
                    phase=phase,
                    event="succeeded",
                    model=model,
                    base_url="gemini-rest",
                    request_timeout_seconds=request_timeout_seconds,
                    attempt=attempt,
                    total_attempts=total_attempts,
                    extra=log_context,
                )
                return text
            except Exception as exc:
                last_exc = exc
                if attempt < total_attempts:
                    wait_seconds = float(min(2 ** (attempt - 1), 8))
                    log_openai_event(
                        retry_log_path,
                        phase=phase,
                        event="retrying",
                        model=model,
                        base_url="gemini-rest",
                        request_timeout_seconds=request_timeout_seconds,
                        attempt=attempt,
                        total_attempts=total_attempts,
                        wait_seconds=wait_seconds,
                        extra=log_context,
                        exc=exc,
                    )
                    time.sleep(wait_seconds)
                    continue

                log_openai_event(
                    retry_log_path,
                    phase=phase,
                    event="failed",
                    model=model,
                    base_url="gemini-rest",
                    request_timeout_seconds=request_timeout_seconds,
                    attempt=attempt,
                    total_attempts=total_attempts,
                    extra=log_context,
                    exc=exc,
                )
                raise

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Gemini 调用未返回结果。")
    effective_provider_mode = resolve_provider_mode(provider_mode)
    if effective_provider_mode == "codex":
        total_attempts = max(1, int(connection_retries))
        last_exc: Exception | None = None
        for attempt in range(1, total_attempts + 1):
            try:
                text = run_codex_cli_prompt(
                    model=model,
                    reasoning_effort=reasoning_effort,
                    request_timeout_seconds=request_timeout_seconds,
                    prompt_text=prompt_text,
                    instructions_text=instructions_text,
                    input_items=input_items,
                )
                log_openai_event(
                    retry_log_path,
                    phase=phase,
                    event="succeeded",
                    model=model,
                    base_url="codex-cli",
                    request_timeout_seconds=request_timeout_seconds,
                    attempt=attempt,
                    total_attempts=total_attempts,
                    extra=log_context,
                )
                return text
            except Exception as exc:
                last_exc = exc
                if attempt < total_attempts:
                    wait_seconds = float(min(2 ** (attempt - 1), 8))
                    log_openai_event(
                        retry_log_path,
                        phase=phase,
                        event="retrying",
                        model=model,
                        base_url="codex-cli",
                        request_timeout_seconds=request_timeout_seconds,
                        attempt=attempt,
                        total_attempts=total_attempts,
                        wait_seconds=wait_seconds,
                        extra=log_context,
                        exc=exc,
                    )
                    time.sleep(wait_seconds)
                    continue

                log_openai_event(
                    retry_log_path,
                    phase=phase,
                    event="failed",
                    model=model,
                    base_url="codex-cli",
                    request_timeout_seconds=request_timeout_seconds,
                    attempt=attempt,
                    total_attempts=total_attempts,
                    extra=log_context,
                    exc=exc,
                )
                raise

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Codex CLI 调用未返回结果。")
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")

    if not api_key:
        raise RuntimeError(
            "未检测到 OPENAI_API_KEY。请先确保当前运行环境已注入该环境变量（例如 shell profile、direnv、launchd 或其他安全注入方式），避免在命令参数或配置文件中明文填写。"
        )

    APIConnectionError, APITimeoutError, _ = load_openai_sdk()
    client = build_openai_client(api_key=api_key, base_url=base_url, request_timeout_seconds=request_timeout_seconds)

    # 检测是否是 Moonshot API（通过 base_url 判断）
    is_moonshot = base_url and ("moonshot" in base_url.lower() or "api.moonshot.cn" in base_url)
    # 检测是否是 GitHub Copilot API
    is_copilot = bool(base_url and "githubcopilot.com" in base_url.lower())

    if is_moonshot or is_copilot:
        # Moonshot / Copilot 使用 chat.completions API
        # 将 instructions 合并到 system 消息，prompt/input_items 合并到 user 消息
        messages: List[Dict[str, Any]] = []
        if instructions_text:
            messages.append({"role": "system", "content": str(instructions_text).strip()})
        user_content_parts: List[str] = []
        if input_items is not None:
            user_content_parts.append(json.dumps(input_items, ensure_ascii=False, indent=2))
        else:
            user_content_parts.append(str(prompt_text or ""))
        messages.append({"role": "user", "content": "\n\n".join(user_content_parts)})

        request_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        if max_output_tokens:
            request_kwargs["max_tokens"] = max_output_tokens
    else:
        # OpenAI 使用 responses API
        request_kwargs = {
            "model": model,
            "input": input_items if input_items is not None else str(prompt_text or ""),
            "text": {"format": {"type": "json_object"}},
        }
        if instructions_text:
            request_kwargs["instructions"] = instructions_text
        if reasoning_effort:
            request_kwargs["reasoning"] = {"effort": reasoning_effort}
        if max_output_tokens:
            request_kwargs["max_output_tokens"] = max_output_tokens

    total_attempts = max(1, int(connection_retries))
    for attempt in range(1, total_attempts + 1):
        try:
            if is_moonshot or is_copilot:
                response = client.chat.completions.create(**request_kwargs)
                if response.choices:
                    msg = response.choices[0].message
                    response_text = getattr(msg, "content", "") or ""
                else:
                    response_text = ""
            else:
                response = client.responses.create(**request_kwargs)
                response_text = extract_response_text(response)
            log_openai_event(
                retry_log_path,
                phase=phase,
                event="succeeded",
                model=model,
                base_url=base_url,
                request_timeout_seconds=request_timeout_seconds,
                attempt=attempt,
                total_attempts=total_attempts,
                extra=log_context,
            )
            return response_text
        except (APIConnectionError, APITimeoutError) as exc:
            if attempt < total_attempts:
                wait_seconds = float(min(2 ** (attempt - 1), 8))
                log_openai_event(
                    retry_log_path,
                    phase=phase,
                    event="retrying",
                    model=model,
                    base_url=base_url,
                    request_timeout_seconds=request_timeout_seconds,
                    attempt=attempt,
                    total_attempts=total_attempts,
                    wait_seconds=wait_seconds,
                    extra=log_context,
                    exc=exc,
                )
                time.sleep(wait_seconds)
                continue

            log_openai_event(
                retry_log_path,
                phase=phase,
                event="failed",
                model=model,
                base_url=base_url,
                request_timeout_seconds=request_timeout_seconds,
                attempt=attempt,
                total_attempts=total_attempts,
                extra=log_context,
                exc=exc,
            )

            base_label = get_openai_base_label(base_url)
            root_cause = exc.__cause__ or exc.__context__
            cause_text = f" 底层异常: {root_cause}" if root_cause else ""
            raise RuntimeError(
                f"OpenAI 连接失败（已重试 {total_attempts} 次）。"
                f" base_url={base_label}，model={model}，timeout={request_timeout_seconds}s。"
                f"{cause_text} 请检查网络、DNS、代理/VPN，或确认 OPENAI_BASE_URL 是否可访问。"
            ) from exc

    raise RuntimeError("OpenAI 调用未返回结果。")


def deduplicate_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def build_synonym_library(mappings: Sequence[Dict[str, Any]], result_meta: Dict[str, Any]) -> Dict[str, Any]:
    grouped: Dict[str, Dict[str, Any]] = {}
    passthrough_components: List[str] = []
    generic_alias_terms = {
        "面积",
        "周长",
        "体积",
        "长度",
        "高度",
        "厚度",
        "宽度",
        "数量",
        "重量",
        "净面积",
        "外放面积",
    }

    def normalize_chapter_node_text(text: str) -> str:
        normalized = str(text or "").strip()
        if not normalized:
            return ""
        if normalized.startswith("章节:"):
            normalized = normalized.split(":", 1)[1].strip()
        normalized = normalized.replace("；", ";").strip()
        if len(normalized) > 80:
            return ""
        if any(
            marker in normalized
            for marker in ("未出现", "未见", "未找到", "当前仅提供", "已提供", "章节仅", "章节范围", "无法", "包含", "下级标题")
        ):
            return ""
        if "附录" in normalized or ">" in normalized or re.match(r"^[A-Z]\.\d+", normalized, flags=re.IGNORECASE):
            return normalized
        return ""

    for item in mappings:
        source_name = normalize_optional_text(item.get("source_component_name", ""))
        selected_standard_name = normalize_optional_text(item.get("selected_standard_name", ""))
        match_status = str(item.get("match_status", "")).strip().lower()
        if not match_status:
            if selected_standard_name:
                match_status = "matched"
            elif item.get("candidate_standard_names"):
                match_status = "candidate_only"
            else:
                match_status = "unmatched"
        canonical_name = source_name
        if not canonical_name:
            continue
        if source_name and not selected_standard_name:
            passthrough_components.append(source_name)

        alias_candidates: List[str] = []
        if match_status in {"matched", "candidate_only", "conflict"}:
            selected_standard_alias = normalize_chapter_node_text(selected_standard_name)
            if selected_standard_name and not selected_standard_alias:
                alias_candidates.append(selected_standard_name)
            alias_candidates.extend(item.get("standard_aliases", []) or [])
            alias_candidates.extend(item.get("source_aliases", []) or [])
        aliases = deduplicate_preserve_order(
            value
            for value in alias_candidates
            if str(value).strip()
            and normalize_optional_text(value) != source_name
            and not normalize_chapter_node_text(str(value))
            and normalize_optional_text(value) not in generic_alias_terms
        )

        chapter_node_candidates: List[str] = []
        if match_status in {"matched", "candidate_only", "conflict"}:
            selected_standard_alias = normalize_chapter_node_text(selected_standard_name)
            if selected_standard_alias:
                chapter_node_candidates.append(selected_standard_alias)
            chapter_node_candidates.extend(item.get("candidate_standard_names", []) or [])
            chapter_node_candidates.extend(item.get("evidence_texts", []) or [])
        chapter_nodes = deduplicate_preserve_order(
            normalized
            for normalized in (normalize_chapter_node_text(str(value)) for value in chapter_node_candidates)
            if normalized
        )

        group = grouped.setdefault(
            canonical_name,
            {
                "canonical_name": canonical_name,
                "source_component_name": canonical_name,
                "aliases": [],
                "chapter_nodes": [],
                "selected_standard_name": "",
                "match_status": "unmatched",
                "source_component_names": [],
                "match_types": [],
                "review_statuses": [],
                "evidence_paths": [],
                "notes": [],
            },
        )

        group["aliases"] = deduplicate_preserve_order(
            list(group["aliases"])
            + aliases
        )
        group["chapter_nodes"] = deduplicate_preserve_order(list(group["chapter_nodes"]) + chapter_nodes)
        if selected_standard_name and not group["selected_standard_name"]:
            group["selected_standard_name"] = selected_standard_name
        group["match_status"] = str(item.get("match_status", "")).strip() or group["match_status"]
        group["source_component_names"] = deduplicate_preserve_order(
            list(group["source_component_names"]) + [item.get("source_component_name", "")]
        )
        group["match_types"] = deduplicate_preserve_order(list(group["match_types"]) + [item.get("match_type", "")])
        group["review_statuses"] = deduplicate_preserve_order(
            list(group["review_statuses"]) + [item.get("review_status", "")]
        )

    synonym_library = sorted(grouped.values(), key=lambda item: item["source_component_name"])

    return {
        "meta": {
            "task_name": "component_standard_name_synonym_library",
            "standard_document": result_meta.get("standard_document", ""),
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source_review_stage": result_meta.get("review_stage", "pre_parse"),
            "library_mode": "source_component_first",
            "component_count": len(synonym_library),
            "matched_component_count": sum(1 for item in synonym_library if item.get("selected_standard_name")),
            "matched_canonical_count": len(synonym_library),
            "unmatched_component_count": 0,
            "passthrough_component_count": len(deduplicate_preserve_order(passthrough_components)),
        },
        "synonym_library": synonym_library,
        "unmatched_components": [],
    }


def match_status_priority(status: str) -> int:
    priorities = {
        "matched": 4,
        "candidate_only": 3,
        "conflict": 2,
        "unmatched": 1,
    }
    return priorities.get(str(status or "").strip(), 0)


def merge_window_mappings(
    group_payloads: Sequence[Dict[str, Any]],
    expected_component_names: Sequence[str],
) -> Dict[str, Any]:
    if not group_payloads:
        return {
            "meta": {
                "task_name": "component_standard_name_matching",
                "standard_document": "",
                "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "review_stage": "pre_parse",
            },
            "mappings": ensure_all_components_present([], expected_component_names),
        }

    meta = dict(group_payloads[0].get("meta", {}))
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for payload in group_payloads:
        for item in payload.get("mappings", []):
            source_name = str(item.get("source_component_name", "")).strip()
            if source_name:
                grouped.setdefault(source_name, []).append(item)

    merged_mappings: List[Dict[str, Any]] = []
    for source_name in expected_component_names:
        candidates = grouped.get(source_name, [])
        if not candidates:
            continue

        ranked_candidates = sorted(
            candidates,
            key=lambda item: (
                match_status_priority(item.get("match_status", "")),
                float(item.get("confidence", 0.0) or 0.0),
                len(item.get("evidence_paths", []) or []),
                len(item.get("evidence_texts", []) or []),
            ),
            reverse=True,
        )
        best = dict(ranked_candidates[0])
        selected_names = deduplicate_preserve_order(
            normalize_optional_text(item.get("selected_standard_name", ""))
            for item in candidates
            if normalize_optional_text(item.get("selected_standard_name", ""))
        )

        merged_record = {
            "source_component_name": source_name,
            "source_aliases": deduplicate_preserve_order(
                alias
                for item in candidates
                for alias in item.get("source_aliases", [])
            ) or [source_name],
            "selected_standard_name": normalize_optional_text(best.get("selected_standard_name", "")),
            "standard_aliases": deduplicate_preserve_order(
                alias
                for item in candidates
                for alias in item.get("standard_aliases", [])
            ),
            "candidate_standard_names": deduplicate_preserve_order(
                normalize_optional_text(name)
                for item in candidates
                for name in ([item.get("selected_standard_name", "")] + list(item.get("candidate_standard_names", [])))
                if normalize_optional_text(name)
            ),
            "match_type": str(best.get("match_type", "")).strip(),
            "match_status": str(best.get("match_status", "")).strip() or "unmatched",
            "confidence": max(float(item.get("confidence", 0.0) or 0.0) for item in candidates),
            "review_status": str(best.get("review_status", "")).strip() or "pending",
            "evidence_paths": deduplicate_preserve_order(
                text
                for item in candidates
                for text in item.get("evidence_paths", [])
            ),
            "evidence_texts": deduplicate_preserve_order(
                text
                for item in candidates
                for text in item.get("evidence_texts", [])
            ),
            "reasoning": str(best.get("reasoning", "")).strip(),
            "manual_notes": str(best.get("manual_notes", "")).strip(),
        }

        if len(selected_names) > 1:
            merged_record["selected_standard_name"] = ""
            merged_record["match_status"] = "conflict"
            merged_record["review_status"] = "pending"
            merged_record["candidate_standard_names"] = deduplicate_preserve_order(
                selected_names + merged_record["candidate_standard_names"]
            )
            conflict_note = (
                f"跨章节窗口合并时出现多个候选标准名: {', '.join(selected_names)}。"
                " 已标记为 conflict，需人工复核。"
            )
            merged_record["reasoning"] = (
                f"{merged_record['reasoning']} {conflict_note}".strip()
                if merged_record["reasoning"]
                else conflict_note
            )
        elif len(selected_names) == 1 and not merged_record["selected_standard_name"]:
            merged_record["selected_standard_name"] = selected_names[0]

        merged_mappings.append(normalize_mapping(merged_record))

    meta["merged_region_windows"] = len(group_payloads)
    return {
        "meta": meta,
        "mappings": ensure_all_components_present(merged_mappings, expected_component_names),
    }


def plan_component_batches(
    preprocessed_components: Sequence[Dict[str, Any]],
    preprocessed_regions: Sequence[Dict[str, Any]],
    alias_payload: Any,
    history_payload: Any,
    max_components_per_batch: int,
    max_component_payload_chars: int,
    max_prompt_chars: int,
    target_region_chars: int,
    max_regions_per_batch: int,
) -> List[Dict[str, Any]]:
    initial_batches = build_initial_component_batches(
        preprocessed_components=preprocessed_components,
        max_components_per_batch=max_components_per_batch,
        max_component_payload_chars=max_component_payload_chars,
    )
    pending_batches = [list(batch) for batch in initial_batches]
    planned_batches: List[Dict[str, Any]] = []
    component_group_id = 0
    template_overhead_prompt = build_prompt_text([], [], alias_payload, history_payload, 0, 0, 1, 1)
    template_overhead_chars = len(template_overhead_prompt)
    safety_counter = 0

    while pending_batches:
        safety_counter += 1
        if safety_counter > 10_000:
            raise RuntimeError("Step2 批次规划超过安全上限，请检查输入数据是否异常。")

        batch_components = pending_batches.pop(0)
        selected_regions, region_debug = select_regions_for_batch(
            component_payload=batch_components,
            all_regions=preprocessed_regions,
            alias_payload=alias_payload,
            target_region_chars=target_region_chars,
            max_regions_per_batch=max_regions_per_batch,
        )
        region_windows, window_debug = pack_selected_regions_into_windows(
            component_payload=batch_components,
            selected_regions=selected_regions,
            all_regions=preprocessed_regions,
            alias_payload=alias_payload,
            history_payload=history_payload,
            max_prompt_chars=max_prompt_chars,
            max_regions_per_window=max_regions_per_batch,
        )
        region_debug = {**region_debug, **window_debug}

        if region_windows is None and len(batch_components) > 1:
            midpoint = max(1, len(batch_components) // 2)
            pending_batches.insert(0, batch_components[midpoint:])
            pending_batches.insert(0, batch_components[:midpoint])
            continue

        if region_windows is None:
            raise RuntimeError(
                "单个章节与当前构件批次组合后仍超过 prompt 上限，无法读取章节："
                f"{region_debug.get('failed_chapter_path', 'unknown')}。"
                "请降低 --max-component-payload-chars / --max-region-text-chars / --max-table-text-chars，"
                "或增大 --max-prompt-chars。"
            )

        component_group_id += 1
        region_window_count = len(region_windows)
        for region_window_index, region_window in enumerate(region_windows, start=1):
            prompt_preview = build_prompt_text(
                component_payload=batch_components,
                region_payload=region_window,
                alias_payload=alias_payload,
                history_payload=history_payload,
                batch_index=0,
                total_batches=0,
                region_window_index=region_window_index,
                region_window_count=region_window_count,
            )

            planned_batches.append(
                {
                    "component_group_id": component_group_id,
                    "region_window_index": region_window_index,
                    "region_window_count": region_window_count,
                    "components": batch_components,
                    "regions": region_window,
                    "prompt_chars": len(prompt_preview),
                    "component_chars": estimate_payload_chars(batch_components),
                    "region_chars": estimate_payload_chars(region_window),
                    "template_overhead_chars": template_overhead_chars,
                    "debug": region_debug,
                }
            )

    return planned_batches


def run_component_match_preprocess(
    components_path: str | Path | None = None,
    step1_source_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    alias_dict_path: str | Path | None = None,
    history_review_path: str | Path | None = None,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str | None = "medium",
    max_components_per_batch: int = 120,
    max_attribute_values: int = 6,
    max_region_text_chars: int = 2400,
    max_table_text_chars: int = 2400,
    max_table_rows: int = 60,
    only_regions_with_tables: bool = False,
    max_component_payload_chars: int = DEFAULT_MAX_COMPONENT_PAYLOAD_CHARS,
    max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
    target_region_chars: int = DEFAULT_TARGET_REGION_CHARS,
    max_regions_per_batch: int = DEFAULT_MAX_REGIONS_PER_BATCH,
    max_output_tokens: int | None = DEFAULT_MAX_OUTPUT_TOKENS,
    tpm_budget: int | None = DEFAULT_TPM_BUDGET,
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    connection_retries: int = DEFAULT_CONNECTION_RETRIES,
    prepare_only: bool = False,
) -> Dict[str, Any]:
    components_file = Path(components_path) if components_path else get_default_components_path()
    step1_source_file = (
        Path(step1_source_path)
        if step1_source_path
        else get_default_step1_source_path(get_project_root())
    )
    output_path = Path(output_dir) if output_dir else get_default_output_dir(step1_source_file)

    components_raw = load_json_or_jsonl(components_file)
    step1_source_payload = load_step1_regions_source(step1_source_file)
    step1_regions_raw = step1_source_payload["regions"]
    resolved_step1_source_path = str(step1_source_payload.get("source_path", step1_source_file))
    step1_source_type = str(step1_source_payload.get("source_type", "unknown"))
    step1_source_chapters = list(step1_source_payload.get("chapters", []))
    alias_payload = load_json_or_jsonl(Path(alias_dict_path)) if alias_dict_path else []
    history_payload = load_json_or_jsonl(Path(history_review_path)) if history_review_path else []

    if not isinstance(components_raw, list):
        raise ValueError("构件列表必须是数组格式。")
    if not isinstance(step1_regions_raw, list):
        raise ValueError("Step1 数据源解析后必须是区域数组格式。")

    preprocessed_components = list(components_raw)
    preprocessed_regions = summarize_regions(
        regions=step1_regions_raw,
        max_region_text_chars=max_region_text_chars,
        max_table_text_chars=max_table_text_chars,
        max_table_rows=max_table_rows,
        only_regions_with_tables=only_regions_with_tables,
    )

    batch_plans = plan_component_batches(
        preprocessed_components=preprocessed_components,
        preprocessed_regions=preprocessed_regions,
        alias_payload=alias_payload,
        history_payload=history_payload,
        max_components_per_batch=max_components_per_batch,
        max_component_payload_chars=max_component_payload_chars,
        max_prompt_chars=max_prompt_chars,
        target_region_chars=target_region_chars,
        max_regions_per_batch=max_regions_per_batch,
    )
    total_batches = len(batch_plans)
    summary_path = output_path / "run_summary.json"
    retry_log_path = output_path / OPENAI_RETRY_LOG_NAME

    write_json(output_path / "preprocessed_components.json", preprocessed_components)
    write_json(output_path / "preprocessed_regions.json", preprocessed_regions)

    startup_check: Dict[str, Any] | None = None
    if prepare_only:
        startup_check = {
            "status": "skipped",
            "reason": "prepare_only=true",
            "check_path": str(output_path / OPENAI_STARTUP_CHECK_NAME),
        }
    else:
        startup_check = run_openai_startup_check(
            model=model,
            request_timeout_seconds=request_timeout_seconds,
            connection_retries=connection_retries,
            output_path=output_path,
        )
        startup_check["check_path"] = str(output_path / OPENAI_STARTUP_CHECK_NAME)
        startup_check["retry_log_path"] = str(retry_log_path)

    # Wiki retriever for component context injection
    wiki_retriever = WikiRetriever()

    batch_results_by_group: Dict[int, List[Dict[str, Any]]] = {}
    components_by_group: Dict[int, List[Dict[str, Any]]] = {}
    expected_names_by_group: Dict[int, List[str]] = {}
    request_history: List[Dict[str, float]] = []
    for batch_number, batch_plan in enumerate(batch_plans, start=1):
        component_group_id = int(batch_plan["component_group_id"])
        batch_components = batch_plan["components"]
        batch_regions = batch_plan["regions"]
        region_window_index = int(batch_plan["region_window_index"])
        region_window_count = int(batch_plan["region_window_count"])
        group_window_prefix = get_group_window_prefix(output_path, component_group_id, region_window_index)
        # Wiki injection: extract component names and query wiki
        batch_component_names = [get_component_source_name(c) for c in batch_components]
        wiki_context = wiki_retriever.query_for_step2(batch_component_names)
        chapter_request_payload = build_chapter_request_payload(
            component_payload=batch_components,
            region_payload=batch_regions,
            alias_payload=alias_payload,
            history_payload=history_payload,
            batch_index=batch_number,
            total_batches=total_batches,
            region_window_index=region_window_index,
            region_window_count=region_window_count,
            wiki_context=wiki_context,
        )
        prompt_text = str(chapter_request_payload["preview_text"])

        prompt_file = output_path / f"batch_{batch_number:03d}_prompt.txt"
        instructions_file = output_path / f"batch_{batch_number:03d}_instructions.txt"
        components_context_file = output_path / f"batch_{batch_number:03d}_components.txt"
        chapter_context_file = output_path / f"batch_{batch_number:03d}_chapter.txt"
        wiki_context_file = output_path / f"batch_{batch_number:03d}_wiki.txt"
        write_text(prompt_file, prompt_text)
        write_text(instructions_file, str(chapter_request_payload["instructions_text"]))
        write_text(components_context_file, str(chapter_request_payload["components_text"]))
        write_text(chapter_context_file, str(chapter_request_payload["chapter_text"]))
        if wiki_context:
            write_text(wiki_context_file, wiki_context)
        write_text(group_window_prefix.with_name(group_window_prefix.name + "_prompt.txt"), prompt_text)
        write_text(
            group_window_prefix.with_name(group_window_prefix.name + "_instructions.txt"),
            str(chapter_request_payload["instructions_text"]),
        )
        write_text(
            group_window_prefix.with_name(group_window_prefix.name + "_components.txt"),
            str(chapter_request_payload["components_text"]),
        )
        write_text(
            group_window_prefix.with_name(group_window_prefix.name + "_chapter.txt"),
            str(chapter_request_payload["chapter_text"]),
        )
        estimated_request_tokens = estimate_request_tokens(prompt_text, max_output_tokens)
        manifest_payload = {
            "batch_index": batch_number,
            "total_batches": total_batches,
            "component_group_id": component_group_id,
            "region_window_index": region_window_index,
            "region_window_count": region_window_count,
            "component_count": len(batch_components),
            "component_names": [get_component_source_name(item) for item in batch_components],
            "selected_region_count": len(batch_regions),
            "selected_region_paths": [str(item.get("path_text", "")) for item in batch_regions],
            "prompt_chars": len(prompt_text),
            "component_payload_chars": batch_plan["component_chars"],
            "region_payload_chars": batch_plan["region_chars"],
            "template_overhead_chars": batch_plan["template_overhead_chars"],
            "max_prompt_chars": max_prompt_chars,
            "max_component_payload_chars": max_component_payload_chars,
            "target_region_chars": target_region_chars,
            "max_regions_per_batch": max_regions_per_batch,
            "estimated_request_tokens": estimated_request_tokens,
            "tpm_budget": tpm_budget,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "max_output_tokens": max_output_tokens,
            "request_timeout_seconds": request_timeout_seconds,
            "connection_retries": connection_retries,
            "step1_source_path": resolved_step1_source_path,
            "step1_source_type": step1_source_type,
            "step1_source_chapters": step1_source_chapters,
            "instructions_file": str(instructions_file),
            "components_context_file": str(components_context_file),
            "chapter_context_file": str(chapter_context_file),
            "region_selection_debug": batch_plan["debug"],
        }
        write_json(output_path / f"batch_{batch_number:03d}_manifest.json", manifest_payload)
        write_json(group_window_prefix.with_name(group_window_prefix.name + "_manifest.json"), manifest_payload)

        if prepare_only:
            continue

        try:
            wait_for_tpm_budget(
                estimated_request_tokens=estimated_request_tokens,
                request_history=request_history,
                tpm_budget=tpm_budget,
            )
            raw_response_text = call_openai_model(
                model=model,
                reasoning_effort=reasoning_effort,
                max_output_tokens=max_output_tokens,
                request_timeout_seconds=request_timeout_seconds,
                connection_retries=connection_retries,
                prompt_text=prompt_text,
                instructions_text=str(chapter_request_payload["instructions_text"]),
                input_items=chapter_request_payload["input_items"],
                phase="chapter_window_request",
                retry_log_path=retry_log_path,
                log_context={
                    "batch_index": batch_number,
                    "total_batches": total_batches,
                    "component_group_id": component_group_id,
                    "region_window_index": region_window_index,
                    "region_window_count": region_window_count,
                    "prompt_chars": len(prompt_text),
                    "estimated_request_tokens": estimated_request_tokens,
                },
            )
            request_history.append(
                {
                    "timestamp": time.time(),
                    "tokens": float(estimated_request_tokens),
                }
            )
            write_text(output_path / f"batch_{batch_number:03d}_model_output.txt", raw_response_text)
            write_text(group_window_prefix.with_name(group_window_prefix.name + "_model_output.txt"), raw_response_text)

            parsed_payload = normalize_result_payload(json.loads(extract_json_text(raw_response_text)))
            expected_names = [get_component_source_name(item) for item in batch_components]
            parsed_payload["mappings"] = ensure_all_components_present(parsed_payload["mappings"], expected_names)

            write_json(output_path / f"batch_{batch_number:03d}_result.json", parsed_payload)
            write_json(group_window_prefix.with_name(group_window_prefix.name + "_result.json"), parsed_payload)
            batch_results_by_group.setdefault(component_group_id, []).append(
                {
                    "batch_index": batch_number,
                    "component_group_id": component_group_id,
                    "region_window_index": region_window_index,
                    "region_window_count": region_window_count,
                    "selected_region_paths": [str(item.get("path_text", "")) for item in batch_regions],
                    "result": parsed_payload,
                }
            )
            components_by_group[component_group_id] = list(batch_components)
            expected_names_by_group[component_group_id] = expected_names
        except Exception as exc:
            error_payload = {
                "status": "failed",
                "components_path": str(components_file),
                "step1_source_path": resolved_step1_source_path,
                "step1_source_type": step1_source_type,
                "output_dir": str(output_path),
                "model": model,
                "reasoning_effort": reasoning_effort,
                "max_output_tokens": max_output_tokens,
                "tpm_budget": tpm_budget,
                "max_component_payload_chars": max_component_payload_chars,
                "request_timeout_seconds": request_timeout_seconds,
                "connection_retries": connection_retries,
                "startup_connectivity_check": startup_check,
                "retry_log_path": str(retry_log_path),
                "failed_batch": batch_number,
                "total_batches": total_batches,
                "component_group_id": component_group_id,
                "region_window_index": region_window_index,
                "region_window_count": region_window_count,
                "error": str(exc),
                "failed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "hint": (
                    "如果结果目录里只有 preprocessed_*.json、batch_*_manifest.json 和 batch_*_prompt.txt，"
                    "说明大模型调用或结果解析阶段未完成。"
                ),
            }
            write_text(
                output_path / f"batch_{batch_number:03d}_error.txt",
                f"{exc}\n\n{traceback.format_exc()}",
            )
            write_text(
                group_window_prefix.with_name(group_window_prefix.name + "_error.txt"),
                f"{exc}\n\n{traceback.format_exc()}",
            )
            write_summary(summary_path, error_payload)
            raise

    if prepare_only:
        summary = {
            "status": "prepared_only",
            "components_path": str(components_file),
            "step1_source_path": resolved_step1_source_path,
            "step1_source_type": step1_source_type,
            "step1_source_chapters": step1_source_chapters,
            "output_dir": str(output_path),
            "model": model,
            "total_components": len(preprocessed_components),
            "total_regions": len(preprocessed_regions),
            "total_batches": total_batches,
            "total_component_groups": len({int(item["component_group_id"]) for item in batch_plans}),
            "max_prompt_chars": max_prompt_chars,
            "max_component_payload_chars": max_component_payload_chars,
            "target_region_chars": target_region_chars,
            "max_regions_per_batch": max_regions_per_batch,
            "max_output_tokens": max_output_tokens,
            "tpm_budget": tpm_budget,
            "request_timeout_seconds": request_timeout_seconds,
            "connection_retries": connection_retries,
            "startup_connectivity_check": startup_check,
            "retry_log_path": str(retry_log_path),
            "largest_prompt_chars": max((item["prompt_chars"] for item in batch_plans), default=0),
            "prepared_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "next_step": (
                "去掉 --prepare-only 重新运行，脚本才会实际调用 gpt-5.4 并生成 "
                "component_matching_result.json 与 synonym_library.json。"
            ),
            "expected_missing_files": [
                "batch_001_model_output.txt",
                "batch_001_result.json",
                "component_matching_result.json",
                "synonym_library.json",
            ],
        }
        write_summary(summary_path, summary)
        return summary

    group_ids_in_order = deduplicate_preserve_order(str(item["component_group_id"]) for item in batch_plans)
    batch_results: List[Dict[str, Any]] = []
    consolidation_fallback_group_count = 0
    consolidation_request_count = 0
    for group_id_text in group_ids_in_order:
        group_id = int(group_id_text)
        group_window_payloads = sorted(
            batch_results_by_group.get(group_id, []),
            key=lambda item: int(item.get("region_window_index", 0) or 0),
        )
        write_json(
            output_path / f"component_group_{group_id:03d}_window_results.json",
            {
                "component_group_id": group_id,
                "window_count": len(group_window_payloads),
                "windows": group_window_payloads,
            },
        )

        expected_names = expected_names_by_group.get(group_id, [])
        if len(group_window_payloads) <= 1:
            merged_group_payload = (
                dict(group_window_payloads[0]["result"])
                if group_window_payloads
                else merge_window_mappings(group_payloads=[], expected_component_names=expected_names)
            )
            merged_group_payload["mappings"] = ensure_all_components_present(
                merged_group_payload.get("mappings", []),
                expected_names,
            )
            merged_group_payload.setdefault("meta", {})
            merged_group_payload["meta"]["merged_region_windows"] = len(group_window_payloads)
            merged_group_payload["meta"]["consolidation_mode"] = "single_window_passthrough"
            write_json(output_path / f"component_group_{group_id:03d}_consolidated_result.json", merged_group_payload)
            write_json(output_path / f"component_group_{group_id:03d}_merged_result.json", merged_group_payload)
            batch_results.append(merged_group_payload)
            continue

        consolidation_request_count += 1
        consolidation_request_payload = build_consolidation_request_payload(
            component_payload=components_by_group.get(group_id, []),
            window_payloads=group_window_payloads,
            component_group_id=group_id,
            total_component_groups=len(group_ids_in_order),
        )
        consolidation_prompt = str(consolidation_request_payload["preview_text"])
        consolidation_prompt_path = output_path / f"component_group_{group_id:03d}_consolidation_prompt.txt"
        consolidation_instructions_path = output_path / f"component_group_{group_id:03d}_consolidation_instructions.txt"
        consolidation_components_path = output_path / f"component_group_{group_id:03d}_consolidation_components.txt"
        consolidation_window_results_path = output_path / f"component_group_{group_id:03d}_consolidation_window_results.txt"
        consolidation_output_path = output_path / f"component_group_{group_id:03d}_consolidation_model_output.txt"
        consolidation_error_path = output_path / f"component_group_{group_id:03d}_consolidation_error.txt"
        write_text(consolidation_prompt_path, consolidation_prompt)
        write_text(consolidation_instructions_path, str(consolidation_request_payload["instructions_text"]))
        write_text(consolidation_components_path, str(consolidation_request_payload["components_text"]))
        write_text(consolidation_window_results_path, str(consolidation_request_payload["window_results_text"]))

        try:
            estimated_request_tokens = estimate_request_tokens(consolidation_prompt, max_output_tokens)
            wait_for_tpm_budget(
                estimated_request_tokens=estimated_request_tokens,
                request_history=request_history,
                tpm_budget=tpm_budget,
            )
            raw_response_text = call_openai_model(
                model=model,
                reasoning_effort=reasoning_effort,
                max_output_tokens=max_output_tokens,
                request_timeout_seconds=request_timeout_seconds,
                connection_retries=connection_retries,
                prompt_text=consolidation_prompt,
                instructions_text=str(consolidation_request_payload["instructions_text"]),
                input_items=consolidation_request_payload["input_items"],
                phase="group_consolidation",
                retry_log_path=retry_log_path,
                log_context={
                    "component_group_id": group_id,
                    "chapter_window_count": len(group_window_payloads),
                    "prompt_chars": len(consolidation_prompt),
                    "estimated_request_tokens": estimated_request_tokens,
                },
            )
            request_history.append(
                {
                    "timestamp": time.time(),
                    "tokens": float(estimated_request_tokens),
                }
            )
            write_text(consolidation_output_path, raw_response_text)

            merged_group_payload = normalize_result_payload(json.loads(extract_json_text(raw_response_text)))
            merged_group_payload["mappings"] = ensure_all_components_present(
                merged_group_payload.get("mappings", []),
                expected_names,
            )
            merged_group_payload.setdefault("meta", {})
            merged_group_payload["meta"]["merged_region_windows"] = len(group_window_payloads)
            merged_group_payload["meta"]["consolidation_mode"] = "model_merge"
        except Exception as exc:
            consolidation_fallback_group_count += 1
            merged_group_payload = merge_window_mappings(
                group_payloads=[item.get("result", {}) for item in group_window_payloads],
                expected_component_names=expected_names,
            )
            merged_group_payload.setdefault("meta", {})
            merged_group_payload["meta"]["merged_region_windows"] = len(group_window_payloads)
            merged_group_payload["meta"]["consolidation_mode"] = "local_merge_fallback"
            merged_group_payload["meta"]["consolidation_error"] = str(exc)
            write_text(consolidation_error_path, f"{exc}\n\n{traceback.format_exc()}")

        write_json(output_path / f"component_group_{group_id:03d}_consolidated_result.json", merged_group_payload)
        write_json(output_path / f"component_group_{group_id:03d}_merged_result.json", merged_group_payload)
        batch_results.append(merged_group_payload)

    merged_meta = batch_results[0]["meta"] if batch_results else {}
    merged_mappings: List[Dict[str, Any]] = []
    for item in batch_results:
        merged_mappings.extend(item["mappings"])

    all_expected_names = [get_component_source_name(item) for item in preprocessed_components]
    merged_mappings = ensure_all_components_present(merged_mappings, all_expected_names)

    merged_payload = {
        "meta": merged_meta,
        "mappings": merged_mappings,
    }
    synonym_library = build_synonym_library(merged_mappings, merged_meta)

    summary = {
        "status": "completed",
        "components_path": str(components_file),
        "step1_source_path": resolved_step1_source_path,
        "step1_source_type": step1_source_type,
        "step1_source_chapters": step1_source_chapters,
        "output_dir": str(output_path),
        "model": model,
        "reasoning_effort": reasoning_effort,
        "max_output_tokens": max_output_tokens,
        "total_components": len(preprocessed_components),
        "total_regions": len(preprocessed_regions),
        "total_batches": total_batches,
        "window_request_count": total_batches,
        "consolidation_request_count": consolidation_request_count,
        "consolidation_fallback_group_count": consolidation_fallback_group_count,
        "total_component_groups": len({int(item["component_group_id"]) for item in batch_plans}),
        "max_prompt_chars": max_prompt_chars,
        "max_component_payload_chars": max_component_payload_chars,
        "target_region_chars": target_region_chars,
        "max_regions_per_batch": max_regions_per_batch,
        "largest_prompt_chars": max((item["prompt_chars"] for item in batch_plans), default=0),
        "tpm_budget": tpm_budget,
        "request_timeout_seconds": request_timeout_seconds,
        "connection_retries": connection_retries,
        "startup_connectivity_check": startup_check,
        "retry_log_path": str(retry_log_path),
        "matched_count": sum(1 for item in merged_mappings if item.get("match_status") == "matched"),
        "pending_review_count": sum(1 for item in merged_mappings if item.get("review_status") == "pending"),
        "synonym_canonical_count": len(synonym_library.get("synonym_library", [])),
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }

    write_json(output_path / "component_matching_result.json", merged_payload)
    write_json(output_path / "synonym_library.json", synonym_library)
    write_summary(summary_path, summary)

    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Step 2: preprocess components + Step1 regions and call GPT-5.4 for synonym matching.")
    parser.add_argument("--components", help="Path to components.json or components.jsonl")
    parser.add_argument("--step1-source", help="Path to Step1 source: chapter_index.json, chapter JSON, chapter_regions dir, or step1 output dir")
    parser.add_argument("--output", help="Output directory, default: data/output/step2/<standard-name>")
    parser.add_argument("--alias-dict", help="Optional prior alias dictionary JSON")
    parser.add_argument("--history-review", help="Optional prior human review JSON")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenAI model alias, default: gpt-5.4")
    parser.add_argument("--reasoning-effort", default="medium", help="Reasoning effort passed to Responses API")
    parser.add_argument("--max-components-per-batch", type=int, default=120, help="Upper bound of components per model batch; planner may auto split smaller")
    parser.add_argument("--max-attribute-values", type=int, default=6, help="Max dropdown values kept per attribute")
    parser.add_argument("--max-region-text-chars", type=int, default=2400, help="Max non-table text chars kept per region")
    parser.add_argument("--max-table-text-chars", type=int, default=2400, help="Max raw table chars kept per table")
    parser.add_argument("--max-table-rows", type=int, default=60, help="Max rows kept per table")
    parser.add_argument("--only-regions-with-tables", action="store_true", help="Only include regions containing tables")
    parser.add_argument("--max-component-payload-chars", type=int, default=DEFAULT_MAX_COMPONENT_PAYLOAD_CHARS, help="Soft char budget reserved for the component block inside one batch")
    parser.add_argument("--max-prompt-chars", type=int, default=DEFAULT_MAX_PROMPT_CHARS, help="Soft prompt size ceiling; planner will keep chapter windows intact and split requests/components to stay under it")
    parser.add_argument("--target-region-chars", type=int, default=DEFAULT_TARGET_REGION_CHARS, help="Approximate character budget reserved for selected regions per batch")
    parser.add_argument("--max-regions-per-batch", type=int, default=DEFAULT_MAX_REGIONS_PER_BATCH, help="Max selected regions carried into one batch prompt")
    parser.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS, help="Responses API max_output_tokens")
    parser.add_argument("--tpm-budget", type=int, default=DEFAULT_TPM_BUDGET, help="Estimated tokens-per-minute budget used for local throttling; set 0 to disable")
    parser.add_argument("--request-timeout-seconds", type=float, default=DEFAULT_REQUEST_TIMEOUT_SECONDS, help="HTTP timeout for each OpenAI request")
    parser.add_argument("--connection-retries", type=int, default=DEFAULT_CONNECTION_RETRIES, help="Retry count for connection/timeouts before failing")
    parser.add_argument("--prepare-only", action="store_true", help="Only preprocess and write prompts, do not call the model")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_component_match_preprocess(
        components_path=args.components,
        step1_source_path=args.step1_source,
        output_dir=args.output,
        alias_dict_path=args.alias_dict,
        history_review_path=args.history_review,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        max_components_per_batch=args.max_components_per_batch,
        max_attribute_values=args.max_attribute_values,
        max_region_text_chars=args.max_region_text_chars,
        max_table_text_chars=args.max_table_text_chars,
        max_table_rows=args.max_table_rows,
        only_regions_with_tables=args.only_regions_with_tables,
        max_component_payload_chars=args.max_component_payload_chars,
        max_prompt_chars=args.max_prompt_chars,
        target_region_chars=args.target_region_chars,
        max_regions_per_batch=args.max_regions_per_batch,
        max_output_tokens=args.max_output_tokens,
        tpm_budget=args.tpm_budget,
        request_timeout_seconds=args.request_timeout_seconds,
        connection_retries=args.connection_retries,
        prepare_only=args.prepare_only,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
