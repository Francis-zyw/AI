#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构件类型-属性库工具对外接口。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

try:
    from .convert_excel_to_jsonl import excel_to_jsonl, save_components
    from .paths import get_component_library_jsonl, get_component_source_dir
except ImportError:
    from convert_excel_to_jsonl import excel_to_jsonl, save_components
    from paths import get_component_library_jsonl, get_component_source_dir


def build_component_library(
    source_dir: Optional[str | Path] = None,
    output_file: Optional[str | Path] = None,
) -> List[dict]:
    """从 Excel 源目录构建构件类型-属性库。"""
    resolved_source = Path(source_dir) if source_dir else get_component_source_dir()
    resolved_output = Path(output_file) if output_file else get_component_library_jsonl()
    return excel_to_jsonl(str(resolved_source), str(resolved_output))


def write_component_library(
    components: List[dict],
    output_file: Optional[str | Path] = None,
) -> tuple[Path, Path]:
    """将构件库对象直接写回主流程输入目录。"""
    resolved_output = Path(output_file) if output_file else get_component_library_jsonl()
    return save_components(components, resolved_output)
