from __future__ import annotations

import json
import os
import re
import sqlite3
from fnmatch import fnmatch
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from pipeline_v2.knowledge_base import (
    DEFAULT_MAX_CONTEXT_CHARS,
    DEFAULT_TOP_K,
    DEFAULT_VECTOR_DIM,
    build_hashed_embedding,
    cosine_similarity,
    sanitize_slug,
)
from pipeline_v2.step3_engine.api import load_json_or_jsonl, write_json, write_text


GLOBAL_KNOWLEDGE_DB_NAME = "global_knowledge.db"
GLOBAL_INGEST_SUMMARY_NAME = "global_knowledge_ingest_summary.json"
GLOBAL_QUERY_RESULT_NAME = "global_knowledge_query_result.json"
GLOBAL_WIKI_DIR_NAME = "wiki"

DEFAULT_COLLECTION = "general"
DEFAULT_SOURCE_TYPE = "generic"
DEFAULT_CHUNK_CHARS = 1400
DEFAULT_CHUNK_OVERLAP = 180
DEFAULT_MAX_FILE_BYTES = 2_000_000

TEXT_EXTENSIONS = {
    ".md",
    ".markdown",
    ".txt",
    ".rst",
    ".json",
    ".jsonl",
    ".csv",
    ".tsv",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".go",
    ".rs",
    ".sql",
    ".html",
    ".xml",
}

TITLE_LINE_RE = re.compile(r"^\s{0,3}#\s+(.+?)\s*$", flags=re.MULTILINE)


@dataclass(frozen=True)
class GlobalSourceSpec:
    path: str
    collection: str
    source_type: str
    tags: List[str]
    title: str
    recursive: bool
    include_globs: List[str]
    exclude_globs: List[str]
    content_fields: List[str]
    metadata_fields: List[str]


@dataclass(frozen=True)
class GlobalKnowledgeDocument:
    entry_id: str
    collection: str
    source_type: str
    title: str
    content: str
    source_path: str
    source_ref: str
    tags: List[str]
    metadata: Dict[str, Any]


@dataclass(frozen=True)
class GlobalWikiPage:
    slug: str
    page_type: str
    title: str
    content: str
    collection: str
    tags: List[str]
    source_refs: List[str]


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _normalize_tags(values: Iterable[Any]) -> List[str]:
    seen = set()
    normalized: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _extract_title(text: str, fallback: str) -> str:
    value = str(text or "")
    match = TITLE_LINE_RE.search(value)
    if match:
        title = match.group(1).strip()
        if title:
            return title[:160]
    first_line = value.splitlines()[0].strip() if value.strip() else ""
    if first_line:
        return first_line[:160]
    return fallback[:160] or "Untitled"


def _chunk_text(text: str, *, chunk_chars: int, chunk_overlap: int) -> List[str]:
    cleaned = str(text or "").replace("\r\n", "\n").strip()
    if not cleaned:
        return []
    if len(cleaned) <= chunk_chars:
        return [cleaned]

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    if not paragraphs:
        paragraphs = [cleaned]

    chunks: List[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= chunk_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)
            overlap_text = current[-chunk_overlap:].strip()
            current = f"{overlap_text}\n\n{paragraph}".strip() if overlap_text else paragraph
        else:
            for start in range(0, len(paragraph), max(1, chunk_chars - chunk_overlap)):
                piece = paragraph[start:start + chunk_chars].strip()
                if piece:
                    chunks.append(piece)
            current = ""

    if current:
        chunks.append(current)
    return chunks


def _build_entry_id(collection: str, source_path: str, source_ref: str, title: str) -> str:
    import hashlib

    digest = hashlib.sha1(f"{collection}|{source_path}|{source_ref}|{title}".encode("utf-8")).hexdigest()
    return f"gk_{digest[:20]}"


def _resolve_path(raw_path: str, *, base_dir: Path) -> Path:
    expanded = os.path.expanduser(os.path.expandvars(str(raw_path or "").strip()))
    if not expanded:
        raise ValueError("source path 不能为空。")
    candidate = Path(expanded)
    if candidate.is_absolute():
        return candidate.resolve()
    return (base_dir / candidate).resolve()


