from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from pipeline_v2.step3_engine.api import load_json_or_jsonl, write_json, write_text


DEFAULT_VECTOR_DIM = 192
DEFAULT_TOP_K = 4
DEFAULT_MAX_CONTEXT_CHARS = 3200
KNOWLEDGE_DB_NAME = "knowledge.db"
INGEST_SUMMARY_NAME = "knowledge_ingest_summary.json"
QUERY_RESULT_NAME = "knowledge_query_result.json"
WIKI_DIR_NAME = "wiki"

ASCII_WORD_RE = re.compile(r"[A-Za-z0-9_.:-]+")
CJK_BLOCK_RE = re.compile(r"[\u4e00-\u9fff]+")


@dataclass(frozen=True)
class KnowledgeEntry:
    entry_id: str
    stage: str
    title: str
    content: str
    source_path: str
    source_ref: str
    chapter_title: str
    component_type: str
    metadata: Dict[str, Any]


@dataclass(frozen=True)
class WikiPage:
    slug: str
    page_type: str
    title: str
    content: str
    component_type: str
    source_refs: List[str]


def sanitize_slug(text: str) -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", str(text or "").strip(), flags=re.UNICODE)
    value = re.sub(r"_+", "_", value).strip("_")
    return value[:96] or "untitled"


def _tokenize_for_vector(text: str) -> List[str]:
    value = str(text or "").strip().lower()
    if not value:
        return []

    tokens: List[str] = []
    tokens.extend(match.group(0) for match in ASCII_WORD_RE.finditer(value))

    for match in CJK_BLOCK_RE.finditer(value):
        block = match.group(0)
        if not block:
            continue
        if len(block) <= 8:
            tokens.append(block)
        for n in (2, 3, 4):
            if len(block) < n:
                continue
            tokens.extend(block[index:index + n] for index in range(0, len(block) - n + 1))

    # 让“项目编码”“构件类型”这类结构化字段也能参与召回。
    compact_value = re.sub(r"\s+", "", value)
    if compact_value and compact_value not in tokens and len(compact_value) <= 24:
        tokens.append(compact_value)

    return tokens


def build_hashed_embedding(text: str, *, dim: int = DEFAULT_VECTOR_DIM) -> List[float]:
    vector = [0.0] * max(8, int(dim or DEFAULT_VECTOR_DIM))
    token_counts = Counter(_tokenize_for_vector(text))
    if not token_counts:
        return vector

    for token, count in token_counts.items():
        digest = hashlib.sha1(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % len(vector)
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign * float(count)

    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [value / norm for value in vector]


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right:
        return 0.0
    limit = min(len(left), len(right))
    return float(sum(float(left[index]) * float(right[index]) for index in range(limit)))


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _extract_primary_chapter(path_text: str) -> str:
    value = str(path_text or "").strip()
    if not value:
        return ""
    return value.split(" > ", 1)[0].strip()


def _shorten(text: str, *, max_chars: int = 320) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) <= max_chars:
        return value
    return f"{value[: max_chars - 1].rstrip()}…"


def _make_entry_id(stage: str, source_ref: str, title: str) -> str:
    digest = hashlib.sha1(f"{stage}|{source_ref}|{title}".encode("utf-8")).hexdigest()
    return f"{stage}_{digest[:16]}"


def _make_entry(
    *,
    stage: str,
    title: str,
    content: str,
    source_path: str = "",
    source_ref: str = "",
    chapter_title: str = "",
    component_type: str = "",
    metadata: Dict[str, Any] | None = None,
) -> KnowledgeEntry | None:
    body = str(content or "").strip()
    if not body:
        return None
    resolved_source_ref = str(source_ref or title).strip()
    return KnowledgeEntry(
        entry_id=_make_entry_id(stage, resolved_source_ref, title),
        stage=stage,
        title=str(title or "").strip(),
        content=body,
        source_path=str(source_path or "").strip(),
        source_ref=resolved_source_ref,
        chapter_title=str(chapter_title or "").strip(),
        component_type=str(component_type or "").strip(),
        metadata=dict(metadata or {}),
    )


