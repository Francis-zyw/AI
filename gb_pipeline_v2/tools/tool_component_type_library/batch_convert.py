#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量转换脚本 - 将文件夹下的所有 Excel 文件转换为 JSON/JSONL
"""

import sys
from pathlib import Path

try:
    from .convert_excel_to_jsonl import excel_to_jsonl
    from .paths import get_component_library_jsonl, get_component_source_dir
except ImportError:
    from convert_excel_to_jsonl import excel_to_jsonl
    from paths import get_component_library_jsonl, get_component_source_dir


def has_excel_files(folder: Path) -> bool:
    """检查目录下是否存在 Excel 文件。"""
    return any(folder.glob("*.xls")) or any(folder.glob("*.xlsx")) or any(folder.glob("*.xlsm"))


def resolve_source_dir(script_dir: Path, cli_arg: str = "") -> Path:
    """优先使用命令行参数，否则自动选择最可能的数据目录。"""
    if cli_arg:
        return Path(cli_arg)

    candidates = [
        get_component_source_dir(),
        script_dir / "upload",
        script_dir,
    ]

    for candidate in candidates:
        if candidate.exists() and candidate.is_dir() and has_excel_files(candidate):
            return candidate

    return script_dir / "upload"


if __name__ == '__main__':
    script_dir = Path(__file__).parent

    source_dir = resolve_source_dir(script_dir, sys.argv[1] if len(sys.argv) > 1 else "")
    output_file = Path(sys.argv[2]) if len(sys.argv) > 2 else get_component_library_jsonl()

    if not source_dir.exists():
        print(f"错误: 未找到源目录: {source_dir}")
        print("请传入包含 Excel 文件的目录，或将数据放到 data/input/component_type_attribute_excels 目录中")
        sys.exit(1)

    print("=" * 60)
    print("批量转换 Excel 文件到规则数据")
    print("=" * 60)
    print(f"源目录: {source_dir}")
    print(f"输出文件: {output_file}")
    print()

    excel_to_jsonl(str(source_dir), str(output_file))

    print()
    print("=" * 60)
    print("转换完成！")
    print(f"数据文件: {output_file}")
    print(f"配套JSON: {output_file.with_suffix('.json')}")
    print("=" * 60)
