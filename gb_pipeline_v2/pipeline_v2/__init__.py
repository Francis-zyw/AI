from __future__ import annotations

from importlib import import_module


_EXPORT_MAP = {
    "audit_project": (".audit", "audit_project"),
    "build_redesign_plan": (".audit", "build_redesign_plan"),
    "render_markdown_report": (".audit", "render_markdown_report"),
    "step2_prepare": (".step2_v2", "prepare"),
    "load_all_bill_chapters": (".step2_v2", "load_all_bill_chapters"),
    "match_bill_items_to_component": (".step3_v2", "match_bill_items_to_component"),
    "direct_match_bill_item": (".step4_direct_match", "direct_match_bill_item"),
    "direct_match_bill_items": (".step4_direct_match", "direct_match_bill_items"),
}

__all__ = [
    "audit_project",
    "build_redesign_plan",
    "render_markdown_report",
    "step2_prepare",
    "load_all_bill_chapters",
    "match_bill_items_to_component",
    "direct_match_bill_item",
    "direct_match_bill_items",
]


def __getattr__(name: str):
    if name not in _EXPORT_MAP:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _EXPORT_MAP[name]
    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value