def _resolve_step1_region_payload(step1_source: str | Path | None) -> tuple[Path | None, List[Dict[str, Any]], Dict[str, Any]]:
    if not step1_source:
        return None, [], {}

    source_path = Path(step1_source).expanduser().resolve()
    table_regions_path = source_path
    catalog_summary_path: Path | None = None
    if source_path.is_dir():
        table_regions_path = source_path / "table_regions.json"
        catalog_summary_path = source_path / "catalog_summary.json"

    if not table_regions_path.exists():
        raise FileNotFoundError(f"未找到 Step1 table_regions 数据：{table_regions_path}")

    regions_payload = load_json_or_jsonl(table_regions_path)
    if not isinstance(regions_payload, list):
        raise ValueError("Step1 table_regions 必须是数组。")

    catalog_summary: Dict[str, Any] = {}
    if catalog_summary_path and catalog_summary_path.exists():
        raw_summary = load_json_or_jsonl(catalog_summary_path)
        if isinstance(raw_summary, dict):
            catalog_summary = raw_summary

    return source_path, [item for item in regions_payload if isinstance(item, dict)], catalog_summary


def collect_step1_entries(step1_source: str | Path | None) -> List[KnowledgeEntry]:
    source_path, regions_payload, catalog_summary = _resolve_step1_region_payload(step1_source)
    if source_path is None:
        return []

    entries: List[KnowledgeEntry] = []
    if catalog_summary:
        summary_entry = _make_entry(
            stage="step1_catalog",
            title="Step1 总览",
            source_path=str(source_path),
            source_ref="catalog_summary",
            chapter_title="目录总览",
            content=_json_dumps(catalog_summary),
            metadata={"summary_type": "catalog_summary"},
        )
        if summary_entry is not None:
            entries.append(summary_entry)

    for region_index, region in enumerate(regions_payload, start=1):
        path_text = str(region.get("path_text", "")).strip()
        chapter_title = _extract_primary_chapter(path_text)
        non_table_text = str(region.get("non_table_text", "")).strip()
        if non_table_text:
            entry = _make_entry(
                stage="step1_rule",
                title=f"Step1 章节规则 | {path_text or f'region_{region_index}'}",
                source_path=str(source_path),
                source_ref=f"{path_text}#rule",
                chapter_title=chapter_title,
                content=f"章节路径: {path_text}\n规则说明:\n{non_table_text}",
                metadata={"path_text": path_text, "region_index": region_index, "content_kind": "non_table_text"},
            )
            if entry is not None:
                entries.append(entry)

        for table_index, table in enumerate(region.get("tables", []) or [], start=1):
            table_title = str(table.get("title", "")).strip() or str(table.get("raw_text", "")).strip()[:48]
            rows = table.get("rows", []) if isinstance(table.get("rows"), list) else []
            raw_text = str(table.get("raw_text", "")).strip()
            if raw_text:
                table_entry = _make_entry(
                    stage="step1_table",
                    title=f"Step1 表格摘要 | {table_title or path_text or table_index}",
                    source_path=str(source_path),
                    source_ref=f"{path_text}#table-{table_index}",
                    chapter_title=chapter_title,
                    content=f"章节路径: {path_text}\n表格标题: {table_title}\n表格原文: {raw_text}",
                    metadata={
                        "path_text": path_text,
                        "table_index": table_index,
                        "table_title": table_title,
                        "row_count": len(rows),
                    },
                )
                if table_entry is not None:
                    entries.append(table_entry)

            for row_index, row in enumerate(rows, start=1):
                if not isinstance(row, dict):
                    continue
                project_code = str(row.get("project_code", "")).strip()
                project_name = str(row.get("project_name", "")).strip()
                project_features = str(row.get("project_features", "")).strip()
                measurement_unit = str(row.get("measurement_unit", "")).strip()
                quantity_rule = str(row.get("quantity_rule", "")).strip()
                work_content = str(row.get("work_content", "")).strip()
                row_body = "\n".join(
                    [
                        f"章节路径: {path_text}",
                        f"表格标题: {table_title}",
                        f"项目编码: {project_code}",
                        f"项目名称: {project_name}",
                        f"项目特征: {project_features}",
                        f"计量单位: {measurement_unit}",
                        f"工程量计算规则: {quantity_rule}",
                        f"工作内容: {work_content}",
                    ]
                ).strip()
                row_entry = _make_entry(
                    stage="step1_row",
                    title=f"Step1 清单行 | {project_code} {project_name}".strip(),
                    source_path=str(source_path),
                    source_ref=f"{path_text}#table-{table_index}-row-{row_index}",
                    chapter_title=chapter_title,
                    content=row_body,
                    metadata={
                        "path_text": path_text,
                        "table_index": table_index,
                        "row_index": row_index,
                        "project_code": project_code,
                        "project_name": project_name,
                        "measurement_unit": measurement_unit,
                    },
                )
                if row_entry is not None:
                    entries.append(row_entry)

    return entries


