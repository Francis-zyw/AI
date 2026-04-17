from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List


BILL_CHAPTER_PATTERN = re.compile(r"^附录\s*[A-Z]", re.IGNORECASE)


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


def get_default_step1_source_path(project_root: Path) -> Path:
    chapter_index_candidates = sorted(
        project_root.glob("data/output/step1/*/chapter_regions/chapter_index.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if chapter_index_candidates:
        return _resolve_first_chapter_entry_path(chapter_index_candidates[0])

    raise FileNotFoundError("未找到 Step1 chapter_regions 输出，请先执行 step1。")


def resolve_standard_name_from_step1_source(step1_source_path: Path) -> str:
    source_path = step1_source_path
    if source_path.name == "chapter_index.json" and source_path.parent.name == "chapter_regions":
        return source_path.parent.parent.name
    if source_path.parent.name == "chapter_regions":
        return source_path.parent.parent.name
    if source_path.is_dir() and source_path.name == "chapter_regions":
        return source_path.parent.name
    if source_path.is_dir():
        return source_path.name
    return source_path.stem


def is_bill_chapter_title(chapter_title: str) -> bool:
    return bool(BILL_CHAPTER_PATTERN.match(str(chapter_title or "").strip()))


def get_default_output_dir(step1_source_path: Path, project_root: Path) -> Path:
    standard_name = resolve_standard_name_from_step1_source(step1_source_path)
    return project_root / "data" / "output" / "step2" / standard_name


def _normalize_step1_source_path(step1_source_path: Path) -> Path:
    path = step1_source_path.expanduser().resolve()
    if not path.is_dir():
        if path.name == "flat_regions.json":
            raise ValueError("Step2 已不再支持 flat_regions.json，请改用 Step1 导出的 chapter_regions 章节文件。")
        if path.name == "chapter_index.json":
            return _resolve_first_chapter_entry_path(path)
        return path

    direct_chapter_index = path / "chapter_index.json"
    if direct_chapter_index.exists():
        return _resolve_first_chapter_entry_path(direct_chapter_index)

    nested_chapter_index = path / "chapter_regions" / "chapter_index.json"
    if nested_chapter_index.exists():
        return _resolve_first_chapter_entry_path(nested_chapter_index)

    raise FileNotFoundError(f"未能在目录中识别 Step1 数据源：{path}")


def _resolve_chapter_entry_path(index_path: Path, chapter_item: Dict[str, Any]) -> Path:
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
        if not candidate_path.is_absolute():
            candidate_path = index_path.parent.parent / candidate_path if candidate_text.startswith("chapter_regions/") else index_path.parent / candidate_path
        if candidate_path.exists():
            return candidate_path.resolve()
    raise FileNotFoundError(f"章节索引缺少可用文件路径：{chapter_item}")


def _resolve_first_chapter_entry_path(index_path: Path) -> Path:
    payload = load_json_or_jsonl(index_path)
    chapters = payload.get("chapters", []) if isinstance(payload, dict) else []
    for chapter_item in chapters:
        if not isinstance(chapter_item, dict):
            continue
        chapter_title = str(chapter_item.get("title", "")).strip()
        if chapter_title and not is_bill_chapter_title(chapter_title):
            continue
        return _resolve_chapter_entry_path(index_path, chapter_item)
    raise FileNotFoundError(f"chapter_index 中未找到可用的清单章节：{index_path}")


def load_step1_regions_source(step1_source_path: str | Path) -> Dict[str, Any]:
    source_path = _normalize_step1_source_path(Path(step1_source_path))
    payload = load_json_or_jsonl(source_path)
    standard_document = resolve_standard_name_from_step1_source(source_path)

    if isinstance(payload, dict) and isinstance(payload.get("regions"), list):
        chapter_meta = payload.get("chapter", {}) if isinstance(payload.get("chapter"), dict) else {}
        chapter_title = str(chapter_meta.get("title", "")).strip()
        return {
            "regions": payload["regions"],
            "source_type": "chapter_package",
            "source_path": str(source_path),
            "standard_document": standard_document,
            "chapters": [chapter_title] if chapter_title else [],
            "chapter_meta": chapter_meta,
        }

    if isinstance(payload, dict) and isinstance(payload.get("chapters"), list):
        for chapter_item in payload["chapters"]:
            if not isinstance(chapter_item, dict):
                continue
            chapter_title = str(chapter_item.get("title", "")).strip()
            if chapter_title and not is_bill_chapter_title(chapter_title):
                continue
            chapter_path = _resolve_chapter_entry_path(source_path, chapter_item)
            return load_step1_regions_source(chapter_path)

    raise ValueError(f"无法识别的 Step1 数据源格式：{source_path}")
