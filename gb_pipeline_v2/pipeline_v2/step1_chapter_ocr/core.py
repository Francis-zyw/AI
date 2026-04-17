from __future__ import annotations

import json
import re
from bisect import bisect_left
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import fitz

from .models import (
    CatalogDetection,
    ChapterExtractionResult,
    ContentBlock,
    ExtractionSummary,
    OutlineEntry,
    RegionNode,
    RegionResult,
    TableBlock,
    TableRow,
)
from .providers import PageTextResolver


FRONT_MATTER_KEYWORDS = (
    "封面",
    "题名页",
    "版权页",
    "公告",
    "前言",
    "目次",
    "contents",
)

BACK_MATTER_KEYWORDS = (
    "本标准用词说明",
    "引用标准名录",
    "条文说明",
    "封底",
)

TABLE_HEADER_ALIASES = {
    "项目编码": ("项目编码", "编码"),
    "项目名称": ("项目名称", "名称"),
    "项目特征": ("项目特征", "特征"),
    "计量单位": ("计量单位", "单位"),
    "工程量计算规则": ("工程量计算规则", "工程量计算代码", "工程量计算规则及说明"),
    "工作内容": ("工作内容",),
}

TABLE_CANONICAL_HEADERS = [
    "项目编码",
    "项目名称",
    "项目特征",
    "计量单位",
    "工程量计算规则",
    "工作内容",
]

FEATURE_HINTS = (
    "类别",
    "材质",
    "厚度",
    "深度",
    "方式",
    "品种",
    "规格",
    "做法",
    "名称",
    "尺寸",
    "部位",
    "面层",
    "运距",
    "强度",
    "断面",
    "高度",
    "宽度",
    "长度",
    "半径",
    "坡度",
    "掺量",
    "密实度",
    "土类别",
    "岩石类别",
)

UNIT_PATTERN = re.compile(
    r"^(?:m|m2|m3|m²|m³|㎡|m2/m3|km|kg|t|樘|个|项|座|套|根|孔|处|块|延长米|10m2|100m2|1000m2|10m3|100m3|n\?|0\?)$",
    re.IGNORECASE,
)
WORK_ITEM_PATTERN = re.compile(r"^(\d+)\s*[\.．、]")
BILL_CHAPTER_PATTERN = re.compile(r"^附录\s*[A-Z]", re.IGNORECASE)


def is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"


def normalize_with_mapping(text: str) -> Tuple[str, List[int]]:
    chars: List[str] = []
    mapping: List[int] = []
    for idx, char in enumerate(text):
        if char.isalnum() or is_cjk(char):
            chars.append(char.lower())
            mapping.append(idx)
    return "".join(chars), mapping


def normalize_for_match(text: str) -> str:
    return normalize_with_mapping(text)[0]


def sanitize_filename(name: str, max_len: int = 80) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff\-\.]+", "_", name.strip())
    cleaned = cleaned.strip("._")
    if not cleaned:
        cleaned = "untitled"
    return cleaned[:max_len]


def chapter_slug(chapter_index: int, chapter_title: str) -> str:
    return f"{chapter_index:03d}_{sanitize_filename(chapter_title)}"


def is_bill_chapter_title(chapter_title: str) -> bool:
    return bool(BILL_CHAPTER_PATTERN.match(str(chapter_title or "").strip()))


def build_anchor_candidates(title: str) -> List[str]:
    compact = re.sub(r"\s+", "", title)
    title_only = re.sub(r"^(?:[A-Za-z]\.\d+(?:\.\d+)*|\d+(?:\.\d+)*|附录\s*[A-Z])\s*", "", title).strip()
    appendix_only = re.sub(r"^附录\s*[A-Z]\s*", "", title).strip()

    candidates = [title, compact, title.replace(" ", ""), title_only, appendix_only]
    deduped: List[str] = []
    seen = set()
    for candidate in candidates:
        candidate = candidate.strip()
        if len(normalize_for_match(candidate)) < 2:
            continue
        if candidate not in seen:
            seen.add(candidate)
            deduped.append(candidate)
    return deduped


def find_anchor(page_text: str, title: str, raw_start: int = 0) -> Optional[Tuple[int, int]]:
    normalized_page, mapping = normalize_with_mapping(page_text)
    if not normalized_page:
        return None

    start_norm_index = bisect_left(mapping, raw_start)
    for candidate in build_anchor_candidates(title):
        normalized_candidate = normalize_for_match(candidate)
        if not normalized_candidate:
            continue
        match_index = normalized_page.find(normalized_candidate, start_norm_index)
        if match_index == -1:
            continue
        raw_begin = mapping[match_index]
        raw_end = mapping[match_index + len(normalized_candidate) - 1] + 1
        return raw_begin, raw_end
    return None


def classify_title(title: str) -> str:
    lowered = title.lower()
    if any(keyword.lower() in lowered for keyword in FRONT_MATTER_KEYWORDS):
        return "front"
    if any(keyword.lower() in lowered for keyword in BACK_MATTER_KEYWORDS):
        return "back"
    return "body"


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def match_table_header(line: str) -> Optional[str]:
    compact = compact_text(line)
    if not compact:
        return None

    for canonical, aliases in TABLE_HEADER_ALIASES.items():
        for alias in aliases:
            if compact == alias:
                return canonical
            if alias in compact and len(compact) <= len(alias) + 2:
                return canonical
    return None


def is_table_title(line: str) -> bool:
    compact = compact_text(line)
    if not compact or not compact.startswith("表"):
        return False
    return not compact.endswith(("规定执行。", "规定执行", "执行。", "执行"))


def is_continuation_title(line: str) -> bool:
    compact = compact_text(line)
    return compact.startswith("续表")


def is_page_marker(line: str) -> bool:
    compact = compact_text(line)
    if re.match(r"^[•·]\d+[•·]$", compact):
        return True
    return bool(re.fullmatch(r"\d{1,3}", compact))


def is_section_heading(line: str) -> bool:
    stripped = line.strip()
    return bool(
        re.match(r"^(?:[A-Z]\.\s*\d+(?:\.\d+)*|\d+\.\d+(?:\.\d+)*|\d+\s+[\u4e00-\u9fff])", stripped)
    )


def normalize_project_code(line: str) -> Optional[str]:
    match = split_project_code_line(line)
    if match is None:
        return None
    return match[0]


