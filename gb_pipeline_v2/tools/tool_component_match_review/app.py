#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构件匹配结果人工修订工具
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAVE_PATH = PROJECT_ROOT / "data" / "output" / "manual_reviews" / "component_match_review.json"
APP_VERSION = "1.0.0"

ROOT_KEYS = ["mappings", "matches", "匹配结果", "data"]
ARRAY_FIELDS = [
    "source_aliases",
    "standard_aliases",
    "candidate_standard_names",
    "evidence_paths",
    "evidence_texts",
]
TEXT_FIELDS = [
    "source_component_name",
    "selected_standard_name",
    "match_type",
    "match_status",
    "review_status",
    "reasoning",
    "manual_notes",
]
NUMBER_FIELDS = ["confidence"]
BOOLEAN_FIELDS = ["delete_row"]
DEFAULT_COLUMNS = (
    ["source_component_name"]
    + ARRAY_FIELDS[:1]
    + ["selected_standard_name", "standard_aliases", "candidate_standard_names"]
    + ["match_type", "match_status", "confidence", "review_status"]
    + ["evidence_paths", "evidence_texts", "reasoning", "manual_notes", "delete_row"]
)


st.set_page_config(
    page_title="构件匹配结果人工修订工具",
    page_icon="📎",
    layout="wide",
    initial_sidebar_state="expanded",
)


def ensure_session_state() -> None:
    if "meta" not in st.session_state:
        st.session_state.meta = default_meta()
    if "records" not in st.session_state:
        st.session_state.records = []
    if "source_name" not in st.session_state:
        st.session_state.source_name = "未加载数据"
    if "raw_json_text" not in st.session_state:
        st.session_state.raw_json_text = ""
    if "save_path" not in st.session_state:
        st.session_state.save_path = str(DEFAULT_SAVE_PATH)


def default_meta() -> Dict[str, Any]:
    return {
        "task_name": "component_standard_name_matching",
        "standard_document": "",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "review_stage": "manual_review",
    }


def sample_payload() -> Dict[str, Any]:
    return {
        "meta": {
            "task_name": "component_standard_name_matching",
            "standard_document": "房屋建筑与装饰工程工程量计算标准",
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "review_stage": "pre_parse",
        },
        "mappings": [
            {
                "source_component_name": "砼墙",
                "source_aliases": ["砼墙", "混凝土墙"],
                "selected_standard_name": "钢筋混凝土墙",
                "standard_aliases": ["钢筋混凝土墙", "混凝土墙", "现浇混凝土墙"],
                "candidate_standard_names": ["钢筋混凝土墙", "现浇混凝土墙"],
                "match_type": "alias_bridge",
                "match_status": "matched",
                "confidence": 0.93,
                "review_status": "pending",
                "evidence_paths": [
                    "附录G 混凝土及钢筋混凝土工程 > G.2 现浇混凝土墙"
                ],
                "evidence_texts": ["章节中存在高相关名称证据。"],
                "reasoning": "基于行业简称与章节上下文完成匹配。",
                "manual_notes": "",
            }
        ],
    }


def parse_root_payload(payload: Any) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    if isinstance(payload, list):
        return default_meta(), ensure_record_list(payload)

    if not isinstance(payload, dict):
        raise ValueError("JSON 根节点必须是对象或数组。")

    for key in ROOT_KEYS:
        if key in payload:
            meta = payload.get("meta", default_meta())
            return meta, ensure_record_list(payload[key])

    if "source_component_name" in payload:
        return default_meta(), ensure_record_list([payload])

    raise ValueError("未识别到可编辑的记录列表，请使用 `mappings`、`matches`、`匹配结果`、`data` 或直接数组。")


def ensure_record_list(records: Any) -> List[Dict[str, Any]]:
    if not isinstance(records, list):
        raise ValueError("记录列表必须是数组。")

    normalized = []
    for item in records:
        if not isinstance(item, dict):
            raise ValueError("记录列表中的每一项必须是对象。")
        normalized.append(normalize_record(item))
    return normalized