def _match_any_glob(path: Path, patterns: Sequence[str]) -> bool:
    path_text = path.as_posix()
    path_name = path.name
    for pattern in patterns:
        normalized_pattern = str(pattern or "").strip()
        if not normalized_pattern:
            continue
        candidates = [normalized_pattern]
        if normalized_pattern.startswith("**/"):
            candidates.append(normalized_pattern[3:])
        if any(path.match(candidate) for candidate in candidates if candidate):
            return True
        if any(fnmatch(path_text, candidate) for candidate in candidates if candidate):
            return True
        if any(fnmatch(path_name, candidate) for candidate in candidates if candidate):
            return True
    return False


def _iter_source_files(spec: GlobalSourceSpec, *, base_dir: Path) -> List[Path]:
    target_path = _resolve_path(spec.path, base_dir=base_dir)
    if not target_path.exists():
        raise FileNotFoundError(f"未找到知识源路径：{target_path}")

    if target_path.is_file():
        return [target_path]

    if not target_path.is_dir():
        return []

    walker = target_path.rglob("*") if spec.recursive else target_path.glob("*")
    files: List[Path] = []
    for candidate in walker:
        if not candidate.is_file():
            continue
        if spec.include_globs and not _match_any_glob(candidate.relative_to(target_path), spec.include_globs):
            continue
        if spec.exclude_globs and _match_any_glob(candidate.relative_to(target_path), spec.exclude_globs):
            continue
        if candidate.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        try:
            if candidate.stat().st_size > DEFAULT_MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        files.append(candidate)
    return sorted(files)


def _safe_read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _select_content_fields(item: Dict[str, Any], fields: Sequence[str]) -> str:
    if not fields:
        return _json_dumps(item)
    parts: List[str] = []
    for field in fields:
        if field in item and item[field] not in (None, "", [], {}):
            parts.append(f"{field}: {item[field]}")
    return "\n".join(parts).strip()


def _select_metadata_fields(item: Dict[str, Any], fields: Sequence[str]) -> Dict[str, Any]:
    if not fields:
        return dict(item)
    return {field: item[field] for field in fields if field in item}


def _build_documents_from_json_payload(
    *,
    payload: Any,
    file_path: Path,
    spec: GlobalSourceSpec,
    chunk_chars: int,
    chunk_overlap: int,
) -> List[GlobalKnowledgeDocument]:
    documents: List[GlobalKnowledgeDocument] = []
    base_metadata = {
        "file_suffix": file_path.suffix.lower(),
        "source_name": file_path.name,
        "ingest_mode": "json_payload",
    }

    if isinstance(payload, list):
        for index, item in enumerate(payload, start=1):
            title = spec.title or f"{file_path.stem} item {index}"
            metadata: Dict[str, Any] = {"item_index": index, **base_metadata}
            if isinstance(item, dict):
                content = _select_content_fields(item, spec.content_fields) or _json_dumps(item)
                if not spec.title:
                    title = str(item.get("title") or item.get("name") or title)
                metadata.update(_select_metadata_fields(item, spec.metadata_fields))
                tags = _normalize_tags(spec.tags + list(item.get("tags", [])) if isinstance(item.get("tags"), list) else spec.tags)
            else:
                content = str(item)
                tags = list(spec.tags)
            for chunk_index, chunk in enumerate(_chunk_text(content, chunk_chars=chunk_chars, chunk_overlap=chunk_overlap), start=1):
                source_ref = f"{file_path}#item-{index}-chunk-{chunk_index}"
                documents.append(
                    GlobalKnowledgeDocument(
                        entry_id=_build_entry_id(spec.collection, str(file_path), source_ref, title),
                        collection=spec.collection,
                        source_type=spec.source_type or "json",
                        title=str(title).strip()[:160],
                        content=chunk,
                        source_path=str(file_path),
                        source_ref=source_ref,
                        tags=tags,
                        metadata={**metadata, "chunk_index": chunk_index},
                    )
                )
        return documents

    if isinstance(payload, dict):
        complex_items = [(key, value) for key, value in payload.items() if isinstance(value, (list, dict))]
        if complex_items:
            for key, value in complex_items:
                title = spec.title or f"{file_path.stem} | {key}"
                content = _json_dumps(value)
                for chunk_index, chunk in enumerate(_chunk_text(content, chunk_chars=chunk_chars, chunk_overlap=chunk_overlap), start=1):
                    source_ref = f"{file_path}#{key}-chunk-{chunk_index}"
                    documents.append(
                        GlobalKnowledgeDocument(
                            entry_id=_build_entry_id(spec.collection, str(file_path), source_ref, title),
                            collection=spec.collection,
                            source_type=spec.source_type or "json",
                            title=title[:160],
                            content=chunk,
                            source_path=str(file_path),
                            source_ref=source_ref,
                            tags=list(spec.tags),
                            metadata={**base_metadata, "top_level_key": key, "chunk_index": chunk_index},
                        )
                    )
            return documents

    raw_content = _json_dumps(payload)
    title = spec.title or file_path.stem
    for chunk_index, chunk in enumerate(_chunk_text(raw_content, chunk_chars=chunk_chars, chunk_overlap=chunk_overlap), start=1):
        source_ref = f"{file_path}#chunk-{chunk_index}"
        documents.append(
            GlobalKnowledgeDocument(
                entry_id=_build_entry_id(spec.collection, str(file_path), source_ref, title),
                collection=spec.collection,
                source_type=spec.source_type or "json",
                title=title[:160],
                content=chunk,
                source_path=str(file_path),
                source_ref=source_ref,
                tags=list(spec.tags),
                metadata={**base_metadata, "chunk_index": chunk_index},
            )
        )
    return documents


