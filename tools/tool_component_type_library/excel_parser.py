#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
共享的 Excel 解析模块。

兼容两类工作簿：
1. 旧版规范：属性 / 计算项目 / 核心项目
2. 当前提量数据：属性 / 计算项目 / 项目特征
"""

from __future__ import annotations

import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Dict, List, Optional, Union

import pandas as pd

ExcelSource = Union[str, Path, BinaryIO]


SHEET_TYPE_MAPPING = {
    "attributes": [
        "属性",
        "attributes",
        "attr",
        "property",
        "properties",
        "属性列表",
        "项目特征",
        "特征",
        "feature",
        "features",
    ],
    "calculations": ["计算", "calculations", "calc", "计算项目", "计算公式", "工程量"],
    "core_params": ["核心", "core", "coreparams", "核心项目", "核心参数", "参数"],
}

TEXT_NAME_HINTS = (
    "类型",
    "类别",
    "做法",
    "备注",
    "状态",
    "方式",
    "节点",
    "名称",
    "楼层",
    "区域",
    "编号",
    "标号",
    "钢筋",
    "模板",
    "规则",
    "砼",
    "抗震",
)

NUMBER_NAME_HINTS = (
    "宽",
    "高",
    "厚",
    "长",
    "径",
    "半径",
    "直径",
    "面积",
    "体积",
    "周长",
    "数量",
    "长度",
    "高度",
    "厚度",
    "标高",
    "坡度",
    "角度",
    "距离",
    "重量",
    "质量",
    "容重",
)


def detect_sheet_type(sheet_name: str) -> Optional[str]:
    """根据 Sheet 名称自动识别类型。"""
    sheet_lower = str(sheet_name).strip().lower()

    for sheet_type, keywords in SHEET_TYPE_MAPPING.items():
        for keyword in keywords:
            if keyword.lower() in sheet_lower:
                return sheet_type

    return None


def import_excel_file(file: ExcelSource, sheet_types: Optional[Dict[str, Optional[str]]] = None) -> Optional[Dict]:
    """从 Excel 文件导入构件类型。"""
    try:
        excel_file = _open_excel_file(file)
        component_name = Path(_get_source_name(file)).stem

        properties = {"attributes": [], "calculations": [], "core_params": []}
        parsed_sheets: List[tuple[str, pd.DataFrame, Optional[str]]] = []

        for sheet_name in excel_file.sheet_names:
            selected_type = None
            if sheet_types and sheet_name in sheet_types:
                selected_type = sheet_types[sheet_name]
                if not selected_type:
                    continue

            df = excel_file.parse(sheet_name=sheet_name)
            if _is_empty_sheet(df):
                continue

            detected_type = selected_type or detect_sheet_type(sheet_name)
            parsed_sheets.append((sheet_name, df, detected_type))

        calculation_unit_map: Dict[str, str] = {}
        for sheet_name, df, detected_type in parsed_sheets:
            sheet_kind = _classify_sheet(sheet_name, df, detected_type)
            if sheet_kind == "calculations":
                calculation_unit_map.update(_build_calculation_unit_map(df))

        for sheet_name, df, detected_type in parsed_sheets:
            sheet_kind = _classify_sheet(sheet_name, df, detected_type)

            if sheet_kind == "feature_attributes":
                properties["attributes"].extend(
                    _parse_feature_sheet(df, sheet_name, calculation_unit_map)
                )
            elif sheet_kind == "legacy_attributes":
                properties["attributes"].extend(
                    _parse_attribute_sheet(df, sheet_name, calculation_unit_map)
                )
            elif sheet_kind == "calculations":
                properties["calculations"].extend(_parse_calculation_sheet(df, sheet_name))
            elif sheet_kind in {"property_defaults", "legacy_core_params"}:
                properties["core_params"].extend(
                    _parse_core_param_sheet(df, sheet_name, calculation_unit_map)
                )

        for key in properties:
            properties[key] = _dedupe_items(properties[key])

        now = datetime.now().isoformat()
        return {
            "component_type": component_name,
            "properties": properties,
            "source_file": Path(_get_source_name(file)).name,
            "created_at": now,
            "updated_at": now,
        }

    except Exception as exc:
        print(f"导入失败 {_get_source_name(file)}: {exc}")
        return None


def _open_excel_file(file: ExcelSource) -> pd.ExcelFile:
    engine = _detect_excel_engine(file)
    kwargs = {"engine": engine} if engine else {}
    _rewind_file(file)
    return pd.ExcelFile(file, **kwargs)


def _detect_excel_engine(file: ExcelSource) -> Optional[str]:
    try:
        if isinstance(file, (str, Path)):
            return "openpyxl" if zipfile.is_zipfile(file) else None

        if hasattr(file, "read") and hasattr(file, "seek"):
            position = file.tell()
            header = file.read(4)
            file.seek(position)
            if header.startswith(b"PK"):
                return "openpyxl"
    except Exception:
        return None

    return None


def _get_source_name(file: ExcelSource) -> str:
    if isinstance(file, Path):
        return str(file)
    if isinstance(file, str):
        return file
    return getattr(file, "name", "uploaded.xlsx")


def _rewind_file(file: ExcelSource) -> None:
    if hasattr(file, "seek"):
        try:
            file.seek(0)
        except Exception:
            pass


def _is_empty_sheet(df: pd.DataFrame) -> bool:
    if df is None or df.empty:
        return True

    trimmed = df.dropna(how="all")
    return trimmed.empty


def _classify_sheet(sheet_name: str, df: pd.DataFrame, detected_type: Optional[str]) -> Optional[str]:
    columns = {str(column).strip() for column in df.columns}

    if {"名称", "CODE", "下拉"}.issubset(columns):
        return "feature_attributes"

    if {"名称", "CODE", "属性值"}.issubset(columns):
        return "property_defaults"

    if detected_type == "calculations":
        return "calculations"

    if detected_type == "core_params":
        return "legacy_core_params"

    if detected_type == "attributes":
        return "legacy_attributes"

    if {"名称", "CODE"}.issubset(columns) and (
        {"单位", "计量单位", "unit"} & columns
        or {"计算表达式", "表达式", "formula", "公式"} & columns
    ):
        return "calculations"

    return None


def _build_calculation_unit_map(df: pd.DataFrame) -> Dict[str, str]:
    unit_map: Dict[str, str] = {}

    for _, row in df.iterrows():
        code = _normalize_code(row.get("CODE"))
        unit = _first_text(row, ["单位", "unit", "计量单位"])
        if code and unit:
            unit_map[code] = unit

    return unit_map


def _parse_feature_sheet(
    df: pd.DataFrame, sheet_name: str, calculation_unit_map: Dict[str, str]
) -> List[Dict]:
    attributes: List[Dict] = []

    for _, row in df.iterrows():
        name = _normalize_text(row.get("名称"))
        code = _normalize_code(row.get("CODE"))

        if not name and not code:
            continue

        values = _split_values(row.get("下拉"))
        data_type = _infer_data_type(
            name=name,
            values=values,
            linked_unit=calculation_unit_map.get(code, ""),
        )

        attributes.append(
            {
                "name": name,
                "code": code,
                "data_type": data_type,
                "values": values,
                "source_sheet": sheet_name,
            }
        )

    return attributes


def _parse_attribute_sheet(
    df: pd.DataFrame, sheet_name: str, calculation_unit_map: Dict[str, str]
) -> List[Dict]:
    attributes: List[Dict] = []

    for _, row in df.iterrows():
        name = _normalize_text(row.get("名称"))
        code = _normalize_code(row.get("CODE"))

        if not name and not code:
            continue

        data_type = _normalize_text(row.get("数据类型")).lower()
        if data_type not in {"text", "number"}:
            data_type = _infer_data_type(
                name=name,
                values=_split_values(_first_text(row, ["可选值", "下拉", "values", "值"])),
                linked_unit=calculation_unit_map.get(code, ""),
            )

        values = _split_values(_first_text(row, ["可选值", "下拉", "values", "值"]))

        attributes.append(
            {
                "name": name,
                "code": code,
                "data_type": data_type,
                "values": values,
                "source_sheet": sheet_name,
            }
        )

    return attributes


def _parse_calculation_sheet(df: pd.DataFrame, sheet_name: str) -> List[Dict]:
    calculations: List[Dict] = []

    for _, row in df.iterrows():
        name = _normalize_text(row.get("名称"))
        code = _normalize_code(row.get("CODE"))

        if not name and not code:
            continue

        calculations.append(
            {
                "name": name,
                "code": code,
                "expression": _first_text(row, ["计算表达式", "表达式", "formula", "公式"]),
                "unit": _first_text(row, ["单位", "unit", "计量单位"]),
                "source_sheet": sheet_name,
            }
        )

    return calculations


def _parse_core_param_sheet(
    df: pd.DataFrame, sheet_name: str, calculation_unit_map: Dict[str, str]
) -> List[Dict]:
    core_params: List[Dict] = []

    for _, row in df.iterrows():
        name = _normalize_text(row.get("名称"))
        code = _normalize_code(row.get("CODE"))

        if not name and not code:
            continue

        value = _first_text(row, ["属性值", "默认值", "value", "数值", "值"])
        data_type = _normalize_text(row.get("数据类型")).lower()
        if data_type not in {"text", "number"}:
            data_type = _infer_data_type(
                name=name,
                sample_value=value,
                linked_unit=calculation_unit_map.get(code, ""),
            )

        core_params.append(
            {
                "name": name,
                "code": code,
                "data_type": data_type,
                "value": value,
                "source_sheet": sheet_name,
            }
        )

    return core_params


def _normalize_text(value) -> str:
    if value is None or pd.isna(value):
        return ""

    if isinstance(value, int):
        return str(value)

    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value}".rstrip("0").rstrip(".")

    return str(value).strip()


def _normalize_code(value) -> str:
    return _normalize_text(value).upper()


def _first_text(row: pd.Series, column_names: List[str]) -> str:
    for column_name in column_names:
        if column_name in row and pd.notna(row.get(column_name)):
            text = _normalize_text(row.get(column_name))
            if text:
                return text
    return ""


def _split_values(raw_value) -> List[str]:
    text = _normalize_text(raw_value)
    if not text:
        return []

    parts = re.split(r"[\r\n、,，|;；]+", text)
    values: List[str] = []
    seen = set()

    for part in parts:
        item = part.strip()
        if item and item not in seen:
            seen.add(item)
            values.append(item)

    return values


def _dedupe_items(items: List[Dict]) -> List[Dict]:
    result: List[Dict] = []
    index_by_key: Dict[str, int] = {}

    for item in items:
        key = item.get("code") or f"name:{item.get('name', '')}"
        if key in index_by_key:
            result[index_by_key[key]] = item
        else:
            index_by_key[key] = len(result)
            result.append(item)

    return result


def _infer_data_type(
    name: str,
    sample_value: str = "",
    values: Optional[List[str]] = None,
    linked_unit: str = "",
) -> str:
    cleaned_values = [value for value in (values or []) if value]
    if cleaned_values:
        return "number" if all(_looks_numeric(value) for value in cleaned_values) else "text"

    if sample_value and _looks_numeric(sample_value):
        return "number"

    if any(hint in name for hint in TEXT_NAME_HINTS):
        return "text"

    if linked_unit:
        return "number"

    if any(hint in name for hint in NUMBER_NAME_HINTS):
        return "number"

    return "text"


def _looks_numeric(value: str) -> bool:
    normalized = _normalize_text(value)
    if not normalized:
        return False

    return bool(re.fullmatch(r"[+-]?\d+(?:\.\d+)?", normalized))
