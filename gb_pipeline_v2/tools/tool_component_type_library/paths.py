#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构件类型-属性库工具的统一路径定义。
"""

from __future__ import annotations

from pathlib import Path


def get_project_root() -> Path:
    """返回项目根目录。"""
    return Path(__file__).resolve().parents[2]


def get_input_dir() -> Path:
    """返回主流程统一输入目录。"""
    path = get_project_root() / "data" / "input"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_component_library_jsonl() -> Path:
    """返回构件类型-属性库 JSONL 路径。"""
    return get_input_dir() / "components.jsonl"


def get_component_library_json() -> Path:
    """返回构件类型-属性库 JSON 路径。"""
    return get_component_library_jsonl().with_suffix(".json")


def get_component_source_dir() -> Path:
    """返回构件类型源 Excel 默认目录。"""
    path = get_input_dir() / "component_type_attribute_excels"
    path.mkdir(parents=True, exist_ok=True)
    return path