def _build_documents_from_text_file(
    *,
    file_path: Path,
    spec: GlobalSourceSpec,
    chunk_chars: int,
    chunk_overlap: int,
) -> List[GlobalKnowledgeDocument]:
    text = _safe_read_text(file_path)
    if not text.strip():
        return []
    title = spec.title or _extract_title(text, file_path.stem)
    tags = list(spec.tags)
    documents: List[GlobalKnowledgeDocument] = []
    for chunk_index, chunk in enumerate(_chunk_text(text, chunk_chars=chunk_chars, chunk_overlap=chunk_overlap), start=1):
        source_ref = f"{file_path}#chunk-{chunk_index}"
        documents.append(
            GlobalKnowledgeDocument(
                entry_id=_build_entry_id(spec.collection, str(file_path), source_ref, title),
                collection=spec.collection,
                source_type=spec.source_type or file_path.suffix.lower().lstrip(".") or DEFAULT_SOURCE_TYPE,
                title=title[:160],
                content=chunk,
                source_path=str(file_path),
                source_ref=source_ref,
                tags=tags,
                metadata={
                    "file_suffix": file_path.suffix.lower(),
                    "source_name": file_path.name,
                    "chunk_index": chunk_index,
                },
            )
        )
    return documents


def _build_documents_from_file(
    *,
    file_path: Path,
    spec: GlobalSourceSpec,
    chunk_chars: int,
    chunk_overlap: int,
) -> List[GlobalKnowledgeDocument]:
    suffix = file_path.suffix.lower()
    if suffix in {".json", ".jsonl"}:
        try:
            payload = load_json_or_jsonl(file_path)
        except Exception:
            return _build_documents_from_text_file(
                file_path=file_path,
                spec=spec,
                chunk_chars=chunk_chars,
                chunk_overlap=chunk_overlap,
            )
        return _build_documents_from_json_payload(
            payload=payload,
            file_path=file_path,
            spec=spec,
            chunk_chars=chunk_chars,
            chunk_overlap=chunk_overlap,
        )
    return _build_documents_from_text_file(
        file_path=file_path,
        spec=spec,
        chunk_chars=chunk_chars,
        chunk_overlap=chunk_overlap,
    )


def _parse_manifest(manifest_path: str | Path) -> tuple[Path, Dict[str, Any]]:
    resolved_path = Path(manifest_path).expanduser().resolve()
    payload = load_json_or_jsonl(resolved_path)
    if not isinstance(payload, dict):
        raise ValueError("全局知识库 manifest 必须是对象。")
    return resolved_path, payload


def _normalize_source_spec(raw_spec: Dict[str, Any], *, default_collection: str) -> GlobalSourceSpec:
    return GlobalSourceSpec(
        path=str(raw_spec.get("path", "")).strip(),
        collection=str(raw_spec.get("collection", "")).strip() or default_collection,
        source_type=str(raw_spec.get("source_type", "")).strip() or DEFAULT_SOURCE_TYPE,
        tags=_normalize_tags(raw_spec.get("tags", []) if isinstance(raw_spec.get("tags"), list) else []),
        title=str(raw_spec.get("title", "")).strip(),
        recursive=bool(raw_spec.get("recursive", True)),
        include_globs=[str(item).strip() for item in raw_spec.get("include_globs", []) if str(item).strip()],
        exclude_globs=[str(item).strip() for item in raw_spec.get("exclude_globs", []) if str(item).strip()],
        content_fields=[str(item).strip() for item in raw_spec.get("content_fields", []) if str(item).strip()],
        metadata_fields=[str(item).strip() for item in raw_spec.get("metadata_fields", []) if str(item).strip()],
    )


