"""
Step5 项目特征审核导出工具 v2

读取 Step3 匹配结果，提取所有项目特征 (feature_expression_items，含已匹配和未匹配)，
按 source_component|label 聚合去重，生成可交互式审核/标记/导出的单页 HTML 工具。

v2 增强:
- 展示全部特征（已匹配+未匹配），已匹配绿色显示属性绑定
- 间歇性匹配失败自动检测（同 comp|label 部分匹配部分不匹配）
- 构件属性参考面板（加载 component_source_table.json）
- Wiki 知识沉淀导出（wiki_patch.json，兼容 wiki_patch_import.py）
- 新增状态：匹配失败-需沉淀

功能概览:
- 仪表盘: 总特征数 / 未处理 / 待补充 / 无需补充 / 待确认 / 需沉淀 + 进度条
- 左侧: 构件类型列表（按特征数降序）
- 主区: 筛选栏（含匹配状态）+ 属性参考面板 + 虚拟滚动特征列表
- 每条支持: 状态标记 / 批注 / 查看来源行
- 批量操作: 全选/反选、批量设状态
- 导出: Excel(多sheet) + JSON + Wiki补丁 + 进度保存/恢复
- 持久化: localStorage 自动保存审核状态
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

# ──────────────────────────── Defaults ────────────────────────────
DEFAULT_STEP3_RESULT = "data/output/step3/run-20260416-full/project_component_feature_calc_matching_result.json"
DEFAULT_COMPONENTS = "data/input/components.json"
DEFAULT_COMP_SOURCE_TABLE = "data/output/step3/run-20260416-full/component_source_table.json"
DEFAULT_OUTPUT_DIR = "data/output/step5"
OUTPUT_HTML_NAME = "feature_audit_tool.html"


def _esc(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        v = json.dumps(v, ensure_ascii=False)
    return html_mod.escape(str(v))


# ──────────────────────── Data Loading ─────────────────────────
def load_step3_results(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    rows = data.get("rows", [])
    meta = data.get("meta", {})
    print(f"  Step3 结果: {len(rows)} 行")
    return {"rows": rows, "meta": meta}


def load_components_library(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        comps = json.load(f)
    print(f"  构件库: {len(comps)} 种构件类型")
    return comps


def load_component_source_table(path: Path) -> list[dict]:
    """加载 component_source_table.json，返回 components 列表。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    comps = data.get("components", [])
    print(f"  构件来源表: {len(comps)} 种构件类型")
    return comps


# ──────────────────── Extract & Aggregate ───────────────────
def extract_all_items(rows: list[dict]) -> list[dict]:
    """遍历所有行的 feature_expression_items，提取全部条目（含已匹配和未匹配）。"""
    items = []
    for r in rows:
        comp = r.get("source_component_name", "") or r.get("resolved_component_name", "") or "未知构件"
        row_id = r.get("row_id", r.get("result_id", ""))
        project_code = r.get("project_code", "")
        project_name = r.get("project_name", "")
        for fei in r.get("feature_expression_items", []):
            items.append({
                "source_component": comp,
                "label": fei.get("label", fei.get("raw_text", "")),
                "raw_text": fei.get("raw_text", ""),
                "attribute_name": fei.get("attribute_name", ""),
                "attribute_code": fei.get("attribute_code", ""),
                "value_expression": fei.get("value_expression", ""),
                "expression": fei.get("expression", ""),
                "matched": bool(fei.get("matched", False)),
                "row_id": row_id,
                "project_code": project_code,
                "project_name": project_name,
            })
    matched = sum(1 for it in items if it["matched"])
    print(f"  全部特征条目: {len(items)} (已匹配 {matched}, 未匹配 {len(items) - matched})")
    return items


def aggregate_by_component(items: list[dict]) -> list[dict]:
    """按 source_component|label 合并，计算出现次数，检测间歇性匹配失败。"""
    groups: dict[str, dict] = {}
    for it in items:
        key = f"{it['source_component']}|{it['label']}"
        if key not in groups:
            groups[key] = {
                "item_key": key,
                "source_component": it["source_component"],
                "label": it["label"],
                "raw_text": it["raw_text"],
                "attribute_name": "",
                "attribute_code": "",
                "occurrence_count": 0,
                "matched_count": 0,
                "unmatched_count": 0,
                "value_samples": [],
                "source_rows": [],
            }
        g = groups[key]
        g["occurrence_count"] += 1
        if it["matched"]:
            g["matched_count"] += 1
            # Use attribute info from matched FEI (first wins)
            if not g["attribute_name"] and it.get("attribute_name"):
                g["attribute_name"] = it["attribute_name"]
                g["attribute_code"] = it.get("attribute_code", "")
        else:
            g["unmatched_count"] += 1
        ve = it.get("value_expression", "")
        if ve and ve not in g["value_samples"] and len(g["value_samples"]) < 3:
            g["value_samples"].append(ve)
        g["source_rows"].append({
            "row_id": it["row_id"],
            "project_code": it["project_code"],
            "project_name": it["project_name"],
            "expression": it.get("expression", ""),
            "matched": it["matched"],
        })

    # Determine match_type for each group
    for g in groups.values():
        if g["matched_count"] > 0 and g["unmatched_count"] > 0:
            g["match_type"] = "intermittent"
        elif g["matched_count"] > 0:
            g["match_type"] = "matched"
        else:
            g["match_type"] = "unmatched"

    result = sorted(groups.values(), key=lambda x: (
        0 if x["match_type"] == "intermittent" else 1 if x["match_type"] == "unmatched" else 2,
        -x["occurrence_count"],
        x["source_component"],
        x["label"],
    ))
    matched_g = sum(1 for g in result if g["match_type"] == "matched")
    unmatched_g = sum(1 for g in result if g["match_type"] == "unmatched")
    intermittent_g = sum(1 for g in result if g["match_type"] == "intermittent")
    print(f"  聚合后: {len(result)} 条 (已匹配 {matched_g}, 未匹配 {unmatched_g}, 间歇性 {intermittent_g})")
    return result


def build_stats(audit_items: list[dict], rows: list[dict]) -> dict:
    total_fei = sum(len(r.get("feature_expression_items", [])) for r in rows)
    total_matched = sum(
        1 for r in rows for f in r.get("feature_expression_items", []) if f.get("matched")
    )
    total_unmatched = total_fei - total_matched

    # By component (all items)
    by_comp: dict[str, dict] = {}
    for g in audit_items:
        comp = g["source_component"]
        if comp not in by_comp:
            by_comp[comp] = {"total": 0, "matched": 0, "unmatched": 0, "intermittent": 0}
        by_comp[comp]["total"] += 1
        by_comp[comp][g["match_type"]] += 1
    comp_ranking = sorted(by_comp.items(), key=lambda x: -x[1]["total"])

    # Top labels (unmatched + intermittent only)
    label_counts = Counter(
        g["label"] for g in audit_items if g["match_type"] != "matched"
    )
    top_labels = label_counts.most_common(30)

    return {
        "total_fei": total_fei,
        "total_matched": total_matched,
        "total_unmatched": total_unmatched,
        "total_items": len(audit_items),
        "total_matched_items": sum(1 for g in audit_items if g["match_type"] == "matched"),
        "total_unmatched_items": sum(1 for g in audit_items if g["match_type"] == "unmatched"),
        "total_intermittent_items": sum(1 for g in audit_items if g["match_type"] == "intermittent"),
        "total_components": len(by_comp),
        "comp_ranking": comp_ranking,
        "top_labels": top_labels,
    }


# ──────────────────── Build Component References ──────────────────
def build_comp_ref(components: list[dict]) -> dict:
    """将 components.json 转为前端可用的引用字典。"""
    ref = {}
    for c in components:
        ct = c.get("component_type", "")
        props = c.get("properties", {})
        ref[ct] = {
            "attributes": [
                {"name": a.get("name", ""), "code": a.get("code", ""), "data_type": a.get("data_type", ""), "values": a.get("values", [])}
                for a in props.get("attributes", [])
            ],
            "calculations": [
                {"name": ca.get("name", ""), "code": ca.get("code", ""), "unit": ca.get("unit", "")}
                for ca in props.get("calculations", [])
            ],
        }
    return ref


def build_comp_source_ref(comp_source_table: list[dict]) -> dict:
    """将 component_source_table.json 转为 {构件名: {attributes: [...]}} 字典。"""
    ref = {}
    for c in comp_source_table:
        name = c.get("component_name", "")
        attrs = [
            {
                "name": a.get("name", ""),
                "code": a.get("code", ""),
                "data_type": a.get("data_type", ""),
                "values": a.get("values", []),
                "source_sheet": a.get("source_sheet", ""),
            }
            for a in c.get("attributes", [])
        ]
        ref[name] = {"attributes": attrs}
        # Also map aliases
        for alias in c.get("aliases", []):
            if alias and alias != name and alias not in ref:
                ref[alias] = {"attributes": attrs}
    return ref