def split_project_code_line(line: str) -> Optional[Tuple[str, str]]:
    compact = compact_text(line)
    compact = compact.translate(str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1"}))
    if re.fullmatch(r"\d{9,12}", compact):
        return compact, ""

    match = re.match(r"^\s*([0-9OIl]{9,12})\s*(.*)$", line)
    if match:
        code = match.group(1).translate(str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1"}))
        if re.fullmatch(r"\d{9,12}", code):
            return code, match.group(2).strip()
    return None


def looks_like_unit_line(line: str) -> bool:
    return bool(UNIT_PATTERN.fullmatch(compact_text(line)))


def looks_like_quantity_rule_line(line: str) -> bool:
    compact = compact_text(line)
    return compact.startswith(("按", "以", "并按", "按设计", "按图示", "按原始", "按展开", "按水平", "按垂直"))


def looks_like_work_item_line(line: str) -> bool:
    stripped = line.strip()
    return bool(re.match(r"^\d+\s*[\.．、]", stripped))


def looks_like_feature_line(line: str) -> bool:
    compact = compact_text(line)
    if not compact or looks_like_quantity_rule_line(line) or looks_like_unit_line(line) or looks_like_work_item_line(line):
        return False
    return any(hint in compact for hint in FEATURE_HINTS)


def should_merge_name_lines(first_line: str, second_line: str) -> bool:
    if not second_line:
        return False
    if looks_like_feature_line(second_line) or looks_like_quantity_rule_line(second_line) or looks_like_unit_line(second_line):
        return False
    if looks_like_work_item_line(second_line) or normalize_project_code(second_line):
        return False

    first_compact = compact_text(first_line)
    second_compact = compact_text(second_line)
    return len(first_compact) <= 6 and len(second_compact) <= 8


def detect_table_header_sequence(lines: Sequence[str], start_index: int) -> Optional[Tuple[int, int, List[str]]]:
    headers: List[str] = []
    header_start: Optional[int] = None
    index = start_index

    while index < len(lines) and index < start_index + 8:
        line = lines[index].strip()
        if not line:
            index += 1
            continue

        header = match_table_header(line)
        if header:
            if header_start is None:
                header_start = index
            if header not in headers:
                headers.append(header)
            index += 1
            continue

        if header_start is not None:
            break

        if is_table_title(line) or is_continuation_title(line):
            index += 1
            continue

        break

    if header_start is None:
        return None

    header_set = set(headers)
    required = {"项目编码", "项目名称", "项目特征"}
    if required.issubset(header_set) and len(headers) >= 4:
        return header_start, index, headers
    return None


def find_table_end(lines: Sequence[str], start_index: int) -> int:
    seen_row = False
    index = start_index

    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue

        if normalize_project_code(line):
            seen_row = True
            index += 1
            continue

        if is_page_marker(line) or is_table_title(line) or is_continuation_title(line) or match_table_header(line):
            index += 1
            continue

        repeated_header = detect_table_header_sequence(lines, index)
        if repeated_header and repeated_header[0] == index:
            index += 1
            continue

        if seen_row and is_section_heading(line):
            return index

        index += 1

    return len(lines)


def parse_table_row(row_index: int, raw_lines: Sequence[str]) -> TableRow:
    split_result = split_project_code_line(raw_lines[0])
    project_code = split_result[0] if split_result else compact_text(raw_lines[0])
    remaining = [line.strip() for line in raw_lines[1:] if line.strip()]
    if split_result and split_result[1]:
        remaining.insert(0, split_result[1])

    if remaining:
        inline_name_match = re.match(r"^(.*?)\s+(\d+\s*[\.．、].+)$", remaining[0])
        if inline_name_match:
            remaining[0] = inline_name_match.group(1).strip()
            remaining.insert(1, inline_name_match.group(2).strip())

    project_name_lines: List[str] = []
    if remaining:
        project_name_lines.append(remaining[0])
        cursor = 1
        if cursor < len(remaining) and should_merge_name_lines(remaining[0], remaining[cursor]):
            project_name_lines.append(remaining[cursor])
            cursor += 1
        remaining = remaining[cursor:]

    measurement_unit = ""
    filtered_remaining: List[str] = []
    for line in remaining:
        if not measurement_unit and looks_like_unit_line(line):
            measurement_unit = compact_text(line)
            continue
        filtered_remaining.append(line)

    quantity_start: Optional[int] = None
    work_start: Optional[int] = None
    for index, line in enumerate(filtered_remaining):
        if quantity_start is None and looks_like_quantity_rule_line(line):
            quantity_start = index
        if work_start is None and looks_like_work_item_line(line):
            work_start = index

    if work_start is None:
        work_lines = []
        before_work = filtered_remaining
    else:
        work_lines = filtered_remaining[work_start:]
        before_work = filtered_remaining[:work_start]

    if quantity_start is not None and quantity_start < len(before_work):
        project_feature_lines = before_work[:quantity_start]
        quantity_rule_lines = before_work[quantity_start:]
    else:
        project_feature_lines = before_work
        quantity_rule_lines = []

    return TableRow(
        row_index=row_index,
        project_code=project_code,
        project_name="\n".join(project_name_lines).strip(),
        project_features="\n".join(project_feature_lines).strip(),
        measurement_unit=measurement_unit,
        quantity_rule="\n".join(quantity_rule_lines).strip(),
        work_content="\n".join(work_lines).strip(),
        raw_lines=[line for line in raw_lines if line.strip()],
    )


def parse_table_rows(table_lines: Sequence[str]) -> List[TableRow]:
    body_lines: List[str] = []
    for line in table_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if is_page_marker(stripped) or is_table_title(stripped) or is_continuation_title(stripped) or match_table_header(stripped):
            continue
        body_lines.append(stripped)

    code_indexes = [index for index, line in enumerate(body_lines) if normalize_project_code(line)]
    rows: List[TableRow] = []
    for row_offset, code_index in enumerate(code_indexes):
        end_index = code_indexes[row_offset + 1] if row_offset + 1 < len(code_indexes) else len(body_lines)
        row_lines = body_lines[code_index:end_index]
        rows.append(parse_table_row(row_offset + 1, row_lines))
    return rows


def parse_region_content(text: str) -> Tuple[List[TableBlock], List[ContentBlock], str]:
    lines = text.splitlines()
    tables_with_spans: List[Tuple[int, int, TableBlock]] = []
    index = 0

    while index < len(lines):
        header_info = detect_table_header_sequence(lines, index)
        if header_info is None:
            index += 1
            continue

        header_start, header_end, headers = header_info
        table_start = header_start
        title = ""
        lookback = header_start - 1
        while lookback >= 0 and header_start - lookback <= 2:
            candidate = lines[lookback].strip()
            if is_table_title(candidate) or is_continuation_title(candidate):
                title = candidate if not title else f"{candidate}\n{title}"
                table_start = lookback
                lookback -= 1
                continue
            break

        table_end = find_table_end(lines, header_end)
        raw_lines = [line.rstrip() for line in lines[table_start:table_end] if line.strip()]
        raw_text = "\n".join(raw_lines).strip()
        rows = parse_table_rows(lines[header_end:table_end])
        table_block = TableBlock(
            table_index=len(tables_with_spans) + 1,
            title=title,
            headers=headers,
            row_count=len(rows),
            raw_text=raw_text,
            rows=rows,
        )
        tables_with_spans.append((table_start, table_end, table_block))
        index = table_end

    content_blocks: List[ContentBlock] = []
    non_table_parts: List[str] = []
    cursor = 0
    for start, end, table in tables_with_spans:
        text_lines = [line.rstrip() for line in lines[cursor:start] if line.strip()]
        text_part = "\n".join(text_lines).strip()
        if text_part:
            non_table_parts.append(text_part)
            content_blocks.append(
                ContentBlock(
                    block_index=len(content_blocks) + 1,
                    block_type="text",
                    text=text_part,
                )
            )

        content_blocks.append(
            ContentBlock(
                block_index=len(content_blocks) + 1,
                block_type="table",
                text=table.raw_text,
                table_index=table.table_index,
            )
        )
        cursor = end

    tail_lines = [line.rstrip() for line in lines[cursor:] if line.strip()]
    tail_text = "\n".join(tail_lines).strip()
    if tail_text:
        non_table_parts.append(tail_text)
        content_blocks.append(
            ContentBlock(
                block_index=len(content_blocks) + 1,
                block_type="text",
                text=tail_text,
            )
        )

    return [table for _, _, table in tables_with_spans], content_blocks, "\n\n".join(non_table_parts).strip()


def cluster_word_lines(words: Sequence[Tuple], tolerance: float = 3.0) -> List[Dict]:
    clusters: List[Dict] = []
    sorted_words = sorted(words, key=lambda item: (((item[1] + item[3]) / 2), item[0]))
    for word in sorted_words:
        y_center = (word[1] + word[3]) / 2
        if clusters and abs(clusters[-1]["y_center"] - y_center) <= tolerance:
            cluster = clusters[-1]
            cluster["words"].append(word)
            cluster["y_center"] = (cluster["y_center"] * cluster["count"] + y_center) / (cluster["count"] + 1)
            cluster["count"] += 1
        else:
            clusters.append({"y_center": y_center, "count": 1, "words": [word]})
    return clusters


def words_to_line_text(words: Sequence[Tuple]) -> str:
    ordered = sorted(words, key=lambda item: item[0])
    return "".join(word[4] for word in ordered).strip()


def extract_header_centers(line_words: Sequence[Tuple], fallback_centers: Optional[List[float]] = None) -> Optional[List[float]]:
    mapping: Dict[str, float] = {}
    line_text = words_to_line_text(line_words)
    for word in sorted(line_words, key=lambda item: item[0]):
        text = word[4].strip()
        if text in TABLE_CANONICAL_HEADERS:
            mapping[text] = (word[0] + word[2]) / 2

    required = {"项目编码", "项目名称", "项目特征", "工作内容"}
    if required.issubset(mapping):
        if fallback_centers:
            centers: List[float] = []
            for index, header in enumerate(TABLE_CANONICAL_HEADERS):
                centers.append(mapping.get(header, fallback_centers[index]))
            return centers
        if all(header in mapping for header in TABLE_CANONICAL_HEADERS):
            return [mapping[header] for header in TABLE_CANONICAL_HEADERS]

    if fallback_centers and all(header in line_text for header in required):
        return fallback_centers

    return None


def assign_words_to_columns(words: Sequence[Tuple], column_centers: Sequence[float]) -> List[str]:
    cells = [[] for _ in column_centers]
    boundaries = [
        (column_centers[index] + column_centers[index + 1]) / 2
        for index in range(len(column_centers) - 1)
    ]

    for word in sorted(words, key=lambda item: item[0]):
        x_center = (word[0] + word[2]) / 2
        column_index = 0
        while column_index < len(boundaries) and x_center > boundaries[column_index]:
            column_index += 1
        cells[column_index].append(word[4])

    return ["".join(parts).strip() for parts in cells]


def append_cell_value(target: Dict[str, List[str]], key: str, value: str) -> None:
    value = value.strip()
    if not value:
        return
    target.setdefault(key, [])
    target[key].append(value)


def normalize_row_payload(
    row_index: int,
    row_cells: Dict[str, List[str]],
    raw_lines: List[str],
    raw_line_cells: Optional[List[Dict[str, str]]] = None,
) -> TableRow:
    project_code = "\n".join(row_cells.get("项目编码", [])).strip()
    project_name = "\n".join(row_cells.get("项目名称", [])).strip()
    project_features = "\n".join(row_cells.get("项目特征", [])).strip()
    measurement_unit = "\n".join(row_cells.get("计量单位", [])).strip()
    quantity_rule = "\n".join(row_cells.get("工程量计算规则", [])).strip()
    work_content = "\n".join(row_cells.get("工作内容", [])).strip()

    return TableRow(
        row_index=row_index,
        project_code=project_code,
        project_name=project_name,
        project_features=project_features,
        measurement_unit=measurement_unit,
        quantity_rule=quantity_rule,
        work_content=work_content,
        raw_columns={
            "项目编码": project_code,
            "项目名称": project_name,
            "项目特征": project_features,
            "计量单位": measurement_unit,
            "工程量计算规则": quantity_rule,
            "工作内容": work_content,
        },
        raw_lines=[line for line in raw_lines if line.strip()],
        raw_line_cells=list(raw_line_cells or []),
    )


def build_raw_line_cell(cells: Sequence[str], raw_line: str) -> Dict[str, str]:
    payload = {"raw_text": raw_line}
    for index, header in enumerate(TABLE_CANONICAL_HEADERS):
        payload[header] = cells[index].strip() if index < len(cells) else ""
    return payload


def refresh_row_raw_columns(row: TableRow) -> None:
    row.raw_columns = {
        "项目编码": row.project_code,
        "项目名称": row.project_name,
        "项目特征": row.project_features,
        "计量单位": row.measurement_unit,
        "工程量计算规则": row.quantity_rule,
        "工作内容": row.work_content,
    }


def split_numbered_items(text: str) -> List[str]:
    items: List[str] = []
    current: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if WORK_ITEM_PATTERN.match(line):
            if current:
                items.append("\n".join(current).strip())
            current = [line]
        elif current:
            current.append(line)
        else:
            current = [line]
    if current:
        items.append("\n".join(current).strip())
    return items


def first_work_item_number(text: str) -> Optional[int]:
    for line in text.splitlines():
        match = WORK_ITEM_PATTERN.match(line.strip())
        if match:
            return int(match.group(1))
    return None


def find_future_code_distance(
    line_cells: Sequence[Tuple[List[str], str]],
    start_index: int,
    max_distance: int = 6,
) -> Optional[int]:
    for offset in range(1, max_distance + 1):
        future_index = start_index + offset
        if future_index >= len(line_cells):
            break
        future_cells = line_cells[future_index][0]
        if future_cells and future_cells[0] and split_project_code_line(future_cells[0]):
            return offset
    return None


def has_prefix_before_future_code(
    line_cells: Sequence[Tuple[List[str], str]],
    start_index: int,
    max_distance: int = 6,
) -> bool:
    for offset in range(1, max_distance + 1):
        future_index = start_index + offset
        if future_index >= len(line_cells):
            break
        future_cells = line_cells[future_index][0]
        if future_cells and future_cells[0] and split_project_code_line(future_cells[0]):
            return False
        if any(future_cells[index] for index in (1, 2, 3)):
            return True
    return False


def infer_measurement_unit(text: str) -> str:
    compact = compact_text(text)
    if not compact:
        return ""
    if "体积计算" in compact or "立方米" in compact:
        return "m3"
    if "面积计算" in compact or "建筑面积" in compact or "投影面积" in compact:
        return "m2"
    if "延长米" in compact or "长度计算" in compact or "中心线长度" in compact:
        return "m"
    return ""


def split_trailing_feature(project_name: str, project_features: str) -> Tuple[str, str]:
    if project_features.strip():
        return project_name, project_features

    candidates = (
        "开挖深度",
        "冻土厚度",
        "土类别",
        "岩石类别",
        "填方部位",
        "材料品种",
        "密实度",
    )
    for candidate in candidates:
        if project_name.endswith(candidate) and len(project_name) > len(candidate):
            stripped_name = project_name[: -len(candidate)].strip()
            if stripped_name:
                return stripped_name, candidate
    return project_name, project_features


def normalize_measurement_unit(value: str, fallback: str) -> str:
    compact = compact_text(value)
    if not compact:
        return fallback
    if compact in {"n?", "0?", "m*"}:
        return fallback or compact
    return value


def postprocess_table_rows(rows: List[TableRow], table_raw_text: str) -> List[TableRow]:
    table_level_unit = infer_measurement_unit(table_raw_text)

    for index in range(len(rows) - 1):
        current = rows[index]
        next_row = rows[index + 1]
        current_no = first_work_item_number(current.work_content)
        next_no = first_work_item_number(next_row.work_content)
        current_items = split_numbered_items(current.work_content)
        if (
            current_no == 1
            and len(current_items) == 1
            and next_no is not None
            and next_no > 1
        ):
            next_row.work_content = (
                f"{current.work_content}\n{next_row.work_content}".strip()
                if next_row.work_content
                else current.work_content
            )
            current.work_content = ""

    next_rule = ""
    for row in reversed(rows):
        if row.quantity_rule.strip():
            next_rule = row.quantity_rule
        elif next_rule:
            row.quantity_rule = next_rule

    shared_rule = ""
    for row in rows:
        if row.quantity_rule.strip():
            shared_rule = row.quantity_rule
        elif shared_rule:
            row.quantity_rule = shared_rule

    shared_work = ""
    for row in rows:
        if row.work_content.strip():
            shared_work = row.work_content
        elif shared_work:
            row.work_content = shared_work

    for row in rows:
        row.project_name, row.project_features = split_trailing_feature(row.project_name, row.project_features)
        row.measurement_unit = normalize_measurement_unit(
            row.measurement_unit,
            infer_measurement_unit(row.quantity_rule) or table_level_unit,
        )
        refresh_row_raw_columns(row)

    return rows


def build_rows_from_column_lines(
    line_cells: Sequence[Tuple[List[str], str]],
    continuation: bool,
) -> Tuple[List[TableRow], Optional[TableRow]]:
    rows: List[TableRow] = []
    current_cells: Optional[Dict[str, List[str]]] = None
    current_raw_lines: List[str] = []
    current_raw_line_cells: List[Dict[str, str]] = []
    leading_cells: Optional[Dict[str, List[str]]] = None
    leading_raw_lines: List[str] = []
    leading_raw_line_cells: List[Dict[str, str]] = []
    pending_prefix_cells: Optional[Dict[str, List[str]]] = None
    pending_prefix_raw_lines: List[str] = []
    pending_prefix_raw_line_cells: List[Dict[str, str]] = []
    pending_next_row_mode = False

    def make_empty_cells() -> Dict[str, List[str]]:
        return {header: [] for header in TABLE_CANONICAL_HEADERS}

    for line_index, (cells, raw_line) in enumerate(line_cells):
        raw_line_cell = build_raw_line_cell(cells, raw_line)
        code_cell = cells[0]
        code_info = split_project_code_line(code_cell) if code_cell else None
        next_code_info: Optional[Tuple[str, str]] = None
        if line_index + 1 < len(line_cells):
            next_cells = line_cells[line_index + 1][0]
            next_code_info = split_project_code_line(next_cells[0]) if next_cells and next_cells[0] else None
        future_code_distance = find_future_code_distance(line_cells, line_index)
        prefix_before_future_code = has_prefix_before_future_code(line_cells, line_index)

        if current_cells is None and continuation and code_info is None:
            consumed = False

            if cells[4] or cells[5]:
                if leading_cells is None:
                    leading_cells = make_empty_cells()
                if cells[4]:
                    append_cell_value(leading_cells, "工程量计算规则", cells[4])
                if cells[5]:
                    append_cell_value(leading_cells, "工作内容", cells[5])
                leading_raw_lines.append(raw_line)
                leading_raw_line_cells.append(
                    build_raw_line_cell(["", "", "", "", cells[4], cells[5]], raw_line)
                )
                consumed = True

            if cells[1] or cells[2] or cells[3]:
                if pending_prefix_cells is None:
                    pending_prefix_cells = make_empty_cells()
                if cells[1]:
                    append_cell_value(pending_prefix_cells, "项目名称", cells[1])
                if cells[2]:
                    append_cell_value(pending_prefix_cells, "项目特征", cells[2])
                if cells[3]:
                    append_cell_value(pending_prefix_cells, "计量单位", cells[3])
                pending_prefix_raw_lines.append(raw_line)
                pending_prefix_raw_line_cells.append(
                    build_raw_line_cell(["", cells[1], cells[2], cells[3], "", ""], raw_line)
                )
                consumed = True

            if consumed:
                continue

        if (
            code_info is None
            and future_code_distance is not None
            and (
                pending_next_row_mode
                or (
                    prefix_before_future_code
                    and (
                        first_work_item_number(cells[5]) == 1
                        or first_work_item_number(cells[4]) == 1
                    )
                )
                or (
                    any(cells[index] for index in (1, 2, 3))
                    and (
                        first_work_item_number(cells[5]) == 1
                        or first_work_item_number(cells[4]) == 1
                    )
                )
            )
        ):
            if pending_prefix_cells is None:
                pending_prefix_cells = make_empty_cells()
            for index, header in enumerate(TABLE_CANONICAL_HEADERS):
                if index < len(cells) and cells[index]:
                    append_cell_value(pending_prefix_cells, header, cells[index])
            pending_prefix_raw_lines.append(raw_line)
            pending_prefix_raw_line_cells.append(raw_line_cell)
            pending_next_row_mode = True
            continue

        if (
            code_info is None
            and next_code_info is not None
            and (cells[1] or cells[2] or cells[3])
            and not cells[4]
            and not cells[5]
        ):
            if pending_prefix_cells is None:
                pending_prefix_cells = make_empty_cells()
            for index, header in enumerate(TABLE_CANONICAL_HEADERS):
                if index < len(cells) and cells[index]:
                    append_cell_value(pending_prefix_cells, header, cells[index])
            pending_prefix_raw_lines.append(raw_line)
            pending_prefix_raw_line_cells.append(raw_line_cell)
            continue

        if code_info:
            if current_cells is not None:
                rows.append(
                    normalize_row_payload(
                        len(rows) + 1,
                        current_cells,
                        current_raw_lines,
                        current_raw_line_cells,
                    )
                )

            current_cells = make_empty_cells()
            current_raw_lines = []
            current_raw_line_cells = []
            pending_next_row_mode = False
            append_cell_value(current_cells, "项目编码", code_info[0])
            inline_name = code_info[1]
            if inline_name:
                append_cell_value(current_cells, "项目名称", inline_name)
            if leading_cells is not None:
                for header in TABLE_CANONICAL_HEADERS[1:]:
                    for value in leading_cells.get(header, []):
                        append_cell_value(current_cells, header, value)
                current_raw_lines.extend(leading_raw_lines)
                current_raw_line_cells.extend(leading_raw_line_cells)
                leading_cells = None
                leading_raw_lines = []
                leading_raw_line_cells = []
            if pending_prefix_cells is not None:
                for header in TABLE_CANONICAL_HEADERS[1:]:
                    for value in pending_prefix_cells.get(header, []):
                        append_cell_value(current_cells, header, value)
                current_raw_lines.extend(pending_prefix_raw_lines)
                current_raw_line_cells.extend(pending_prefix_raw_line_cells)
                pending_prefix_cells = None
                pending_prefix_raw_lines = []
                pending_prefix_raw_line_cells = []
            if cells[1]:
                append_cell_value(current_cells, "项目名称", cells[1])
            if cells[2]:
                append_cell_value(current_cells, "项目特征", cells[2])
            if cells[3]:
                append_cell_value(current_cells, "计量单位", cells[3])
            if cells[4]:
                append_cell_value(current_cells, "工程量计算规则", cells[4])
            if cells[5]:
                append_cell_value(current_cells, "工作内容", cells[5])
            current_raw_lines.append(raw_line)
            current_raw_line_cells.append(raw_line_cell)
            continue

        target_cells = current_cells
        target_raw_lines = current_raw_lines
        target_raw_line_cells = current_raw_line_cells
        if target_cells is None and continuation:
            if leading_cells is None:
                leading_cells = {header: [] for header in TABLE_CANONICAL_HEADERS}
            target_cells = leading_cells
            target_raw_lines = leading_raw_lines
            target_raw_line_cells = leading_raw_line_cells

        if target_cells is None:
            continue

        for index, header in enumerate(TABLE_CANONICAL_HEADERS):
            if index < len(cells) and cells[index]:
                append_cell_value(target_cells, header, cells[index])
        target_raw_lines.append(raw_line)
        target_raw_line_cells.append(raw_line_cell)

    if current_cells is not None:
        rows.append(
            normalize_row_payload(
                len(rows) + 1,
                current_cells,
                current_raw_lines,
                current_raw_line_cells,
            )
        )

    leading_row: Optional[TableRow] = None
    if leading_cells and any(leading_cells[header] for header in TABLE_CANONICAL_HEADERS):
        leading_row = normalize_row_payload(0, leading_cells, leading_raw_lines, leading_raw_line_cells)

    return rows, leading_row


def merge_table_row_segments(base_row: TableRow, leading_row: TableRow) -> TableRow:
    def merge_text(first: str, second: str) -> str:
        first = first.strip()
        second = second.strip()
        if first and second:
            return f"{first}\n{second}"
        return first or second

    base_row.project_name = merge_text(base_row.project_name, leading_row.project_name)
    base_row.project_features = merge_text(base_row.project_features, leading_row.project_features)
    base_row.measurement_unit = merge_text(base_row.measurement_unit, leading_row.measurement_unit)
    base_row.quantity_rule = merge_text(base_row.quantity_rule, leading_row.quantity_rule)
    base_row.work_content = merge_text(base_row.work_content, leading_row.work_content)
    base_row.raw_lines.extend(leading_row.raw_lines)
    base_row.raw_line_cells.extend(leading_row.raw_line_cells)
    refresh_row_raw_columns(base_row)
    return base_row


def extract_table_identifier(title: str) -> str:
    compact = compact_text(title).replace("・", ".").replace("．", ".")
    match = re.search(r"(?:续表)?([A-Z]\.?\d+(?:\.\d+)*)", compact)
    return match.group(1) if match else compact


def extract_tables_from_page_words(
    words: Sequence[Tuple],
    fallback_centers: Optional[List[float]] = None,
) -> Tuple[List[Dict], Optional[List[float]]]:
    lines = cluster_word_lines(words)
    tables: List[Dict] = []
    current_fallback = fallback_centers
    index = 0

    while index < len(lines):
        line_text = words_to_line_text(lines[index]["words"])
        title_lines: List[str] = []
        continuation = False

        if is_table_title(line_text) or is_continuation_title(line_text):
            continuation = is_continuation_title(line_text)
            while index < len(lines):
                current_text = words_to_line_text(lines[index]["words"])
                if is_table_title(current_text) or is_continuation_title(current_text):
                    title_lines.append(current_text)
                    continuation = continuation or is_continuation_title(current_text)
                    index += 1
                    continue
                break

        header_index = index
        header_centers: Optional[List[float]] = None
        while header_index < len(lines) and header_index < index + 3:
            header_centers = extract_header_centers(lines[header_index]["words"], current_fallback)
            if header_centers:
                break
            if words_to_line_text(lines[header_index]["words"]):
                break
            header_index += 1

        if header_centers is None:
            index += 1
            continue

        current_fallback = header_centers
        data_index = header_index + 1
        line_cells: List[Tuple[List[str], str]] = []
        while data_index < len(lines):
            data_text = words_to_line_text(lines[data_index]["words"])
            if not data_text or is_page_marker(data_text):
                data_index += 1
                continue
            if is_table_title(data_text) or is_continuation_title(data_text) or is_section_heading(data_text):
                break
            if extract_header_centers(lines[data_index]["words"], current_fallback):
                data_index += 1
                continue

            cells = assign_words_to_columns(lines[data_index]["words"], header_centers)
            if any(cell for cell in cells):
                line_cells.append((cells, data_text))
            data_index += 1

        rows, leading_row = build_rows_from_column_lines(line_cells, continuation=continuation)
        tables.append(
            {
                "title": "\n".join(title_lines).strip(),
                "headers": list(TABLE_CANONICAL_HEADERS),
                "rows": rows,
                "leading_row": leading_row,
                "continuation": continuation,
                "identifier": extract_table_identifier("\n".join(title_lines).strip()),
                "raw_text": "\n".join([*title_lines, *[text for _, text in line_cells]]).strip(),
            }
        )
        index = data_index

    return tables, current_fallback


def looks_like_body_title(title: str) -> bool:
    return bool(
        re.match(r"^\d+\s*", title)
        or re.match(r"^\d+\.\d+", title)
        or re.match(r"^附录\s*[A-Z]", title)
        or re.match(r"^[A-Z]\.\d+", title)
    )


class GBStandardChapterExtractor:
    def __init__(self, text_resolver: PageTextResolver):
        self.text_resolver = text_resolver

    def process_pdf(self, pdf_path: str | Path, output_dir: str | Path | None = None, save_outputs: bool = True) -> ChapterExtractionResult:
        pdf_path = Path(pdf_path).expanduser().resolve()
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        if output_dir is None:
            project_root = Path(__file__).resolve().parent.parent
            output_dir = project_root / "data" / "output" / "step1" / pdf_path.stem
        output_dir = Path(output_dir).expanduser().resolve()

        with fitz.open(str(pdf_path)) as doc:
            extraction = _ExtractorRun(
                doc=doc,
                pdf_path=pdf_path,
                output_dir=output_dir,
                text_resolver=self.text_resolver,
            )
            result = extraction.run(save_outputs=save_outputs)

        return result


class _ExtractorRun:
    def __init__(self, doc: fitz.Document, pdf_path: Path, output_dir: Path, text_resolver: PageTextResolver):
        self.doc = doc
        self.pdf_path = pdf_path
        self.output_dir = output_dir
        self.text_resolver = text_resolver
        self.page_cache: Dict[int, Dict[str, str]] = {}
        self.word_cache: Dict[int, List[Tuple]] = {}

    def get_page_text(self, page_index: int) -> Dict[str, str]:
        cached = self.page_cache.get(page_index)
        if cached is not None:
            return cached

        result = self.text_resolver.resolve(self.doc, page_index)
        payload = {"text": result.text.strip(), "source": result.source}
        self.page_cache[page_index] = payload
        return payload

    def get_page_words(self, page_index: int) -> List[Tuple]:
        cached = self.word_cache.get(page_index)
        if cached is not None:
            return cached

        page = self.doc.load_page(page_index)
        words = page.get_text("words")
        self.word_cache[page_index] = words
        return words

    def extract_region_tables(self, pdf_page_start: int, pdf_page_end: int) -> List[TableBlock]:
        table_dicts: List[Dict] = []
        fallback_centers: Optional[List[float]] = None

        for page_index in range(pdf_page_start - 1, pdf_page_end):
            page_tables, fallback_centers = extract_tables_from_page_words(
                self.get_page_words(page_index),
                fallback_centers=fallback_centers,
            )
            for page_table in page_tables:
                if page_table["continuation"] and table_dicts:
                    previous = table_dicts[-1]
                    if (
                        not page_table["identifier"]
                        or page_table["identifier"] == previous["identifier"]
                    ):
                        previous["rows"].extend(page_table["rows"])
                        previous["raw_text"] = "\n".join(
                            part for part in [previous["raw_text"], page_table["raw_text"]] if part
                        ).strip()
                        continue
                table_dicts.append(page_table)

        tables: List[TableBlock] = []
        for table_index, page_table in enumerate(table_dicts, start=1):
            rows = postprocess_table_rows(page_table["rows"], page_table["raw_text"])
            for row_index, row in enumerate(rows, start=1):
                row.row_index = row_index
            tables.append(
                TableBlock(
                    table_index=table_index,
                    title=page_table["title"],
                    headers=page_table["headers"],
                    row_count=len(rows),
                    raw_text=page_table["raw_text"],
                    rows=rows,
                )
            )

        return tables

    def load_outline(self) -> List[OutlineEntry]:
        toc = self.doc.get_toc()
        outline: List[OutlineEntry] = []
        parent_stack: List[OutlineEntry] = []

        first_body_pdf_page: Optional[int] = None
        for level, title, pdf_page in toc:
            if looks_like_body_title(title):
                first_body_pdf_page = pdf_page
                break

        body_offset = first_body_pdf_page - 1 if first_body_pdf_page is not None else None

        for index, (level, title, pdf_page) in enumerate(toc):
            category = classify_title(title)
            if category == "body" and not looks_like_body_title(title):
                if first_body_pdf_page is None or pdf_page < first_body_pdf_page:
                    category = "front"

            while parent_stack and parent_stack[-1].level >= level:
                parent_stack.pop()

            parent_title = parent_stack[-1].title if parent_stack else None
            body_page = None
            if category == "body" and body_offset is not None and pdf_page > body_offset:
                body_page = pdf_page - body_offset

            entry = OutlineEntry(
                index=index,
                level=level,
                title=title.strip(),
                pdf_page=pdf_page,
                category=category,
                parent_index=parent_stack[-1].index if parent_stack else None,
                parent_title=parent_title,
                body_page=body_page,
            )
            outline.append(entry)
            parent_stack.append(entry)

        return outline

    def detect_catalog_range(self, outline: Sequence[OutlineEntry]) -> CatalogDetection:
        catalog_entry = next((entry for entry in outline if entry.title.strip().lower() in {"目次", "contents"}), None)
        first_body = next((entry for entry in outline if entry.category == "body" and looks_like_body_title(entry.title)), None)

        catalog_start = catalog_entry.pdf_page if catalog_entry else None
        catalog_end = first_body.pdf_page - 1 if catalog_entry and first_body else None
        front_end = first_body.pdf_page - 1 if first_body else None

        return CatalogDetection(
            catalog_start_pdf_page=catalog_start,
            catalog_end_pdf_page=catalog_end,
            front_matter_end_pdf_page=front_end,
            body_start_pdf_page=first_body.pdf_page if first_body else None,
        )

    def boundary_for_entry(self, outline: Sequence[OutlineEntry], entry: OutlineEntry) -> Optional[OutlineEntry]:
        for candidate in outline[entry.index + 1 :]:
            if candidate.level <= entry.level:
                return candidate
        return None

    def body_end_page(self, outline: Sequence[OutlineEntry]) -> int:
        back_entries = [entry for entry in outline if entry.category == "back"]
        if back_entries:
            return back_entries[0].pdf_page - 1
        return self.doc.page_count

    def extract_segment(
        self,
        entry: OutlineEntry,
        boundary: Optional[OutlineEntry],
        last_page: int,
    ) -> Tuple[str, str, bool, bool, int, int]:
        start_page_index = entry.pdf_page - 1
        end_page_index = last_page - 1 if boundary is None else boundary.pdf_page - 1

        start_page_info = self.get_page_text(start_page_index)
        start_page_text = start_page_info["text"]
        start_anchor = find_anchor(start_page_text, entry.title)

        start_found = start_anchor is not None
        start_raw_index = start_anchor[0] if start_anchor else 0
        start_raw_after = start_anchor[1] if start_anchor else 0

        parts: List[Tuple[int, str, str]] = []
        end_found = False

        if boundary and boundary.pdf_page == entry.pdf_page:
            end_anchor = find_anchor(start_page_text, boundary.title, raw_start=start_raw_after)
            end_found = end_anchor is not None
            end_raw_index = end_anchor[0] if end_anchor else len(start_page_text)
            parts.append((entry.pdf_page, start_page_text[start_raw_index:end_raw_index].strip(), start_page_info["source"]))
            return self._finalize_segment(parts, entry.pdf_page, start_found, end_found, start_page_info["source"])

        parts.append((entry.pdf_page, start_page_text[start_raw_index:].strip(), start_page_info["source"]))

        if boundary is None:
            last_inclusive_index = last_page - 1
            for page_index in range(start_page_index + 1, last_inclusive_index + 1):
                page_info = self.get_page_text(page_index)
                parts.append((page_index + 1, page_info["text"].strip(), page_info["source"]))
            return self._finalize_segment(parts, entry.pdf_page, start_found, False, start_page_info["source"])

        for page_index in range(start_page_index + 1, end_page_index):
            page_info = self.get_page_text(page_index)
            parts.append((page_index + 1, page_info["text"].strip(), page_info["source"]))

        boundary_page_info = self.get_page_text(end_page_index)
        boundary_page_text = boundary_page_info["text"]
        end_anchor = find_anchor(boundary_page_text, boundary.title)
        end_found = end_anchor is not None
        end_raw_index = end_anchor[0] if end_anchor else len(boundary_page_text)
        parts.append((boundary.pdf_page, boundary_page_text[:end_raw_index].strip(), boundary_page_info["source"]))
        return self._finalize_segment(parts, entry.pdf_page, start_found, end_found, start_page_info["source"])

    def _finalize_segment(
        self,
        parts: List[Tuple[int, str, str]],
        start_page: int,
        start_found: bool,
        end_found: bool,
        default_source: str,
    ) -> Tuple[str, str, bool, bool, int, int]:
        filtered_parts = [(page, text, source) for page, text, source in parts if text]
        actual_end_page = filtered_parts[-1][0] if filtered_parts else start_page
        unique_sources = []
        for _, _, source in filtered_parts:
            if source not in unique_sources:
                unique_sources.append(source)
        text_source = ",".join(unique_sources) if unique_sources else default_source
        text = "\n".join(text for _, text, _ in filtered_parts).strip()
        return text, text_source, start_found, end_found, start_page, actual_end_page

    def build_regions(self, outline: Sequence[OutlineEntry], save_outputs: bool) -> List[RegionResult]:
        target_entries = [entry for entry in outline if entry.category == "body"]
        text_dir = self.output_dir / "region_texts"
        if save_outputs:
            text_dir.mkdir(parents=True, exist_ok=True)

        last_body_page = self.body_end_page(outline)
        results: List[RegionResult] = []
        entries_by_index = {entry.index: entry for entry in outline}

        for idx, entry in enumerate(target_entries):
            boundary = self.boundary_for_entry(outline, entry)
            text, text_source, start_found, end_found, pdf_page_start, pdf_page_end = self.extract_segment(
                entry=entry,
                boundary=boundary,
                last_page=last_body_page,
            )
            body_page_start = entry.body_page
            body_page_end = pdf_page_end - (entry.pdf_page - (entry.body_page or entry.pdf_page))
            output_path: Optional[Path] = None
            path_titles = self._build_region_path(entry, entries_by_index)
            path_text = " > ".join(path_titles)
            text_tables, content_blocks, non_table_text = parse_region_content(text)
            positional_tables = self.extract_region_tables(pdf_page_start, pdf_page_end)
            tables = positional_tables or text_tables
            if save_outputs:
                output_name = f"{idx + 1:03d}_L{entry.level}_{sanitize_filename(path_text)}.txt"
                output_path = text_dir / output_name
                output_path.write_text(text, encoding="utf-8")

            results.append(
                RegionResult(
                    index=idx + 1,
                    outline_index=entry.index,
                    level=entry.level,
                    title=entry.title,
                    path=path_titles,
                    path_text=path_text,
                    parent_index=entry.parent_index,
                    parent_title=entry.parent_title,
                    pdf_page_start=pdf_page_start,
                    pdf_page_end=pdf_page_end,
                    body_page_start=body_page_start,
                    body_page_end=body_page_end,
                    text_source=text_source,
                    start_anchor_found=start_found,
                    end_anchor_found=end_found,
                    text_length=len(text),
                    output_file=str(output_path) if output_path else None,
                    table_count=len(tables),
                    table_row_count=sum(table.row_count for table in tables),
                    non_table_text=non_table_text,
                    text=text,
                    tables=tables,
                    content_blocks=content_blocks,
                )
            )

        return results

    def _build_region_path(self, entry: OutlineEntry, entries_by_index: Dict[int, OutlineEntry]) -> List[str]:
        path: List[str] = []
        current: Optional[OutlineEntry] = entry
        while current is not None:
            path.append(current.title)
            if current.parent_index is None:
                break
            current = entries_by_index.get(current.parent_index)
        return list(reversed(path))

    def build_region_tree(self, flat_regions: Sequence[RegionResult]) -> List[RegionNode]:
        nodes = {
            region.outline_index: RegionNode(region=region)
            for region in flat_regions
        }
        roots: List[RegionNode] = []

        for region in flat_regions:
            node = nodes[region.outline_index]
            if region.parent_index is not None and region.parent_index in nodes:
                nodes[region.parent_index].children.append(node)
            else:
                roots.append(node)

        return roots

    def build_chapter_packages(self, flat_regions: Sequence[RegionResult]) -> List[Dict[str, Any]]:
        grouped_regions: Dict[str, List[RegionResult]] = {}
        for region in flat_regions:
            chapter_title = region.path[0] if region.path else region.title
            grouped_regions.setdefault(chapter_title, []).append(region)

        packages: List[Dict[str, Any]] = []
        chapter_index = 0
        for chapter_title, regions in grouped_regions.items():
            if not is_bill_chapter_title(chapter_title):
                continue
            chapter_index += 1
            chapter_region = next(
                (item for item in regions if len(item.path) == 1 and item.title == chapter_title),
                regions[0],
            )
            regions_with_tables = [item for item in regions if item.table_count > 0]
            package = {
                "chapter": {
                    "chapter_index": chapter_index,
                    "title": chapter_title,
                    "path_text": chapter_title,
                    "slug": chapter_slug(chapter_index, chapter_title),
                    "outline_index": chapter_region.outline_index,
                    "level": chapter_region.level,
                    "pdf_page_start": min(item.pdf_page_start for item in regions),
                    "pdf_page_end": max(item.pdf_page_end for item in regions),
                    "body_page_start": min(
                        (item.body_page_start for item in regions if item.body_page_start is not None),
                        default=None,
                    ),
                    "body_page_end": max(
                        (item.body_page_end for item in regions if item.body_page_end is not None),
                        default=None,
                    ),
                    "region_count": len(regions),
                    "regions_with_tables": len(regions_with_tables),
                    "table_count": sum(item.table_count for item in regions),
                    "table_row_count": sum(item.table_row_count for item in regions),
                },
                "regions": [item.to_dict() for item in regions],
            }
            packages.append(package)

        return packages

    def run(self, save_outputs: bool) -> ChapterExtractionResult:
        if save_outputs:
            self.output_dir.mkdir(parents=True, exist_ok=True)

        outline = self.load_outline()
        catalog_detection = self.detect_catalog_range(outline)
        flat_regions = self.build_regions(outline, save_outputs=save_outputs)
        region_tree = self.build_region_tree(flat_regions)
        body_levels = [entry.level for entry in outline if entry.category == "body"]

        summary = ExtractionSummary(
            pdf_path=str(self.pdf_path),
            total_pdf_pages=self.doc.page_count,
            catalog_detection=catalog_detection,
            outline_counts={
                "total": len(outline),
                "front": len([entry for entry in outline if entry.category == "front"]),
                "body": len([entry for entry in outline if entry.category == "body"]),
                "back": len([entry for entry in outline if entry.category == "back"]),
            },
            region_counts={
                "top_level": len(region_tree),
                "total": len(flat_regions),
                "max_level": max(body_levels) if body_levels else 0,
            },
            table_counts={
                "regions_with_tables": len([region for region in flat_regions if region.table_count > 0]),
                "tables": sum(region.table_count for region in flat_regions),
                "rows": sum(region.table_row_count for region in flat_regions),
            },
            providers=self.text_resolver.provider_names,
            output_dir=str(self.output_dir) if save_outputs else None,
        )

        result = ChapterExtractionResult(
            summary=summary,
            outline_entries=outline,
            region_tree=region_tree,
            flat_regions=flat_regions,
        )

        if save_outputs:
            table_regions = [item.to_dict() for item in flat_regions if item.table_count > 0]
            chapter_packages = self.build_chapter_packages(flat_regions)
            chapter_dir = self.output_dir / "chapter_regions"
            chapter_dir.mkdir(parents=True, exist_ok=True)
            (self.output_dir / "catalog_summary.json").write_text(
                json.dumps(summary.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (self.output_dir / "outline_entries.json").write_text(
                json.dumps([entry.to_dict() for entry in outline], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (self.output_dir / "flat_regions.json").write_text(
                json.dumps([item.to_dict() for item in flat_regions], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (self.output_dir / "region_tree.json").write_text(
                json.dumps([item.to_dict() for item in region_tree], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (self.output_dir / "table_regions.json").write_text(
                json.dumps(table_regions, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            chapter_index_payload = {
                "pdf_path": str(self.pdf_path),
                "output_dir": str(self.output_dir),
                "generated_from": "flat_regions",
                "chapters": [],
            }
            for package in chapter_packages:
                chapter_meta = dict(package["chapter"])
                file_name = f"{chapter_meta['slug']}.json"
                file_path = chapter_dir / file_name
                file_path.write_text(
                    json.dumps(package, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                chapter_meta["file_name"] = file_name
                chapter_meta["file_path"] = str(file_path)
                chapter_meta["relative_path"] = str(Path("chapter_regions") / file_name)
                chapter_index_payload["chapters"].append(chapter_meta)
            (chapter_dir / "chapter_index.json").write_text(
                json.dumps(chapter_index_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        return result