def _build_source_specs(
    *,
    source_paths: Sequence[str] | None,
    manifest_path: str | Path | None,
    default_collection: str,
) -> tuple[List[GlobalSourceSpec], Dict[str, Any]]:
    specs: List[GlobalSourceSpec] = []
    manifest_meta: Dict[str, Any] = {}
    if manifest_path:
        manifest_file, manifest_payload = _parse_manifest(manifest_path)
        manifest_meta = {
            "manifest_path": str(manifest_file),
            "manifest_name": manifest_file.name,
        }
        manifest_default_collection = str(manifest_payload.get("default_collection", "")).strip() or default_collection
        for raw_spec in manifest_payload.get("sources", []):
            if isinstance(raw_spec, dict):
                specs.append(_normalize_source_spec(raw_spec, default_collection=manifest_default_collection))
    for source_path in source_paths or []:
        specs.append(
            GlobalSourceSpec(
                path=str(source_path),
                collection=default_collection,
                source_type=DEFAULT_SOURCE_TYPE,
                tags=[],
                title="",
                recursive=True,
                include_globs=[],
                exclude_globs=[],
                content_fields=[],
                metadata_fields=[],
            )
        )
    if not specs:
        raise ValueError("至少需要提供 --source 或 --manifest。")
    return specs, manifest_meta


def _collect_documents(
    *,
    source_specs: Sequence[GlobalSourceSpec],
    base_dir: Path,
    chunk_chars: int,
    chunk_overlap: int,
) -> tuple[List[GlobalKnowledgeDocument], Dict[str, Any]]:
    documents: List[GlobalKnowledgeDocument] = []
    source_summary: Dict[str, Any] = {
        "source_count": 0,
        "file_count": 0,
        "collection_counts": {},
        "source_type_counts": {},
    }

    collection_counter: Counter[str] = Counter()
    source_type_counter: Counter[str] = Counter()
    file_count = 0
    for spec in source_specs:
        files = _iter_source_files(spec, base_dir=base_dir)
        file_count += len(files)
        source_summary["source_count"] += 1
        for file_path in files:
            file_documents = _build_documents_from_file(
                file_path=file_path,
                spec=spec,
                chunk_chars=chunk_chars,
                chunk_overlap=chunk_overlap,
            )
            documents.extend(file_documents)
            collection_counter[spec.collection] += len(file_documents)
            source_type_counter[spec.source_type] += len(file_documents)

    source_summary["file_count"] = file_count
    source_summary["collection_counts"] = dict(collection_counter)
    source_summary["source_type_counts"] = dict(source_type_counter)
    return documents, source_summary