def _resolve_step2_paths(step2_source: str | Path | None) -> tuple[Path | None, Path | None, Path | None]:
    if not step2_source:
        return None, None, None

    source_path = Path(step2_source).expanduser().resolve()
    result_path = source_path
    synonym_path: Path | None = None
    if source_path.is_dir():
        for candidate_name in ("component_matching_result.json", "result.json"):
            candidate = source_path / candidate_name
            if candidate.exists():
                result_path = candidate
                break
        synonym_candidate = source_path / "synonym_library.json"
        if synonym_candidate.exists():
            synonym_path = synonym_candidate

    if not result_path.exists():
        raise FileNotFoundError(f"未找到 Step2 结果文件：{result_path}")
    return source_path, result_path, synonym_path


def collect_step2_entries(step2_source: str | Path | None) -> List[KnowledgeEntry]:
    source_path, result_path, synonym_path = _resolve_step2_paths(step2_source)
    if source_path is None or result_path is None:
        return []

    payload = load_json_or_jsonl(result_path)
    entries: List[KnowledgeEntry] = []

    mappings: List[Dict[str, Any]] = []
    if isinstance(payload, dict) and isinstance(payload.get("mappings"), list):
        mappings = [item for item in payload["mappings"] if isinstance(item, dict)]
    elif isinstance(payload, dict) and isinstance(payload.get("匹配结果"), list):
        mappings = [item for item in payload["匹配结果"] if isinstance(item, dict)]

    for index, item in enumerate(mappings, start=1):
        source_component_name = str(item.get("source_component_name", "") or item.get("量筋构件", "")).strip()
        selected_standard_name = str(item.get("selected_standard_name", "")).strip()
        aliases = item.get("source_aliases") or item.get("aliases") or []
        candidate_standard_names = item.get("candidate_standard_names") or []
        content_parts = [
            f"来源构件: {source_component_name}",
            f"标准名称: {selected_standard_name}",
            f"别名: {aliases}",
            f"候选标准名: {candidate_standard_names}",
            f"匹配状态: {item.get('match_status', '')}",
            f"匹配类型: {item.get('match_type', '')}",
            f"置信度: {item.get('confidence', '')}",
            f"证据路径: {item.get('evidence_paths', [])}",
            f"证据文本: {item.get('evidence_texts', [])}",
            f"推理: {item.get('reasoning', '')}",
            f"备注: {item.get('manual_notes', '')}",
        ]
        entry = _make_entry(
            stage="step2_mapping",
            title=f"Step2 构件映射 | {source_component_name or f'mapping_{index}'}",
            source_path=str(source_path),
            source_ref=f"step2_mapping#{index}",
            chapter_title=selected_standard_name,
            component_type=source_component_name,
            content="\n".join(part for part in content_parts if str(part).strip()),
            metadata=item,
        )
        if entry is not None:
            entries.append(entry)

    if synonym_path and synonym_path.exists():
        synonym_payload = load_json_or_jsonl(synonym_path)
        synonym_rows = []
        if isinstance(synonym_payload, dict) and isinstance(synonym_payload.get("synonym_library"), list):
            synonym_rows = [item for item in synonym_payload["synonym_library"] if isinstance(item, dict)]

        for index, item in enumerate(synonym_rows, start=1):
            canonical_name = str(item.get("canonical_name", "")).strip()
            source_component_name = str(item.get("source_component_name", "")).strip()
            selected_standard_name = str(item.get("selected_standard_name", "")).strip()
            source_component_names = item.get("source_component_names") or []
            chapter_nodes = item.get("chapter_nodes") or []
            aliases = item.get("aliases") or []
            notes = item.get("notes") or []
            if source_component_name:
                source_component_names = dedupe_preserve_order([source_component_name] + list(source_component_names))
            title_name = source_component_name or canonical_name or f"synonym_{index}"
            entry = _make_entry(
                stage="step2_synonym",
                title=f"Step2 源构件桥接 | {title_name}",
                source_path=str(source_path),
                source_ref=f"step2_synonym#{index}",
                chapter_title=selected_standard_name or canonical_name,
                component_type=" / ".join(str(name).strip() for name in source_component_names if str(name).strip()),
                content="\n".join(
                    [
                        f"源构件: {source_component_name or canonical_name}",
                        f"当前匹配结果: {selected_standard_name}",
                        f"别名: {aliases}",
                        f"章节/节点: {chapter_nodes}",
                        f"来源构件集合: {source_component_names}",
                        f"匹配类型: {item.get('match_types', [])}",
                        f"复核状态: {item.get('review_statuses', [])}",
                        f"证据路径: {item.get('evidence_paths', [])}",
                        f"说明: {notes}",
                    ]
                ),
                metadata=item,
            )
            if entry is not None:
                entries.append(entry)

    return entries