def normalize_array_value(value: Any) -> List[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        lines = []
        for part in value.replace("；", ";").replace("，", ",").splitlines():
            for chunk in part.replace(";", ",").split(","):
                text = chunk.strip()
                if text:
                    lines.append(text)
        return lines
    return [str(value).strip()]


def normalize_record(record: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}

    for field in ARRAY_FIELDS:
        normalized[field] = normalize_array_value(record.get(field))

    for field in TEXT_FIELDS:
        value = record.get(field, "")
        normalized[field] = "" if value is None else str(value)

    confidence = record.get("confidence", "")
    if confidence in (None, ""):
        normalized["confidence"] = ""
    else:
        try:
            normalized["confidence"] = float(confidence)
        except (TypeError, ValueError):
            normalized["confidence"] = ""

    normalized["delete_row"] = bool(record.get("delete_row", False))

    for key, value in record.items():
        if key not in normalized:
            normalized[key] = value

    return normalized


def records_to_dataframe(records: List[Dict[str, Any]]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    extra_keys = sorted(
        {
            key
            for record in records
            for key in record.keys()
            if key not in set(DEFAULT_COLUMNS)
        }
    )
    columns = list(DEFAULT_COLUMNS) + extra_keys

    for record in records:
        row: Dict[str, Any] = {}
        for key in columns:
            value = record.get(key, "")
            if key in ARRAY_FIELDS:
                row[key] = "\n".join(normalize_array_value(value))
            else:
                row[key] = value
        rows.append(row)

    if not rows:
        rows = [{key: "" for key in columns}]
        rows[0]["delete_row"] = False

    return pd.DataFrame(rows, columns=columns)


def dataframe_to_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []

    for row in df.to_dict(orient="records"):
        delete_row = bool(row.get("delete_row", False))
        if delete_row:
            continue

        record: Dict[str, Any] = {}
        for key, value in row.items():
            if key == "delete_row":
                continue
            if key in ARRAY_FIELDS:
                record[key] = normalize_array_value(value)
                continue
            if key == "confidence":
                if value in ("", None):
                    record[key] = ""
                else:
                    try:
                        numeric = float(value)
                    except (TypeError, ValueError):
                        record[key] = ""
                    else:
                        record[key] = max(0.0, min(1.0, numeric))
                continue

            if isinstance(value, float) and pd.isna(value):
                record[key] = ""
            elif value is None:
                record[key] = ""
            else:
                record[key] = str(value).strip() if isinstance(value, str) else value

        if has_meaningful_content(record):
            records.append(record)

    return records


def has_meaningful_content(record: Dict[str, Any]) -> bool:
    for value in record.values():
        if isinstance(value, list) and value:
            return True
        if value not in ("", None, []):
            return True
    return False


def make_payload(meta: Dict[str, Any], records: List[Dict[str, Any]]) -> Dict[str, Any]:
    merged_meta = default_meta()
    merged_meta.update(meta or {})
    merged_meta["generated_at"] = merged_meta.get("generated_at") or datetime.now().astimezone().isoformat(timespec="seconds")
    return {
        "meta": merged_meta,
        "mappings": records,
    }


def load_json_from_text(raw_text: str, source_name: str) -> None:
    payload = json.loads(raw_text)
    meta, records = parse_root_payload(payload)
    st.session_state.meta = meta
    st.session_state.records = records
    st.session_state.raw_json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    st.session_state.source_name = source_name


def relative_display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def resolve_workspace_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def validate_save_path(path: Path) -> None:
    project_root_resolved = PROJECT_ROOT.resolve()
    if project_root_resolved not in path.parents and path != project_root_resolved:
        raise ValueError("仅支持保存到当前工作区内的路径。")


def render_sidebar() -> None:
    st.sidebar.title("修订说明")
    st.sidebar.caption(f"版本 {APP_VERSION}")
    st.sidebar.write("这个工具只做人工补充修订，不参与主分析流程。")

    st.sidebar.subheader("推荐处理顺序")
    st.sidebar.markdown(
        "\n".join(
            [
                "1. 先导入 AI 生成的匹配结果 JSON",
                "2. 再人工修改标准名、别名、状态和备注",
                "3. 最后导出新的 JSON 或保存到工作区",
            ]
        )
    )

    st.sidebar.subheader("重点检查")
    st.sidebar.markdown(
        "\n".join(
            [
                "- `confidence < 0.85`",
                "- `match_status != matched`",
                "- `review_status = pending`",
                "- `selected_standard_name` 为空",
            ]
        )
    )


def render_meta_editor() -> None:
    meta = st.session_state.meta or default_meta()
    st.subheader("元信息")
    col1, col2 = st.columns(2)
    with col1:
        meta["task_name"] = st.text_input("task_name", value=str(meta.get("task_name", "")))
        meta["standard_document"] = st.text_input("standard_document", value=str(meta.get("standard_document", "")))
    with col2:
        meta["review_stage"] = st.text_input("review_stage", value=str(meta.get("review_stage", "")))
        meta["generated_at"] = st.text_input("generated_at", value=str(meta.get("generated_at", "")))
    st.session_state.meta = meta


def render_loader() -> None:
    st.subheader("加载 JSON")
    col1, col2, col3 = st.columns([1.2, 1.2, 1])

    with col1:
        uploaded = st.file_uploader("上传 JSON 文件", type=["json"], accept_multiple_files=False)
        if uploaded is not None:
            raw_text = uploaded.getvalue().decode("utf-8")
            try:
                load_json_from_text(raw_text, f"上传文件: {uploaded.name}")
                st.success("JSON 已加载。")
            except Exception as exc:
                st.error(f"加载失败: {exc}")

    with col2:
        load_path = st.text_input("从工作区路径读取", placeholder="例如: data/output/manual_reviews/example.json")
        if st.button("读取路径中的 JSON", use_container_width=True):
            if not load_path.strip():
                st.warning("请先填写路径。")
            else:
                try:
                    path = resolve_workspace_path(load_path.strip())
                    raw_text = path.read_text(encoding="utf-8")
                    load_json_from_text(raw_text, f"路径文件: {relative_display_path(path)}")
                    st.success(f"已读取 {relative_display_path(path)}")
                except Exception as exc:
                    st.error(f"读取失败: {exc}")

    with col3:
        if st.button("加载示例数据", use_container_width=True):
            payload = sample_payload()
            load_json_from_text(json.dumps(payload, ensure_ascii=False), "示例数据")
            st.success("示例数据已加载。")

    raw_text = st.text_area(
        "或直接粘贴 JSON",
        value=st.session_state.raw_json_text,
        height=220,
        placeholder='{"meta": {...}, "mappings": [...]}',
    )
    if st.button("从文本框加载 JSON", use_container_width=True):
        if not raw_text.strip():
            st.warning("请输入 JSON 文本。")
        else:
            try:
                load_json_from_text(raw_text, "文本输入")
                st.success("JSON 已从文本框加载。")
            except Exception as exc:
                st.error(f"JSON 解析失败: {exc}")


def render_editor() -> Tuple[List[Dict[str, Any]], str]:
    st.subheader("匹配结果编辑")
    st.caption(f"当前数据来源: {st.session_state.source_name}")

    records = st.session_state.records
    df = records_to_dataframe(records)
    edited_df = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "confidence": st.column_config.NumberColumn(
                "confidence",
                min_value=0.0,
                max_value=1.0,
                step=0.01,
                help="置信度范围 0 到 1",
            ),
            "delete_row": st.column_config.CheckboxColumn(
                "delete_row",
                help="勾选后导出时会删除该行",
            ),
        },
    )

    records = dataframe_to_records(edited_df)
    st.session_state.records = records
    payload = make_payload(st.session_state.meta, records)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    return records, json_text


