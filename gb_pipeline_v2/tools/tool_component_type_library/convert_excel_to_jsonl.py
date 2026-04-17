#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构件类型 Excel 转 JSON/JSONL 转换脚本。
"""

import json
import sys
from pathlib import Path
from typing import List, Optional

try:
    from .excel_parser import import_excel_file
    from .paths import get_component_library_jsonl
except ImportError:
    from excel_parser import import_excel_file
    from paths import get_component_library_jsonl


def save_components(components: List[dict], output_file: Path) -> tuple[Path, Path]:
    """同时输出 JSONL 和 JSON 两份文件。"""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    json_file = output_file.with_suffix(".json")

    with open(output_file, "w", encoding="utf-8") as handle:
        for component in components:
            handle.write(json.dumps(component, ensure_ascii=False) + "\n")

    with open(json_file, "w", encoding="utf-8") as handle:
        json.dump(components, handle, ensure_ascii=False, indent=2)

    return output_file, json_file


def excel_to_jsonl(excel_dir: str, output_file: Optional[str] = None) -> List[dict]:
    """
    将目录下的所有 Excel 文件转换为 JSONL 格式，并同步输出 JSON。
    """
    source_dir = Path(excel_dir)
    if output_file is None:
        output_path = get_component_library_jsonl()
    else:
        output_path = Path(output_file)

    excel_files = []
    for pattern in ("*.xls", "*.xlsx", "*.xlsm"):
        excel_files.extend(source_dir.glob(pattern))
    excel_files = sorted(excel_files)

    if not excel_files:
        print(f"警告: 在 {source_dir} 中未找到 Excel 文件")
        return []

    print(f"找到 {len(excel_files)} 个 Excel 文件")

    components: List[dict] = []
    for excel_file in excel_files:
        component = import_excel_file(excel_file)
        if not component:
            print(f"✗ 转换失败: {excel_file.name}")
            continue

        components.append(component)
        print(f"✓ 已转换: {excel_file.name}")
        print(f"  - 项目特征/属性: {len(component['properties']['attributes'])}")
        print(f"  - 计算项目: {len(component['properties']['calculations'])}")
        print(f"  - 属性默认值/核心参数: {len(component['properties']['core_params'])}")

    jsonl_file, json_file = save_components(components, output_path)

    print(f"\n✓ 转换完成！共 {len(components)} 个构件类型")
    print(f"JSONL 文件: {jsonl_file}")
    print(f"JSON 文件: {json_file}")

    return components


if __name__ == "__main__":
    if len(sys.argv) < 2:
        try:
            from .paths import get_component_source_dir
        except ImportError:
            from paths import get_component_source_dir

        default_dir = get_component_source_dir()
        print("用法: python convert_excel_to_jsonl.py <Excel目录> [输出JSONL文件]")
        print(f"示例: python convert_excel_to_jsonl.py {default_dir}")
        sys.exit(1)

    source_dir = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    excel_to_jsonl(source_dir, output_path)
