from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional


@dataclass
class OutlineEntry:
    index: int
    level: int
    title: str
    pdf_page: int
    category: str
    parent_index: Optional[int] = None
    parent_title: Optional[str] = None
    body_page: Optional[int] = None

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class RegionResult:
    index: int
    outline_index: int
    level: int
    title: str
    path: List[str]
    path_text: str
    parent_index: Optional[int]
    parent_title: Optional[str]
    pdf_page_start: int
    pdf_page_end: int
    body_page_start: Optional[int]
    body_page_end: Optional[int]
    text_source: str
    start_anchor_found: bool
    end_anchor_found: bool
    text_length: int
    output_file: Optional[str]
    table_count: int
    table_row_count: int
    non_table_text: str
    text: str
    tables: List[TableBlock] = field(default_factory=list)
    content_blocks: List[ContentBlock] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "index": self.index,
            "outline_index": self.outline_index,
            "level": self.level,
            "title": self.title,
            "path": list(self.path),
            "path_text": self.path_text,
            "parent_index": self.parent_index,
            "parent_title": self.parent_title,
            "pdf_page_start": self.pdf_page_start,
            "pdf_page_end": self.pdf_page_end,
            "body_page_start": self.body_page_start,
            "body_page_end": self.body_page_end,
            "text_source": self.text_source,
            "start_anchor_found": self.start_anchor_found,
            "end_anchor_found": self.end_anchor_found,
            "text_length": self.text_length,
            "output_file": self.output_file,
            "table_count": self.table_count,
            "table_row_count": self.table_row_count,
            "non_table_text": self.non_table_text,
            "text": self.text,
            "tables": [table.to_dict() for table in self.tables],
            "content_blocks": [block.to_dict() for block in self.content_blocks],
        }


@dataclass
class RegionNode:
    region: RegionResult
    children: List["RegionNode"] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "region": self.region.to_dict(),
            "children": [child.to_dict() for child in self.children],
        }


@dataclass
class TableRow:
    row_index: int
    project_code: str
    project_name: str
    project_features: str
    measurement_unit: str
    quantity_rule: str
    work_content: str
    raw_columns: Dict[str, str] = field(default_factory=dict)
    raw_lines: List[str] = field(default_factory=list)
    raw_line_cells: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "row_index": self.row_index,
            "project_code": self.project_code,
            "project_name": self.project_name,
            "project_features": self.project_features,
            "measurement_unit": self.measurement_unit,
            "quantity_rule": self.quantity_rule,
            "work_content": self.work_content,
        }


@dataclass
class TableBlock:
    table_index: int
    title: str
    headers: List[str]
    row_count: int
    raw_text: str
    rows: List[TableRow] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "table_index": self.table_index,
            "title": self.title,
            "headers": list(self.headers),
            "row_count": self.row_count,
            "raw_text": self.raw_text,
            "rows": [row.to_dict() for row in self.rows],
        }


@dataclass
class ContentBlock:
    block_index: int
    block_type: str
    text: str
    table_index: Optional[int] = None

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class CatalogDetection:
    catalog_start_pdf_page: Optional[int]
    catalog_end_pdf_page: Optional[int]
    front_matter_end_pdf_page: Optional[int]
    body_start_pdf_page: Optional[int]

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ExtractionSummary:
    pdf_path: str
    total_pdf_pages: int
    catalog_detection: CatalogDetection
    outline_counts: Dict[str, int]
    region_counts: Dict[str, int]
    table_counts: Dict[str, int]
    providers: List[str] = field(default_factory=list)
    output_dir: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "pdf_path": self.pdf_path,
            "total_pdf_pages": self.total_pdf_pages,
            "catalog_detection": self.catalog_detection.to_dict(),
            "outline_counts": dict(self.outline_counts),
            "region_counts": dict(self.region_counts),
            "table_counts": dict(self.table_counts),
            "providers": list(self.providers),
            "output_dir": self.output_dir,
        }


@dataclass
class ChapterExtractionResult:
    summary: ExtractionSummary
    outline_entries: List[OutlineEntry]
    region_tree: List[RegionNode]
    flat_regions: List[RegionResult]

    def to_dict(self) -> Dict:
        return {
            "summary": self.summary.to_dict(),
            "outline_entries": [item.to_dict() for item in self.outline_entries],
            "region_tree": [item.to_dict() for item in self.region_tree],
            "flat_regions": [item.to_dict() for item in self.flat_regions],
        }
