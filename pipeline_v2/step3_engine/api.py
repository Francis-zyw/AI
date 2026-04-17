from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from pipeline_v2.model_runtime import (
    DEFAULT_OPENAI_BASE_URL,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_REASONING_EFFORT,
    load_step_model_config,
    normalize_model_name,
    resolve_provider_env,
)
from pipeline_v2.wiki_retriever import WikiRetriever

from .html_report import build_step3_html_report
from pipeline_v2.step3_component_analysis import build_analysis_html as _build_analysis_html
from pipeline_v2.step3_review_editor import build_review_editor as _build_review_editor

PROMPT_TEMPLATE_NAME = "prompt_template.txt"
DEFAULT_MODEL = DEFAULT_OPENAI_MODEL
DEFAULT_REQUEST_TIMEOUT_SECONDS = 120.0
DEFAULT_CONNECTION_RETRIES = 5
FINAL_JSON_NAME = "project_component_feature_calc_matching_result.json"
FINAL_MARKDOWN_NAME = "project_component_feature_calc_matching_result.md"
LOCAL_JSON_NAME = "local_rule_project_component_feature_calc_result.json"
CHAPTER_RULE_JSON_NAME = "chapter_rule_catalog.json"
CHAPTER_CONTEXT_JSON_NAME = "step1_chapter_contexts.json"
COUNT_UNITS = {"个", "樘", "套", "座", "块", "根", "孔", "件", "处", "项"}
DEFAULT_CONFIG_NAME = "runtime_config.ini"
STEP3_READY_STEP2_STATUSES = {"completed", "completed_from_existing", "partial_from_existing"}


GENERIC_ATTRIBUTE_CODES = {
    "GJLX",
    "GJMC",
    "REGMC",
    "LAYMC",
    "LAYFW",
    "NBZ",
    "BJSGCL",
    "GJZDYZF",
}

GENERIC_ATTRIBUTE_NAME_PARTS = (
    "构件编号",
    "区域名称",
    "楼层名称",
    "楼层范围",
    "备注",
    "是否计算工程量",
    "构件做法",
)

PREFIXES = ("现浇", "预制", "钢筋混凝土", "混凝土", "砼")
SUFFIXES = ("构件", "组件", "单元")

ATTRIBUTE_HINTS = {
    "TLX": ["混凝土种类", "混凝土类型", "砼种类", "砼类型"],
    "TBH": ["混凝土强度等级", "砼强度等级", "强度等级", "砼标号", "混凝土等级", "标号"],
    "NYZTBH": ["混凝土强度等级", "砼强度等级", "强度等级", "砼标号", "混凝土等级", "标号"],
    "YZTBH": ["混凝土强度等级", "砼强度等级", "强度等级", "砼标号", "混凝土等级", "标号"],
    "JDFS": ["浇筑方式", "浇捣方式"],
    "HD": ["墙厚", "厚度", "墙体厚度", "挡墙厚度"],
    "QH": ["墙厚", "厚度", "墙体厚度"],
    "BH": ["板厚", "厚度"],
    "GD": ["高度", "墙高", "柱高", "梁高"],
    "CD": ["长度", "墙长", "梁长", "中心线长度"],
    "JMK": ["截面宽度", "宽度"],
    "JMG": ["截面高度", "高度"],
    "GJLB": ["构件类型", "墙类型", "柱类型", "梁类型", "板类型", "基础类型", "部位", "形式", "类型"],
}

SPECIAL_ITEM_COMPONENTS = {
    "钢筋混凝土墙": ["砼墙", "暗柱", "连梁", "暗梁"],
    "混凝土墙": ["砼墙"],
    "直行墙": ["砼墙"],
    "直形墙": ["砼墙"],
    "基础联系梁": ["基础梁", "基础连梁", "承台梁"],
    "楼梯": ["参数楼梯", "楼梯平面", "直形梯段", "螺旋梯段", "休息平台"],
    "矩形柱": ["柱"],
    "钢筋混凝土柱": ["柱"],
    "混凝土柱": ["柱"],
    # --- 土石方章节常见条目 ---
    "挖单独石方": ["土石方"],
    "挖基坑石方": ["土石方"],
    "挖沟槽石方": ["土石方"],
    "挖冻土": ["土石方"],
    "挖淤泥流砂": ["土石方"],
    "余方弃置": ["土石方"],
    "单独土石方回填": ["土石方", "房心回填", "灰土回填"],
}

# 章节→主构件映射：当匹配全部失败时，按章节归属给出兜底候选
CHAPTER_PRIMARY_COMPONENTS: Dict[str, List[str]] = {
    "附录A 土石方工程": ["土石方", "平整场地", "房心回填"],
    "附录B 地基处理与边坡支护工程": ["灰土回填"],
    "附录C 桩基工程": ["桩基础"],
    "附录D 砌筑工程": ["砖墙"],
    "附录E 混凝土及钢筋混凝土工程": [],
    "附录F 金属结构工程": [],
}

RULE_TRIGGER_KEYWORDS = (
    "项目特征",
    "可描述",
    "列项",
    "应按",
    "按本标准",
    "按本附录",
    "并入",
    "适用于",
    "包括",
    "不增加相应工程量",
    "工程量按",
)

RULE_SCOPE_STOP_WORDS = {
    "本附录",
    "本标准",
    "项目特征",
    "工程量计算规则",
    "工程量",
    "工作内容",
    "项目编码",
    "编码",
    "相关项目",
    "相关",
    "相应",
    "设计要求",
    "设计文件",
    "本附录中",
    "本标准中",
    "项目",
}


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_default_config_path() -> Path:
    return Path(__file__).with_name(DEFAULT_CONFIG_NAME)


def resolve_path_from_config(raw_value: str, config_path: Path, must_exist: bool = True) -> str | None:
    value = os.path.expanduser(os.path.expandvars(str(raw_value or "").strip()))
    if not value:
        return None

    candidate = Path(value)
    if candidate.is_absolute():
        if must_exist and not candidate.exists():
            return None
        return str(candidate)

    for base_dir in (get_project_root(), config_path.parent):
        resolved = (base_dir / candidate).resolve()
        if resolved.exists() or not must_exist:
            return str(resolved)
    return None


def parse_optional_bool(value: str | None) -> bool | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"无法解析布尔配置值：{value}")


def parse_optional_int(value: str | None) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    return int(text)


def load_runtime_config(config_path: str | Path | None) -> Dict[str, Any]:
    if not config_path:
        return {}

    resolved_path = Path(config_path)
    if not resolved_path.exists():
        raise FileNotFoundError(f"未找到 Step 3 配置文件：{resolved_path}")

    parser = configparser.ConfigParser()
    parser.read(resolved_path, encoding="utf-8")

    return {
        "config_path": str(resolved_path),
        "step1_table_regions_path": resolve_path_from_config(
            parser.get("paths", "step1_table_regions", fallback=""),
            resolved_path,
            must_exist=True,
        ),
        "step2_result_path": resolve_path_from_config(
            parser.get("paths", "step2_result", fallback=""),
            resolved_path,
            must_exist=True,
        ),
        "components_path": resolve_path_from_config(
            parser.get("paths", "components", fallback=""),
            resolved_path,
            must_exist=True,
        ),
        "synonym_library_path": resolve_path_from_config(
            parser.get("paths", "synonym_library", fallback=""),
            resolved_path,
            must_exist=True,
        ),
        "output_dir": resolve_path_from_config(
            parser.get("paths", "output", fallback=""),
            resolved_path,
            must_exist=False,
        ),
        "model": str(parser.get("model", "model", fallback="")).strip() or None,
        "reasoning_effort": str(parser.get("model", "reasoning_effort", fallback="")).strip() or None,
        "provider_mode": str(parser.get("model", "provider_mode", fallback="")).strip() or None,
        "api_key_env": str(parser.get("model", "api_key_env", fallback="")).strip() or None,
        "base_url_env": str(parser.get("model", "base_url_env", fallback="")).strip() or None,
        "openai_api_key": str(parser.get("model", "openai_api_key", fallback="")).strip() or None,
        "openai_base_url": str(parser.get("model", "openai_base_url", fallback="")).strip() or None,
        "request_timeout_seconds": float(parser.get("model", "request_timeout_seconds", fallback="") or 0) or None,
        "connection_retries": parse_optional_int(parser.get("model", "connection_retries", fallback="")),
        "max_rows_per_batch": parse_optional_int(parser.get("run", "max_rows_per_batch", fallback="")),
        "max_components_per_item": parse_optional_int(parser.get("run", "max_components_per_item", fallback="")),
        "prepare_only": parse_optional_bool(parser.get("run", "prepare_only", fallback="")),
        "local_only": parse_optional_bool(parser.get("run", "local_only", fallback="")),
    }


def merge_runtime_value(cli_value: Any, config_value: Any, default_value: Any) -> Any:
    if cli_value is not None:
        return cli_value
    if config_value is not None:
        return config_value
    return default_value


def resolve_runtime_options(args: argparse.Namespace) -> Dict[str, Any]:
    explicit_config_path = Path(args.config).expanduser() if args.config else None
    default_config_path = get_default_config_path()

    if explicit_config_path is not None:
        config_values = load_runtime_config(explicit_config_path)
        config_path_text = str(explicit_config_path)
    elif default_config_path.exists():
        config_values = load_runtime_config(default_config_path)
        config_path_text = str(default_config_path)
    else:
        config_values = {}
        config_path_text = ""

    step_model_cfg = load_step_model_config("step3")
    merged_step_model_cfg = dict(step_model_cfg)
    for key in ("provider_mode", "api_key_env", "base_url_env"):
        if not merged_step_model_cfg.get(key) and config_values.get(key):
            merged_step_model_cfg[key] = config_values[key]
    provider_env = resolve_provider_env(merged_step_model_cfg)

    prepare_only = bool(merge_runtime_value(args.prepare_only, config_values.get("prepare_only"), False))
    local_only = bool(merge_runtime_value(args.local_only, config_values.get("local_only"), False))
    if args.prepare_only is True and args.local_only is None:
        local_only = False

    return {
        "config_path": config_path_text,
        "step1_table_regions_path": merge_runtime_value(
            args.step1_table_regions,
            config_values.get("step1_table_regions_path"),
            None,
        ),
        "step2_result_path": merge_runtime_value(
            args.step2_result,
            config_values.get("step2_result_path"),
            None,
        ),
        "components_path": merge_runtime_value(
            args.components,
            config_values.get("components_path"),
            None,
        ),
        "synonym_library_path": merge_runtime_value(
            args.synonym_library,
            config_values.get("synonym_library_path"),
            None,
        ),
        "output_dir": merge_runtime_value(
            args.output,
            config_values.get("output_dir"),
            None,
        ),
        "model": normalize_model_name(
            merge_runtime_value(args.model, step_model_cfg.get("model") or config_values.get("model"), DEFAULT_MODEL),
            DEFAULT_MODEL,
        ),
        "reasoning_effort": merge_runtime_value(
            args.reasoning_effort,
            step_model_cfg.get("reasoning_effort") or config_values.get("reasoning_effort"),
            DEFAULT_REASONING_EFFORT,
        ),
        "request_timeout_seconds": merge_runtime_value(
            getattr(args, "request_timeout_seconds", None),
            config_values.get("request_timeout_seconds"),
            DEFAULT_REQUEST_TIMEOUT_SECONDS,
        ),
        "connection_retries": merge_runtime_value(
            getattr(args, "connection_retries", None),
            config_values.get("connection_retries"),
            DEFAULT_CONNECTION_RETRIES,
        ),
        "max_rows_per_batch": merge_runtime_value(args.max_rows_per_batch, config_values.get("max_rows_per_batch"), 40),
        "max_components_per_item": merge_runtime_value(
            args.max_components_per_item,
            config_values.get("max_components_per_item"),
            3,
        ),
        "prepare_only": prepare_only,
        "local_only": local_only,
        "provider_mode": provider_env.get("provider_mode"),
        "use_codex_subscription": provider_env.get("use_codex_subscription"),
        "openai_api_key": provider_env.get("openai_api_key") or config_values.get("openai_api_key"),
        "openai_base_url": provider_env.get("openai_base_url") or config_values.get("openai_base_url"),
    }


