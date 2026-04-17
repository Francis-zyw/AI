"""
Step3 人工审定编辑器

按清单条目(project_code)为主维度，生成可编辑 HTML 页面：
- 每个清单条目展示所有候选构件行
- 支持修改构件分配、匹配状态、计算项目、特征表达式
- 增删构件行
- 保存审定结果为 JSON
- 可导入 wiki 供后续匹配积累知识
"""

from __future__ import annotations

import html as html_mod
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence

FINAL_JSON_NAME = "project_component_feature_calc_matching_result.json"
LOCAL_RESULT_JSON_NAME = "local_rule_project_component_feature_calc_result.json"
RESULT_JSON_NAME = LOCAL_RESULT_JSON_NAME
COMPONENT_SOURCE_TABLE = "component_source_table.json"
OUTPUT_HTML_NAME = "step3_review_editor.html"


def _esc(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        v = json.dumps(v, ensure_ascii=False)
    return html_mod.escape(str(v))


def _safe_int(value: Any, default: int = 0) -> int:
  try:
    return int(value)
  except (TypeError, ValueError):
    return default


def _safe_float(value: Any, default: float = 0.0) -> float:
  try:
    return float(value)
  except (TypeError, ValueError):
    return default


def _row_priority(row: Dict[str, Any]) -> tuple[int, int, int, float]:
  match_status = str(row.get("match_status", "")).strip()
  match_rank = 0 if match_status == "matched" else 1 if match_status == "candidate_only" else 2
  review_status = str(row.get("review_status", "")).strip()
  review_rank = 0 if review_status == "reviewed" else 1 if review_status == "suggested" else 2
  candidate_rank = _safe_int(row.get("candidate_rank"), 9999)
  confidence_rank = -_safe_float(row.get("confidence"), 0.0)
  return match_rank, review_rank, candidate_rank, confidence_rank


def _format_feature_expression(item: Dict[str, Any]) -> str:
  expression = str(item.get("expression", "")).strip()
  if expression:
    return expression
  label = str(item.get("label", "")).strip()
  if label:
    return label
  return str(item.get("raw_text", "")).strip()


def _feature_identity(item: Dict[str, Any]) -> str:
  label = str(item.get("label", "")).strip() or str(item.get("raw_text", "")).strip()
  value_expression = str(item.get("value_expression", "")).strip()
  if label or value_expression:
    return f"{label.casefold()}|{value_expression.casefold()}"
  return _format_feature_expression(item).casefold()


def _build_project_feature_summary(rows: Sequence[Dict[str, Any]]) -> str:
  ordered_rows = sorted(rows, key=_row_priority)
  summary_lines: List[str] = []
  seen: set[str] = set()
  for row in ordered_rows:
    for item in row.get("feature_expression_items", []) or []:
      if not isinstance(item, dict):
        continue
      expression = _format_feature_expression(item)
      if not expression:
        continue
      identity = _feature_identity(item)
      if identity in seen:
        continue
      seen.add(identity)
      summary_lines.append(expression)

  if summary_lines:
    preview = summary_lines[:12]
    summary = "\n".join(f"{index}. {line}" for index, line in enumerate(preview, start=1))
    if len(summary_lines) > len(preview):
      summary += f"\n…… 共 {len(summary_lines)} 项"
    return summary

  first_row = ordered_rows[0] if ordered_rows else {}
  return str(first_row.get("project_features_raw", "")).strip()


def _resolve_result_path(requested_path: Path) -> Path:
  if requested_path.is_dir():
    final_path = requested_path / FINAL_JSON_NAME
    if final_path.exists():
      return final_path
    local_path = requested_path / LOCAL_RESULT_JSON_NAME
    if local_path.exists():
      return local_path
    raise FileNotFoundError(
      f"未在目录中找到 Step3 结果：{requested_path / FINAL_JSON_NAME} 或 {requested_path / LOCAL_RESULT_JSON_NAME}"
    )
  return requested_path


def _find_latest_result(step3_dir: Path) -> Path:
  final_candidates = sorted(step3_dir.glob(f"*/{FINAL_JSON_NAME}"))
  if final_candidates:
    return final_candidates[-1]

  local_candidates = sorted(step3_dir.glob(f"*/{LOCAL_RESULT_JSON_NAME}"))
  if local_candidates:
    return local_candidates[-1]

  raise FileNotFoundError(f"未找到 Step3 结果: {step3_dir}")


def build_review_editor(
    step3_result_path: str | Path,
    component_source_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> Path:
    step3_path = Path(step3_result_path)
    with open(step3_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows = data.get("rows", [])
    meta = data.get("meta", {})

    # Load component source table for dropdowns
    if component_source_path is None:
        component_source_path = step3_path.parent / COMPONENT_SOURCE_TABLE
    cst_path = Path(component_source_path)
    if cst_path.exists():
        with open(cst_path, "r", encoding="utf-8") as f:
            cst = json.load(f)
        components_ref = cst.get("components", [])
    else:
        components_ref = []

    if output_path is None:
        output_path = step3_path.parent / OUTPUT_HTML_NAME
    else:
        output_path = Path(output_path)

    # Group rows by project_code, preserving order
    by_code: Dict[str, List[Dict]] = defaultdict(list)
    code_order = []
    for r in rows:
        code = r.get("project_code", "")
        if code not in by_code:
            code_order.append(code)
        by_code[code].append(r)

    # Build bill items array for JS
    bill_items = []
    for code in code_order:
        code_rows = by_code[code]
        first = code_rows[0]
        bill_items.append({
            "project_code": code,
            "project_name": first.get("project_name", ""),
            "section_path": first.get("section_path", ""),
            "chapter_root": first.get("chapter_root", ""),
            "project_features_raw": first.get("project_features_raw", ""),
        "project_features_display": _build_project_feature_summary(code_rows),
            "rows": code_rows,
        })

    # Build component reference for dropdowns
    comp_ref = []
    for c in components_ref:
        calcs = c.get("calculations", [])
        attrs = c.get("attributes", [])
        comp_ref.append({
            "name": c.get("component_name", ""),
            "calculations": [
                {"code": calc.get("code", ""), "name": calc.get("name", ""), "unit": calc.get("unit", "")}
                for calc in calcs
            ],
            "attributes": [
                {"code": a.get("code", ""), "name": a.get("name", "")}
                for a in attrs
            ],
        })

    bill_json = json.dumps(bill_items, ensure_ascii=False)
    comp_ref_json = json.dumps(comp_ref, ensure_ascii=False)

    total_items = len(bill_items)
    total_rows = len(rows)
    total_comps = len(comp_ref)

    doc = _build_html(meta, total_items, total_rows, total_comps, bill_json, comp_ref_json)

    output_path.write_text(doc, encoding="utf-8")
    print(f"Editor: {output_path} ({output_path.stat().st_size / 1024:.0f} KB)")
    return output_path


def _build_html(meta, total_items, total_rows, total_comps, bill_json, comp_ref_json):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    std_doc = _esc(meta.get("standard_document", ""))

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Step3 人工审定编辑器</title>
<style>
:root {{ color-scheme:dark; --bg:#0f172a; --card:#111827; --card2:#1e293b; --border:#334155; --text:#e2e8f0; --muted:#94a3b8; --ok:#16a34a; --warn:#d97706; --danger:#dc2626; --blue:#3b82f6; --purple:#8b5cf6; --input-bg:#1e293b; }}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; background:var(--bg); color:var(--text); font-size:14px; line-height:1.5; }}
.wrap {{ max-width:1900px; margin:0 auto; padding:16px 24px; }}
h1 {{ font-size:22px; margin-bottom:4px; }}
h2 {{ font-size:16px; }}
.muted {{ color:var(--muted); }}
.small {{ font-size:12px; }}

/* Top bar */
.top-bar {{ display:flex; align-items:center; gap:16px; flex-wrap:wrap; margin:16px 0 12px; }}
.top-bar input[type=text] {{ flex:1; min-width:200px; padding:8px 12px; border:1px solid var(--border); background:var(--input-bg); color:var(--text); border-radius:8px; font-size:14px; }}
.top-bar select {{ padding:8px 12px; border:1px solid var(--border); background:var(--input-bg); color:var(--text); border-radius:8px; }}
.btn {{ padding:8px 16px; border:none; border-radius:8px; cursor:pointer; font-size:13px; font-weight:600; transition:all .15s; }}
.btn-primary {{ background:var(--blue); color:#fff; }}
.btn-primary:hover {{ background:#2563eb; }}
.btn-ok {{ background:var(--ok); color:#fff; }}
.btn-ok:hover {{ background:#15803d; }}
.btn-danger {{ background:var(--danger); color:#fff; }}
.btn-danger:hover {{ background:#b91c1c; }}
.btn-outline {{ background:transparent; border:1px solid var(--border); color:var(--text); }}
.btn-outline:hover {{ border-color:var(--blue); color:var(--blue); }}
.btn-sm {{ padding:4px 10px; font-size:12px; }}

/* Stats */
.stats {{ display:flex; gap:16px; margin-bottom:12px; font-size:13px; }}
.stat-item {{ padding:4px 12px; background:var(--card); border:1px solid var(--border); border-radius:8px; }}
.stat-item b {{ margin-left:4px; }}

/* Main layout */
.main {{ display:grid; grid-template-columns:360px 1fr; gap:12px; }}
.sidebar {{ max-height:calc(100vh - 140px); overflow-y:auto; position:sticky; top:12px; }}
.detail-panel {{ min-height:60vh; }}

/* Bill item list */
.item-card {{ padding:10px 12px; border:1px solid transparent; border-radius:10px; cursor:pointer; margin-bottom:4px; transition:all .15s; }}
.item-card:hover {{ background:var(--card); border-color:var(--border); }}
.item-card.active {{ background:var(--card); border-color:var(--blue); }}
.item-card .code {{ font-weight:700; font-size:13px; font-family:monospace; }}
.item-card .name {{ font-size:13px; margin-top:2px; }}
.item-card .meta-line {{ font-size:11px; color:var(--muted); margin-top:2px; display:flex; gap:8px; }}
.item-card .badge {{ display:inline-block; padding:1px 6px; border-radius:4px; font-size:11px; font-weight:600; }}
.badge-matched {{ background:rgba(22,163,74,.15); color:#86efac; }}
.badge-candidate {{ background:rgba(217,119,6,.15); color:#fcd34d; }}
.badge-unmatched {{ background:rgba(220,38,38,.15); color:#fca5a5; }}
.badge-reviewed {{ background:rgba(139,92,246,.15); color:#c4b5fd; }}

/* Detail panel */
.detail {{ background:var(--card); border:1px solid var(--border); border-radius:14px; padding:20px; }}
.detail-header {{ margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid var(--border); }}
.detail-header .project-code {{ font-size:20px; font-weight:700; font-family:monospace; }}
.detail-header .project-name {{ font-size:16px; margin-top:4px; }}
.detail-header .section {{ font-size:12px; color:var(--muted); margin-top:4px; }}
.detail-header .raw-features {{ font-size:13px; color:var(--warn); margin-top:8px; padding:8px; background:var(--card2); border-radius:8px; white-space:pre-wrap; }}
.detail-header details.raw-features-raw {{ margin-top:8px; padding:8px; background:var(--card2); border-radius:8px; }}
.detail-header details.raw-features-raw summary {{ cursor:pointer; color:var(--muted); font-size:12px; }}
.detail-header details.raw-features-raw div {{ margin-top:8px; white-space:pre-wrap; color:var(--muted); font-size:12px; }}

/* Component row editor */
.comp-row {{ background:var(--card2); border:1px solid var(--border); border-radius:12px; padding:16px; margin-bottom:12px; }}
.comp-row.is-new {{ border-color:var(--blue); border-style:dashed; }}
.comp-row-header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }}
.comp-row-header .row-id {{ font-family:monospace; font-size:12px; color:var(--muted); }}
.comp-row-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }}
.field {{ display:flex; flex-direction:column; gap:4px; }}
.field label {{ font-size:12px; color:var(--muted); font-weight:600; }}
.field select, .field input {{ padding:6px 10px; border:1px solid var(--border); background:var(--bg); color:var(--text); border-radius:6px; font-size:13px; }}
.field select:focus, .field input:focus {{ outline:none; border-color:var(--blue); }}

/* Feature tags editor */
.features-editor {{ margin-top:12px; }}
.feat-tag {{ display:inline-flex; align-items:center; gap:4px; padding:3px 10px; border-radius:6px; font-size:12px; margin:3px; cursor:pointer; transition:all .15s; }}
.feat-tag.matched {{ background:rgba(22,163,74,.15); color:#86efac; border:1px solid rgba(22,163,74,.3); }}
.feat-tag.unmatched {{ background:rgba(220,38,38,.15); color:#fca5a5; border:1px solid rgba(220,38,38,.3); }}
.feat-tag:hover {{ filter:brightness(1.2); }}
.feat-tag .toggle-icon {{ font-size:10px; }}

/* review status */
.review-bar {{ display:flex; gap:8px; align-items:center; margin-top:12px; padding-top:12px; border-top:1px solid var(--border); }}
.review-bar label {{ font-size:12px; color:var(--muted); }}
.review-bar textarea {{ flex:1; padding:6px 10px; border:1px solid var(--border); background:var(--bg); color:var(--text); border-radius:6px; font-size:12px; min-height:32px; resize:vertical; }}

/* Actions */
.actions-bar {{ display:flex; gap:8px; margin-top:12px; justify-content:flex-end; }}
.action-float {{ position:fixed; bottom:24px; right:24px; z-index:100; display:flex; gap:8px; }}

/* Placeholder */
.placeholder {{ display:flex; align-items:center; justify-content:center; min-height:40vh; color:var(--muted); font-size:16px; }}

/* Toast */
.toast {{ position:fixed; top:20px; right:20px; padding:12px 20px; border-radius:10px; color:#fff; font-weight:600; font-size:14px; z-index:1000; opacity:0; transition:opacity .3s; pointer-events:none; }}
.toast.show {{ opacity:1; }}
.toast-ok {{ background:var(--ok); }}
.toast-err {{ background:var(--danger); }}

/* Diff indicator */
.changed {{ position:relative; }}
.changed::after {{ content:''; position:absolute; top:0; left:-6px; width:3px; height:100%; background:var(--warn); border-radius:2px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Step3 人工审定编辑器</h1>
  <p class="muted">按清单条目逐一审定构件匹配结果 &mdash; {std_doc} &mdash; {ts}</p>

  <div class="top-bar">
    <input type="text" id="searchInput" placeholder="搜索项目编码或名称..." />
    <select id="filterStatus">
      <option value="">全部状态</option>
      <option value="matched">已匹配</option>
      <option value="candidate_only">候选</option>
      <option value="unmatched">未匹配</option>
      <option value="reviewed">已审定</option>
    </select>
    <select id="filterChapter">
      <option value="">全部章节</option>
    </select>
    <button class="btn btn-primary" onclick="exportReviewed()">💾 导出审定结果</button>
    <button class="btn btn-ok" onclick="exportWikiPatch()">📖 导出 Wiki 补丁</button>
  </div>

  <div class="stats" id="statsBar"></div>

  <div class="main">
    <div class="sidebar" id="sidebar"></div>
    <div class="detail-panel" id="detailPanel">
      <div class="placeholder">← 选择左侧清单条目开始审定</div>
    </div>
  </div>
</div>

<div id="toast" class="toast"></div>

<script>
const BILL_ITEMS = {bill_json};
const COMP_REF = {comp_ref_json};
const COMP_NAMES = COMP_REF.map(c => c.name).sort();

// Track modifications
const modifications = {{}};  // project_code -> modified rows array

let currentCode = null;
let filteredItems = BILL_ITEMS;

// ====== Init ======
function init() {{
  // Populate chapter filter
  const chapters = [...new Set(BILL_ITEMS.map(b => b.chapter_root).filter(Boolean))].sort();
  const chSel = document.getElementById('filterChapter');
  chapters.forEach(ch => {{
    const opt = document.createElement('option');
    opt.value = ch; opt.textContent = ch;
    chSel.appendChild(opt);
  }});

  document.getElementById('searchInput').addEventListener('input', applyFilters);
  document.getElementById('filterStatus').addEventListener('change', applyFilters);
  document.getElementById('filterChapter').addEventListener('change', applyFilters);

  applyFilters();
}}

function applyFilters() {{
  const q = document.getElementById('searchInput').value.toLowerCase();
  const status = document.getElementById('filterStatus').value;
  const chapter = document.getElementById('filterChapter').value;

  filteredItems = BILL_ITEMS.filter(b => {{
    if (q && !b.project_code.toLowerCase().includes(q) && !b.project_name.toLowerCase().includes(q)) return false;
    if (chapter && b.chapter_root !== chapter) return false;
    if (status) {{
      const rows = getRows(b.project_code);
      if (status === 'reviewed') {{
        if (!modifications[b.project_code]) return false;
      }} else {{
        if (!rows.some(r => r.match_status === status)) return false;
      }}
    }}
    return true;
  }});

  renderSidebar();
  updateStats();
}}

function getRows(code) {{
  if (modifications[code]) return modifications[code];
  const item = BILL_ITEMS.find(b => b.project_code === code);
  return item ? item.rows : [];
}}

function updateStats() {{
  let totalReviewed = Object.keys(modifications).length;
  let totalMatched = 0, totalCandidate = 0, totalUnmatched = 0;
  BILL_ITEMS.forEach(b => {{
    const rows = getRows(b.project_code);
    rows.forEach(r => {{
      if (r.match_status === 'matched') totalMatched++;
      else if (r.match_status === 'candidate_only') totalCandidate++;
      else if (r.match_status === 'unmatched') totalUnmatched++;
    }});
  }});
  document.getElementById('statsBar').innerHTML = `
    <div class="stat-item">清单条目<b>${{filteredItems.length}}/{{{total_items}}}</b></div>
    <div class="stat-item" style="color:var(--ok)">已匹配<b>${{totalMatched}}</b></div>
    <div class="stat-item" style="color:var(--warn)">候选<b>${{totalCandidate}}</b></div>
    <div class="stat-item" style="color:var(--danger)">未匹配<b>${{totalUnmatched}}</b></div>
    <div class="stat-item" style="color:var(--purple)">已审定<b>${{totalReviewed}}</b></div>
  `;
}}

// ====== Sidebar ======
function renderSidebar() {{
  const el = document.getElementById('sidebar');
  el.innerHTML = '';
  filteredItems.forEach(b => {{
    const rows = getRows(b.project_code);
    const bestStatus = getBestStatus(rows);
    const isModified = !!modifications[b.project_code];
    const comps = rows.map(r => r.source_component_name || '(无)').join(', ');

    const div = document.createElement('div');
    div.className = 'item-card' + (b.project_code === currentCode ? ' active' : '');
    div.onclick = () => selectItem(b.project_code);
    div.innerHTML = `
      <div class="code">${{esc(b.project_code)}}${{isModified ? ' <span class="badge badge-reviewed">已审定</span>' : ''}}</div>
      <div class="name">${{esc(b.project_name)}}</div>
      <div class="meta-line">
        <span class="badge badge-${{bestStatus === 'matched' ? 'matched' : bestStatus === 'candidate_only' ? 'candidate' : 'unmatched'}}">${{statusLabel(bestStatus)}}</span>
        <span>${{rows.length}}个构件</span>
        <span class="muted">${{esc(b.chapter_root)}}</span>
      </div>
    `;
    el.appendChild(div);
  }});
}}

function getBestStatus(rows) {{
  if (rows.some(r => r.match_status === 'matched')) return 'matched';
  if (rows.some(r => r.match_status === 'candidate_only')) return 'candidate_only';
  return 'unmatched';
}}

function statusLabel(s) {{
  return s === 'matched' ? '已匹配' : s === 'candidate_only' ? '候选' : '未匹配';
}}

// ====== Detail ======
function selectItem(code) {{
  currentCode = code;
  document.querySelectorAll('.item-card').forEach(el => {{
    el.classList.toggle('active', el.querySelector('.code').textContent.startsWith(code));
  }});
  renderDetail();
}}

function renderDetail() {{
  if (!currentCode) return;
  const item = BILL_ITEMS.find(b => b.project_code === currentCode);
  if (!item) return;
  const rows = getRows(currentCode);
  const panel = document.getElementById('detailPanel');

  let h = `<div class="detail">
    <div class="detail-header">
      <div class="project-code">${{esc(item.project_code)}}</div>
      <div class="project-name">${{esc(item.project_name)}}</div>
      <div class="section">${{esc(item.section_path)}}</div>
      ${{item.project_features_display ? '<div class="raw-features">Step3特征：' + esc(item.project_features_display) + '</div>' : ''}}
      ${{item.project_features_raw && item.project_features_raw !== item.project_features_display
        ? '<details class="raw-features-raw"><summary>查看原始项目特征</summary><div>' + esc(item.project_features_raw) + '</div></details>'
        : ''}}
    </div>`;

  rows.forEach((r, idx) => {{
    h += renderCompRow(r, idx);
  }});

  h += `<div class="actions-bar">
    <button class="btn btn-outline btn-sm" onclick="addComponent()">＋ 添加构件</button>
    <button class="btn btn-primary btn-sm" onclick="saveItem()">✓ 确认审定</button>
    <button class="btn btn-outline btn-sm" onclick="resetItem()">↩ 重置</button>
  </div>`;

  h += '</div>';
  panel.innerHTML = h;
}}

function renderCompRow(r, idx) {{
  const compRef = COMP_REF.find(c => c.name === (r.source_component_name || ''));
  const calcs = compRef ? compRef.calculations : [];

  let compOptions = '<option value="">(无构件)</option>';
  COMP_NAMES.forEach(n => {{
    compOptions += '<option value="' + esc(n) + '"' + (n === (r.source_component_name || '') ? ' selected' : '') + '>' + esc(n) + '</option>';
  }});

  let calcOptions = '<option value="">(无)</option>';
  // Always show current value even if not in ref
  if (r.calculation_item_code && !calcs.find(c => c.code === r.calculation_item_code)) {{
    calcOptions += '<option value="' + esc(r.calculation_item_code) + '" selected>' + esc(r.calculation_item_code + ' ' + (r.calculation_item_name || '')) + '</option>';
  }}
  calcs.forEach(c => {{
    calcOptions += '<option value="' + esc(c.code) + '"' + (c.code === (r.calculation_item_code || '') ? ' selected' : '') + '>' + esc(c.code + ' ' + c.name + ' (' + c.unit + ')') + '</option>';
  }});

  let statusOpts = '';
  ['matched','candidate_only','unmatched'].forEach(s => {{
    statusOpts += '<option value="' + s + '"' + (s === r.match_status ? ' selected' : '') + '>' + statusLabel(s) + '</option>';
  }});

  // Feature tags
  const feats = r.feature_expression_items || [];
  let featHtml = '';
  feats.forEach((f, fi) => {{
    const cls = f.matched ? 'matched' : 'unmatched';
    const label = f.label || f.raw_text || '';
    featHtml += '<span class="feat-tag ' + cls + '" onclick="toggleFeature(' + idx + ',' + fi + ')" title="点击切换匹配状态">' +
      '<span class="toggle-icon">' + (f.matched ? '✓' : '✗') + '</span> ' + esc(label) +
      (f.value_expression ? ': ' + esc(f.value_expression) : '') + '</span>';
  }});

  return `<div class="comp-row" data-idx="${{idx}}">
    <div class="comp-row-header">
      <span class="row-id">${{esc(r.row_id || 'NEW')}} #${{idx + 1}}</span>
      <button class="btn btn-danger btn-sm" onclick="removeComponent(${{idx}})">✕ 移除</button>
    </div>
    <div class="comp-row-grid">
      <div class="field">
        <label>构件类型</label>
        <select onchange="onCompChange(${{idx}}, this.value)">${{compOptions}}</select>
      </div>
      <div class="field">
        <label>匹配状态</label>
        <select onchange="onFieldChange(${{idx}}, 'match_status', this.value)">${{statusOpts}}</select>
      </div>
      <div class="field">
        <label>计算项目</label>
        <select id="calc-${{idx}}" onchange="onCalcChange(${{idx}}, this.value)">${{calcOptions}}</select>
      </div>
      <div class="field">
        <label>计量单位</label>
        <input value="${{esc(r.measurement_unit || '')}}" onchange="onFieldChange(${{idx}}, 'measurement_unit', this.value)" />
      </div>
    </div>
    <div class="features-editor">
      <label class="small muted">项目特征 <span class="small">(点击切换匹配状态)</span></label>
      <div style="margin-top:4px">${{featHtml || '<span class="muted">无特征项</span>'}}</div>
    </div>
    <div class="review-bar">
      <label>备注</label>
      <textarea onchange="onFieldChange(${{idx}}, 'notes', this.value)" placeholder="审定备注...">${{esc(r.notes || '')}}</textarea>
    </div>
  </div>`;
}}

// ====== Edit operations ======
function ensureModified() {{
  if (!modifications[currentCode]) {{
    const item = BILL_ITEMS.find(b => b.project_code === currentCode);
    modifications[currentCode] = JSON.parse(JSON.stringify(item.rows));
  }}
}}

function onCompChange(idx, newComp) {{
  ensureModified();
  const row = modifications[currentCode][idx];
  row.source_component_name = newComp;
  row.resolved_component_name = newComp;
  row.quantity_component = newComp;
  // Update calc dropdown for new component
  const ref = COMP_REF.find(c => c.name === newComp);
  if (ref) {{
    row.calculation_item_code = '';
    row.calculation_item_name = '';
    // Rebuild calc dropdown
    const sel = document.getElementById('calc-' + idx);
    if (sel) {{
      sel.innerHTML = '<option value="">(无)</option>';
      ref.calculations.forEach(c => {{
        const opt = document.createElement('option');
        opt.value = c.code;
        opt.textContent = c.code + ' ' + c.name + ' (' + c.unit + ')';
        sel.appendChild(opt);
      }});
    }}
  }}
  markDirty();
}}

function onCalcChange(idx, code) {{
  ensureModified();
  const row = modifications[currentCode][idx];
  row.calculation_item_code = code;
  // Find name from ref
  const comp = COMP_REF.find(c => c.name === row.source_component_name);
  if (comp) {{
    const calc = comp.calculations.find(c => c.code === code);
    if (calc) {{
      row.calculation_item_name = calc.name;
      row.measurement_unit = calc.unit;
    }}
  }}
  markDirty();
}}

function onFieldChange(idx, field, value) {{
  ensureModified();
  modifications[currentCode][idx][field] = value;
  markDirty();
}}

function toggleFeature(rowIdx, featIdx) {{
  ensureModified();
  const feat = modifications[currentCode][rowIdx].feature_expression_items[featIdx];
  feat.matched = !feat.matched;
  renderDetail();
  markDirty();
}}

function addComponent() {{
  ensureModified();
  const item = BILL_ITEMS.find(b => b.project_code === currentCode);
  modifications[currentCode].push({{
    row_id: '',
    result_id: '',
    project_code: currentCode,
    project_name: item.project_name,
    section_path: item.section_path,
    chapter_root: item.chapter_root,
    source_component_name: '',
    resolved_component_name: '',
    quantity_component: '',
    match_status: 'unmatched',
    confidence: 0,
    match_basis: 'manual',
    calculation_item_code: '',
    calculation_item_name: '',
    measurement_unit: '',
    feature_expression_items: JSON.parse(JSON.stringify(
      (modifications[currentCode][0] || {{}}).feature_expression_items || []
    )),
    review_status: 'manual',
    notes: '',
  }});
  renderDetail();
  markDirty();
}}

function removeComponent(idx) {{
  ensureModified();
  if (modifications[currentCode].length <= 1) {{
    showToast('至少保留一个构件行', 'err');
    return;
  }}
  modifications[currentCode].splice(idx, 1);
  renderDetail();
  markDirty();
}}

function saveItem() {{
  ensureModified();
  modifications[currentCode].forEach(r => {{
    r.review_status = 'reviewed';
  }});
  renderDetail();
  renderSidebar();
  updateStats();
  showToast(currentCode + ' 已审定', 'ok');
  // Auto-advance to next unreviewed
  const nextItem = filteredItems.find(b => b.project_code !== currentCode && !modifications[b.project_code]);
  if (nextItem) selectItem(nextItem.project_code);
}}

function resetItem() {{
  delete modifications[currentCode];
  renderDetail();
  renderSidebar();
  updateStats();
  showToast(currentCode + ' 已重置', 'ok');
}}

function markDirty() {{
  updateStats();
}}

// ====== Export ======
function exportReviewed() {{
  const result = {{
    meta: {{
      source: 'step3_review_editor',
      exported_at: new Date().toISOString(),
      total_reviewed: Object.keys(modifications).length,
    }},
    reviewed_items: {{}},
  }};
  Object.entries(modifications).forEach(([code, rows]) => {{
    result.reviewed_items[code] = rows;
  }});

  const blob = new Blob([JSON.stringify(result, null, 2)], {{type: 'application/json'}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'step3_reviewed_' + new Date().toISOString().slice(0,10) + '.json';
  a.click();
  URL.revokeObjectURL(url);
  showToast('已导出 ' + Object.keys(modifications).length + ' 条审定结果', 'ok');
}}

function exportWikiPatch() {{
  // Group reviewed items by component for wiki feedback
  const byComp = {{}};
  Object.entries(modifications).forEach(([code, rows]) => {{
    rows.forEach(r => {{
      const comp = r.source_component_name || '';
      if (!comp) return;
      if (!byComp[comp]) byComp[comp] = [];
      byComp[comp].push({{
        project_code: r.project_code,
        project_name: r.project_name,
        match_status: r.match_status,
        calculation_item_code: r.calculation_item_code,
        calculation_item_name: r.calculation_item_name,
        measurement_unit: r.measurement_unit,
        feature_expression_items: (r.feature_expression_items || []).map(f => ({{
          label: f.label || f.raw_text || '',
          matched: f.matched,
          value_expression: f.value_expression || '',
        }})),
        notes: r.notes || '',
        reviewed: true,
      }});
    }});
  }});

  const patch = {{
    meta: {{
      source: 'step3_review_editor',
      exported_at: new Date().toISOString(),
      purpose: 'wiki_knowledge_patch',
    }},
    components: byComp,
  }};

  const blob = new Blob([JSON.stringify(patch, null, 2)], {{type: 'application/json'}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'wiki_patch_' + new Date().toISOString().slice(0,10) + '.json';
  a.click();
  URL.revokeObjectURL(url);
  showToast('已导出 Wiki 补丁（' + Object.keys(byComp).length + ' 构件）', 'ok');
}}

// ====== Helpers ======
function esc(s) {{
  if (s == null) return '';
  const d = document.createElement('div');
  d.textContent = String(s);
  return d.innerHTML;
}}

function showToast(msg, type) {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast toast-' + type + ' show';
  setTimeout(() => t.className = 'toast', 2000);
}}

// Keyboard navigation
document.addEventListener('keydown', e => {{
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
  const idx = filteredItems.findIndex(b => b.project_code === currentCode);
  if (e.key === 'ArrowDown' || e.key === 'j') {{
    e.preventDefault();
    if (idx < filteredItems.length - 1) selectItem(filteredItems[idx + 1].project_code);
  }} else if (e.key === 'ArrowUp' || e.key === 'k') {{
    e.preventDefault();
    if (idx > 0) selectItem(filteredItems[idx - 1].project_code);
  }} else if (e.key === 'Enter') {{
    e.preventDefault();
    saveItem();
  }}
}});

init();
</script>
</body>
</html>"""


def main():
    import sys
    base = Path(__file__).resolve().parent.parent
    step3_dir = base / "data" / "output" / "step3"
    if len(sys.argv) > 1:
        step3_path = _resolve_result_path(Path(sys.argv[1]))
    else:
        try:
            step3_path = _find_latest_result(step3_dir)
        except FileNotFoundError as exc:
            print(str(exc))
            sys.exit(1)

    # Auto-find component source table
    cst_path = step3_path.parent / COMPONENT_SOURCE_TABLE
    if not cst_path.exists():
        # Try other step3 run dirs
        for p in step3_dir.glob("*/" + COMPONENT_SOURCE_TABLE):
            cst_path = p
            break

    build_review_editor(step3_path, cst_path if cst_path.exists() else None)


if __name__ == "__main__":
    main()