# ──────────────────────── Build HTML ─────────────────────────
def build_audit_html(audit_items: list[dict], comp_ref: dict, comp_source_ref: dict,
                     stats: dict, meta: dict) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    std_doc = _esc(meta.get("standard_document", ""))

    # Escape </script> in JSON to prevent script tag breakout (security)
    audit_json = json.dumps(audit_items, ensure_ascii=False).replace("</", "<\\/")
    comp_ref_json = json.dumps(comp_ref, ensure_ascii=False).replace("</", "<\\/")
    comp_src_json = json.dumps(comp_source_ref, ensure_ascii=False).replace("</", "<\\/")
    stats_json = json.dumps(stats, ensure_ascii=False).replace("</", "<\\/")

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Step5 项目特征审核导出工具 v2</title>
<script src="https://cdn.sheetjs.com/xlsx-0.20.3/package/dist/xlsx.full.min.js"></script>
<style>
:root {{
  color-scheme: light;
  --bg: #f8fafc;
  --card: #ffffff;
  --card2: #f1f5f9;
  --border: #e2e8f0;
  --text: #1e293b;
  --muted: #64748b;
  --blue: #3b82f6;
  --blue-light: #eff6ff;
  --green: #16a34a;
  --green-light: #f0fdf4;
  --orange: #d97706;
  --orange-light: #fffbeb;
  --red: #dc2626;
  --red-light: #fef2f2;
  --purple: #7c3aed;
  --purple-light: #f5f3ff;
  --teal: #0d9488;
  --teal-light: #f0fdfa;
  --radius: 10px;
  --shadow: 0 1px 3px rgba(0,0,0,.08);
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  background: var(--bg);
  color: var(--text);
  font-size: 14px;
  line-height: 1.5;
}}
.wrap {{ max-width: 1800px; margin: 0 auto; padding: 12px 20px; }}
h1 {{ font-size: 20px; font-weight: 700; }}
.muted {{ color: var(--muted); font-size: 13px; }}

/* ─── Dashboard ─── */
.dashboard {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(155px, 1fr));
  gap: 10px;
  margin: 14px 0;
}}
.stat-card {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px 14px;
  cursor: pointer;
  transition: all .15s;
  box-shadow: var(--shadow);
}}
.stat-card:hover {{ border-color: var(--blue); transform: translateY(-1px); }}
.stat-card.active {{ border-color: var(--blue); background: var(--blue-light); }}
.stat-card .label {{ font-size: 12px; color: var(--muted); margin-bottom: 3px; }}
.stat-card .value {{ font-size: 24px; font-weight: 700; }}
.stat-card .sub {{ font-size: 11px; color: var(--muted); margin-top: 2px; }}
.stat-card.card-total .value {{ color: var(--text); }}
.stat-card.card-pending .value {{ color: var(--orange); }}
.stat-card.card-no-need .value {{ color: var(--green); }}
.stat-card.card-confirm .value {{ color: var(--blue); }}
.stat-card.card-to-fill .value {{ color: var(--red); }}
.stat-card.card-wiki .value {{ color: var(--purple); }}
.progress-bar {{ height: 6px; background: var(--card2); border-radius: 3px; margin: 8px 0 2px; overflow: hidden; }}
.progress-fill {{ height: 100%; background: linear-gradient(90deg, var(--green), var(--blue)); border-radius: 3px; transition: width .3s; }}

/* ─── Main Grid ─── */
.main-grid {{
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 12px;
  margin-top: 8px;
}}

/* ─── ComponentTree ─── */
.comp-tree {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px 0;
  max-height: calc(100vh - 240px);
  overflow-y: auto;
  position: sticky;
  top: 12px;
  box-shadow: var(--shadow);
}}
.comp-item {{
  padding: 6px 12px;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  transition: background .1s;
  font-size: 13px;
  gap: 4px;
}}
.comp-item:hover {{ background: var(--card2); }}
.comp-item.active {{ background: var(--blue-light); color: var(--blue); font-weight: 600; }}
.comp-item .badge {{
  background: var(--card2);
  color: var(--muted);
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 10px;
  font-weight: 600;
  min-width: 26px;
  text-align: center;
  flex-shrink: 0;
}}
.comp-item.active .badge {{ background: var(--blue); color: #fff; }}
.comp-item .comp-name {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}

/* ─── Content Area ─── */
.content-area {{ min-height: 60vh; }}

/* ─── Attribute Reference Panel ─── */
.attr-panel {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: 10px;
  box-shadow: var(--shadow);
  overflow: hidden;
  transition: max-height .3s;
}}
.attr-panel.collapsed {{ max-height: 40px; }}
.attr-panel-header {{
  padding: 8px 14px;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 600;
  color: var(--teal);
  background: var(--teal-light);
  user-select: none;
}}
.attr-panel-header:hover {{ filter: brightness(0.96); }}
.attr-panel-body {{
  padding: 8px 14px;
  max-height: 200px;
  overflow-y: auto;
}}
.attr-panel.collapsed .attr-panel-body {{ display: none; }}
.attr-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 6px;
}}
.attr-tag {{
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: var(--card2);
  border-radius: 6px;
  font-size: 12px;
  border: 1px solid var(--border);
}}
.attr-tag .attr-name {{ font-weight: 600; }}
.attr-tag .attr-code {{ color: var(--muted); }}
.attr-tag .attr-type {{ font-size: 10px; color: var(--teal); margin-left: auto; }}
.attr-empty {{ color: var(--muted); font-size: 13px; padding: 8px 0; }}

/* ─── FilterBar ─── */
.filter-bar {{
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 10px;
}}
.filter-bar input[type=text] {{
  flex: 1;
  min-width: 160px;
  padding: 7px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 13px;
  background: var(--card);
}}
.filter-bar select {{
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 13px;
  background: var(--card);
}}
.filter-bar input:focus, .filter-bar select:focus {{
  outline: none;
  border-color: var(--blue);
}}
.match-count {{
  font-size: 12px;
  color: var(--muted);
  white-space: nowrap;
}}

/* ─── ActionBar ─── */
.action-bar {{
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  padding: 8px 12px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: 10px;
  box-shadow: var(--shadow);
}}
.action-bar .sel-info {{ font-size: 12px; color: var(--muted); margin-right: auto; }}

/* ─── Buttons ─── */
.btn {{
  padding: 6px 12px;
  border: none;
  border-radius: 7px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  transition: all .15s;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}}