def _resolve_step3_result_path(step3_source: str | Path | None) -> Path | None:
    if not step3_source:
        return None
    source_path = Path(step3_source).expanduser().resolve()
    if source_path.is_file():
        return source_path
    for candidate_name in (
        "project_component_feature_calc_matching_result.json",
        "step4_from_step3_result.json",
    ):
        candidate = source_path / candidate_name
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"未找到 Step3 结果文件：{source_path}")


def collect_step3_entries(step3_source: str | Path | None) -> List[KnowledgeEntry]:
    result_path = _resolve_step3_result_path(step3_source)
    if result_path is None:
        return []

    payload = load_json_or_jsonl(result_path)
    rows = payload.get("rows", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("Step3 结果必须是数组或包含 rows 数组。")

    entries: List[KnowledgeEntry] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        project_code = str(row.get("project_code", "")).strip()
        project_name = str(row.get("project_name", "")).strip()
        resolved_component_name = str(
            row.get("resolved_component_name", "")
            or row.get("quantity_component", "")
            or row.get("source_component_name", "")
        ).strip()
        feature_expression_text = str(row.get("feature_expression_text", "")).strip()
        content = "\n".join(
            [
                f"row_id: {row.get('row_id', '')}",
                f"项目编码: {project_code}",
                f"项目名称: {project_name}",
                f"构件类型: {resolved_component_name}",
                f"原始项目特征: {row.get('project_features_raw', '') or row.get('project_features', '')}",
                f"特征表达式: {feature_expression_text}",
                f"计量单位: {row.get('measurement_unit', '')}",
                f"计算项目代码: {row.get('calculation_item_code', '')}",
                f"计算项目名称: {row.get('calculation_item_name', '')}",
                f"匹配状态: {row.get('match_status', '')}",
                f"匹配依据: {row.get('match_basis', '')}",
                f"章节规则命中: {row.get('chapter_rule_hits', [])}",
                f"章节特征提示: {row.get('chapter_feature_hints', [])}",
                f"推理: {row.get('reasoning', '')}",
                f"备注: {row.get('notes', '') or row.get('manual_notes', '')}",
            ]
        )
        entry = _make_entry(
            stage="step3_match",
            title=f"Step3 清单匹配 | {project_code} {project_name}".strip(),
            source_path=str(result_path),
            source_ref=f"step3_row#{row.get('row_id', '') or index}",
            chapter_title=str(row.get("standard_document", "")).strip(),
            component_type=resolved_component_name,
            content=content,
            metadata=row,
        )
        if entry is not None:
            entries.append(entry)

    return entries


def collect_knowledge_entries(
    *,
    step1_source: str | Path | None = None,
    step2_source: str | Path | None = None,
    step3_source: str | Path | None = None,
) -> List[KnowledgeEntry]:
    return [
        *collect_step1_entries(step1_source),
        *collect_step2_entries(step2_source),
        *collect_step3_entries(step3_source),
    ]


def _group_entries_by_component(entries: Sequence[KnowledgeEntry]) -> Dict[str, List[KnowledgeEntry]]:
    grouped: Dict[str, List[KnowledgeEntry]] = defaultdict(list)
    for entry in entries:
        component_key = str(entry.component_type or "").strip()
        if not component_key and isinstance(entry.metadata, dict):
            for key in ("resolved_component_name", "quantity_component", "source_component_name", "量筋构件"):
                candidate = str(entry.metadata.get(key, "")).strip()
                if candidate:
                    component_key = candidate
                    break
        if component_key:
            grouped[component_key].append(entry)
    return dict(grouped)


def _group_entries_by_chapter(entries: Sequence[KnowledgeEntry]) -> Dict[str, List[KnowledgeEntry]]:
    grouped: Dict[str, List[KnowledgeEntry]] = defaultdict(list)
    for entry in entries:
        chapter_key = str(entry.chapter_title or "").strip()
        if chapter_key:
            grouped[chapter_key].append(entry)
    return dict(grouped)


def build_wiki_pages(entries: Sequence[KnowledgeEntry]) -> List[WikiPage]:
    pages: List[WikiPage] = []

    stage_counts = Counter(entry.stage for entry in entries)
    overview_lines = [
        "# Step4 Knowledge Wiki",
        "",
        "## Overview",
        f"- total_entries: {len(entries)}",
        f"- step1_entries: {sum(count for stage, count in stage_counts.items() if stage.startswith('step1'))}",
        f"- step2_entries: {sum(count for stage, count in stage_counts.items() if stage.startswith('step2'))}",
        f"- step3_entries: {sum(count for stage, count in stage_counts.items() if stage.startswith('step3'))}",
        "",
        "## Retrieval Guidance",
        "- Step4 应优先读取与当前构件类型一致的 component wiki 页面。",
        "- 若本地直匹配缺少章节依据，再补读 step1_rule / step1_row 召回片段。",
        "- 若历史清单行已沉淀出稳定表达式和计算项目，优先参考 step3_match 证据。",
    ]
    pages.append(
        WikiPage(
            slug="overview",
            page_type="overview",
            title="Step4 Knowledge Overview",
            content="\n".join(overview_lines).strip() + "\n",
            component_type="",
            source_refs=[],
        )
    )

    component_groups = _group_entries_by_component(entries)
    for component_type, group in sorted(component_groups.items(), key=lambda item: item[0]):
        if not component_type:
            continue
        step2_items = [entry for entry in group if entry.stage.startswith("step2")]
        step3_items = [entry for entry in group if entry.stage.startswith("step3")]
        step1_items = [entry for entry in group if entry.stage.startswith("step1")]

        lines = [f"# 构件知识页: {component_type}", ""]
        if step2_items:
            lines.extend(["## Step2 映射沉淀"])
            for entry in step2_items[:8]:
                lines.append(f"- {entry.title}: {_shorten(entry.content, max_chars=220)}")
            lines.append("")
        if step3_items:
            lines.extend(["## Step3 历史匹配样本"])
            for entry in step3_items[:10]:
                lines.append(f"- {entry.title}: {_shorten(entry.content, max_chars=220)}")
            lines.append("")
        if step1_items:
            lines.extend(["## Step1 章节原文线索"])
            for entry in step1_items[:6]:
                lines.append(f"- {entry.title}: {_shorten(entry.content, max_chars=220)}")
            lines.append("")

        page_content = "\n".join(lines).strip() + "\n"
        pages.append(
            WikiPage(
                slug=f"components/{sanitize_slug(component_type)}",
                page_type="component",
                title=f"{component_type} 构件知识页",
                content=page_content,
                component_type=component_type,
                source_refs=[entry.source_ref for entry in group[:24]],
            )
        )

    chapter_groups = _group_entries_by_chapter(entries)
    for chapter_title, group in sorted(chapter_groups.items(), key=lambda item: item[0]):
        if not chapter_title or len(group) < 2:
            continue
        lines = [f"# 章节知识页: {chapter_title}", "", "## 关键片段"]
        for entry in group[:10]:
            lines.append(f"- {entry.title}: {_shorten(entry.content, max_chars=180)}")
        pages.append(
            WikiPage(
                slug=f"chapters/{sanitize_slug(chapter_title)}",
                page_type="chapter",
                title=f"{chapter_title} 章节知识页",
                content="\n".join(lines).strip() + "\n",
                component_type="",
                source_refs=[entry.source_ref for entry in group[:24]],
            )
        )

    step3_groups = _group_entries_by_component([entry for entry in entries if entry.stage == "step3_match"])
    if step3_groups:
        lines = ["# Step3 历史表达式模式", ""]
        for component_type, group in sorted(step3_groups.items(), key=lambda item: item[0]):
            lines.append(f"## {component_type}")
            for entry in group[:6]:
                metadata = entry.metadata if isinstance(entry.metadata, dict) else {}
                feature_expression_text = str(metadata.get("feature_expression_text", "")).strip()
                calculation_item_code = str(metadata.get("calculation_item_code", "")).strip()
                project_name = str(metadata.get("project_name", "")).strip()
                lines.append(
                    f"- {project_name or entry.title}: calc={calculation_item_code or '-'} | features={_shorten(feature_expression_text, max_chars=140)}"
                )
            lines.append("")
        pages.append(
            WikiPage(
                slug="patterns/step3_feature_patterns",
                page_type="pattern",
                title="Step3 历史表达式模式",
                content="\n".join(lines).strip() + "\n",
                component_type="",
                source_refs=[],
            )
        )

    return pages


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS knowledge_entries (
            entry_id TEXT PRIMARY KEY,
            stage TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            source_path TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            chapter_title TEXT NOT NULL,
            component_type TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            vector_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS wiki_pages (
            slug TEXT PRIMARY KEY,
            page_type TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            component_type TEXT NOT NULL,
            source_refs_json TEXT NOT NULL,
            vector_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_knowledge_entries_stage ON knowledge_entries(stage);
        CREATE INDEX IF NOT EXISTS idx_knowledge_entries_component ON knowledge_entries(component_type);
        CREATE INDEX IF NOT EXISTS idx_knowledge_entries_chapter ON knowledge_entries(chapter_title);
        CREATE INDEX IF NOT EXISTS idx_wiki_pages_page_type ON wiki_pages(page_type);
        CREATE INDEX IF NOT EXISTS idx_wiki_pages_component ON wiki_pages(component_type);
        """
    )


def build_knowledge_base(
    *,
    step1_source: str | Path | None = None,
    step2_source: str | Path | None = None,
    step3_source: str | Path | None = None,
    output_dir: str | Path,
    vector_dim: int = DEFAULT_VECTOR_DIM,
) -> Dict[str, Any]:
    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    wiki_dir = output_path / WIKI_DIR_NAME
    wiki_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_path / KNOWLEDGE_DB_NAME

    entries = collect_knowledge_entries(
        step1_source=step1_source,
        step2_source=step2_source,
        step3_source=step3_source,
    )
    pages = build_wiki_pages(entries)

    with sqlite3.connect(db_path) as connection:
        _ensure_schema(connection)
        connection.execute("DELETE FROM knowledge_entries")
        connection.execute("DELETE FROM wiki_pages")

        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        connection.executemany(
            """
            INSERT INTO knowledge_entries (
                entry_id, stage, title, content, source_path, source_ref, chapter_title,
                component_type, metadata_json, vector_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    entry.entry_id,
                    entry.stage,
                    entry.title,
                    entry.content,
                    entry.source_path,
                    entry.source_ref,
                    entry.chapter_title,
                    entry.component_type,
                    _json_dumps(entry.metadata),
                    _json_dumps(build_hashed_embedding(f"{entry.title}\n{entry.content}", dim=vector_dim)),
                    timestamp,
                )
                for entry in entries
            ],
        )
        connection.executemany(
            """
            INSERT INTO wiki_pages (
                slug, page_type, title, content, component_type, source_refs_json, vector_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    page.slug,
                    page.page_type,
                    page.title,
                    page.content,
                    page.component_type,
                    _json_dumps(page.source_refs),
                    _json_dumps(build_hashed_embedding(f"{page.title}\n{page.content}", dim=vector_dim)),
                    timestamp,
                )
                for page in pages
            ],
        )
        connection.commit()

    for page in pages:
        page_path = wiki_dir / f"{page.slug}.md"
        write_text(page_path, page.content)

    summary = {
        "status": "completed",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "knowledge_db_path": str(db_path),
        "wiki_dir": str(wiki_dir),
        "entry_count": len(entries),
        "wiki_page_count": len(pages),
        "stage_counts": {
            "step1": sum(1 for entry in entries if entry.stage.startswith("step1")),
            "step2": sum(1 for entry in entries if entry.stage.startswith("step2")),
            "step3": sum(1 for entry in entries if entry.stage.startswith("step3")),
        },
        "source_inputs": {
            "step1_source": str(step1_source or ""),
            "step2_source": str(step2_source or ""),
            "step3_source": str(step3_source or ""),
        },
        "vector_dim": int(vector_dim or DEFAULT_VECTOR_DIM),
    }
    write_json(output_path / INGEST_SUMMARY_NAME, summary)
    return summary


def _load_query_candidates(
    connection: sqlite3.Connection,
    *,
    component_type: str = "",
    stage_filters: Sequence[str] | None = None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    entry_rows = [
        {
            "entry_id": row[0],
            "stage": row[1],
            "title": row[2],
            "content": row[3],
            "source_path": row[4],
            "source_ref": row[5],
            "chapter_title": row[6],
            "component_type": row[7],
            "metadata": json.loads(row[8]),
            "vector": json.loads(row[9]),
        }
        for row in connection.execute(
            """
            SELECT entry_id, stage, title, content, source_path, source_ref, chapter_title,
                   component_type, metadata_json, vector_json
            FROM knowledge_entries
            """
        ).fetchall()
    ]

    page_rows = [
        {
            "slug": row[0],
            "page_type": row[1],
            "title": row[2],
            "content": row[3],
            "component_type": row[4],
            "source_refs": json.loads(row[5]),
            "vector": json.loads(row[6]),
        }
        for row in connection.execute(
            """
            SELECT slug, page_type, title, content, component_type, source_refs_json, vector_json
            FROM wiki_pages
            """
        ).fetchall()
    ]

    normalized_component = str(component_type or "").strip()
    filtered_entries: List[Dict[str, Any]] = []
    for row in entry_rows:
        if stage_filters and row["stage"] not in set(stage_filters):
            continue
        if normalized_component and row["component_type"]:
            if normalized_component != str(row["component_type"]).strip():
                # 不直接丢弃，给通用章节和无 component 的证据留机会。
                if row["stage"].startswith("step3") or row["stage"].startswith("step2"):
                    continue
        filtered_entries.append(row)

    filtered_pages: List[Dict[str, Any]] = []
    for row in page_rows:
        if normalized_component and row["component_type"]:
            if normalized_component != str(row["component_type"]).strip():
                continue
        filtered_pages.append(row)

    return filtered_entries, filtered_pages


def _score_hit(
    *,
    query_vector: Sequence[float],
    query_terms: Sequence[str],
    title: str,
    content: str,
    vector: Sequence[float],
    component_type: str,
    candidate_component: str,
    stage: str = "",
) -> float:
    score = cosine_similarity(query_vector, vector)
    haystack = f"{title}\n{content}".lower()
    token_hits = sum(1 for term in query_terms if term and term in haystack)
    if query_terms:
        score += min(0.35, token_hits * 0.03)
    if component_type and candidate_component and component_type == candidate_component:
        score += 0.18
    if stage.startswith("step3"):
        score += 0.05
    return score


def _build_excerpt(content: str, query_terms: Sequence[str], *, max_chars: int = 260) -> str:
    normalized = re.sub(r"\s+", " ", str(content or "")).strip()
    if len(normalized) <= max_chars:
        return normalized

    lowered = normalized.lower()
    hit_positions = [lowered.find(term) for term in query_terms if term]
    hit_positions = [position for position in hit_positions if position >= 0]
    if not hit_positions:
        return _shorten(normalized, max_chars=max_chars)

    start = max(0, min(hit_positions) - max_chars // 4)
    end = min(len(normalized), start + max_chars)
    snippet = normalized[start:end].strip()
    if start > 0:
        snippet = f"…{snippet}"
    if end < len(normalized):
        snippet = f"{snippet}…"
    return snippet


def query_knowledge_base(
    *,
    knowledge_base_path: str | Path,
    query_text: str,
    component_type: str | None = None,
    top_k: int = DEFAULT_TOP_K,
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
    stage_filters: Sequence[str] | None = None,
) -> Dict[str, Any]:
    db_path = Path(knowledge_base_path).expanduser().resolve()
    if db_path.is_dir():
        db_path = db_path / KNOWLEDGE_DB_NAME
    if not db_path.exists():
        raise FileNotFoundError(f"未找到知识库数据库：{db_path}")

    query_vector = build_hashed_embedding(query_text)
    query_terms = _tokenize_for_vector(query_text)
    normalized_component = str(component_type or "").strip()

    with sqlite3.connect(db_path) as connection:
        entry_rows, page_rows = _load_query_candidates(
            connection,
            component_type=normalized_component,
            stage_filters=stage_filters,
        )

    scored_entries = []
    for row in entry_rows:
        score = _score_hit(
            query_vector=query_vector,
            query_terms=query_terms,
            title=row["title"],
            content=row["content"],
            vector=row["vector"],
            component_type=normalized_component,
            candidate_component=str(row["component_type"] or "").strip(),
            stage=row["stage"],
        )
        scored_entries.append(
            {
                "score": round(score, 4),
                "entry_id": row["entry_id"],
                "stage": row["stage"],
                "title": row["title"],
                "component_type": row["component_type"],
                "chapter_title": row["chapter_title"],
                "source_path": row["source_path"],
                "source_ref": row["source_ref"],
                "excerpt": _build_excerpt(row["content"], query_terms),
                "metadata": row["metadata"],
            }
        )

    scored_pages = []
    for row in page_rows:
        score = _score_hit(
            query_vector=query_vector,
            query_terms=query_terms,
            title=row["title"],
            content=row["content"],
            vector=row["vector"],
            component_type=normalized_component,
            candidate_component=str(row["component_type"] or "").strip(),
            stage=row["page_type"],
        )
        scored_pages.append(
            {
                "score": round(score, 4),
                "slug": row["slug"],
                "page_type": row["page_type"],
                "title": row["title"],
                "component_type": row["component_type"],
                "excerpt": _build_excerpt(row["content"], query_terms),
                "source_refs": row["source_refs"],
            }
        )

    scored_entries.sort(key=lambda item: item["score"], reverse=True)
    scored_pages.sort(key=lambda item: item["score"], reverse=True)

    selected_entries: List[Dict[str, Any]] = []
    selected_chars = 0
    for item in scored_entries:
        candidate_size = len(item["excerpt"])
        if selected_entries and selected_chars + candidate_size > max_context_chars:
            break
        selected_entries.append(item)
        selected_chars += candidate_size
        if len(selected_entries) >= max(1, int(top_k or DEFAULT_TOP_K)):
            break

    selected_pages: List[Dict[str, Any]] = []
    selected_page_chars = 0
    for item in scored_pages:
        candidate_size = len(item["excerpt"])
        if selected_pages and selected_page_chars + candidate_size > max_context_chars:
            break
        selected_pages.append(item)
        selected_page_chars += candidate_size
        if len(selected_pages) >= 3:
            break

    result = {
        "query_text": query_text,
        "component_type": normalized_component,
        "knowledge_db_path": str(db_path),
        "top_k": max(1, int(top_k or DEFAULT_TOP_K)),
        "retrieved_entries": selected_entries,
        "retrieved_wiki_pages": selected_pages,
    }
    write_json(db_path.parent / QUERY_RESULT_NAME, result)
    return result


def build_step4_prompt_knowledge_context(
    *,
    knowledge_base_path: str | Path,
    local_batch_rows: Sequence[Dict[str, Any]],
    component_type: str,
    top_k: int = DEFAULT_TOP_K,
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> Dict[str, Any]:
    wiki_pages: List[Dict[str, Any]] = []
    row_contexts: List[Dict[str, Any]] = []
    seen_page_keys = set()

    for row in local_batch_rows:
        query_text = "\n".join(
            [
                str(component_type or "").strip(),
                str(row.get("project_code", "")).strip(),
                str(row.get("project_name", "")).strip(),
                str(row.get("project_features_raw", "")).strip(),
                str(row.get("feature_expression_text", "")).strip(),
                str(row.get("measurement_unit", "")).strip(),
                str(row.get("quantity_rule", "")).strip(),
                str(row.get("work_content", "")).strip(),
            ]
        ).strip()
        query_result = query_knowledge_base(
            knowledge_base_path=knowledge_base_path,
            query_text=query_text,
            component_type=component_type,
            top_k=top_k,
            max_context_chars=max_context_chars,
        )
        row_contexts.append(
            {
                "row_id": row.get("row_id", ""),
                "query_text": query_text,
                "hits": query_result["retrieved_entries"],
            }
        )
        for page in query_result["retrieved_wiki_pages"]:
            page_key = (page.get("slug", ""), page.get("title", ""))
            if page_key in seen_page_keys:
                continue
            seen_page_keys.add(page_key)
            wiki_pages.append(page)

    return {
        "knowledge_base_path": str(Path(knowledge_base_path).expanduser().resolve()),
        "component_type": str(component_type or "").strip(),
        "wiki_pages": wiki_pages[:4],
        "row_contexts": row_contexts,
    }