def _build_wiki_pages(documents: Sequence[GlobalKnowledgeDocument]) -> List[GlobalWikiPage]:
    collection_groups: Dict[str, List[GlobalKnowledgeDocument]] = defaultdict(list)
    tag_groups: Dict[str, List[GlobalKnowledgeDocument]] = defaultdict(list)
    source_type_groups: Dict[str, List[GlobalKnowledgeDocument]] = defaultdict(list)
    for document in documents:
        collection_groups[document.collection].append(document)
        source_type_groups[document.source_type].append(document)
        for tag in document.tags:
            tag_groups[tag].append(document)

    pages: List[GlobalWikiPage] = []
    collection_counter = Counter(document.collection for document in documents)
    source_type_counter = Counter(document.source_type for document in documents)
    tag_counter = Counter(tag for document in documents for tag in document.tags)
    overview_lines = [
        "# Global Knowledge Base Overview",
        "",
        "## Summary",
        f"- total_documents: {len(documents)}",
        f"- total_collections: {len(collection_groups)}",
        f"- total_tags: {len(tag_groups)}",
        "",
        "## Collections",
    ]
    for collection, count in collection_counter.most_common():
        overview_lines.append(f"- {collection}: {count}")
    overview_lines.extend(["", "## Source Types"])
    for source_type, count in source_type_counter.most_common():
        overview_lines.append(f"- {source_type}: {count}")
    overview_lines.extend(["", "## Top Tags"])
    for tag, count in tag_counter.most_common(20):
        overview_lines.append(f"- {tag}: {count}")
    pages.append(
        GlobalWikiPage(
            slug="overview",
            page_type="overview",
            title="Global Knowledge Base Overview",
            content="\n".join(overview_lines).strip() + "\n",
            collection="",
            tags=[],
            source_refs=[],
        )
    )

    for collection, items in sorted(collection_groups.items(), key=lambda item: item[0]):
        local_tag_counter = Counter(tag for document in items for tag in document.tags)
        lines = [f"# Collection: {collection}", "", "## Summary"]
        lines.append(f"- document_count: {len(items)}")
        lines.append(f"- source_types: {dict(Counter(document.source_type for document in items))}")
        lines.append("")
        lines.append("## Top Tags")
        if local_tag_counter:
            for tag, count in local_tag_counter.most_common(20):
                lines.append(f"- {tag}: {count}")
        else:
            lines.append("- none")
        lines.append("")
        lines.append("## Representative Documents")
        for document in items[:20]:
            lines.append(f"- {document.title}: {document.source_ref}")
        pages.append(
            GlobalWikiPage(
                slug=f"collections/{sanitize_slug(collection)}",
                page_type="collection",
                title=f"{collection} Collection",
                content="\n".join(lines).strip() + "\n",
                collection=collection,
                tags=list(local_tag_counter.keys())[:20],
                source_refs=[document.source_ref for document in items[:50]],
            )
        )

    for tag, items in sorted(tag_groups.items(), key=lambda item: item[0]):
        lines = [f"# Tag: {tag}", "", "## Summary"]
        lines.append(f"- document_count: {len(items)}")
        lines.append(f"- collections: {dict(Counter(document.collection for document in items))}")
        lines.append("")
        lines.append("## Representative Documents")
        for document in items[:20]:
            lines.append(f"- [{document.collection}] {document.title}")
        pages.append(
            GlobalWikiPage(
                slug=f"tags/{sanitize_slug(tag)}",
                page_type="tag",
                title=f"{tag} Tag",
                content="\n".join(lines).strip() + "\n",
                collection="",
                tags=[tag],
                source_refs=[document.source_ref for document in items[:50]],
            )
        )

    for source_type, items in sorted(source_type_groups.items(), key=lambda item: item[0]):
        lines = [f"# Source Type: {source_type}", "", "## Summary"]
        lines.append(f"- document_count: {len(items)}")
        lines.append(f"- collections: {dict(Counter(document.collection for document in items))}")
        lines.append("")
        lines.append("## Representative Documents")
        for document in items[:20]:
            lines.append(f"- [{document.collection}] {document.title}")
        pages.append(
            GlobalWikiPage(
                slug=f"source_types/{sanitize_slug(source_type)}",
                page_type="source_type",
                title=f"{source_type} Source Type",
                content="\n".join(lines).strip() + "\n",
                collection="",
                tags=[],
                source_refs=[document.source_ref for document in items[:50]],
            )
        )

    return pages


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS global_documents (
            entry_id TEXT PRIMARY KEY,
            collection_name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            source_path TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            vector_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS global_wiki_pages (
            slug TEXT PRIMARY KEY,
            page_type TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            collection_name TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            source_refs_json TEXT NOT NULL,
            vector_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_global_documents_collection ON global_documents(collection_name);
        CREATE INDEX IF NOT EXISTS idx_global_documents_source_type ON global_documents(source_type);
        CREATE INDEX IF NOT EXISTS idx_global_wiki_pages_collection ON global_wiki_pages(collection_name);
        CREATE INDEX IF NOT EXISTS idx_global_wiki_pages_page_type ON global_wiki_pages(page_type);
        """
    )


def build_global_knowledge_base(
    *,
    output_dir: str | Path,
    source_paths: Sequence[str] | None = None,
    manifest_path: str | Path | None = None,
    default_collection: str = DEFAULT_COLLECTION,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    vector_dim: int = DEFAULT_VECTOR_DIM,
) -> Dict[str, Any]:
    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    wiki_dir = output_path / GLOBAL_WIKI_DIR_NAME
    wiki_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_path / GLOBAL_KNOWLEDGE_DB_NAME

    source_specs, manifest_meta = _build_source_specs(
        source_paths=source_paths,
        manifest_path=manifest_path,
        default_collection=default_collection,
    )
    base_dir = Path(manifest_path).expanduser().resolve().parent if manifest_path else Path.cwd()
    documents, source_summary = _collect_documents(
        source_specs=source_specs,
        base_dir=base_dir,
        chunk_chars=chunk_chars,
        chunk_overlap=chunk_overlap,
    )
    wiki_pages = _build_wiki_pages(documents)

    timestamp = _now_iso()
    with sqlite3.connect(db_path) as connection:
        _ensure_schema(connection)
        connection.execute("DELETE FROM global_documents")
        connection.execute("DELETE FROM global_wiki_pages")
        connection.executemany(
            """
            INSERT INTO global_documents (
                entry_id, collection_name, source_type, title, content, source_path,
                source_ref, tags_json, metadata_json, vector_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    document.entry_id,
                    document.collection,
                    document.source_type,
                    document.title,
                    document.content,
                    document.source_path,
                    document.source_ref,
                    _json_dumps(document.tags),
                    _json_dumps(document.metadata),
                    _json_dumps(build_hashed_embedding(f"{document.title}\n{document.content}", dim=vector_dim)),
                    timestamp,
                )
                for document in documents
            ],
        )
        connection.executemany(
            """
            INSERT INTO global_wiki_pages (
                slug, page_type, title, content, collection_name, tags_json, source_refs_json, vector_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    page.slug,
                    page.page_type,
                    page.title,
                    page.content,
                    page.collection,
                    _json_dumps(page.tags),
                    _json_dumps(page.source_refs),
                    _json_dumps(build_hashed_embedding(f"{page.title}\n{page.content}", dim=vector_dim)),
                    timestamp,
                )
                for page in wiki_pages
            ],
        )
        connection.commit()

    for page in wiki_pages:
        page_path = wiki_dir / f"{page.slug}.md"
        write_text(page_path, page.content)

    summary = {
        "status": "completed",
        "generated_at": timestamp,
        "knowledge_db_path": str(db_path),
        "wiki_dir": str(wiki_dir),
        "document_count": len(documents),
        "wiki_page_count": len(wiki_pages),
        "collections": dict(Counter(document.collection for document in documents)),
        "source_types": dict(Counter(document.source_type for document in documents)),
        "manifest": manifest_meta,
        "source_summary": source_summary,
        "chunk_chars": int(chunk_chars),
        "chunk_overlap": int(chunk_overlap),
        "vector_dim": int(vector_dim),
    }
    write_json(output_path / GLOBAL_INGEST_SUMMARY_NAME, summary)
    return summary


def _load_documents(connection: sqlite3.Connection) -> List[Dict[str, Any]]:
    return [
        {
            "entry_id": row[0],
            "collection": row[1],
            "source_type": row[2],
            "title": row[3],
            "content": row[4],
            "source_path": row[5],
            "source_ref": row[6],
            "tags": json.loads(row[7]),
            "metadata": json.loads(row[8]),
            "vector": json.loads(row[9]),
        }
        for row in connection.execute(
            """
            SELECT entry_id, collection_name, source_type, title, content, source_path,
                   source_ref, tags_json, metadata_json, vector_json
            FROM global_documents
            """
        ).fetchall()
    ]


def _load_wiki_pages(connection: sqlite3.Connection) -> List[Dict[str, Any]]:
    return [
        {
            "slug": row[0],
            "page_type": row[1],
            "title": row[2],
            "content": row[3],
            "collection": row[4],
            "tags": json.loads(row[5]),
            "source_refs": json.loads(row[6]),
            "vector": json.loads(row[7]),
        }
        for row in connection.execute(
            """
            SELECT slug, page_type, title, content, collection_name, tags_json, source_refs_json, vector_json
            FROM global_wiki_pages
            """
        ).fetchall()
    ]


def _score_query_hit(
    *,
    query_vector: Sequence[float],
    query_terms: Sequence[str],
    title: str,
    content: str,
    vector: Sequence[float],
    collection: str,
    collection_filters: Sequence[str],
    tags: Sequence[str],
    tag_filters: Sequence[str],
) -> float:
    score = cosine_similarity(query_vector, vector)
    haystack = f"{title}\n{content}".lower()
    token_hits = sum(1 for term in query_terms if term and term in haystack)
    if query_terms:
        score += min(0.4, token_hits * 0.03)
    if collection_filters and collection in set(collection_filters):
        score += 0.12
    if tag_filters:
        matched_tags = len(set(tags).intersection(set(tag_filters)))
        score += matched_tags * 0.06
    return score


def _shorten(text: str, *, max_chars: int = 280) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[: max_chars - 1].rstrip()}…"


def query_global_knowledge_base(
    *,
    knowledge_base_path: str | Path,
    query_text: str,
    collections: Sequence[str] | None = None,
    tags: Sequence[str] | None = None,
    top_k: int = DEFAULT_TOP_K,
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> Dict[str, Any]:
    db_path = Path(knowledge_base_path).expanduser().resolve()
    if db_path.is_dir():
        db_path = db_path / GLOBAL_KNOWLEDGE_DB_NAME
    if not db_path.exists():
        raise FileNotFoundError(f"未找到全局知识库数据库：{db_path}")

    normalized_collections = _normalize_tags(collections or [])
    normalized_tags = _normalize_tags(tags or [])
    query_vector = build_hashed_embedding(query_text)
    query_terms = [term.lower() for term in re.findall(r"[A-Za-z0-9_.:-]+|[\u4e00-\u9fff]{1,8}", str(query_text or ""))]

    with sqlite3.connect(db_path) as connection:
        documents = _load_documents(connection)
        wiki_pages = _load_wiki_pages(connection)

    scored_documents: List[Dict[str, Any]] = []
    for document in documents:
        if normalized_collections and document["collection"] not in normalized_collections:
            continue
        if normalized_tags and not set(document["tags"]).intersection(normalized_tags):
            continue
        score = _score_query_hit(
            query_vector=query_vector,
            query_terms=query_terms,
            title=document["title"],
            content=document["content"],
            vector=document["vector"],
            collection=document["collection"],
            collection_filters=normalized_collections,
            tags=document["tags"],
            tag_filters=normalized_tags,
        )
        scored_documents.append(
            {
                "score": round(score, 4),
                "entry_id": document["entry_id"],
                "collection": document["collection"],
                "source_type": document["source_type"],
                "title": document["title"],
                "source_path": document["source_path"],
                "source_ref": document["source_ref"],
                "tags": document["tags"],
                "excerpt": _shorten(document["content"], max_chars=260),
                "metadata": document["metadata"],
            }
        )

    scored_wiki_pages: List[Dict[str, Any]] = []
    for page in wiki_pages:
        if normalized_collections and page["collection"] and page["collection"] not in normalized_collections:
            continue
        if normalized_tags and page["tags"] and not set(page["tags"]).intersection(normalized_tags):
            continue
        score = _score_query_hit(
            query_vector=query_vector,
            query_terms=query_terms,
            title=page["title"],
            content=page["content"],
            vector=page["vector"],
            collection=page["collection"],
            collection_filters=normalized_collections,
            tags=page["tags"],
            tag_filters=normalized_tags,
        )
        scored_wiki_pages.append(
            {
                "score": round(score, 4),
                "slug": page["slug"],
                "page_type": page["page_type"],
                "title": page["title"],
                "collection": page["collection"],
                "tags": page["tags"],
                "source_refs": page["source_refs"],
                "excerpt": _shorten(page["content"], max_chars=260),
            }
        )

    scored_documents.sort(key=lambda item: item["score"], reverse=True)
    scored_wiki_pages.sort(key=lambda item: item["score"], reverse=True)

    selected_documents: List[Dict[str, Any]] = []
    used_chars = 0
    for item in scored_documents:
        candidate_size = len(item["excerpt"])
        if selected_documents and used_chars + candidate_size > max_context_chars:
            break
        selected_documents.append(item)
        used_chars += candidate_size
        if len(selected_documents) >= max(1, int(top_k)):
            break

    selected_pages: List[Dict[str, Any]] = []
    for item in scored_wiki_pages[:4]:
        selected_pages.append(item)

    result = {
        "status": "completed",
        "generated_at": _now_iso(),
        "knowledge_db_path": str(db_path),
        "query_text": query_text,
        "collections": normalized_collections,
        "tags": normalized_tags,
        "top_k": max(1, int(top_k)),
        "retrieved_documents": selected_documents,
        "retrieved_wiki_pages": selected_pages,
    }
    write_json(db_path.parent / GLOBAL_QUERY_RESULT_NAME, result)
    return result