.btn:hover {{ filter: brightness(0.92); }}
.btn:disabled {{ opacity: 0.4; cursor: not-allowed; filter: none; }}
.btn-blue {{ background: var(--blue); color: #fff; }}
.btn-green {{ background: var(--green); color: #fff; }}
.btn-orange {{ background: var(--orange); color: #fff; }}
.btn-red {{ background: var(--red); color: #fff; }}
.btn-purple {{ background: var(--purple); color: #fff; }}
.btn-outline {{
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text);
}}
.btn-outline:hover {{ border-color: var(--blue); color: var(--blue); }}

/* ─── Audit Item List + Virtual Scroll ─── */
.gap-list-container {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  box-shadow: var(--shadow);
}}
.gap-list-viewport {{
  height: calc(100vh - 380px);
  min-height: 400px;
  overflow-y: auto;
  position: relative;
}}
.gap-list-spacer {{ position: relative; }}

/* ─── Audit Card ─── */
.gap-card {{
  position: absolute;
  left: 0;
  right: 0;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  display: grid;
  grid-template-columns: 28px 1fr auto;
  gap: 10px;
  align-items: start;
  transition: background .1s;
}}
.gap-card:hover {{ background: var(--card2); }}
.gap-card input[type=checkbox] {{ margin-top: 3px; width: 16px; height: 16px; cursor: pointer; accent-color: var(--blue); }}
.gap-card .card-body {{ min-width: 0; }}
.gap-card .card-label {{ font-weight: 600; font-size: 14px; }}
.gap-card .card-comp {{ font-size: 12px; color: var(--muted); }}
.gap-card .card-occ {{
  display: inline-block;
  background: var(--orange-light);
  color: var(--orange);
  font-size: 11px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 8px;
  margin-left: 6px;
}}
.gap-card .card-samples {{ font-size: 12px; color: var(--muted); margin-top: 3px; }}
.gap-card .card-attr-badge {{
  display: inline-block;
  background: var(--green-light);
  color: var(--green);
  font-size: 11px;
  font-weight: 600;
  padding: 1px 8px;
  border-radius: 8px;
  margin-left: 6px;
}}
.gap-card .card-warn-badge {{
  display: inline-block;
  background: var(--orange-light);
  color: var(--orange);
  font-size: 11px;
  font-weight: 600;
  padding: 1px 8px;
  border-radius: 8px;
  margin-left: 6px;
}}
.gap-card .card-actions {{ display: flex; gap: 6px; align-items: center; flex-shrink: 0; }}
.gap-card .card-actions select {{
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 12px;
  background: var(--card);
}}
.gap-card .note-input {{
  width: 130px;
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 12px;
  background: var(--card);
}}
.gap-card .note-input:focus {{ border-color: var(--blue); outline: none; }}
.gap-card .src-toggle {{
  font-size: 11px;
  color: var(--blue);
  cursor: pointer;
  text-decoration: underline;
  white-space: nowrap;
}}

/* Match type card styles */
.gap-card.match-matched {{
  border-left: 3px solid var(--green);
  background: var(--green-light);
  grid-template-columns: 1fr auto;
}}
.gap-card.match-matched:hover {{ background: #e8fce8; }}
.gap-card.match-intermittent {{ border-left: 3px solid var(--orange); }}

/* Status colors on card (for unmatched/intermittent) */
.gap-card.status-to-fill {{ border-left: 3px solid var(--red); }}
.gap-card.status-no-need {{ border-left: 3px solid var(--green); background: var(--green-light); }}
.gap-card.status-to-confirm {{ border-left: 3px solid var(--blue); background: var(--blue-light); }}
.gap-card.status-match-fail-wiki {{ border-left: 3px solid var(--purple); background: var(--purple-light); }}

/* Source rows popup */
.src-popup {{
  position: fixed;
  z-index: 200;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: 0 4px 20px rgba(0,0,0,.15);
  padding: 12px;
  max-width: 500px;
  max-height: 300px;
  overflow-y: auto;
  font-size: 12px;
}}
.src-popup .src-row {{ padding: 3px 0; border-bottom: 1px solid var(--border); }}
.src-popup .src-row:last-child {{ border-bottom: none; }}
.src-popup .close-btn {{ float: right; cursor: pointer; font-weight: 700; color: var(--muted); }}

/* ─── Toast ─── */
.toast {{
  position: fixed;
  top: 16px;
  right: 16px;
  padding: 10px 18px;
  border-radius: 8px;
  color: #fff;
  font-weight: 600;
  font-size: 13px;
  z-index: 500;
  opacity: 0;
  transition: opacity .3s;
  pointer-events: none;
}}
.toast.show {{ opacity: 1; }}
.toast-ok {{ background: var(--green); }}
.toast-err {{ background: var(--red); }}

/* ─── Modals ─── */
.modal-overlay {{
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.45);
  z-index: 600;
  justify-content: center;
  align-items: center;
}}
.modal-overlay.show {{ display: flex; }}
.modal {{
  background: var(--card);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0,0,0,.2);
  width: 90%;
  max-width: 640px;
  max-height: 80vh;
  overflow-y: auto;
  padding: 20px 24px;
}}
.modal h3 {{ margin: 0 0 12px; font-size: 16px; }}
.modal .form-group {{ margin-bottom: 12px; }}
.modal .form-group label {{ display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }}
.modal .form-group input,
.modal .form-group select,
.modal .form-group textarea {{
  width: 100%;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
  background: var(--bg);
  box-sizing: border-box;
}}
.modal .form-group textarea {{ resize: vertical; min-height: 60px; }}
.modal .modal-actions {{ display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px; }}
.modal .diff-list {{ max-height: 300px; overflow-y: auto; }}
.modal .diff-row {{ display: flex; gap: 8px; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 12px; }}
.modal .diff-row:last-child {{ border-bottom: none; }}
.modal .diff-added {{ color: var(--green); font-weight: 600; }}
.modal .diff-modified {{ color: var(--orange); font-weight: 600; }}
.modal .diff-ignored {{ color: var(--muted); text-decoration: line-through; }}
.gap-card .card-manual-badge {{
  display: inline-block;
  background: var(--blue-light);
  color: var(--blue);
  font-size: 11px;
  font-weight: 600;
  padding: 1px 8px;
  border-radius: 8px;
  border: 1px dashed var(--blue);
  margin-left: 6px;
}}

/* ─── Responsive ─── */
@media (max-width: 900px) {{
  .main-grid {{ grid-template-columns: 1fr; }}
  .comp-tree {{
    position: static;
    max-height: none;
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    padding: 8px;
  }}
  .comp-item {{ padding: 4px 10px; border-radius: 6px; background: var(--card2); }}
}}
</style>
</head>
<body>
<div class="wrap">
  <h1>Step5 项目特征审核导出工具 <span style="font-size:12px;color:var(--muted);font-weight:400;">v2</span></h1>
  <p class="muted">{std_doc} &mdash; 生成时间 {ts} &mdash; 全部特征审核（已匹配+未匹配）、知识沉淀、导出</p>

  <!-- Dashboard -->
  <div class="dashboard" id="dashboard">
    <div class="stat-card card-total" data-filter="" onclick="dashFilter('')">
      <div class="label">总特征数</div>
      <div class="value" id="stat-total">0</div>
      <div class="sub">已匹配 <span id="stat-matched-items">0</span> / 未匹配 <span id="stat-unmatched-items">0</span></div>
    </div>
    <div class="stat-card card-pending" data-filter="pending" onclick="dashFilter('pending')">
      <div class="label">⏳ 未处理</div>
      <div class="value" id="stat-pending">0</div>
    </div>
    <div class="stat-card card-to-fill" data-filter="to-fill" onclick="dashFilter('to-fill')">
      <div class="label">🔴 待补充</div>
      <div class="value" id="stat-to-fill">0</div>
    </div>
    <div class="stat-card card-no-need" data-filter="no-need" onclick="dashFilter('no-need')">
      <div class="label">✅ 无需补充</div>
      <div class="value" id="stat-no-need">0</div>
    </div>
    <div class="stat-card card-confirm" data-filter="to-confirm" onclick="dashFilter('to-confirm')">
      <div class="label">🔵 待确认</div>
      <div class="value" id="stat-to-confirm">0</div>
    </div>
    <div class="stat-card card-wiki" data-filter="match-fail-wiki" onclick="dashFilter('match-fail-wiki')">
      <div class="label">🔶 需沉淀</div>
      <div class="value" id="stat-wiki">0</div>
    </div>
  </div>
  <div class="progress-bar"><div class="progress-fill" id="progressFill" style="width:0%"></div></div>
  <div class="muted" id="progressText" style="text-align:center;font-size:12px;margin-bottom:8px;">已处理 0 / 0 条（仅计未匹配+间歇性）</div>

  <!-- Main Grid -->
  <div class="main-grid">
    <!-- ComponentTree -->
    <div class="comp-tree" id="compTree"></div>

    <!-- Content -->
    <div class="content-area">
      <!-- Attribute Reference Panel -->
      <div class="attr-panel collapsed" id="attrPanel">
        <div class="attr-panel-header" onclick="toggleAttrPanel()">
          <span id="attrPanelTitle">📋 构件属性参考（选择构件后展示）</span>
          <span id="attrPanelToggle">▼</span>
        </div>
        <div class="attr-panel-body" id="attrPanelBody">
          <div class="attr-empty">请在左侧选择一个构件类型</div>
        </div>
      </div>

      <!-- FilterBar -->
      <div class="filter-bar">
        <input type="text" id="searchInput" placeholder="搜索标签、原始文本、值表达式..." />
        <select id="filterMatchType">
          <option value="">全部匹配状态</option>
          <option value="matched">已匹配</option>
          <option value="unmatched">未匹配</option>
          <option value="intermittent">间歇性失败</option>
        </select>
        <select id="filterStatus">
          <option value="">全部审核状态</option>
          <option value="pending">未处理</option>
          <option value="to-fill">待补充</option>
          <option value="no-need">无需补充</option>
          <option value="to-confirm">待确认</option>
          <option value="match-fail-wiki">需沉淀</option>
        </select>
        <select id="filterLabel">
          <option value="">全部标签</option>
        </select>
        <span class="match-count" id="matchCount"></span>
      </div>

      <!-- ActionBar -->
      <div class="action-bar">
        <label style="font-size:12px;display:flex;align-items:center;gap:4px;cursor:pointer;">
          <input type="checkbox" id="selectAll" onchange="toggleSelectAll(this.checked)" /> 全选
        </label>
        <span class="sel-info" id="selInfo">已选 0 / 共 0 条</span>
        <select id="batchStatus" style="padding:5px 8px;border:1px solid var(--border);border-radius:6px;font-size:12px;">
          <option value="">批量设置状态...</option>
          <option value="to-fill">标记为 待补充</option>
          <option value="no-need">标记为 无需补充</option>
          <option value="to-confirm">标记为 待确认</option>
          <option value="match-fail-wiki">标记为 需沉淀</option>
          <option value="pending">重置为 未处理</option>
        </select>
        <button class="btn btn-blue" onclick="applyBatchStatus()">应用</button>
        <button class="btn btn-blue" onclick="openBatchEdit()" title="批量绑定属性（需先选择条目）">🔗 批量绑定</button>
        <button class="btn btn-green" onclick="exportExcel()">📊 导出 Excel</button>
        <button class="btn btn-orange" onclick="exportJSON()">📄 导出 JSON</button>
        <button class="btn btn-purple" id="btnWikiPatch" onclick="exportWikiPatch()" disabled title="请先标记需沉淀的条目">🔶 导出 Wiki 补丁</button>
        <button class="btn btn-outline" onclick="saveProgress()">💾 保存进度</button>
        <button class="btn btn-outline" onclick="loadProgressFile()">📂 恢复进度</button>
        <button class="btn btn-outline" onclick="document.getElementById('xlsxImportInput').click()">📥 导入 Excel</button>
        <button class="btn btn-outline" id="btnAddFeature" onclick="openAddFeatureDialog()" disabled title="请先选择一个构件类型">➕ 添加特征</button>
      </div>

      <!-- Virtual scroll list -->
      <div class="gap-list-container">
        <div class="gap-list-viewport" id="viewport">
          <div class="gap-list-spacer" id="spacer"></div>
        </div>
      </div>
    </div>
  </div>
</div>

<div id="toast" class="toast"></div>
<div id="srcPopup" class="src-popup" style="display:none;"></div>
<input type="file" id="fileInput" accept=".json" style="display:none" onchange="handleProgressUpload(event)" />
<input type="file" id="xlsxImportInput" accept=".xlsx,.xls" style="display:none" onchange="handleExcelImport(event)" />

<!-- Import Dialog -->
<div class="modal-overlay" id="importModal">
  <div class="modal">
    <h3>📥 导入 Excel 回填数据</h3>
    <p style="font-size:12px;color:var(--muted);">从导出的 Excel 中读取 K(回填-属性名) / L(回填-属性编码) / M(回填-值域) 列，与原数据对比</p>
    <div id="importDiffList" class="diff-list"></div>
    <div class="modal-actions">
      <button class="btn btn-outline" onclick="closeModal('importModal')">取消</button>
      <button class="btn btn-green" id="btnConfirmImport" onclick="confirmImport()" disabled>确认导入</button>
      <button class="btn btn-purple" id="btnGenPatch" onclick="generateComponentsPatch()" style="display:none">生成构件补丁</button>
    </div>
  </div>
</div>

<!-- Edit Modal -->
<div class="modal-overlay" id="editModal">
  <div class="modal">
    <h3>✏️ 编辑特征属性绑定</h3>
    <div id="editInfo" style="font-size:12px;color:var(--muted);margin-bottom:8px;"></div>
    <div class="form-group">
      <label>特征标签</label>
      <input type="text" id="editLabel" readonly style="background:var(--card2);" />
    </div>
    <div class="form-group">
      <label>属性名称</label>
      <select id="editAttrName" onchange="onEditAttrChange()">
        <option value="">-- 请选择属性 --</option>
      </select>
    </div>
    <div class="form-group">
      <label>属性编码</label>
      <input type="text" id="editAttrCode" readonly style="background:var(--card2);" />
    </div>
    <div class="form-group">
      <label>值域表达式</label>
      <input type="text" id="editValueExpr" placeholder="留空则不修改" />
    </div>
    <div class="modal-actions">
      <button class="btn btn-outline" onclick="closeModal('editModal')">取消</button>
      <button class="btn btn-blue" onclick="confirmEdit()">保存</button>
    </div>
  </div>
</div>

<!-- Add Feature Dialog -->
<div class="modal-overlay" id="addFeatureModal">
  <div class="modal">
    <h3>➕ 添加新特征</h3>
    <div id="addFeatureComp" style="font-size:12px;color:var(--muted);margin-bottom:8px;"></div>
    <div class="form-group">
      <label>特征标签 <span style="color:var(--red);">*</span></label>
      <input type="text" id="addLabel" placeholder="例如: 防护材料种类" />
    </div>
    <div class="form-group">
      <label>属性名称</label>
      <select id="addAttrName" onchange="onAddAttrChange()">
        <option value="">-- 选择属性(可选) --</option>
      </select>
    </div>
    <div class="form-group">
      <label>属性编码</label>
      <input type="text" id="addAttrCode" readonly style="background:var(--card2);" />
    </div>
    <div class="form-group">
      <label>值域表达式（可选）</label>
      <input type="text" id="addValueExpr" placeholder="例如: HRB400" />
    </div>
    <div class="modal-actions">
      <button class="btn btn-outline" onclick="closeModal('addFeatureModal')">取消</button>
      <button class="btn btn-green" onclick="confirmAddFeature()">添加</button>
    </div>
  </div>
</div>

<script>
// ═══════════════════════════════════════════════════════════════
// DATA INJECTION
// ═══════════════════════════════════════════════════════════════
const AUDIT_DATA = {audit_json};
const COMP_REF = {comp_ref_json};
const COMP_SOURCE = {comp_src_json};
const INIT_STATS = {stats_json};

// ═══════════════════════════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════════════════════════
const STORAGE_KEY = 'step5_audit_v2_progress';
const auditState = {{}};
const selected = new Set();

let activeComp = '';
let activeStatus = '';
let filteredItems = [];
let currentQuery = '';
let attrPanelOpen = false;

function loadLocalState() {{
  try {{
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {{
      const obj = JSON.parse(saved);
      Object.assign(auditState, obj);
      console.log('Restored audit state:', Object.keys(obj).length, 'items');
    }}
  }} catch(e) {{ console.warn('localStorage restore failed:', e); }}
}}

function saveLocalState() {{
  try {{
    localStorage.setItem(STORAGE_KEY, JSON.stringify(auditState));
  }} catch(e) {{ console.warn('localStorage save failed:', e); }}
}}

function getStatus(itemKey) {{
  return (auditState[itemKey] || {{}}).status || 'pending';
}}
function getNote(itemKey) {{
  return (auditState[itemKey] || {{}}).note || '';
}}
function setAudit(itemKey, status, note) {{
  if (!auditState[itemKey]) auditState[itemKey] = {{}};
  if (status !== undefined) auditState[itemKey].status = status;
  if (note !== undefined) auditState[itemKey].note = note;
  saveLocalState();
  updateDashboard();
}}

// ═══════════════════════════════════════════════════════════════
// DASHBOARD
// ═══════════════════════════════════════════════════════════════
function updateDashboard() {{
  // Only count non-matched items for audit stats
  let pending=0, toFill=0, noNeed=0, toConfirm=0, wikiCount=0;
  let auditableCount = 0;
  let matchedItems = 0, unmatchedItems = 0;
  for (const g of AUDIT_DATA) {{
    if (g.match_type === 'matched') {{
      matchedItems++;
      continue;
    }}
    if (g.match_type === 'intermittent') matchedItems++; // count in both
    unmatchedItems++;
    auditableCount++;
    const s = getStatus(g.item_key);
    if (s === 'pending') pending++;
    else if (s === 'to-fill') toFill++;
    else if (s === 'no-need') noNeed++;
    else if (s === 'to-confirm') toConfirm++;
    else if (s === 'match-fail-wiki') wikiCount++;
  }}
  matchedItems += INIT_STATS.total_matched_items || 0;
  // Fix: use actual counts from data
  matchedItems = AUDIT_DATA.filter(g => g.match_type === 'matched').length;
  unmatchedItems = AUDIT_DATA.filter(g => g.match_type !== 'matched').length;
  const processed = auditableCount - pending;

  document.getElementById('stat-total').textContent = AUDIT_DATA.length;
  document.getElementById('stat-matched-items').textContent = matchedItems;
  document.getElementById('stat-unmatched-items').textContent = unmatchedItems;
  document.getElementById('stat-pending').textContent = pending;
  document.getElementById('stat-to-fill').textContent = toFill;
  document.getElementById('stat-no-need').textContent = noNeed;
  document.getElementById('stat-to-confirm').textContent = toConfirm;
  document.getElementById('stat-wiki').textContent = wikiCount;

  const pct = auditableCount > 0 ? (processed / auditableCount * 100) : 0;
  document.getElementById('progressFill').style.width = pct.toFixed(1) + '%';
  document.getElementById('progressText').textContent =
    `已处理 ${{processed}} / ${{auditableCount}} 条 (${{pct.toFixed(1)}}%)（仅计未匹配+间歇性）`;

  document.querySelectorAll('.stat-card').forEach(c => {{
    c.classList.toggle('active', c.dataset.filter === activeStatus);
  }});

  // Wiki patch button state
  const btn = document.getElementById('btnWikiPatch');
  if (wikiCount > 0) {{
    btn.disabled = false;
    btn.title = `导出 ${{wikiCount}} 条需沉淀的条目为 Wiki 补丁`;
  }} else {{
    btn.disabled = true;
    btn.title = '请先标记需沉淀的条目';
  }}
}}

function dashFilter(status) {{
  activeStatus = activeStatus === status ? '' : status;
  document.getElementById('filterStatus').value = activeStatus;
  applyFilters();
}}

// ═══════════════════════════════════════════════════════════════
// COMPONENT TREE
// ═══════════════════════════════════════════════════════════════
function renderCompTree() {{
  const tree = document.getElementById('compTree');
  const counts = {{}};
  for (const g of AUDIT_DATA) {{
    if (!counts[g.source_component]) counts[g.source_component] = {{total: 0, unmatched: 0}};
    counts[g.source_component].total++;
    if (g.match_type !== 'matched') counts[g.source_component].unmatched++;
  }}
  const sorted = Object.entries(counts).sort((a,b) => b[1].total - a[1].total);

  let html = `<div class="comp-item ${{activeComp===''?'active':''}}" onclick="selectComp('')">
    <span class="comp-name">全部构件</span><span class="badge">${{AUDIT_DATA.length}}</span>
  </div>`;
  for (const [comp, cnt] of sorted) {{
    const esc = comp.replace(/</g,'&lt;');
    const badgeText = cnt.unmatched > 0 ? `${{cnt.unmatched}}/${{cnt.total}}` : `${{cnt.total}}`;
    html += `<div class="comp-item ${{activeComp===comp?'active':''}}" onclick="selectComp('${{esc.replace(/'/g,"\\\\'")}}')" title="${{esc}} (未匹配${{cnt.unmatched}}/共${{cnt.total}})">
      <span class="comp-name">${{esc}}</span><span class="badge">${{badgeText}}</span>
    </div>`;
  }}
  tree.innerHTML = html;
}}

function selectComp(comp) {{
  activeComp = comp;
  renderCompTree();
  renderAttrPanel();
  applyFilters();
  document.getElementById('btnAddFeature').disabled = !activeComp;
}}

// ═══════════════════════════════════════════════════════════════
// ATTRIBUTE REFERENCE PANEL
// ═══════════════════════════════════════════════════════════════
function toggleAttrPanel() {{
  const panel = document.getElementById('attrPanel');
  attrPanelOpen = !attrPanelOpen;
  panel.classList.toggle('collapsed', !attrPanelOpen);
  document.getElementById('attrPanelToggle').textContent = attrPanelOpen ? '▲' : '▼';
}}

function renderAttrPanel() {{
  const body = document.getElementById('attrPanelBody');
  const title = document.getElementById('attrPanelTitle');

  if (!activeComp) {{
    title.textContent = '📋 构件属性参考（选择构件后展示）';
    body.innerHTML = '<div class="attr-empty">请在左侧选择一个构件类型</div>';
    return;
  }}

  const compData = COMP_SOURCE[activeComp];
  title.textContent = `📋 ${{activeComp}} 属性库`;

  if (!compData || !compData.attributes || compData.attributes.length === 0) {{
    body.innerHTML = '<div class="attr-empty">该构件属性库为空</div>';
    return;
  }}

  let html = '<div class="attr-grid">';
  for (const a of compData.attributes) {{
    const vals = (a.values || []).slice(0, 5).join(', ');
    const valsMore = (a.values || []).length > 5 ? `... 等${{a.values.length}}个` : '';
    html += `<div class="attr-tag" title="${{a.data_type || ''}} ${{vals}}${{valsMore}}">
      <span class="attr-name">${{a.name}}</span>
      <span class="attr-code">(${{a.code}})</span>
      <span class="attr-type">${{a.data_type || ''}}</span>
    </div>`;
  }}
  html += '</div>';
  body.innerHTML = html;

  // Auto-expand when component is selected
  if (!attrPanelOpen) {{
    attrPanelOpen = true;
    document.getElementById('attrPanel').classList.remove('collapsed');
    document.getElementById('attrPanelToggle').textContent = '▲';
  }}
}}

// ═══════════════════════════════════════════════════════════════
// FILTER + VIRTUAL SCROLL
// ═══════════════════════════════════════════════════════════════
const ITEM_HEIGHT = 64;
const BUFFER = 20;

function applyFilters() {{
  currentQuery = document.getElementById('searchInput').value.toLowerCase().trim();
  const statusFilter = document.getElementById('filterStatus').value || activeStatus;
  const labelFilter = document.getElementById('filterLabel').value;
  const matchFilter = document.getElementById('filterMatchType').value;

  if (document.getElementById('filterStatus').value) {{
    activeStatus = document.getElementById('filterStatus').value;
  }}

  filteredItems = AUDIT_DATA.filter(g => {{
    if (activeComp && g.source_component !== activeComp) return false;

    // Match type filter
    if (matchFilter) {{
      if (matchFilter === 'matched' && g.match_type !== 'matched') return false;
      if (matchFilter === 'unmatched' && g.match_type !== 'unmatched') return false;
      if (matchFilter === 'intermittent' && g.match_type !== 'intermittent') return false;
    }}

    // Status filter (only applies to non-matched items)
    if (statusFilter) {{
      if (g.match_type === 'matched') {{
        // Matched items don't have audit status — hide them if status filter is active
        return false;
      }}
      if (getStatus(g.item_key) !== statusFilter) return false;
    }}

    if (labelFilter && g.label !== labelFilter) return false;
    if (currentQuery) {{
      const hay = (g.label + ' ' + g.raw_text + ' ' + (g.value_samples||[]).join(' ') + ' '
        + g.source_component + ' ' + (g.attribute_name||'') + ' ' + (g.attribute_code||'')).toLowerCase();
      if (!hay.includes(currentQuery)) return false;
    }}
    return true;
  }});

  document.getElementById('matchCount').textContent = `${{filteredItems.length}} 条`;
  selected.clear();
  document.getElementById('selectAll').checked = false;
  updateSelInfo();
  updateDashboard();
  renderVirtualList();
}}

const viewport = document.getElementById('viewport');
const spacer = document.getElementById('spacer');

function renderVirtualList() {{
  const totalH = filteredItems.length * ITEM_HEIGHT;
  spacer.style.height = totalH + 'px';
  spacer.querySelectorAll('.gap-card').forEach(el => el.remove());
  lastStart = -1; lastEnd = -1;
  onScroll();
}}

let lastStart = -1, lastEnd = -1;
function onScroll() {{
  const scrollTop = viewport.scrollTop;
  const viewH = viewport.clientHeight;
  let start = Math.floor(scrollTop / ITEM_HEIGHT) - BUFFER;
  let end = Math.ceil((scrollTop + viewH) / ITEM_HEIGHT) + BUFFER;
  start = Math.max(0, start);
  end = Math.min(filteredItems.length, end);

  if (start === lastStart && end === lastEnd) return;

  const existing = spacer.querySelectorAll('.gap-card');
  existing.forEach(el => {{
    const idx = parseInt(el.dataset.idx);
    if (idx < start || idx >= end) el.remove();
  }});

  const rendered = new Set();
  spacer.querySelectorAll('.gap-card').forEach(el => rendered.add(parseInt(el.dataset.idx)));

  const frag = document.createDocumentFragment();
  for (let i = start; i < end; i++) {{
    if (rendered.has(i)) continue;
    frag.appendChild(createCard(filteredItems[i], i));
  }}
  spacer.appendChild(frag);

  lastStart = start;
  lastEnd = end;
}}
viewport.addEventListener('scroll', onScroll, {{ passive: true }});

// ═══════════════════════════════════════════════════════════════
// CARD RENDERING
// ═══════════════════════════════════════════════════════════════
function createCard(item, idx) {{
  const div = document.createElement('div');
  div.className = 'gap-card';
  div.dataset.idx = idx;
  div.dataset.key = item.item_key;
  div.style.top = (idx * ITEM_HEIGHT) + 'px';
  div.style.height = ITEM_HEIGHT + 'px';

  const isMatched = item.match_type === 'matched';
  const isIntermittent = item.match_type === 'intermittent';
  const escLabel = item.label.replace(/</g,'&lt;').replace(/"/g,'&quot;');
  const escComp = item.source_component.replace(/</g,'&lt;').replace(/"/g,'&quot;');
  const srcCount = (item.source_rows || []).length;
  const safeKey = btoa(unescape(encodeURIComponent(item.item_key)));
  const samples = (item.value_samples || []).join(', ');

  if (isMatched) {{
    // Matched item: display-only, no checkbox, no status controls
    div.classList.add('match-matched');
    const attrInfo = item.attribute_name
      ? `<span class="card-attr-badge">✓ ${{(item.attribute_name||'').replace(/</g,'&lt;')}}(${{(item.attribute_code||'').replace(/</g,'&lt;')}})</span>`
      : '';
    div.innerHTML = `
      <div class="card-body">
        <span class="card-label">${{escLabel}}</span>
        ${{attrInfo}}
        <span class="card-occ">${{item.occurrence_count}}次</span>
        <span class="card-comp">&nbsp;·&nbsp;${{escComp}}</span>
        ${{samples ? `<div class="card-samples">值样本: ${{samples.replace(/</g,'&lt;')}}</div>` : ''}}
      </div>
      <div class="card-actions">
        <span style="font-size:11px;color:var(--green);font-weight:600;">已匹配</span>
        <span class="src-toggle" onclick="showSourcesB64(event, '${{safeKey}}')">来源(${{srcCount}})</span>
      </div>`;
    return div;
  }}

  // Unmatched or intermittent item
  const st = getStatus(item.item_key);
  if (st !== 'pending') div.classList.add('status-' + st);
  if (isIntermittent) div.classList.add('match-intermittent');

  const isChecked = selected.has(item.item_key) ? 'checked' : '';
  const note = getNote(item.item_key).replace(/"/g, '&quot;');
  const warnBadge = isIntermittent
    ? `<span class="card-warn-badge">⚠️ 间歇(${{item.matched_count}}匹配/${{item.unmatched_count}}未)</span>`
    : '';
  const attrHint = (isIntermittent && item.attribute_name)
    ? `<span class="card-attr-badge">${{(item.attribute_name||'').replace(/</g,'&lt;')}}(${{(item.attribute_code||'').replace(/</g,'&lt;')}})</span>`
    : '';
  const manualBadge = item.source === 'manual_add'
    ? `<span class="card-manual-badge">手动添加</span>` : '';

  div.innerHTML = `
    <input type="checkbox" ${{isChecked}} onchange="toggleSelectB64('${{safeKey}}', this.checked)" />
    <div class="card-body">
      <span class="card-label">${{escLabel}}</span>
      <span class="card-occ">${{item.occurrence_count}}次</span>
      ${{warnBadge}}
      ${{attrHint}}
      ${{manualBadge}}
      <span class="card-comp">&nbsp;·&nbsp;${{escComp}}</span>
      ${{samples ? `<div class="card-samples">值样本: ${{samples.replace(/</g,'&lt;')}}</div>` : ''}}
    </div>
    <div class="card-actions">
      <button class="btn btn-outline" style="padding:3px 8px;font-size:11px;" onclick="openEditModal('${{safeKey}}')">✏️</button>
      <select onchange="setAuditB64('${{safeKey}}', this.value, undefined); refreshCard(${{idx}});">
        <option value="pending" ${{st==='pending'?'selected':''}}>未处理</option>
        <option value="to-fill" ${{st==='to-fill'?'selected':''}}>待补充</option>
        <option value="no-need" ${{st==='no-need'?'selected':''}}>无需补充</option>
        <option value="to-confirm" ${{st==='to-confirm'?'selected':''}}>待确认</option>
        <option value="match-fail-wiki" ${{st==='match-fail-wiki'?'selected':''}}>需沉淀</option>
      </select>
      <input class="note-input" placeholder="批注..." value="${{note}}"
        onblur="setAuditB64('${{safeKey}}', undefined, this.value)" />
      <span class="src-toggle" onclick="showSourcesB64(event, '${{safeKey}}')">来源(${{srcCount}})</span>
    </div>`;
  return div;
}}

function refreshCard(idx) {{
  const old = spacer.querySelector(`.gap-card[data-idx="${{idx}}"]`);
  if (old) {{
    const card = createCard(filteredItems[idx], idx);
    old.replaceWith(card);
  }}
}}

function showSources(evt, itemKey) {{
  evt.stopPropagation();
  const item = AUDIT_DATA.find(g => g.item_key === itemKey);
  if (!item) return;
  const popup = document.getElementById('srcPopup');
  const rows = item.source_rows || [];
  let html = `<span class="close-btn" onclick="document.getElementById('srcPopup').style.display='none'">&times;</span>`;
  html += `<div style="font-weight:600;margin-bottom:6px;">"${{item.label}}" 出现在 ${{rows.length}} 个清单行</div>`;
  for (const r of rows.slice(0, 50)) {{
    const matchIcon = r.matched ? '✓' : '✗';
    const matchColor = r.matched ? 'var(--green)' : 'var(--red)';
    html += `<div class="src-row"><span style="color:${{matchColor}};font-weight:600;">${{matchIcon}}</span> <b>${{r.project_code}}</b> ${{(r.project_name||'').replace(/</g,'&lt;')}}</div>`;
  }}
  if (rows.length > 50) html += `<div class="src-row muted">... 及另 ${{rows.length - 50}} 行</div>`;
  popup.innerHTML = html;
  popup.style.display = 'block';
  popup.style.left = Math.min(evt.clientX, window.innerWidth - 520) + 'px';
  popup.style.top = Math.min(evt.clientY, window.innerHeight - 320) + 'px';
}}
document.addEventListener('click', () => document.getElementById('srcPopup').style.display = 'none');

// ═══════════════════════════════════════════════════════════════
// SELECTION + BATCH
// ═══════════════════════════════════════════════════════════════
function decodeKey(b64) {{
  return decodeURIComponent(escape(atob(b64)));
}}
function toggleSelectB64(b64, checked) {{ toggleSelect(decodeKey(b64), checked); }}
function setAuditB64(b64, status, note) {{ setAudit(decodeKey(b64), status, note); }}
function showSourcesB64(evt, b64) {{ showSources(evt, decodeKey(b64)); }}
function toggleSelect(key, checked) {{
  if (checked) selected.add(key); else selected.delete(key);
  updateSelInfo();
}}
function toggleSelectAll(checked) {{
  selected.clear();
  if (checked) {{
    // Only select non-matched items
    filteredItems.forEach(g => {{
      if (g.match_type !== 'matched') selected.add(g.item_key);
    }});
  }}
  spacer.querySelectorAll('.gap-card input[type=checkbox]').forEach(cb => cb.checked = checked);
  updateSelInfo();
}}
function updateSelInfo() {{
  const auditable = filteredItems.filter(g => g.match_type !== 'matched').length;
  document.getElementById('selInfo').textContent = `已选 ${{selected.size}} / 共 ${{auditable}} 条（可操作）`;
}}
function applyBatchStatus() {{
  const val = document.getElementById('batchStatus').value;
  if (!val) {{ toast('请先选择目标状态', 'err'); return; }}
  if (selected.size === 0) {{ toast('请先勾选条目', 'err'); return; }}
  for (const key of selected) {{
    setAudit(key, val, undefined);
  }}
  document.getElementById('batchStatus').value = '';
  lastStart = -1; lastEnd = -1; onScroll();
  toast(`已将 ${{selected.size}} 条标记为 ${{val}}`, 'ok');
}}

// ═══════════════════════════════════════════════════════════════
// EXPORT EXCEL + JSON
// ═══════════════════════════════════════════════════════════════
function exportExcel() {{
  if (typeof XLSX === 'undefined') {{ toast('SheetJS 未加载，请检查网络', 'err'); return; }}
  const wb = XLSX.utils.book_new();

  // Export non-matched items (to-fill priority, then all non-no-need)
  let exportItems = AUDIT_DATA.filter(g => g.match_type !== 'matched' && getStatus(g.item_key) === 'to-fill');
  if (exportItems.length === 0) {{
    exportItems = AUDIT_DATA.filter(g => g.match_type !== 'matched' && getStatus(g.item_key) !== 'no-need');
  }}

  const groups = {{}};
  for (const g of exportItems) {{
    if (!groups[g.source_component]) groups[g.source_component] = [];
    groups[g.source_component].push(g);
  }}

  // Summary sheet
  const summaryData = [
    ['构件类型', '缺口数', '待补充', '无需补充', '待确认', '需沉淀', '未处理'],
  ];
  const compEntries = Object.entries(groups).sort((a,b) => b[1].length - a[1].length);
  for (const [comp, items] of compEntries) {{
    summaryData.push([
      comp, items.length,
      items.filter(g => getStatus(g.item_key)==='to-fill').length,
      items.filter(g => getStatus(g.item_key)==='no-need').length,
      items.filter(g => getStatus(g.item_key)==='to-confirm').length,
      items.filter(g => getStatus(g.item_key)==='match-fail-wiki').length,
      items.filter(g => getStatus(g.item_key)==='pending').length,
    ]);
  }}
  const summaryWs = XLSX.utils.aoa_to_sheet(summaryData);
  summaryWs['!cols'] = [{{wch:20}},{{wch:8}},{{wch:8}},{{wch:10}},{{wch:8}},{{wch:8}},{{wch:8}}];
  XLSX.utils.book_append_sheet(wb, summaryWs, '总览');

  const headers = [
    'A:特征标签', 'B:原始文本', 'C:出现次数', 'D:值样本',
    'E:匹配类型', 'F:当前属性名', 'G:当前属性编码', 'H:审核状态', 'I:批注',
    'J:来源项目编码(首个)',
    'K:回填-属性名', 'L:回填-属性编码', 'M:回填-值域'
  ];
  for (const [comp, items] of compEntries) {{
    const baseName = comp.substring(0, 28).replace(/[\\[\\]\\*\\?\\/\\\\:]/g, '_');
    // T042: Split sheets with >65535 rows
    const chunks = [];
    for (let c = 0; c < items.length; c += MAX_ROWS_PER_SHEET) {{
      chunks.push(items.slice(c, c + MAX_ROWS_PER_SHEET));
    }}
    for (let ci = 0; ci < chunks.length; ci++) {{
      const sheetName = chunks.length > 1 ? `${{baseName}}_${{ci+1}}` : baseName.substring(0, 31);
      const data = [headers.map(h => h.split(':')[1])];
      for (const g of chunks[ci]) {{
      const firstSrc = (g.source_rows || [])[0] || {{}};
      data.push([
        g.label, g.raw_text, g.occurrence_count,
        (g.value_samples || []).join('; '),
        g.match_type === 'intermittent' ? '间歇性失败' : '未匹配',
        g.attribute_name || '', g.attribute_code || '',
        getStatus(g.item_key), getNote(g.item_key),
        firstSrc.project_code || '',
        '', '', ''
      ]);
    }}
    const ws = XLSX.utils.aoa_to_sheet(data);
    ws['!cols'] = [
      {{wch:18}},{{wch:18}},{{wch:8}},{{wch:24}},
      {{wch:12}},{{wch:14}},{{wch:12}},{{wch:10}},{{wch:20}},
      {{wch:16}},
      {{wch:16}},{{wch:14}},{{wch:20}}
    ];
    XLSX.utils.book_append_sheet(wb, ws, sheetName);
    }}
  }}

  XLSX.writeFile(wb, 'feature_audit_export.xlsx');
  toast(`已导出 ${{exportItems.length}} 条到 Excel (${{compEntries.length}} 个 sheet)`, 'ok');
}}

function exportJSON() {{
  const exportData = AUDIT_DATA.map(g => ({{
    ...g,
    audit_status: g.match_type === 'matched' ? 'matched' : getStatus(g.item_key),
    audit_note: getNote(g.item_key),
  }}));
  downloadJSON(exportData, 'feature_audit_export.json');
  toast(`已导出 ${{exportData.length}} 条 JSON`, 'ok');
}}

// ═══════════════════════════════════════════════════════════════
// WIKI PATCH EXPORT
// ═══════════════════════════════════════════════════════════════
function exportWikiPatch() {{
  // Collect items marked as "match-fail-wiki"
  const wikiItems = AUDIT_DATA.filter(g => getStatus(g.item_key) === 'match-fail-wiki');
  if (wikiItems.length === 0) {{
    toast('无需沉淀的条目', 'err');
    return;
  }}

  // Group by component
  const components = {{}};
  for (const g of wikiItems) {{
    const comp = g.source_component;
    if (!components[comp]) components[comp] = [];

    // Create entries from source rows
    const seenProjects = new Set();
    for (const sr of (g.source_rows || []).slice(0, 20)) {{
      const projKey = sr.project_code || sr.row_id;
      if (seenProjects.has(projKey)) continue;
      seenProjects.add(projKey);
      components[comp].push({{
        project_code: sr.project_code || '',
        project_name: sr.project_name || '',
        match_status: g.match_type === 'intermittent' ? '间歇性失败' : '未匹配',
        feature_expression_items: [{{
          label: g.label,
          matched: false,
          value_expression: (g.value_samples || [])[0] || '',
          attribute_name: g.attribute_name || '',
          attribute_code: g.attribute_code || '',
        }}],
        notes: getNote(g.item_key) || `标签"${{g.label}}"应匹配到属性库中的${{g.attribute_name || '(待定)'}}`,
        reviewed: true,
      }});
    }}
  }}

  const patch = {{
    meta: {{
      source: 'step5_feature_audit',
      exported_at: new Date().toISOString(),
      purpose: 'wiki_knowledge_patch',
      total_items: wikiItems.length,
      components_count: Object.keys(components).length,
    }},
    components: components,
  }};

  downloadJSON(patch, 'wiki_patch.json');
  toast(`已导出 Wiki 补丁: ${{wikiItems.length}} 条，${{Object.keys(components).length}} 个构件`, 'ok');
}}

// ═══════════════════════════════════════════════════════════════
// PROGRESS SAVE/RESTORE
// ═══════════════════════════════════════════════════════════════
function saveProgress() {{
  downloadJSON(auditState, 'feature_audit_progress.json');
  toast('审核进度已保存', 'ok');
}}

function loadProgressFile() {{
  document.getElementById('fileInput').click();
}}
function handleProgressUpload(evt) {{
  const file = evt.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = function(e) {{
    try {{
      const obj = JSON.parse(e.target.result);
      Object.assign(auditState, obj);
      saveLocalState();
      applyFilters();
      toast(`已恢复 ${{Object.keys(obj).length}} 条审核状态`, 'ok');
    }} catch(err) {{
      toast('JSON 解析失败: ' + err.message, 'err');
    }}
  }};
  reader.readAsText(file);
  evt.target.value = '';
}}

function downloadJSON(data, filename) {{
  const blob = new Blob([JSON.stringify(data, null, 2)], {{ type: 'application/json' }});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}}

// ═══════════════════════════════════════════════════════════════
// MODAL HELPERS
// ═══════════════════════════════════════════════════════════════
function closeModal(id) {{
  document.getElementById(id).classList.remove('show');
}}

// ═══════════════════════════════════════════════════════════════
// US4: IMPORT EXCEL BACKFILL (T032-T034)
// ═══════════════════════════════════════════════════════════════
let importDiffs = [];
const MAX_ROWS_PER_SHEET = 65535;

function handleExcelImport(evt) {{
  const file = evt.target.files[0];
  if (!file) return;
  evt.target.value = '';
  if (typeof XLSX === 'undefined') {{ toast('SheetJS 未加载', 'err'); return; }}
  const reader = new FileReader();
  reader.onload = function(e) {{
    try {{
      const wb = XLSX.read(e.target.result, {{ type: 'array' }});
      importDiffs = parseImportExcel(wb);
      renderImportDiffs();
      document.getElementById('importModal').classList.add('show');
    }} catch(err) {{
      toast('Excel 解析失败: ' + err.message, 'err');
    }}
  }};
  reader.readAsArrayBuffer(file);
}}

function parseImportExcel(wb) {{
  const diffs = [];
  const expectedHeaders = ['特征标签', '原始文本', '出现次数', '值样本', '匹配类型',
    '当前属性名', '当前属性编码', '审核状态', '批注', '来源项目编码(首个)',
    '回填-属性名', '回填-属性编码', '回填-值域'];
  for (const sheetName of wb.SheetNames) {{
    if (sheetName === '总览') continue;
    const ws = wb.Sheets[sheetName];
    const rows = XLSX.utils.sheet_to_json(ws, {{ header: 1 }});
    if (!rows.length) continue;
    // Validate columns (T043)
    const header = rows[0];
    const colK = header.indexOf('回填-属性名');
    const colL = header.indexOf('回填-属性编码');
    const colM = header.indexOf('回填-值域');
    const colA = header.indexOf('特征标签');
    if (colK === -1 || colL === -1 || colM === -1 || colA === -1) {{
      toast(`Sheet "${{sheetName}}" 列格式不匹配，跳过。需要列: 回填-属性名, 回填-属性编码, 回填-值域`, 'err');
      continue;
    }}
    for (let i = 1; i < rows.length; i++) {{
      const r = rows[i];
      const label = (r[colA] || '').toString().trim();
      const newAttrName = (r[colK] || '').toString().trim();
      const newAttrCode = (r[colL] || '').toString().trim();
      const newValueExpr = (r[colM] || '').toString().trim();
      if (!label || (!newAttrName && !newAttrCode && !newValueExpr)) continue;
      // Find matching item in AUDIT_DATA
      const itemKey = sheetName + '|' + label;
      const item = AUDIT_DATA.find(g => g.item_key === itemKey || (g.source_component === sheetName && g.label === label));
      if (!item) continue;
      const oldAttr = item.attribute_name || '';
      const oldCode = item.attribute_code || '';
      const type = (!oldAttr && newAttrName) ? 'added' : (oldAttr !== newAttrName || oldCode !== newAttrCode) ? 'modified' : 'unchanged';
      if (type === 'unchanged' && !newValueExpr) continue;
      diffs.push({{
        itemKey: item.item_key,
        component: item.source_component,
        label: label,
        oldAttrName: oldAttr,
        oldAttrCode: oldCode,
        newAttrName: newAttrName,
        newAttrCode: newAttrCode,
        newValueExpr: newValueExpr,
        type: type,
        accepted: true,
      }});
    }}
  }}
  return diffs;
}}

function renderImportDiffs() {{
  const list = document.getElementById('importDiffList');
  if (importDiffs.length === 0) {{
    list.innerHTML = '<div style="padding:12px;color:var(--muted);">没有发现回填数据差异</div>';
    document.getElementById('btnConfirmImport').disabled = true;
    document.getElementById('btnGenPatch').style.display = 'none';
    return;
  }}
  let html = `<div style="margin-bottom:8px;font-size:12px;color:var(--muted);">发现 ${{importDiffs.length}} 条差异</div>`;
  for (let i = 0; i < importDiffs.length; i++) {{
    const d = importDiffs[i];
    const typeClass = d.type === 'added' ? 'diff-added' : d.type === 'modified' ? 'diff-modified' : '';
    const typeLabel = d.type === 'added' ? '新增' : d.type === 'modified' ? '修改' : '值域';
    html += `<div class="diff-row">
      <input type="checkbox" ${{d.accepted ? 'checked' : ''}} onchange="importDiffs[${{i}}].accepted=this.checked" />
      <span class="${{typeClass}}">${{typeLabel}}</span>
      <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${{d.component}} · ${{d.label}}">${{d.component}} · ${{d.label}}</span>
      <span style="font-size:11px;">${{d.newAttrName}} (${{d.newAttrCode}})</span>
    </div>`;
  }}
  list.innerHTML = html;
  document.getElementById('btnConfirmImport').disabled = false;
  document.getElementById('btnGenPatch').style.display = 'inline-flex';
}}

function confirmImport() {{
  const accepted = importDiffs.filter(d => d.accepted);
  if (accepted.length === 0) {{ toast('没有选中任何差异', 'err'); return; }}
  for (const d of accepted) {{
    const item = AUDIT_DATA.find(g => g.item_key === d.itemKey);
    if (!item) continue;
    if (d.newAttrName) item.attribute_name = d.newAttrName;
    if (d.newAttrCode) item.attribute_code = d.newAttrCode;
    // If attribute bound, update match_type visual (still unmatched in source, but user-bound)
    setAudit(d.itemKey, 'to-confirm', `导入回填: ${{d.newAttrName}}(${{d.newAttrCode}})`);
  }}
  closeModal('importModal');
  lastStart = -1; lastEnd = -1; onScroll();
  updateDashboard();
  toast(`已导入 ${{accepted.length}} 条回填数据`, 'ok');
}}

function generateComponentsPatch() {{
  const accepted = importDiffs.filter(d => d.accepted);
  if (accepted.length === 0) {{ toast('没有选中任何差异', 'err'); return; }}
  const components = {{}};
  for (const d of accepted) {{
    if (!d.newAttrName) continue;
    if (!components[d.component]) components[d.component] = [];
    components[d.component].push({{
      label: d.label,
      attribute_name: d.newAttrName,
      attribute_code: d.newAttrCode,
      value_expression: d.newValueExpr || '',
      action: d.type === 'added' ? 'add' : 'update',
    }});
  }}
  const patch = {{
    meta: {{
      source: 'step5_excel_import',
      exported_at: new Date().toISOString(),
      purpose: 'components_patch',
      total_entries: accepted.length,
      components_count: Object.keys(components).length,
    }},
    components: components,
  }};
  downloadJSON(patch, 'components_patch.json');
  toast(`已生成构件补丁: ${{accepted.length}} 条`, 'ok');
}}

// ═══════════════════════════════════════════════════════════════
// US5: EDIT MODAL + BATCH BINDING (T035-T036)
// ═══════════════════════════════════════════════════════════════
let editTargets = []; // item_key(s) being edited

function openEditModal(b64Key) {{
  const key = b64Key ? decodeKey(b64Key) : null;
  editTargets = key ? [key] : Array.from(selected);
  if (editTargets.length === 0) {{ toast('请先选择条目', 'err'); return; }}

  const first = AUDIT_DATA.find(g => g.item_key === editTargets[0]);
  if (!first) return;

  const isBatch = editTargets.length > 1;
  document.getElementById('editInfo').textContent = isBatch
    ? `批量编辑 ${{editTargets.length}} 条 (标签: ${{first.label}})`
    : `${{first.source_component}} · ${{first.label}}`;
  document.getElementById('editLabel').value = first.label;
  document.getElementById('editValueExpr').value = (first.value_samples || [])[0] || '';

  // Populate attribute dropdown from COMP_SOURCE
  const sel = document.getElementById('editAttrName');
  sel.innerHTML = '<option value="">-- 请选择属性 --</option>';
  const compSrc = COMP_SOURCE[first.source_component];
  if (compSrc && compSrc.attributes) {{
    for (const attr of compSrc.attributes) {{
      const opt = document.createElement('option');
      opt.value = attr.name || attr.attribute_name || '';
      opt.textContent = `${{attr.name || attr.attribute_name}} (${{attr.code || attr.attribute_code || ''}})`;
      opt.dataset.code = attr.code || attr.attribute_code || '';
      if (first.attribute_name && (attr.name === first.attribute_name || attr.attribute_name === first.attribute_name)) opt.selected = true;
      sel.appendChild(opt);
    }}
  }}
  onEditAttrChange();
  document.getElementById('editModal').classList.add('show');
}}

function openBatchEdit() {{
  if (selected.size === 0) {{ toast('请先勾选条目', 'err'); return; }}
  editTargets = Array.from(selected);
  openEditModal(null);
}}

function onEditAttrChange() {{
  const sel = document.getElementById('editAttrName');
  const opt = sel.options[sel.selectedIndex];
  document.getElementById('editAttrCode').value = opt && opt.dataset ? (opt.dataset.code || '') : '';
}}

function confirmEdit() {{
  const attrName = document.getElementById('editAttrName').value;
  const attrCode = document.getElementById('editAttrCode').value;
  const valueExpr = document.getElementById('editValueExpr').value.trim();
  if (!attrName) {{ toast('请选择属性', 'err'); return; }}
  let count = 0;
  for (const key of editTargets) {{
    const item = AUDIT_DATA.find(g => g.item_key === key);
    if (!item) continue;
    item.attribute_name = attrName;
    item.attribute_code = attrCode;
    if (valueExpr) item.value_samples = [valueExpr];
    setAudit(key, 'to-confirm', `绑定: ${{attrName}}(${{attrCode}})`);
    count++;
  }}
  closeModal('editModal');
  lastStart = -1; lastEnd = -1; onScroll();
  updateDashboard();
  toast(`已绑定 ${{count}} 条属性`, 'ok');
}}

// ═══════════════════════════════════════════════════════════════
// US8: ADD FEATURE DIALOG (T037-T038)
// ═══════════════════════════════════════════════════════════════
function openAddFeatureDialog() {{
  if (!activeComp) {{ toast('请先在左侧选择一个构件类型', 'err'); return; }}
  document.getElementById('addFeatureComp').textContent = `构件类型: ${{activeComp}}`;
  document.getElementById('addLabel').value = '';
  document.getElementById('addValueExpr').value = '';
  document.getElementById('addAttrCode').value = '';

  // Populate attributes dropdown
  const sel = document.getElementById('addAttrName');
  sel.innerHTML = '<option value="">-- 选择属性(可选) --</option>';
  const compSrc = COMP_SOURCE[activeComp];
  if (compSrc && compSrc.attributes) {{
    for (const attr of compSrc.attributes) {{
      const opt = document.createElement('option');
      opt.value = attr.name || attr.attribute_name || '';
      opt.textContent = `${{attr.name || attr.attribute_name}} (${{attr.code || attr.attribute_code || ''}})`;
      opt.dataset.code = attr.code || attr.attribute_code || '';
      sel.appendChild(opt);
    }}
  }}
  document.getElementById('addFeatureModal').classList.add('show');
}}

function onAddAttrChange() {{
  const sel = document.getElementById('addAttrName');
  const opt = sel.options[sel.selectedIndex];
  document.getElementById('addAttrCode').value = opt && opt.dataset ? (opt.dataset.code || '') : '';
}}

function confirmAddFeature() {{
  const label = document.getElementById('addLabel').value.trim();
  if (!label) {{ toast('请输入特征标签', 'err'); return; }}
  const attrName = document.getElementById('addAttrName').value;
  const attrCode = document.getElementById('addAttrCode').value;
  const valueExpr = document.getElementById('addValueExpr').value.trim();

  // Duplicate check
  const itemKey = activeComp + '|' + label;
  const existing = AUDIT_DATA.find(g => g.item_key === itemKey);
  if (existing) {{
    if (!confirm(`标签 "${{label}}" 在 "${{activeComp}}" 中已存在，是否仍然添加？`)) return;
  }}

  const newItem = {{
    item_key: itemKey,
    source_component: activeComp,
    label: label,
    raw_text: label,
    match_type: attrName ? 'matched' : 'unmatched',
    occurrence_count: 0,
    matched_count: 0,
    unmatched_count: attrName ? 0 : 1,
    attribute_name: attrName,
    attribute_code: attrCode,
    value_samples: valueExpr ? [valueExpr] : [],
    source_rows: [],
    source: 'manual_add',
  }};
  AUDIT_DATA.push(newItem);

  // Re-aggregate stats
  refreshStatsAfterAdd();

  closeModal('addFeatureModal');
  applyFilters();
  toast(`已添加特征: ${{label}}`, 'ok');
}}

function refreshStatsAfterAdd() {{
  // Recompute basic stats from AUDIT_DATA
  let matched = 0, unmatched = 0, intermittent = 0;
  const compCounts = {{}};
  for (const item of AUDIT_DATA) {{
    if (item.match_type === 'matched') matched++;
    else if (item.match_type === 'intermittent') intermittent++;
    else unmatched++;
    if (!compCounts[item.source_component]) compCounts[item.source_component] = {{ matched: 0, unmatched: 0 }};
    if (item.match_type === 'matched') compCounts[item.source_component].matched++;
    else compCounts[item.source_component].unmatched++;
  }}
  INIT_STATS.total_items = AUDIT_DATA.length;
  INIT_STATS.total_matched_items = matched;
  INIT_STATS.total_unmatched_items = unmatched;
  INIT_STATS.total_intermittent_items = intermittent;
  INIT_STATS.total_components = Object.keys(compCounts).length;
  renderCompTree();
  updateDashboard();
  // Enable add button if component selected
  document.getElementById('btnAddFeature').disabled = !activeComp;
}}

// ═══════════════════════════════════════════════════════════════
// TOAST
// ═══════════════════════════════════════════════════════════════
function toast(msg, type) {{
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast toast-' + type + ' show';
  setTimeout(() => el.classList.remove('show'), 2500);
}}

// ═══════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════
function init() {{
  loadLocalState();

  // Populate label filter
  const labelSel = document.getElementById('filterLabel');
  for (const [label] of INIT_STATS.top_labels || []) {{
    const opt = document.createElement('option');
    opt.value = label;
    opt.textContent = label;
    labelSel.appendChild(opt);
  }}

  // Bind filter events
  document.getElementById('searchInput').addEventListener('input', applyFilters);
  document.getElementById('filterStatus').addEventListener('change', function() {{
    activeStatus = this.value;
    applyFilters();
  }});
  document.getElementById('filterLabel').addEventListener('change', applyFilters);
  document.getElementById('filterMatchType').addEventListener('change', applyFilters);

  renderCompTree();
  renderAttrPanel();
  applyFilters();
}}

init();
</script>
</body>
</html>"""


# ──────────────────────────── Main ────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Step5 项目特征审核导出工具 v2")
    parser.add_argument("--step3-result", default=DEFAULT_STEP3_RESULT,
                        help="Step3 匹配结果 JSON 路径")
    parser.add_argument("--components", default=DEFAULT_COMPONENTS,
                        help="构件库 components.json 路径")
    parser.add_argument("--component-source-table", default=DEFAULT_COMP_SOURCE_TABLE,
                        help="构件来源表 component_source_table.json 路径")
    parser.add_argument("--output", default=None,
                        help="输出 HTML 路径（默认: data/output/step5/feature_audit_tool.html）")
    args = parser.parse_args()

    step3_path = Path(args.step3_result)
    comps_path = Path(args.components)
    comp_src_path = Path(args.component_source_table)

    print("Step5 项目特征审核导出工具 v2")
    print("=" * 50)

    # Load data
    data = load_step3_results(step3_path)
    components = load_components_library(comps_path)
    comp_source_table = load_component_source_table(comp_src_path) if comp_src_path.exists() else []

    # Extract & Aggregate (all items, not just unmatched)
    raw_items = extract_all_items(data["rows"])
    audit_items = aggregate_by_component(raw_items)
    stats = build_stats(audit_items, data["rows"])

    # Build references
    comp_ref = build_comp_ref(components)
    comp_source_ref = build_comp_source_ref(comp_source_table)

    # Build HTML
    html = build_audit_html(audit_items, comp_ref, comp_source_ref, stats, data["meta"])

    # Output
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = Path(DEFAULT_OUTPUT_DIR) / OUTPUT_HTML_NAME

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    size_kb = out_path.stat().st_size / 1024
    print("=" * 50)
    print(f"  输出: {out_path} ({size_kb:.0f} KB)")
    print(f"  全部特征: {len(audit_items)} (已匹配 {stats['total_matched_items']}, "
          f"未匹配 {stats['total_unmatched_items']}, 间歇性 {stats['total_intermittent_items']})")
    print(f"  构件类型: {stats['total_components']}")
    print(f"  Top 未匹配标签: {', '.join(l for l,_ in stats['top_labels'][:5])}")


if __name__ == "__main__":
    main()