def apply_runtime_environment(runtime_options: Dict[str, Any]) -> Dict[str, str | None]:
    previous = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
        "OPENAI_BASE_URL": os.getenv("OPENAI_BASE_URL"),
    }
    provider_mode = str(runtime_options.get("provider_mode") or "").strip().lower()
    if provider_mode == "codex":
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("OPENAI_BASE_URL", None)
        return previous

    effective_api_key = runtime_options.get("openai_api_key") or os.getenv("OPENAI_API_KEY")
    effective_base_url = runtime_options.get("openai_base_url") or os.getenv("OPENAI_BASE_URL") or DEFAULT_OPENAI_BASE_URL
    if effective_api_key:
        os.environ["OPENAI_API_KEY"] = str(effective_api_key)
    else:
        os.environ.pop("OPENAI_API_KEY", None)
    if effective_base_url:
        os.environ["OPENAI_BASE_URL"] = str(effective_base_url)
    return previous


def restore_runtime_environment(previous: Dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def load_step1_region_payload(step1_table_regions_path: str | Path) -> List[Dict[str, Any]]:
    payload = load_json_or_jsonl(Path(step1_table_regions_path))
    if not isinstance(payload, list):
        raise ValueError("Step 1 的 table_regions.json 必须是数组。")
    return [item for item in payload if isinstance(item, dict)]


def load_json_or_jsonl(path: Path) -> Any:
    if path.suffix.lower() == ".jsonl":
        rows: List[Any] = []
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                text = line.strip()
                if text:
                    rows.append(json.loads(text))
        return rows
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def dedupe_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def normalize_unit(text: str) -> str:
    value = str(text or "").strip()
    replacements = {
        "㎡": "m2",
        "m²": "m2",
        "M2": "m2",
        "M²": "m2",
        "m³": "m3",
        "M3": "m3",
        "M³": "m3",
        "n?": "m3",
        "m?": "m3",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return value


def normalize_text(text: str) -> str:
    value = str(text or "").strip()
    value = value.replace("（", "").replace("）", "").replace("(", "").replace(")", "")
    value = value.replace("、", "").replace("，", "").replace(",", "")
    value = value.replace("：", "").replace(":", "")
    value = value.replace("·", "").replace(" ", "").replace("\n", "")
    value = value.replace("钢筋混凝土", "混凝土")
    value = value.replace("砼", "混凝土")
    value = value.replace("雨蓬", "雨篷")
    value = value.replace("楼梯平面", "楼梯")
    return value


def strip_affixes(text: str) -> str:
    value = str(text or "").strip()
    for prefix in PREFIXES:
        if value.startswith(prefix) and len(value) > len(prefix):
            value = value[len(prefix):]
            break
    for suffix in SUFFIXES:
        if value.endswith(suffix) and len(value) > len(suffix):
            value = value[: -len(suffix)]
            break
    return value.strip()


def normalize_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return dedupe_preserve_order(str(item).strip() for item in value if str(item).strip())
    text = str(value).strip()
    if not text:
        return []
    return dedupe_preserve_order(re.split(r"[、,，;；/\n]+", text))


def chunk_list(items: Sequence[Any], batch_size: int) -> List[List[Any]]:
    if batch_size <= 0:
        return [list(items)]
    return [list(items[index:index + batch_size]) for index in range(0, len(items), batch_size)]


def load_prompt_template() -> str:
    return Path(__file__).with_name(PROMPT_TEMPLATE_NAME).read_text(encoding="utf-8")


def extract_json_text(raw_text: str) -> str:
    stripped = raw_text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    if stripped.startswith("{") or stripped.startswith("["):
        return stripped

    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return stripped[first_brace:last_brace + 1]

    raise ValueError("模型输出中未找到可解析的 JSON 内容。")


def extract_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    response_dict = None
    if hasattr(response, "model_dump"):
        response_dict = response.model_dump()
    elif hasattr(response, "to_dict"):
        response_dict = response.to_dict()

    if not isinstance(response_dict, dict):
        raise RuntimeError("无法从 Responses API 响应中提取文本内容。")

    chunks: List[str] = []
    for output_item in response_dict.get("output", []):
        for content in output_item.get("content", []):
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text)

    if chunks:
        return "\n".join(chunks)

    raise RuntimeError("Responses API 响应中没有可用文本。")


def call_openai_model(
    prompt_text: str,
    model: str,
    reasoning_effort: str | None,
    *,
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    connection_retries: int = DEFAULT_CONNECTION_RETRIES,
    provider_mode: str | None = None,
    output_path: str | Path | None = None,
    log_context: Dict[str, Any] | None = None,
) -> str:
    from pipeline_v2.step2_engine.api import call_openai_model as shared_call_openai_model

    retry_log_path = Path(output_path) / "openai_request_events.jsonl" if output_path else None
    return shared_call_openai_model(
        model=model,
        reasoning_effort=reasoning_effort,
        max_output_tokens=None,
        request_timeout_seconds=request_timeout_seconds,
        connection_retries=connection_retries,
        provider_mode=provider_mode,
        prompt_text=prompt_text,
        instructions_text=None,
        input_items=None,
        phase="pipeline_v2.step3_engine",
        retry_log_path=retry_log_path,
        log_context=log_context,
    )


def get_default_components_path() -> Path:
    root = get_project_root()
    json_path = root / "data" / "input" / "components.json"
    if json_path.exists():
        return json_path
    jsonl_path = root / "data" / "input" / "components.jsonl"
    if jsonl_path.exists():
        return jsonl_path
    raise FileNotFoundError("未找到默认构件库，请检查 data/input/components.json 或 components.jsonl。")


def get_default_step1_table_regions_path() -> Path:
    root = get_project_root()
    candidates = sorted(
        root.glob("data/output/step1/*/table_regions.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("未找到 Step 1 输出，请先生成 data/output/step1/*/table_regions.json。")
    return candidates[0]


def get_default_synonym_library_path(
    standard_document: str | None = None,
    step2_result_path: str | Path | None = None,
) -> Path | None:
    root = get_project_root()

    if step2_result_path:
        sibling = Path(step2_result_path).parent / "synonym_library.json"
        if sibling.exists():
            return sibling

    if standard_document:
        preferred = root / "data" / "output" / "step2" / standard_document / "synonym_library.json"
        if preferred.exists():
            return preferred

    candidates = sorted(
        root.glob("data/output/step2/*/synonym_library.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def ensure_complete_step2_outputs(
    *,
    step2_result_path: str | Path | None,
    synonym_library_path: str | Path | None,
) -> Dict[str, Any]:
    artifact_path = Path(step2_result_path) if step2_result_path else Path(synonym_library_path) if synonym_library_path else None
    if artifact_path is None:
        raise FileNotFoundError("Step 3 需要完整的 Step 2 输出，至少要能定位 synonym_library.json 所在目录。")

    step2_dir = artifact_path.parent
    run_summary_path = step2_dir / "run_summary.json"
    if not run_summary_path.exists():
        raise FileNotFoundError(f"未找到 Step 2 运行摘要：{run_summary_path}")

    run_summary = load_json_or_jsonl(run_summary_path)
    if not isinstance(run_summary, dict):
        raise ValueError(f"Step 2 运行摘要格式不正确：{run_summary_path}")
    step2_status = str(run_summary.get("status", "")).strip()
    if step2_status not in STEP3_READY_STEP2_STATUSES:
        try:
            from pipeline_v2.step2_v2 import synthesize_existing_step2_outputs

            recovered = synthesize_existing_step2_outputs(step2_dir)
            recovered_summary = recovered.get("run_summary", {}) if isinstance(recovered, dict) else {}
            if isinstance(recovered_summary, dict):
                run_summary = recovered_summary
                step2_status = str(run_summary.get("status", "")).strip()
        except Exception as exc:
            raise RuntimeError(
                f"Step 2 尚未完成，当前状态为 {step2_status or 'unknown'}，且自动合成现有结果失败：{exc}"
            ) from exc

    if step2_status not in STEP3_READY_STEP2_STATUSES:
        raise RuntimeError(
            f"Step 2 尚未产出 Step 3 可用结果，当前状态为 {step2_status or 'unknown'}。"
            f" 请先补齐或恢复 {run_summary_path} 所在目录的 Step 2 结果。"
        )

    if step2_result_path and not Path(step2_result_path).exists():
        raise FileNotFoundError(f"未找到 Step 2 主结果：{step2_result_path}")
    if synonym_library_path and not Path(synonym_library_path).exists():
        raise FileNotFoundError(f"未找到 Step 2 同义词库：{synonym_library_path}")

    return run_summary


def get_default_output_dir(step1_table_regions_path: Path) -> Path:
    root = get_project_root()
    return root / "data" / "output" / "step3" / step1_table_regions_path.parent.name


def build_standard_document_name(step1_table_regions_path: Path) -> str:
    """从 catalog_summary.json 的 pdf_path 提取标准文档名；找不到时回退到目录名。"""
    catalog_path = step1_table_regions_path.parent / "catalog_summary.json"
    if catalog_path.exists():
        try:
            import json as _json
            data = _json.loads(catalog_path.read_text(encoding="utf-8"))
            pdf_path = data.get("pdf_path", "")
            if pdf_path:
                stem = Path(pdf_path).stem
                if stem:
                    return stem
        except Exception:
            pass
    return step1_table_regions_path.parent.name


def _generate_tool_htmls(output_path: Path, result_json_path: Path | None = None) -> None:
    """生成分析和审定编辑器 HTML，输出到 tools/tool_step3_review/。

    result_json_path 为 None 时读取 local_rule JSON（本地规则阶段结果）。
    传入 FINAL_JSON_NAME 路径时生成模型完成后的最终版本（覆盖）。
    """
    tools_dir = Path(__file__).parent.parent.parent / "tools" / "tool_step3_review"
    tools_dir.mkdir(parents=True, exist_ok=True)
    if result_json_path is None:
        result_json_path = output_path / LOCAL_JSON_NAME
    if not result_json_path.exists():
        return
    cst_path = output_path / "component_source_table.json"
    try:
        _build_analysis_html(result_json_path, output_path=tools_dir / "step3_component_analysis.html")
    except Exception as exc:
        print(f"[警告] 生成构件分析 HTML 失败: {exc}", file=sys.stderr)
    try:
        _build_review_editor(
            result_json_path,
            cst_path if cst_path.exists() else None,
            output_path=tools_dir / "step3_review_editor.html",
        )
    except Exception as exc:
        print(f"[警告] 生成审定编辑器 HTML 失败: {exc}", file=sys.stderr)


def clean_cell_text(text: str) -> str:
    value = str(text or "")
    value = value.replace("\u3000", " ")
    value = value.replace("•", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n+", "\n", value)
    return value.strip()


def clean_project_name(text: str) -> str:
    value = clean_cell_text(text)
    value = value.replace("\n", "")
    return value


def clean_multiline_text(text: str) -> str:
    value = clean_cell_text(text)
    lines = [line.strip(" .。；;：:") for line in value.splitlines() if line.strip(" .。；;：:")]
    return "\n".join(lines)


def clean_feature_text(text: str) -> str:
    value = clean_multiline_text(text)
    if not value:
        return ""

    normalized_lines: List[str] = []
    for raw_line in value.splitlines():
        line = raw_line.replace("．", ".").replace("、", ".").replace("：", ":").strip()
        line = re.sub(r"^(\d+)\s*-\s*", r"\1.", line)
        line = re.sub(r"^(\d+)\s*\.\s*", r"\1.", line)
        line = re.sub(r"^(\d+)\s+", r"\1.", line)
        if line.isdigit() and normalized_lines:
            previous = normalized_lines.pop()
            normalized_lines.append(f"{line}.{previous.lstrip('.。')}")
            continue
        normalized_lines.append(line)
    return "\n".join(normalized_lines)


def clean_rule_text(text: str) -> str:
    return clean_multiline_text(text)


def canonicalize_table_title(title: str) -> str:
    value = clean_cell_text(title)
    value = value.replace("续表", "表")
    value = re.sub(r"\s+", "", value)
    return value


def infer_row_family_from_name(name: str) -> str:
    text = f"{name}"
    for keyword, family in (
        ("模板", "模板"),
        ("墙", "墙"),
        ("梁", "梁"),
        ("柱", "柱"),
        ("板", "板"),
        ("楼梯", "楼梯"),
        ("基础", "基础"),
        ("沟", "沟"),
        ("井", "井"),
        ("池", "池"),
        ("土方", "土方"),
        ("石方", "土方"),
        ("冻土", "土方"),
        ("淤泥", "土方"),
        ("回填", "土方"),
        ("场地", "场地"),
        ("钢", "钢构件"),
    ):
        if keyword in text:
            return family
    return "其他"


def split_feature_fragments(text: str) -> List[str]:
    value = clean_feature_text(text)
    if not value:
        return []

    if "\n" in value:
        return [item.strip() for item in value.splitlines() if item.strip()]

    matches = list(re.finditer(r"(\d+)\s*[.\-]\s*(.+?)(?=(?:\s+\d+\s*[.\-])|$)", value))
    if matches:
        return [f"{item.group(1)}.{item.group(2).strip()}" for item in matches]

    return [value]


def parse_feature_entries(text: str) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for index, fragment in enumerate(split_feature_fragments(text), start=1):
        match = re.match(r"^\s*(\d+)\s*[.\-]?\s*(.+?)\s*$", fragment)
        if match:
            order = int(match.group(1))
            raw_text = match.group(2).strip()
        else:
            order = index
            raw_text = fragment.strip()
        if raw_text:
            entries.append({"order": order, "raw_text": raw_text})
    return entries


def format_feature_entries(entries: Sequence[Dict[str, Any]]) -> str:
    lines = []
    for item in sorted(entries, key=lambda entry: entry.get("order", 999)):
        raw_text = str(item.get("raw_text", "")).strip()
        if raw_text:
            lines.append(f"{item.get('order', 0)}.{raw_text}")
    return "\n".join(lines)


def merge_feature_entries(
    current_entries: Sequence[Dict[str, Any]],
    neighbor_entries: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged: Dict[int, Dict[str, Any]] = {}
    for entry in neighbor_entries:
        order = int(entry.get("order", 0) or 0)
        raw_text = str(entry.get("raw_text", "")).strip()
        if order <= 0 or not raw_text:
            continue
        if order not in merged:
            merged[order] = {"order": order, "raw_text": raw_text}

    for entry in current_entries:
        order = int(entry.get("order", 0) or 0)
        raw_text = str(entry.get("raw_text", "")).strip()
        if order <= 0 or not raw_text:
            continue
        merged[order] = {"order": order, "raw_text": raw_text}

    return [merged[key] for key in sorted(merged)]


def feature_text_needs_repair(feature_text: str) -> bool:
    entries = parse_feature_entries(feature_text)
    if not entries:
        return True
    orders = [item["order"] for item in entries]
    return orders[0] != 1 or len(entries) <= 1


def rule_has_calc_intent(text: str) -> bool:
    combined = str(text or "")
    return any(
        keyword in combined
        for keyword in ("体积", "面积", "长度", "数量", "中心线长度", "投影面积", "斜面积", "展开面积", "接触面积")
    )


def load_step1_rows(step1_table_regions_path: str | Path) -> List[Dict[str, Any]]:
    rows, _ = load_step1_rows_and_chapter_rules(step1_table_regions_path)
    return rows


def repair_step1_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped_indexes: Dict[str, List[int]] = defaultdict(list)
    repaired = [dict(row) for row in rows]

    for index, row in enumerate(repaired):
        grouped_indexes[row.get("canonical_table_title", "")].append(index)

    for indexes in grouped_indexes.values():
        for relative_index, absolute_index in enumerate(indexes):
            row = repaired[absolute_index]
            family = row.get("row_family", "其他")
            unit = row.get("measurement_unit", "")

            neighbor_feature_entries: List[Dict[str, Any]] = []
            best_rule = ""
            for candidate_relative_index in range(max(0, relative_index - 2), min(len(indexes), relative_index + 3)):
                candidate_row = repaired[indexes[candidate_relative_index]]
                if candidate_relative_index != relative_index:
                    if candidate_row.get("row_family") != family:
                        continue
                    if unit and candidate_row.get("measurement_unit") and candidate_row.get("measurement_unit") != unit:
                        continue
                neighbor_feature_entries.extend(parse_feature_entries(candidate_row.get("project_features", "")))
                candidate_rule = clean_rule_text(candidate_row.get("quantity_rule", ""))
                if rule_has_calc_intent(candidate_rule) and len(candidate_rule) > len(best_rule):
                    best_rule = candidate_rule

            current_entries = parse_feature_entries(row.get("project_features", ""))
            if feature_text_needs_repair(row.get("project_features", "")):
                merged_entries = merge_feature_entries(current_entries=current_entries, neighbor_entries=neighbor_feature_entries)
                if merged_entries:
                    row["project_features"] = format_feature_entries(merged_entries)

            current_rule = clean_rule_text(row.get("quantity_rule", ""))
            if not current_rule:
                row["quantity_rule"] = best_rule
            elif not rule_has_calc_intent(current_rule) and best_rule and best_rule not in current_rule:
                row["quantity_rule"] = "\n".join(dedupe_preserve_order([best_rule, current_rule]))

    return repaired


def get_chapter_root(section_path: str) -> str:
    return str(section_path or "").split(" > ")[0].strip()


def clean_rule_paragraph_text(text: str) -> str:
    value = str(text or "")
    value = value.replace("|", "\n")
    value = value.replace("“", '"').replace("”", '"')
    value = value.replace("‘", "'").replace("’", "'")
    value = value.replace("．", ".")
    value = value.replace("•", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n+", "\n", value)
    return value.strip()


def strip_rule_numbering(text: str) -> str:
    value = str(text or "").strip()
    return re.sub(r"^[A-Za-z][\.,]?\s*\d+(?:\s*[\.,]\s*\d+)*\s*", "", value).strip()


def extract_quoted_terms(text: str) -> List[str]:
    quoted = re.findall(r'"([^"]+)"', str(text or ""))
    return dedupe_preserve_order(item.strip(" ：:，,。；;（）()") for item in quoted if item.strip())


def clean_scope_term(term: str) -> str:
    value = strip_rule_numbering(term)
    value = re.sub(r"面积\s*[<>=W≤≥]?\s*[\d.]+\s*(?:m2|m3|m|㎡|m²)?\s*的", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^(各种|各类|少量分散的|一般|其他|同类|本附录中|本标准中|本附录|本标准)", "", value)
    value = re.sub(r"(应按.*|可描述为.*|适用于.*|工作内容.*|工程量.*|项目编码列项.*|相关项目编码列项.*)$", "", value)
    value = value.replace("中的", "").replace("项目特征", "").replace("工程量计算规则", "")
    value = value.replace("工程量", "").replace("编码列项", "").replace("列项", "")
    value = value.strip(" ：:，,。；;（）()\"'")
    if value.endswith("项目") and (len(value[:-2]) >= 2 or value[:-2] in {"墙", "梁", "柱", "板", "桩", "门", "窗", "沟", "井", "池"}):
        value = value[:-2]
    return value.strip()


def is_useful_scope_term(term: str) -> bool:
    value = clean_scope_term(term)
    if not value:
        return False
    if len(value) < 2 and value not in {"墙", "梁", "柱", "板", "桩", "门", "窗", "沟", "井", "池"}:
        return False
    if value in RULE_SCOPE_STOP_WORDS:
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9]", value))


def split_scope_terms(text: str) -> List[str]:
    value = clean_rule_paragraph_text(text)
    quoted_terms = extract_quoted_terms(value)
    value = re.sub(r'"[^"]+"', " ", value)
    raw_parts = re.split(r"[、,，;；/\n]|以及|以及|及|和|与|或", value)
    parts = dedupe_preserve_order(quoted_terms + raw_parts)
    cleaned = [clean_scope_term(item) for item in parts if is_useful_scope_term(item)]
    return dedupe_preserve_order(cleaned)


def infer_calculation_codes_from_text(text: str) -> List[str]:
    value = str(text or "")
    codes: List[str] = []
    if "模板" in value and any(keyword in value for keyword in ("接触面积", "模板面积")):
        codes.append("MBMJ")
    if any(keyword in value for keyword in ("体积", "净体积", "体积内", "并入")):
        codes.append("TJ")
    if any(keyword in value for keyword in ("中心线长度", "净长")):
        codes.append("JCD")
    if "长度" in value:
        codes.append("CD")
    if any(keyword in value for keyword in ("水平投影面积", "斜面积", "展开面积", "面积")):
        codes.append("MJ")
    if "数量" in value:
        codes.append("SL")
    return dedupe_preserve_order(codes)


def extract_rule_target_terms(text: str) -> List[str]:
    quoted_terms = extract_quoted_terms(text)
    if quoted_terms:
        return quoted_terms

    cleaned = strip_rule_numbering(text)
    cleaned = re.sub(r"^(本附录|本标准)[^的中]*[的中]", "", cleaned)
    cleaned = cleaned.replace("相关项目编码列项", "")
    cleaned = cleaned.replace("相应项目编码列项", "")
    cleaned = cleaned.replace("项目编码列项", "")
    cleaned = cleaned.replace("项目列项", "")
    cleaned = cleaned.replace("相关项目", "")
    cleaned = cleaned.replace("相应项目", "")
    cleaned = cleaned.replace("相关", "")
    cleaned = cleaned.strip(" ：:，,。；;（）()")
    if not cleaned:
        return []
    return [cleaned]


def build_rule_from_paragraph(
    paragraph_text: str,
    source_path: str,
    rule_id: str,
) -> Dict[str, Any] | None:
    content = strip_rule_numbering(clean_rule_paragraph_text(paragraph_text))
    if not content or not any(keyword in content for keyword in RULE_TRIGGER_KEYWORDS):
        return None

    rule_types: List[str] = []
    scope_terms: List[str] = []
    target_item_terms: List[str] = []
    feature_names: List[str] = []
    feature_examples: List[str] = []

    route_match = re.search(r"(.+?)(?:应)?按(.+?)(?:相关项目|相应项目|项目)(?:编码)?列项", content)
    if route_match:
        scope_terms.extend(split_scope_terms(route_match.group(1)))
        target_item_terms.extend(extract_rule_target_terms(route_match.group(2)))
        rule_types.append("component_route")

    include_match = re.match(r"(.+?)包括(.+)", content)
    if include_match and "工作内容" not in include_match.group(1):
        target_phrase = clean_scope_term(include_match.group(1))
        if is_useful_scope_term(target_phrase):
            target_item_terms.append(target_phrase)
            scope_terms.extend(split_scope_terms(include_match.group(2)))
            rule_types.append("component_route")

    feature_quote_terms = extract_quoted_terms(content)
    if "可描述为" in content and feature_quote_terms:
        feature_names.extend(feature_quote_terms[:4])
        example_text = content.split("可描述为", 1)[1]
        feature_examples.extend(
            split_scope_terms(re.split(r"[。；;]", example_text, maxsplit=1)[0])
        )
        feature_scope_match = re.match(r"(.+?)的\s*\"[^\"]+\"\s*可描述为", content)
        if feature_scope_match and "项目特征中的" not in feature_scope_match.group(1):
            scope_terms.extend(split_scope_terms(feature_scope_match.group(1)))
        rule_types.append("feature_hint")

    increase_feature_match = re.match(r"(.+?)应在项目特征中(?:增加|明确)(.+?)描述", content)
    if increase_feature_match:
        scope_terms.extend(split_scope_terms(increase_feature_match.group(1)))
        feature_names.extend(extract_quoted_terms(increase_feature_match.group(2)))
        rule_types.append("feature_hint")

    calculation_codes = infer_calculation_codes_from_text(content)
    calculation_keywords = [
        keyword
        for keyword in ("模板", "体积", "面积", "接触面积", "中心线长度", "长度", "数量", "并入")
        if keyword in content
    ]
    if calculation_codes or any(keyword in content for keyword in ("不增加相应工程量", "并入")):
        calculation_scope_match = re.match(r"(.+?)(?:工程量)?按.+?计算", content)
        if calculation_scope_match:
            scope_terms.extend(split_scope_terms(calculation_scope_match.group(1)))
        merge_scope_match = re.match(r"(.+?)并入.+?(体积|面积|长度)", content)
        if merge_scope_match:
            scope_terms.extend(split_scope_terms(merge_scope_match.group(1)))
        rule_types.append("calculation_hint")

    if not rule_types:
        return None

    return {
        "rule_id": rule_id,
        "chapter_root": get_chapter_root(source_path),
        "source_path": source_path,
        "paragraph": content,
        "rule_types": dedupe_preserve_order(rule_types),
        "scope_terms": dedupe_preserve_order(scope_terms),
        "target_item_terms": dedupe_preserve_order(target_item_terms),
        "feature_names": dedupe_preserve_order(feature_names),
        "feature_examples": dedupe_preserve_order(feature_examples)[:8],
        "calculation_codes": calculation_codes,
        "calculation_keywords": calculation_keywords,
    }


def extract_rule_paragraphs_from_region(region: Dict[str, Any]) -> List[str]:
    raw_text = str(region.get("non_table_text") or region.get("text") or "").strip()
    if not raw_text:
        return []

    normalized = clean_rule_paragraph_text(raw_text)
    paragraphs: List[str] = []
    current = ""
    for line in normalized.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^[A-Za-z][\.,]?\s*\d+(?:\s*[\.,]\s*\d+)*", stripped):
            if current:
                paragraphs.append(current.strip())
            current = stripped
        elif current:
            current = f"{current} {stripped}".strip()

    if current:
        paragraphs.append(current.strip())

    return dedupe_preserve_order(
        paragraph
        for paragraph in paragraphs
        if any(keyword in paragraph for keyword in RULE_TRIGGER_KEYWORDS)
    )


def build_chapter_rule_catalog(step1_payload: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    chapter_rules: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()

    for region in step1_payload:
        source_path = str(region.get("path_text", "")).strip()
        for paragraph in extract_rule_paragraphs_from_region(region):
            dedupe_key = (source_path, strip_rule_numbering(paragraph))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            rule = build_rule_from_paragraph(
                paragraph_text=paragraph,
                source_path=source_path,
                rule_id=f"CR{len(chapter_rules) + 1:04d}",
            )
            if rule:
                chapter_rules.append(rule)

    return chapter_rules


def rule_matches_row(row: Dict[str, Any], rule: Dict[str, Any]) -> Tuple[float, List[str]]:
    if rule.get("chapter_root") != row.get("chapter_root"):
        return 0.0, []

    row_name_text = str(row.get("project_name", ""))
    feature_text = str(row.get("project_features", ""))
    rule_text = str(row.get("quantity_rule", ""))
    combined_text = "\n".join([row_name_text, feature_text, rule_text, str(row.get("section_path", ""))])
    combined_normalized = normalize_text(combined_text)
    feature_normalized = normalize_text(feature_text)

    matched_terms: List[str] = []
    score = 0.0

    for term in rule.get("scope_terms", []):
        normalized_term = normalize_text(term)
        if normalized_term and normalized_term in combined_normalized:
            matched_terms.append(term)
    if matched_terms:
        score += 0.55

    matched_feature_names = []
    for feature_name in rule.get("feature_names", []):
        normalized_feature_name = normalize_text(feature_name)
        if normalized_feature_name and normalized_feature_name in feature_normalized:
            matched_feature_names.append(feature_name)
    if matched_feature_names:
        matched_terms.extend(matched_feature_names)
        score += 0.25

    for keyword in rule.get("calculation_keywords", []):
        normalized_keyword = normalize_text(keyword)
        if normalized_keyword and normalized_keyword in combined_normalized:
            matched_terms.append(keyword)
            score += 0.08

    if "component_route" in rule.get("rule_types", []) and matched_terms:
        score += 0.08
    if "feature_hint" in rule.get("rule_types", []) and matched_terms:
        score += 0.04
    if "calculation_hint" in rule.get("rule_types", []) and matched_terms:
        score += 0.04

    return min(score, 0.98), dedupe_preserve_order(matched_terms)


def attach_chapter_rules_to_rows(
    rows: Sequence[Dict[str, Any]],
    chapter_rules: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    attached_rows: List[Dict[str, Any]] = []
    for row in rows:
        current = dict(row)
        current["chapter_root"] = get_chapter_root(current.get("section_path", ""))
        rule_hits: List[Dict[str, Any]] = []
        chapter_feature_hints: List[str] = []
        chapter_target_terms: List[str] = []
        chapter_calculation_codes: List[str] = []

        for rule in chapter_rules:
            hit_score, matched_terms = rule_matches_row(current, rule)
            if hit_score < 0.3:
                continue
            rule_hits.append(
                {
                    "rule_id": rule.get("rule_id", ""),
                    "source_path": rule.get("source_path", ""),
                    "rule_types": list(rule.get("rule_types", [])),
                    "scope_terms": list(rule.get("scope_terms", [])),
                    "matched_terms": matched_terms,
                    "target_item_terms": list(rule.get("target_item_terms", [])),
                    "feature_names": list(rule.get("feature_names", [])),
                    "feature_examples": list(rule.get("feature_examples", [])),
                    "calculation_codes": list(rule.get("calculation_codes", [])),
                    "calculation_keywords": list(rule.get("calculation_keywords", [])),
                    "paragraph": rule.get("paragraph", ""),
                    "confidence": round(hit_score, 4),
                }
            )
            chapter_feature_hints.extend(rule.get("feature_names", []))
            chapter_target_terms.extend(rule.get("target_item_terms", []))
            chapter_calculation_codes.extend(rule.get("calculation_codes", []))

        rule_hits.sort(key=lambda item: item.get("confidence", 0.0), reverse=True)
        current["chapter_rule_hits"] = rule_hits[:8]
        current["chapter_feature_hints"] = dedupe_preserve_order(chapter_feature_hints)
        current["chapter_target_terms"] = dedupe_preserve_order(chapter_target_terms)
        current["chapter_calculation_codes"] = dedupe_preserve_order(chapter_calculation_codes)
        attached_rows.append(current)

    return attached_rows


def load_step1_rows_and_chapter_rules(
    step1_table_regions_path: str | Path,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    payload = load_step1_region_payload(step1_table_regions_path)

    rows: List[Dict[str, Any]] = []
    seen_codes = set()
    for region in payload:
        section_path = str(region.get("path_text", "")).strip()
        region_text = str(region.get("text") or region.get("non_table_text") or "").strip()
        for table in region.get("tables", []) if isinstance(region.get("tables"), list) else []:
            if not isinstance(table, dict):
                continue
            table_title = str(table.get("title", "")).strip()
            canonical_table_title = canonicalize_table_title(table_title)
            table_raw_text = str(table.get("raw_text", "")).strip()
            for row in table.get("rows", []) if isinstance(table.get("rows"), list) else []:
                if not isinstance(row, dict):
                    continue
                project_code = str(row.get("project_code", "")).strip()
                if not project_code or project_code in seen_codes:
                    continue
                seen_codes.add(project_code)
                rows.append(
                    {
                        "row_id": f"R{len(rows) + 1:04d}",
                        "project_code": project_code,
                        "project_name": clean_project_name(row.get("project_name", "")),
                        "project_features": clean_feature_text(row.get("project_features", "")),
                        "measurement_unit": normalize_unit(str(row.get("measurement_unit", "")).strip()),
                        "quantity_rule": clean_rule_text(row.get("quantity_rule", "")),
                        "work_content": clean_multiline_text(row.get("work_content", "")),
                        "section_path": section_path,
                        "table_title": table_title,
                        "canonical_table_title": canonical_table_title,
                        "table_raw_text": table_raw_text,
                        "region_text_excerpt": region_text[:4000],
                        "row_family": infer_row_family_from_name(str(row.get("project_name", ""))),
                    }
                )

    repaired_rows = repair_step1_rows(rows)
    chapter_rules = build_chapter_rule_catalog(payload)
    return attach_chapter_rules_to_rows(repaired_rows, chapter_rules), chapter_rules


def is_meaningful_attribute(attribute: Dict[str, Any]) -> bool:
    code = str(attribute.get("code", "")).strip()
    name = str(attribute.get("name", "")).strip()
    if not code or not name:
        return False
    if code in GENERIC_ATTRIBUTE_CODES:
        return False
    return not any(part in name for part in GENERIC_ATTRIBUTE_NAME_PARTS)


def generate_component_aliases(name: str) -> List[str]:
    aliases = [name]
    stripped = strip_affixes(name)
    if stripped and stripped != name:
        aliases.append(stripped)
    if "砼" in name:
        aliases.append(name.replace("砼", "混凝土"))
    if "混凝土" in name:
        aliases.append(name.replace("混凝土", "砼"))
    normalized = normalize_text(name)
    if normalized and normalized != name:
        aliases.append(normalized)
    return dedupe_preserve_order(aliases)


def build_synonym_maps(
    synonym_payload: Any,
    component_names: Sequence[str],
) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    component_name_set = set(component_names)
    alias_to_components: Dict[str, List[str]] = defaultdict(list)
    component_to_bridge_names: Dict[str, List[str]] = defaultdict(list)

    if isinstance(synonym_payload, dict) and isinstance(synonym_payload.get("synonym_library"), list):
        items = synonym_payload["synonym_library"]
    elif isinstance(synonym_payload, list):
        items = synonym_payload
    else:
        return {}, {}

    for item in items:
        if not isinstance(item, dict):
            continue
        canonical_name = str(item.get("canonical_name", "")).strip()
        source_component_name = str(item.get("source_component_name", "")).strip()
        selected_standard_name = str(item.get("selected_standard_name", "")).strip()
        aliases = normalize_string_list(item.get("aliases"))
        chapter_nodes = normalize_string_list(item.get("chapter_nodes"))
        source_component_names = normalize_string_list(item.get("source_component_names"))
        if source_component_name:
            source_component_names = dedupe_preserve_order([source_component_name] + source_component_names)
        source_component_names = [name for name in source_component_names if name in component_name_set]
        if not source_component_names:
            continue

        bridge_names = dedupe_preserve_order(
            [source_component_name]
            + aliases
            + chapter_nodes
            + ([selected_standard_name] if selected_standard_name else [])
            + ([canonical_name] if canonical_name and canonical_name != source_component_name else [])
        )
        for bridge_name in bridge_names:
            key = normalize_text(bridge_name)
            alias_to_components[key].extend(source_component_names)
            stripped_key = normalize_text(strip_affixes(bridge_name))
            if stripped_key:
                alias_to_components[stripped_key].extend(source_component_names)

        for component_name in source_component_names:
            component_to_bridge_names[component_name].extend(bridge_names)

    return (
        {key: dedupe_preserve_order(value) for key, value in alias_to_components.items()},
        {key: dedupe_preserve_order(value) for key, value in component_to_bridge_names.items()},
    )


def build_component_source_table(components_payload: Any, synonym_payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(components_payload, list):
        raise ValueError("构件库必须是数组格式。")

    component_names = [str(item.get("component_type", "")).strip() for item in components_payload if str(item.get("component_type", "")).strip()]
    _, component_to_bridge_names = build_synonym_maps(synonym_payload, component_names)

    table: List[Dict[str, Any]] = []
    for item in components_payload:
        component_name = str(item.get("component_type", "")).strip()
        if not component_name:
            continue
        properties = item.get("properties", {}) if isinstance(item.get("properties"), dict) else {}
        attributes_raw = properties.get("attributes", []) if isinstance(properties.get("attributes"), list) else []
        calculations_raw = properties.get("calculations", []) if isinstance(properties.get("calculations"), list) else []

        attributes = [
            {
                "name": str(attribute.get("name", "")).strip(),
                "code": str(attribute.get("code", "")).strip(),
                "data_type": str(attribute.get("data_type", "")).strip(),
                "values": normalize_string_list(attribute.get("values")),
                "source_sheet": str(attribute.get("source_sheet", "")).strip(),
            }
            for attribute in attributes_raw
            if isinstance(attribute, dict) and is_meaningful_attribute(attribute)
        ]

        calculations = [
            {
                "name": str(calculation.get("name", "")).strip(),
                "code": str(calculation.get("code", "")).strip(),
                "expression": str(calculation.get("expression", "")).strip(),
                "unit": normalize_unit(str(calculation.get("unit", "")).strip()),
                "source_sheet": str(calculation.get("source_sheet", "")).strip(),
            }
            for calculation in calculations_raw
            if isinstance(calculation, dict) and str(calculation.get("code", "")).strip()
        ]

        aliases = generate_component_aliases(component_name)
        bridge_names = dedupe_preserve_order(component_to_bridge_names.get(component_name, []))
        query_names = dedupe_preserve_order([component_name] + aliases + bridge_names)

        table.append(
            {
                "component_name": component_name,
                "aliases": aliases,
                "bridge_names": bridge_names,
                "query_names": query_names,
                "attributes": attributes,
                "calculations": calculations,
                "source_file": str(item.get("source_file", "")).strip(),
            }
        )

    return table


def build_alias_index(source_table: Sequence[Dict[str, Any]], synonym_payload: Any) -> Dict[str, List[str]]:
    index: Dict[str, List[str]] = defaultdict(list)
    component_names = [entry.get("component_name", "") for entry in source_table]
    synonym_alias_index, _ = build_synonym_maps(synonym_payload, component_names)

    for entry in source_table:
        component_name = entry.get("component_name", "")
        for query_name in entry.get("query_names", []):
            key = normalize_text(query_name)
            if key:
                index[key].append(component_name)
            stripped_key = normalize_text(strip_affixes(query_name))
            if stripped_key:
                index[stripped_key].append(component_name)

    for key, values in synonym_alias_index.items():
        index[key].extend(values)

    for item_name, component_list in SPECIAL_ITEM_COMPONENTS.items():
        key = normalize_text(item_name)
        index[key].extend(component_list)

    return {key: dedupe_preserve_order(value) for key, value in index.items()}


def summarize_source_entry_for_prompt(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "component_name": entry.get("component_name", ""),
        "query_names": list(entry.get("query_names", []))[:15],
        "attributes": [
            {
                "name": attribute.get("name", ""),
                "code": attribute.get("code", ""),
                "data_type": attribute.get("data_type", ""),
                "value_examples": list(attribute.get("values", []))[:6],
            }
            for attribute in entry.get("attributes", [])[:15]
        ],
        "calculations": [
            {
                "name": calculation.get("name", ""),
                "code": calculation.get("code", ""),
                "unit": calculation.get("unit", ""),
            }
            for calculation in entry.get("calculations", [])[:20]
        ],
    }


# 中文建筑领域常见动词/修饰词前缀，用于提取核心名词
_CN_VERB_PREFIXES = ("挖", "浇", "砌", "铺", "做", "装", "拆", "运", "填", "刷", "喷", "抹", "涂", "贴")
_CN_MODIFIER_TOKENS = {"单独", "基坑", "沟槽", "大开挖", "干挖", "湿挖", "人工", "机械", "现浇", "预制"}


def _extract_core_tokens(text: str) -> List[str]:
    """将建筑工程项目名称拆分为核心名词 token。
    例：'挖单独石方' → ['单独石方', '石方']
         '挖基坑土方' → ['基坑土方', '土方']
    """
    value = normalize_text(text)
    if not value:
        return []
    # 去掉动词前缀
    for vp in _CN_VERB_PREFIXES:
        if value.startswith(vp) and len(value) > len(vp):
            value = value[len(vp):]
            break
    tokens = [value]
    # 去掉修饰词
    for mod in _CN_MODIFIER_TOKENS:
        if value.startswith(mod) and len(value) > len(mod):
            tokens.append(value[len(mod):])
    return dedupe_preserve_order(tokens)


def score_name_match(query_name: str, candidate_names: Sequence[str]) -> Tuple[float, str]:
    normalized_query = normalize_text(query_name)
    stripped_query = normalize_text(strip_affixes(query_name))
    best_score = 0.0
    best_basis = "fuzzy"

    # 提取核心 token 用于兜底匹配
    core_tokens = _extract_core_tokens(query_name)

    for candidate_name in candidate_names:
        normalized_candidate = normalize_text(candidate_name)
        stripped_candidate = normalize_text(strip_affixes(candidate_name))
        if not normalized_candidate:
            continue
        if normalized_query == normalized_candidate:
            return 1.0, "exact"
        if stripped_query and stripped_query == normalized_candidate:
            best_score = max(best_score, 0.95)
            best_basis = "normalized"
            continue
        if normalized_query == stripped_candidate and stripped_candidate:
            best_score = max(best_score, 0.95)
            best_basis = "normalized"
            continue
        if normalized_query in normalized_candidate or normalized_candidate in normalized_query:
            best_score = max(best_score, 0.88)
            if best_basis != "normalized":
                best_basis = "contains"
            continue

        # --- 核心 token 子串匹配（新增） ---
        # 如 "石方" in "土石方" 或 "土石方" in "单独石方"
        token_matched = False
        for token in core_tokens:
            if token in normalized_candidate or normalized_candidate in token:
                score_val = 0.82
                if score_val > best_score:
                    best_score = score_val
                    best_basis = "token_contains"
                token_matched = True
                break
        if token_matched:
            continue

        query_chars = set(normalized_query)
        candidate_chars = set(normalized_candidate)
        if query_chars and candidate_chars:
            score = len(query_chars & candidate_chars) / len(query_chars | candidate_chars)
            if score > best_score:
                best_score = score
                best_basis = "fuzzy"

    return best_score, best_basis


def rank_candidate_components(
    row: Dict[str, Any],
    source_table: Sequence[Dict[str, Any]],
    alias_index: Dict[str, List[str]],
    max_components_per_item: int,
) -> List[Dict[str, Any]]:
    source_by_name = {entry["component_name"]: entry for entry in source_table}
    query_name = row.get("project_name", "")
    query_key = normalize_text(query_name)
    stripped_key = normalize_text(strip_affixes(query_name))
    chapter_target_terms = normalize_string_list(row.get("chapter_target_terms"))

    explicit_candidates = dedupe_preserve_order(alias_index.get(query_key, []) + alias_index.get(stripped_key, []))
    chapter_explicit_candidates: List[str] = []
    for target_term in chapter_target_terms:
        target_key = normalize_text(target_term)
        stripped_target_key = normalize_text(strip_affixes(target_term))
        chapter_explicit_candidates.extend(alias_index.get(target_key, []))
        chapter_explicit_candidates.extend(alias_index.get(stripped_target_key, []))
    chapter_explicit_candidates = dedupe_preserve_order(chapter_explicit_candidates)
    explicit_candidates = dedupe_preserve_order(explicit_candidates + chapter_explicit_candidates)
    candidate_names = [name for name in explicit_candidates if name in source_by_name]

    if not candidate_names:
        candidate_names = list(source_by_name)

    row_family = row.get("row_family", infer_row_family_from_name(query_name))
    # SPECIAL_ITEM_COMPONENTS: 精确匹配 + 核心 token 模糊匹配（应对 OCR 噪声）
    special_candidates: set = set(SPECIAL_ITEM_COMPONENTS.get(query_name, []))
    if not special_candidates:
        for item_name, comp_list in SPECIAL_ITEM_COMPONENTS.items():
            if normalize_text(item_name) in normalize_text(query_name):
                special_candidates.update(comp_list)

    rankings: List[Dict[str, Any]] = []
    for component_name in candidate_names:
        source_entry = source_by_name[component_name]
        score, basis = score_name_match(query_name, source_entry.get("query_names", []))

        if component_name in explicit_candidates:
            score = max(score, 0.93)
            if basis not in {"exact", "normalized"}:
                basis = "alias_bridge"

        if component_name in chapter_explicit_candidates and basis not in {"exact", "normalized", "alias_bridge"}:
            score = max(score, 0.91)
            basis = "chapter_rule"

        if component_name in special_candidates and basis not in {"exact", "normalized", "alias_bridge"}:
            score = max(score, 0.88)
            basis = "special_rule"

        component_family = infer_row_family_from_name(component_name)
        if component_family == row_family and score > 0:
            score += 0.04

        calculations = source_entry.get("calculations", [])
        if calculations:
            preferred_unit = row.get("measurement_unit", "")
            if preferred_unit and any(item.get("unit") == preferred_unit for item in calculations):
                score += 0.03

        rankings.append(
            {
                "component_name": component_name,
                "match_score": round(min(score, 1.0), 4),
                "match_basis": basis,
                "source_entry": source_entry,
            }
        )

    rankings.sort(key=lambda item: item["match_score"], reverse=True)
    if not rankings:
        return []

    threshold = max(rankings[0]["match_score"] * 0.75, 0.62)
    selected = [item for item in rankings if item["match_score"] >= threshold][:max_components_per_item]

    # --- 章节兜底：若评分全部低于阈值，用章节主构件作为低置信度候选 ---
    if not selected:
        chapter_root = row.get("chapter_root", "")
        chapter_primary = CHAPTER_PRIMARY_COMPONENTS.get(chapter_root, [])
        for fallback_name in chapter_primary:
            if fallback_name in source_by_name:
                source_entry = source_by_name[fallback_name]
                selected.append({
                    "component_name": fallback_name,
                    "match_score": 0.65,
                    "match_basis": "chapter_fallback",
                    "source_entry": source_entry,
                })
                if len(selected) >= max_components_per_item:
                    break

    return selected


def extract_feature_value_expression(text: str) -> Tuple[str, str]:
    raw_text = str(text or "").strip()
    if not raw_text:
        return "", ""

    label = raw_text
    for source, target in (
        ("大于等于", ">="),
        ("小于等于", "<="),
        ("不小于", ">="),
        ("不少于", ">="),
        ("不大于", "<="),
        ("不高于", "<="),
        ("高于", ">"),
        ("低于", "<"),
        ("大于", ">"),
        ("小于", "<"),
        ("＞", ">"),
        ("＜", "<"),
        ("≥", ">="),
        ("≤", "<="),
    ):
        label = label.replace(source, target)

    comparator_match = re.match(r"^(.*?)(>=|<=|>|<|=)\s*(.+?)$", label)
    if comparator_match:
        return comparator_match.group(1).strip(" ：:."), f"{comparator_match.group(2)}{comparator_match.group(3).strip()}"

    suffix_match = re.match(
        r"^(.*?)(C\d{2,3}(?:\.\d+)?|\d+(?:\.\d+)?\s*(?:mm|cm|m|m2|m3|kg|t|MPa|%|级))$",
        label,
        flags=re.IGNORECASE,
    )
    if suffix_match:
        return suffix_match.group(1).strip(" ：:."), suffix_match.group(2).strip()

    return raw_text.strip(" ：:."), ""


def score_attribute_match(label: str, attribute: Dict[str, Any]) -> float:
    attribute_name = str(attribute.get("name", "")).strip()
    attribute_code = str(attribute.get("code", "")).strip()
    normalized_label = normalize_text(label)
    normalized_attribute_name = normalize_text(attribute_name)

    if not normalized_label or not normalized_attribute_name:
        return 0.0
    if normalized_label == normalized_attribute_name:
        return 1.0

    score = 0.0
    if normalized_label in normalized_attribute_name or normalized_attribute_name in normalized_label:
        score = max(score, 0.9)

    for keyword in [attribute_name] + ATTRIBUTE_HINTS.get(attribute_code, []):
        normalized_keyword = normalize_text(keyword)
        if not normalized_keyword:
            continue
        if normalized_label == normalized_keyword:
            score = max(score, 0.98)
        elif normalized_label in normalized_keyword or normalized_keyword in normalized_label:
            score = max(score, 0.92)

    label_chars = set(normalized_label)
    attribute_chars = set(normalized_attribute_name)
    if label_chars and attribute_chars:
        score = max(score, len(label_chars & attribute_chars) / len(label_chars | attribute_chars))

    return round(score, 4)


def match_feature_to_attribute(label: str, attributes: Sequence[Dict[str, Any]]) -> Dict[str, Any] | None:
    best_attribute = None
    best_score = 0.0
    for attribute in attributes:
        score = score_attribute_match(label, attribute)
        if score > best_score:
            best_score = score
            best_attribute = attribute
    if best_score >= 0.55:
        return best_attribute
    return None


def build_feature_expression_items(
    project_features_text: str,
    source_entry: Dict[str, Any] | None,
    chapter_feature_hints: Sequence[str] | None = None,
) -> List[Dict[str, Any]]:
    feature_entries = parse_feature_entries(project_features_text)
    if not feature_entries and chapter_feature_hints:
        feature_entries = [
            {"order": index, "raw_text": hint}
            for index, hint in enumerate(dedupe_preserve_order(chapter_feature_hints), start=1)
            if str(hint).strip()
        ]
    if not feature_entries:
        return []

    attributes = source_entry.get("attributes", []) if source_entry else []
    expression_items: List[Dict[str, Any]] = []
    for index, entry in enumerate(feature_entries, start=1):
        label, value_expression = extract_feature_value_expression(entry["raw_text"])
        attribute = match_feature_to_attribute(label, attributes) if attributes else None
        if attribute:
            expression = f"{label}:{attribute.get('code', '')}"
            if value_expression:
                expression = f"{expression}={value_expression}"
            expression_items.append(
                {
                    "order": entry.get("order", index),
                    "raw_text": entry["raw_text"],
                    "label": label,
                    "attribute_name": attribute.get("name", ""),
                    "attribute_code": attribute.get("code", ""),
                    "value_expression": value_expression,
                    "expression": expression,
                    "matched": True,
                }
            )
        else:
            expression_items.append(
                {
                    "order": entry.get("order", index),
                    "raw_text": entry["raw_text"],
                    "label": label,
                    "attribute_name": "",
                    "attribute_code": "",
                    "value_expression": value_expression,
                    "expression": entry["raw_text"],
                    "matched": False,
                }
            )
    return expression_items


def build_feature_expression_text(items: Sequence[Dict[str, Any]]) -> str:
    if not items:
        return ""
    return "<br>".join(f"{item.get('order', 0)}. {item.get('expression', '')}" for item in items)


def detect_calculation_preferences(row: Dict[str, Any]) -> Dict[str, Any]:
    project_name = str(row.get("project_name", ""))
    quantity_rule = str(row.get("quantity_rule", ""))
    measurement_unit = str(row.get("measurement_unit", ""))
    chapter_codes = normalize_string_list(row.get("chapter_calculation_codes"))
    combined = f"{project_name}\n{quantity_rule}"

    if "模板" in combined:
        return {
            "codes": ["MBMJ", "DMMB", "CMMB", "ZMBMJ", "ZMB"],
            "keywords": ["模板", "接触面积"],
            "reason": "规则文本指向模板接触面积。",
        }
    if any(keyword in combined for keyword in ("体积", "净体积")):
        return {
            "codes": ["TJ", "ZTJ", "JLQTJ", "DZJLQTJ", "CGTJ"],
            "keywords": ["体积"],
            "reason": "规则文本明确出现体积计算。",
        }
    if any(keyword in combined for keyword in ("水平投影面积", "斜面积", "展开面积", "接触面积", "面积")):
        return {
            "codes": ["MJ", "TYMJ", "MBMJ", "TQMJ", "DMMJ", "CMMJ"],
            "keywords": ["面积", "投影面积", "接触面积"],
            "reason": "规则文本明确出现面积计算。",
        }
    if any(keyword in combined for keyword in ("中心线长度", "长度")):
        return {
            "codes": ["CD", "JCD", "YCD"],
            "keywords": ["长度"],
            "reason": "规则文本明确出现长度计算。",
        }
    if any(keyword in combined for keyword in ("数量", "按设计图示数量")):
        return {
            "codes": ["SL"],
            "keywords": ["数量"],
            "reason": "规则文本明确出现数量计算。",
        }
    if chapter_codes:
        return {
            "codes": chapter_codes,
            "keywords": [keyword for keyword in ("体积", "面积", "长度", "数量", "模板") if keyword in combined] or chapter_codes,
            "reason": "章节补充说明中命中了额外的计算项目提示。",
        }
    if measurement_unit == "m3":
        return {"codes": ["TJ", "ZTJ"], "keywords": ["体积"], "reason": "计量单位为 m3。"}
    if measurement_unit == "m2":
        return {"codes": ["MJ", "TYMJ", "MBMJ"], "keywords": ["面积"], "reason": "计量单位为 m2。"}
    if measurement_unit == "m":
        return {"codes": ["CD", "JCD"], "keywords": ["长度"], "reason": "计量单位为 m。"}
    if measurement_unit in COUNT_UNITS:
        return {"codes": ["SL"], "keywords": ["数量"], "reason": "计量单位为计数型单位。"}
    return {"codes": [], "keywords": [], "reason": "未识别到明确的计算项目偏好。"}


def score_calculation_match(
    calculation: Dict[str, Any],
    row: Dict[str, Any],
    preferences: Dict[str, Any],
) -> float:
    score = 0.0
    calculation_code = str(calculation.get("code", "")).strip()
    calculation_name = str(calculation.get("name", "")).strip()
    calculation_unit = str(calculation.get("unit", "")).strip()
    measurement_unit = str(row.get("measurement_unit", "")).strip()
    preferred_codes = preferences.get("codes", [])
    keywords = preferences.get("keywords", [])

    if calculation_code in preferred_codes:
        score += 0.7 - preferred_codes.index(calculation_code) * 0.05
    if measurement_unit and calculation_unit == measurement_unit:
        score += 0.25
    if any(keyword and keyword in calculation_name for keyword in keywords):
        score += 0.2
    if "模板" in row.get("project_name", "") and "模板" in calculation_name:
        score += 0.25

    return round(score, 4)


def infer_generic_calculation(row: Dict[str, Any], preferences: Dict[str, Any]) -> Dict[str, Any]:
    mapping = {
        "TJ": ("体积", "m3"),
        "MJ": ("面积", "m2"),
        "CD": ("长度", "m"),
        "SL": ("数量", row.get("measurement_unit", "")),
    }
    for code in preferences.get("codes", []):
        if code in mapping:
            name, unit = mapping[code]
            return {
                "calculation_item_name": name,
                "calculation_item_code": code,
                "calculation_basis": f"{preferences.get('reason', '')} 未匹配到具体构件计算项目时采用通用代码。",
                "measurement_unit": row.get("measurement_unit", unit) or unit,
            }
    return {
        "calculation_item_name": "",
        "calculation_item_code": "",
        "calculation_basis": preferences.get("reason", ""),
        "measurement_unit": row.get("measurement_unit", ""),
    }


def select_best_calculation(source_entry: Dict[str, Any] | None, row: Dict[str, Any]) -> Dict[str, Any]:
    preferences = detect_calculation_preferences(row)
    calculations = source_entry.get("calculations", []) if source_entry else []
    if not calculations:
        return infer_generic_calculation(row, preferences)

    scored = [
        (
            score_calculation_match(calculation, row, preferences),
            calculation,
        )
        for calculation in calculations
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_calculation = scored[0]
    if best_score < 0.25:
        return infer_generic_calculation(row, preferences)

    return {
        "calculation_item_name": best_calculation.get("name", ""),
        "calculation_item_code": best_calculation.get("code", ""),
        "calculation_basis": preferences.get("reason", ""),
        "measurement_unit": row.get("measurement_unit", "") or best_calculation.get("unit", ""),
    }


def build_result_statistics(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    distinct_row_ids = {row.get("row_id", "") for row in rows}
    return {
        "total_source_rows": len(distinct_row_ids),
        "generated_rows": len(rows),
        "matched_rows": sum(1 for row in rows if row.get("match_status") == "matched"),
        "candidate_only_rows": sum(1 for row in rows if row.get("match_status") == "candidate_only"),
        "unmatched_rows": sum(1 for row in rows if row.get("match_status") == "unmatched"),
        "rows_with_feature_expressions": sum(1 for row in rows if row.get("feature_expression_items")),
        "rows_with_calculation_item": sum(1 for row in rows if row.get("calculation_item_code")),
    }


def build_unmatched_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "row_id": row.get("row_id", ""),
            "project_code": row.get("project_code", ""),
            "project_name": row.get("project_name", ""),
            "reason": row.get("reasoning", "") or "未找到可靠构件候选。",
        }
        for row in rows
        if row.get("match_status") == "unmatched"
    ]


def build_local_match_payload(
    step1_rows: Sequence[Dict[str, Any]],
    source_table: Sequence[Dict[str, Any]],
    alias_index: Dict[str, List[str]],
    standard_document: str,
    max_components_per_item: int,
) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    result_counter = 1

    for row in step1_rows:
        ranked_components = rank_candidate_components(
            row=row,
            source_table=source_table,
            alias_index=alias_index,
            max_components_per_item=max_components_per_item,
        )

        if not ranked_components or ranked_components[0]["match_score"] < 0.62:
            feature_expression_items = build_feature_expression_items(
                row.get("project_features", ""),
                None,
                chapter_feature_hints=row.get("chapter_feature_hints", []),
            )
            generic_calculation = select_best_calculation(None, row)
            results.append(
                {
                    "result_id": f"M{result_counter:06d}",
                    "row_id": row.get("row_id", ""),
                    "project_code": row.get("project_code", ""),
                    "project_name": row.get("project_name", ""),
                    "section_path": row.get("section_path", ""),
                    "table_title": row.get("table_title", ""),
                    "chapter_root": row.get("chapter_root", ""),
                    "chapter_rule_hits": row.get("chapter_rule_hits", []),
                    "chapter_feature_hints": row.get("chapter_feature_hints", []),
                    "chapter_target_terms": row.get("chapter_target_terms", []),
                    "chapter_calculation_codes": row.get("chapter_calculation_codes", []),
                    "project_features_raw": row.get("project_features", ""),
                    "feature_expression_items": feature_expression_items,
                    "feature_expression_text": build_feature_expression_text(feature_expression_items),
                    "quantity_rule": row.get("quantity_rule", ""),
                    "quantity_component": "",
                    "resolved_component_name": "",
                    "source_component_name": "",
                    "candidate_rank": 0,
                    "match_status": "unmatched",
                    "match_basis": "unmatched",
                    "confidence": 0.0,
                    "calculation_item_name": generic_calculation.get("calculation_item_name", ""),
                    "calculation_item_code": generic_calculation.get("calculation_item_code", ""),
                    "measurement_unit": generic_calculation.get("measurement_unit", row.get("measurement_unit", "")),
                    "review_status": "pending",
                    "reasoning": "未在 Step 2 同义词库、章节补充规则和构件库中找到可靠的构件映射，请人工复核。",
                    "notes": "；".join(
                        dedupe_preserve_order(
                            [str(hit.get("paragraph", "")).strip() for hit in row.get("chapter_rule_hits", []) if str(hit.get("paragraph", "")).strip()]
                        )
                    )[:500],
                }
            )
            result_counter += 1
            continue

        for rank, candidate in enumerate(ranked_components, start=1):
            source_entry = candidate["source_entry"]
            feature_expression_items = build_feature_expression_items(
                row.get("project_features", ""),
                source_entry,
                chapter_feature_hints=row.get("chapter_feature_hints", []),
            )
            calculation = select_best_calculation(source_entry, row)
            match_status = (
                "matched"
                if candidate["match_score"] >= 0.8 and candidate.get("match_basis") in {"exact", "normalized", "alias_bridge", "special_rule", "chapter_rule"}
                else "candidate_only"
            )
            review_status = "suggested" if match_status == "matched" else "pending"
            results.append(
                {
                    "result_id": f"M{result_counter:06d}",
                    "row_id": row.get("row_id", ""),
                    "project_code": row.get("project_code", ""),
                    "project_name": row.get("project_name", ""),
                    "section_path": row.get("section_path", ""),
                    "table_title": row.get("table_title", ""),
                    "chapter_root": row.get("chapter_root", ""),
                    "chapter_rule_hits": row.get("chapter_rule_hits", []),
                    "chapter_feature_hints": row.get("chapter_feature_hints", []),
                    "chapter_target_terms": row.get("chapter_target_terms", []),
                    "chapter_calculation_codes": row.get("chapter_calculation_codes", []),
                    "project_features_raw": row.get("project_features", ""),
                    "feature_expression_items": feature_expression_items,
                    "feature_expression_text": build_feature_expression_text(feature_expression_items),
                    "quantity_rule": row.get("quantity_rule", ""),
                    "quantity_component": source_entry.get("component_name", ""),
                    "resolved_component_name": source_entry.get("component_name", ""),
                    "source_component_name": source_entry.get("component_name", ""),
                    "candidate_rank": rank,
                    "match_status": match_status,
                    "match_basis": candidate.get("match_basis", "alias_bridge"),
                    "confidence": candidate.get("match_score", 0.0),
                    "calculation_item_name": calculation.get("calculation_item_name", ""),
                    "calculation_item_code": calculation.get("calculation_item_code", ""),
                    "measurement_unit": calculation.get("measurement_unit", row.get("measurement_unit", "")),
                    "review_status": review_status,
                    "reasoning": (
                        f"基于 Step 2 同义词库、章节补充规则与构件库属性，按“{candidate.get('match_basis', '')}”"
                        "方式生成清单-构件-项目特征表达式候选。"
                    ),
                    "notes": "；".join(
                        dedupe_preserve_order(
                            [
                                calculation.get("calculation_basis", ""),
                                *[
                                    str(hit.get("paragraph", "")).strip()
                                    for hit in row.get("chapter_rule_hits", [])
                                    if str(hit.get("paragraph", "")).strip()
                                ],
                            ]
                        )
                    )[:500],
                }
            )
            result_counter += 1

    statistics = build_result_statistics(results)
    return {
        "meta": {
            "task_name": "project_component_feature_calc_matching",
            "standard_document": standard_document,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "generation_mode": "local_rule",
        },
        "statistics": statistics,
        "rows": results,
        "unmatched_rows": build_unmatched_rows(results),
    }


def build_prompt_batch_payload(
    batch_step1_rows: Sequence[Dict[str, Any]],
    local_rows_by_row_id: Dict[str, List[Dict[str, Any]]],
    source_table_by_name: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    payload: List[Dict[str, Any]] = []
    for row in batch_step1_rows:
        local_rows = local_rows_by_row_id.get(row["row_id"], [])
        payload.append(
            {
                "source_row": row,
                "local_candidate_rows": local_rows,
                "candidate_source_components": [
                    summarize_source_entry_for_prompt(source_table_by_name[item["source_component_name"]])
                    for item in local_rows
                    if item.get("source_component_name") in source_table_by_name
                ],
            }
        )
    return payload


def build_prompt_text(
    batch_step1_rows: Sequence[Dict[str, Any]],
    local_batch_rows: Sequence[Dict[str, Any]],
    batch_payload: Sequence[Dict[str, Any]],
    standard_document: str,
    batch_index: int,
    total_batches: int,
    wiki_context: str = "",
) -> str:
    template = load_prompt_template()
    replacements = {
        "${STANDARD_DOCUMENT}": standard_document,
        "${STEP1_BATCH_ROWS_JSON}": json.dumps(batch_step1_rows, ensure_ascii=False, indent=2),
        "${LOCAL_RULE_RESULT_JSON}": json.dumps(local_batch_rows, ensure_ascii=False, indent=2),
        "${ROW_CANDIDATE_SOURCE_JSON}": json.dumps(batch_payload, ensure_ascii=False, indent=2),
        "${WIKI_COMPONENT_CONTEXT}": wiki_context if wiki_context else "",
    }

    prompt_text = template
    for placeholder, value in replacements.items():
        prompt_text = prompt_text.replace(placeholder, value)

    batch_header = (
        f"当前批次信息:\n"
        f"- standard_document: {standard_document}\n"
        f"- batch_index: {batch_index}\n"
        f"- total_batches: {total_batches}\n"
        f"- current_batch_row_count: {len(batch_step1_rows)}\n\n"
    )
    return batch_header + prompt_text


def normalize_feature_expression_items(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []

    results: List[Dict[str, Any]] = []
    if isinstance(value, list):
        for index, item in enumerate(value, start=1):
            if not isinstance(item, dict):
                continue
            expression = str(item.get("expression", "")).strip()
            if not expression:
                continue
            order = item.get("order", index)
            try:
                order_value = int(order)
            except (TypeError, ValueError):
                order_value = index
            results.append(
                {
                    "order": order_value,
                    "raw_text": str(item.get("raw_text", "")).strip(),
                    "label": str(item.get("label", "")).strip(),
                    "attribute_name": str(item.get("attribute_name", "")).strip(),
                    "attribute_code": str(item.get("attribute_code", "")).strip(),
                    "value_expression": str(item.get("value_expression", "")).strip(),
                    "expression": expression,
                    "matched": bool(item.get("matched", False)),
                }
            )
    elif isinstance(value, str):
        for index, line in enumerate(value.replace("<br>", "\n").splitlines(), start=1):
            text = line.strip()
            if not text:
                continue
            text = re.sub(r"^\d+[.、]\s*", "", text)
            results.append(
                {
                    "order": index,
                    "raw_text": text,
                    "label": "",
                    "attribute_name": "",
                    "attribute_code": "",
                    "value_expression": "",
                    "expression": text,
                    "matched": ":" in text,
                }
            )

    return results


def build_feature_expression_text_from_items(items: Sequence[Dict[str, Any]]) -> str:
    if not items:
        return ""
    return "<br>".join(f"{index}. {item.get('expression', '')}" for index, item in enumerate(items, start=1))


def normalize_model_result_row(record: Dict[str, Any]) -> Dict[str, Any]:
    provided_fields = set(record.keys())
    confidence = record.get("confidence", 0.0)
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = 0.0

    feature_expression_items = normalize_feature_expression_items(record.get("feature_expression_items"))
    feature_expression_text = str(record.get("feature_expression_text", "")).strip()
    if not feature_expression_text:
        feature_expression_text = build_feature_expression_text_from_items(feature_expression_items)

    return {
        "_provided_fields": sorted(provided_fields),
        "result_id": str(record.get("result_id", "")).strip(),
        "row_id": str(record.get("row_id", "")).strip(),
        "project_code": str(record.get("project_code", "")).strip(),
        "project_name": str(record.get("project_name", "")).strip(),
        "quantity_component": str(record.get("quantity_component", "")).strip(),
        "resolved_component_name": str(record.get("resolved_component_name", "")).strip(),
        "source_component_name": str(record.get("source_component_name", "")).strip(),
        "match_status": str(record.get("match_status", "")).strip() or "matched",
        "match_basis": str(record.get("match_basis", "")).strip(),
        "confidence": max(0.0, min(1.0, confidence_value)),
        "feature_expression_items": feature_expression_items,
        "feature_expression_text": feature_expression_text,
        "calculation_item_name": str(record.get("calculation_item_name", "")).strip(),
        "calculation_item_code": str(record.get("calculation_item_code", "")).strip(),
        "measurement_unit": normalize_unit(str(record.get("measurement_unit", "")).strip()),
        "review_status": str(record.get("review_status", "")).strip() or "pending",
        "reasoning": str(record.get("reasoning", "")).strip(),
        "notes": str(record.get("notes", "")).strip(),
    }


def normalize_model_result_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    if not isinstance(meta, dict):
        meta = {}
    if not isinstance(rows, list):
        raise ValueError("模型输出中的 rows 字段必须为数组。")

    return {
        "meta": {
            "task_name": str(meta.get("task_name", "project_component_feature_calc_matching")),
            "standard_document": str(meta.get("standard_document", "")),
            "generated_at": str(meta.get("generated_at", datetime.now().astimezone().isoformat(timespec="seconds"))),
            "review_stage": str(meta.get("review_stage", "model_refine")),
        },
        "rows": [normalize_model_result_row(item) for item in rows if isinstance(item, dict)],
    }


def merge_model_row_with_local(model_row: Dict[str, Any], local_row: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(local_row)
    provided_fields = set(model_row.get("_provided_fields", []))
    for key, value in model_row.items():
        if key.startswith("_"):
            continue
        if provided_fields and key not in provided_fields and key != "result_id":
            continue
        if key == "feature_expression_items":
            merged[key] = value
            continue
        if isinstance(value, str):
            if value.strip():
                merged[key] = value.strip()
            continue
        if value not in (None, [], {}):
            merged[key] = value

    merged["confidence"] = max(0.0, min(1.0, float(merged.get("confidence", 0.0) or 0.0)))
    merged["feature_expression_items"] = normalize_feature_expression_items(merged.get("feature_expression_items"))
    merged["feature_expression_text"] = (
        str(merged.get("feature_expression_text", "")).strip()
        or build_feature_expression_text_from_items(merged["feature_expression_items"])
    )
    merged["review_status"] = str(merged.get("review_status", "")).strip() or "pending"
    merged["measurement_unit"] = normalize_unit(str(merged.get("measurement_unit", "")).strip())
    return merged


def ensure_all_rows_present(
    model_rows: Sequence[Dict[str, Any]],
    local_rows: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    local_by_result_id = {row["result_id"]: row for row in local_rows}
    model_by_result_id = {
        row["result_id"]: row
        for row in model_rows
        if str(row.get("result_id", "")).strip()
    }
    merged_rows: List[Dict[str, Any]] = []
    for local_row in local_rows:
        result_id = local_row["result_id"]
        if result_id in model_by_result_id:
            merged_rows.append(merge_model_row_with_local(model_by_result_id[result_id], local_row))
        else:
            merged_rows.append(dict(local_row))
    return merged_rows


def build_result_markdown(rows: Sequence[Dict[str, Any]]) -> str:
    lines = [
        "| 项目编码 | 项目名称 | 构件类型 | 项目特征表达式 | 计算项目 | 单位 | 匹配方式 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {project_code} | {project_name} | {quantity_component} | {feature_expression_text} | {calculation_item_code} | {measurement_unit} | {match_basis} |".format(
                project_code=row.get("project_code", ""),
                project_name=row.get("project_name", ""),
                quantity_component=row.get("quantity_component", ""),
                feature_expression_text=str(row.get("feature_expression_text", "")).replace("|", "\\|"),
                calculation_item_code=row.get("calculation_item_code", ""),
                measurement_unit=row.get("measurement_unit", ""),
                match_basis=row.get("match_basis", ""),
            )
        )
    return "\n".join(lines) + "\n"


def run_filter_condition_match(
    step1_table_regions_path: str | Path | None = None,
    components_path: str | Path | None = None,
    synonym_library_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    max_components_per_item: int = 3,
    step2_result_path: str | Path | None = None,
) -> Dict[str, Any]:
    step1_file = Path(step1_table_regions_path) if step1_table_regions_path else get_default_step1_table_regions_path()
    standard_document = build_standard_document_name(step1_file)
    components_file = Path(components_path) if components_path else get_default_components_path()
    synonym_file = (
        Path(synonym_library_path)
        if synonym_library_path
        else get_default_synonym_library_path(standard_document=standard_document, step2_result_path=step2_result_path)
    )
    output_path = Path(output_dir) if output_dir else get_default_output_dir(step1_file)

    step1_rows, chapter_rules = load_step1_rows_and_chapter_rules(step1_file)
    components_payload = load_json_or_jsonl(components_file)
    synonym_payload = load_json_or_jsonl(synonym_file) if synonym_file else {}

    source_table = build_component_source_table(components_payload, synonym_payload)
    alias_index = build_alias_index(source_table, synonym_payload)
    final_payload = build_local_match_payload(
        step1_rows=step1_rows,
        source_table=source_table,
        alias_index=alias_index,
        standard_document=standard_document,
        max_components_per_item=max_components_per_item,
    )
    final_payload["meta"].update(
        {
            "step1_table_regions_path": str(step1_file),
            "components_path": str(components_file),
            "synonym_library_path": str(synonym_file) if synonym_file else "",
            "chapter_rule_catalog_path": str(output_path / CHAPTER_RULE_JSON_NAME),
        }
    )

    source_table_payload = {
        "meta": {
            "task_name": "component_source_table",
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "components_path": str(components_file),
            "synonym_library_path": str(synonym_file) if synonym_file else "",
        },
        "components": source_table,
    }

    summary = {
        "status": "completed",
        "step1_table_regions_path": str(step1_file),
        "components_path": str(components_file),
        "synonym_library_path": str(synonym_file) if synonym_file else "",
        "output_dir": str(output_path),
        **final_payload["statistics"],
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }

    write_json(output_path / "normalized_step1_rows.json", step1_rows)
    write_json(output_path / CHAPTER_RULE_JSON_NAME, chapter_rules)
    write_json(output_path / "component_source_table.json", source_table_payload)
    write_json(output_path / LOCAL_JSON_NAME, final_payload)
    write_json(output_path / FINAL_JSON_NAME, final_payload)
    write_text(output_path / FINAL_MARKDOWN_NAME, build_result_markdown(final_payload["rows"]))
    write_json(output_path / "run_summary.json", summary)
    return summary


def run_filter_condition_pipeline(
    step1_table_regions_path: str | Path | None = None,
    components_path: str | Path | None = None,
    synonym_library_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str | None = "medium",
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    connection_retries: int = DEFAULT_CONNECTION_RETRIES,
    provider_mode: str | None = None,
    max_rows_per_batch: int = 40,
    max_components_per_item: int = 3,
    prepare_only: bool = False,
    local_only: bool = False,
    step2_result_path: str | Path | None = None,
) -> Dict[str, Any]:
    step1_file = Path(step1_table_regions_path) if step1_table_regions_path else get_default_step1_table_regions_path()
    standard_document = build_standard_document_name(step1_file)
    components_file = Path(components_path) if components_path else get_default_components_path()
    synonym_file = (
        Path(synonym_library_path)
        if synonym_library_path
        else get_default_synonym_library_path(standard_document=standard_document, step2_result_path=step2_result_path)
    )
    if not synonym_file:
        raise FileNotFoundError("未找到 Step 2 的 synonym_library.json。Step 3 需要完整的 Step 2 输出后才能运行。")
    output_path = Path(output_dir) if output_dir else get_default_output_dir(step1_file)
    step2_run_summary = ensure_complete_step2_outputs(
        step2_result_path=step2_result_path,
        synonym_library_path=synonym_file,
    )

    step1_rows, chapter_rules = load_step1_rows_and_chapter_rules(step1_file)
    components_payload = load_json_or_jsonl(components_file)
    synonym_payload = load_json_or_jsonl(synonym_file)

    source_table = build_component_source_table(components_payload, synonym_payload)
    alias_index = build_alias_index(source_table, synonym_payload)
    source_table_by_name = {entry["component_name"]: entry for entry in source_table}

    local_payload = build_local_match_payload(
        step1_rows=step1_rows,
        source_table=source_table,
        alias_index=alias_index,
        standard_document=standard_document,
        max_components_per_item=max_components_per_item,
    )
    local_payload["meta"].update(
        {
            "step1_table_regions_path": str(step1_file),
            "components_path": str(components_file),
            "synonym_library_path": str(synonym_file) if synonym_file else "",
            "chapter_rule_catalog_path": str(output_path / CHAPTER_RULE_JSON_NAME),
            "step2_run_summary_path": str(Path(synonym_file).parent / "run_summary.json"),
        }
    )

    local_rows = local_payload["rows"]
    local_rows_by_row_id: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in local_rows:
        local_rows_by_row_id[row["row_id"]].append(row)

    source_table_payload = {
        "meta": {
            "task_name": "component_source_table",
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "components_path": str(components_file),
            "synonym_library_path": str(synonym_file) if synonym_file else "",
        },
        "components": source_table,
    }

    write_json(output_path / "normalized_step1_rows.json", step1_rows)
    write_json(output_path / CHAPTER_RULE_JSON_NAME, chapter_rules)
    write_json(output_path / "component_source_table.json", source_table_payload)
    write_json(output_path / LOCAL_JSON_NAME, local_payload)
    # 生成工具 HTML（本地规则阶段预览），tools/ 中可立即查看
    _generate_tool_htmls(output_path)

    if local_only:
        final_payload = dict(local_payload)
        final_payload["meta"] = {
            **local_payload["meta"],
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "generation_mode": "local_rule",
        }
        summary = {
            "status": "completed_local_only",
            "step1_table_regions_path": str(step1_file),
            "components_path": str(components_file),
            "synonym_library_path": str(synonym_file) if synonym_file else "",
            "output_dir": str(output_path),
            "step2_status": step2_run_summary.get("status", ""),
            **final_payload["statistics"],
            "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        write_json(output_path / FINAL_JSON_NAME, final_payload)
        write_text(output_path / FINAL_MARKDOWN_NAME, build_result_markdown(final_payload["rows"]))
        build_step3_html_report(output_path)
        _generate_tool_htmls(output_path, output_path / FINAL_JSON_NAME)
        write_json(output_path / "run_summary.json", summary)
        return summary

    step1_batches = chunk_list(step1_rows, max_rows_per_batch)
    total_batches = len(step1_batches)
    batch_results: List[Dict[str, Any]] = []
    summary_path = output_path / "run_summary.json"
    startup_check: Dict[str, Any]
    if prepare_only:
        startup_check = {"status": "skipped", "reason": "prepare_only=true"}
    else:
        startup_check = {
            "status": "skipped",
            "reason": "startup_check_disabled_for_step3_runtime",
        }

    # Wiki retriever for component context injection
    wiki_retriever = WikiRetriever()

    for batch_number, batch_step1_rows in enumerate(step1_batches, start=1):
        local_batch_rows = [item for row in batch_step1_rows for item in local_rows_by_row_id.get(row["row_id"], [])]
        prompt_batch_payload = build_prompt_batch_payload(
            batch_step1_rows=batch_step1_rows,
            local_rows_by_row_id=local_rows_by_row_id,
            source_table_by_name=source_table_by_name,
        )
        # Wiki injection: extract unique component names from batch candidates
        batch_component_names = list({
            item.get("source_component_name", "")
            for row in batch_step1_rows
            for item in local_rows_by_row_id.get(row["row_id"], [])
            if item.get("source_component_name")
        })
        wiki_context = wiki_retriever.query_for_step3(batch_component_names)
        prompt_text = build_prompt_text(
            batch_step1_rows=batch_step1_rows,
            local_batch_rows=local_batch_rows,
            batch_payload=prompt_batch_payload,
            standard_document=standard_document,
            batch_index=batch_number,
            total_batches=total_batches,
            wiki_context=wiki_context,
        )

        write_json(output_path / f"batch_{batch_number:03d}_prompt_input.json", prompt_batch_payload)
        write_text(output_path / f"batch_{batch_number:03d}_prompt.txt", prompt_text)
        if wiki_context:
            write_text(output_path / f"batch_{batch_number:03d}_wiki.txt", wiki_context)

        if prepare_only:
            continue

        batch_result_path = output_path / f"batch_{batch_number:03d}_result.json"
        if batch_result_path.exists():
            try:
                with open(batch_result_path, "r", encoding="utf-8") as fb:
                    cached_payload = json.load(fb)
                batch_results.append(cached_payload)
                print(f"Skipping batch {batch_number}/{total_batches} (already completed)", flush=True)
                continue
            except Exception as e:
                print(f"Failed to load cached result for batch {batch_number}: {e}", flush=True)

        try:
            raw_response_text = call_openai_model(
                prompt_text=prompt_text,
                model=model,
                reasoning_effort=reasoning_effort,
                request_timeout_seconds=request_timeout_seconds,
                connection_retries=connection_retries,
                provider_mode=provider_mode,
                output_path=output_path,
                log_context={"batch_index": batch_number, "total_batches": total_batches},
            )
            write_text(output_path / f"batch_{batch_number:03d}_model_output.txt", raw_response_text)

            parsed_payload = normalize_model_result_payload(json.loads(extract_json_text(raw_response_text)))
            parsed_rows = ensure_all_rows_present(parsed_payload["rows"], local_batch_rows)
            batch_payload = {
                "meta": parsed_payload["meta"],
                "statistics": build_result_statistics(parsed_rows),
                "rows": parsed_rows,
                "unmatched_rows": build_unmatched_rows(parsed_rows),
            }
            write_json(output_path / f"batch_{batch_number:03d}_result.json", batch_payload)
            batch_results.append(batch_payload)
        except Exception as exc:
            error_payload = {
                "status": "failed",
                "step1_table_regions_path": str(step1_file),
                "components_path": str(components_file),
                "synonym_library_path": str(synonym_file) if synonym_file else "",
                "output_dir": str(output_path),
                "model": model,
                "reasoning_effort": reasoning_effort,
                "request_timeout_seconds": request_timeout_seconds,
                "connection_retries": connection_retries,
                "failed_batch": batch_number,
                "total_batches": total_batches,
                "error": str(exc),
                "failed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "hint": "如果结果目录里只有 batch_*_prompt.txt，说明大模型调用或结果解析阶段未完成。",
            }
            write_text(output_path / f"batch_{batch_number:03d}_error.txt", str(exc))
            write_json(summary_path, error_payload)
            raise

    if prepare_only:
        summary = {
            "status": "prepared_only",
            "step1_table_regions_path": str(step1_file),
            "components_path": str(components_file),
            "synonym_library_path": str(synonym_file) if synonym_file else "",
            "output_dir": str(output_path),
            "model": model,
            "reasoning_effort": reasoning_effort,
            "step2_status": step2_run_summary.get("status", ""),
            "total_rows": len(step1_rows),
            "total_batches": total_batches,
            "prepared_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "next_step": "去掉 --prepare-only 重新运行，脚本才会实际调用模型并生成最终结果。",
            "expected_missing_files": [
                "batch_001_model_output.txt",
                "batch_001_result.json",
                FINAL_JSON_NAME,
            ],
        }
        write_json(summary_path, summary)
        return summary

    merged_rows: List[Dict[str, Any]] = []
    for item in batch_results:
        merged_rows.extend(item["rows"])
    final_rows = ensure_all_rows_present(merged_rows, local_rows)
    final_payload = {
        "meta": {
            "task_name": "project_component_feature_calc_matching",
            "standard_document": standard_document,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "step1_table_regions_path": str(step1_file),
            "components_path": str(components_file),
            "synonym_library_path": str(synonym_file) if synonym_file else "",
            "chapter_rule_catalog_path": str(output_path / CHAPTER_RULE_JSON_NAME),
            "generation_mode": "model",
            "model": model,
            "reasoning_effort": reasoning_effort,
            "step2_run_summary_path": str(Path(synonym_file).parent / "run_summary.json"),
            "local_rule_baseline": str(output_path / LOCAL_JSON_NAME),
        },
        "statistics": build_result_statistics(final_rows),
        "rows": final_rows,
        "unmatched_rows": build_unmatched_rows(final_rows),
    }
    summary = {
        "status": "completed",
        "step1_table_regions_path": str(step1_file),
        "components_path": str(components_file),
        "synonym_library_path": str(synonym_file) if synonym_file else "",
        "output_dir": str(output_path),
        "model": model,
        "reasoning_effort": reasoning_effort,
        "step2_status": step2_run_summary.get("status", ""),
        "startup_connectivity_check": startup_check,
        "total_batches": total_batches,
        **final_payload["statistics"],
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }

    write_json(output_path / FINAL_JSON_NAME, final_payload)
    write_text(output_path / FINAL_MARKDOWN_NAME, build_result_markdown(final_rows))
    build_step3_html_report(output_path)
    _generate_tool_htmls(output_path, output_path / FINAL_JSON_NAME)
    write_json(output_path / "run_summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Step 3: build 清单-构件-项目特征表达式-计算项目 matching table from Step 1 + Step 2 synonym library."
    )
    parser.add_argument("--config", help="Path to runtime_config.ini. If omitted, pipeline_v2/step3_engine/runtime_config.ini will be used when present.")
    parser.add_argument("--step1-table-regions", help="Path to Step 1 table_regions.json")
    parser.add_argument("--step2-result", help="Optional Step 2 result path, used to infer sibling synonym_library.json")
    parser.add_argument("--components", help="Path to components.json or components.jsonl")
    parser.add_argument("--synonym-library", help="Optional synonym_library.json from Step 2")
    parser.add_argument("--output", help="Output directory, default: data/output/step3/<step1-parent>")
    parser.add_argument("--model", help="OpenAI model alias, default: gpt-5.4")
    parser.add_argument("--reasoning-effort", help="Reasoning effort passed to Responses API")
    parser.add_argument("--request-timeout-seconds", type=float, help="HTTP timeout seconds for model requests")
    parser.add_argument("--connection-retries", type=int, help="Connection retries for startup check and model requests")
    parser.add_argument("--max-rows-per-batch", type=int, help="Max Step 1 rows per prompt batch")
    parser.add_argument("--max-components-per-item", type=int, help="Max candidate components kept per item")
    parser.add_argument(
        "--prepare-only",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Only preprocess and write prompts, do not call the model",
    )
    parser.add_argument(
        "--local-only",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Only use local rules, skip model call",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runtime_options = resolve_runtime_options(args)
    previous_environment = apply_runtime_environment(runtime_options)
    try:
        summary = run_filter_condition_pipeline(
            step1_table_regions_path=runtime_options["step1_table_regions_path"],
            components_path=runtime_options["components_path"],
            synonym_library_path=runtime_options["synonym_library_path"],
            output_dir=runtime_options["output_dir"],
            model=runtime_options["model"],
            reasoning_effort=runtime_options["reasoning_effort"],
            request_timeout_seconds=runtime_options["request_timeout_seconds"],
            connection_retries=runtime_options["connection_retries"],
            max_rows_per_batch=runtime_options["max_rows_per_batch"],
            max_components_per_item=runtime_options["max_components_per_item"],
            prepare_only=runtime_options["prepare_only"],
            local_only=runtime_options["local_only"],
            step2_result_path=runtime_options["step2_result_path"],
        )
    except Exception as exc:
        print(f"[Step 3 错误] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        restore_runtime_environment(previous_environment)

    if runtime_options.get("config_path"):
        summary["config_path"] = runtime_options["config_path"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