def render_export(records: List[Dict[str, Any]], json_text: str) -> None:
    st.subheader("导出结果")

    col1, col2, col3 = st.columns([1, 1, 1.4])
    with col1:
        st.metric("记录数", len(records))
    with col2:
        pending_count = sum(1 for record in records if str(record.get("review_status", "")) == "pending")
        st.metric("待复核数", pending_count)
    with col3:
        matched_count = sum(1 for record in records if str(record.get("match_status", "")) == "matched")
        st.metric("已匹配数", matched_count)

    st.download_button(
        label="下载修订后的 JSON",
        data=json_text.encode("utf-8"),
        file_name="component_match_review.json",
        mime="application/json",
        use_container_width=True,
    )

    st.session_state.save_path = st.text_input("保存到工作区路径", value=st.session_state.save_path)
    if st.button("保存到工作区文件", use_container_width=True):
        try:
            save_path = resolve_workspace_path(st.session_state.save_path.strip())
            validate_save_path(save_path)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(json_text, encoding="utf-8")
            st.success(f"已保存到 {relative_display_path(save_path)}")
        except Exception as exc:
            st.error(f"保存失败: {exc}")

    st.text_area("导出 JSON 预览", value=json_text, height=360)


def main() -> None:
    ensure_session_state()
    render_sidebar()

    st.title("构件匹配结果人工修订工具")
    st.caption("用于把 AI 预解析得到的构件匹配 JSON 转成可编辑表格，并在人工调整后重新导出为 JSON。")

    render_loader()
    st.divider()
    render_meta_editor()
    st.divider()
    records, json_text = render_editor()
    st.divider()
    render_export(records, json_text)


if __name__ == "__main__":
    main()
