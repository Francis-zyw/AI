from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

FINAL_JSON_NAME = "project_component_feature_calc_matching_result.json"
FINAL_HTML_NAME = "project_component_feature_calc_matching_result.html"
RUN_SUMMARY_NAME = "run_summary.json"


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _esc(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return html.escape(str(value))


def _badge(status: str) -> str:
    color = {
        "matched": "#16a34a",
        "candidate_only": "#d97706",
        "unmatched": "#dc2626",
        "reviewed": "#2563eb",
        "pending": "#7c3aed",
    }.get(status, "#64748b")
    return f'<span class="badge" style="background:{color}22;color:{color};border-color:{color}55">{_esc(status)}</span>'


def build_step3_html_report(output_dir: str | Path) -> Path:
    output_path = Path(output_dir)
    result_path = output_path / FINAL_JSON_NAME
    summary_path = output_path / RUN_SUMMARY_NAME

    payload = _load_json(result_path)
    summary = _load_json(summary_path) if summary_path.exists() else {}

    meta = payload.get("meta", {})
    stats = payload.get("statistics", {})
    rows = payload.get("rows", [])

    cards = [
        ("状态", summary.get("status", "")),
        ("模型", summary.get("model", meta.get("model", ""))),
        ("总批次", summary.get("total_batches", "")),
        ("源行数", summary.get("total_source_rows", stats.get("total_source_rows", ""))),
        ("生成行数", summary.get("generated_rows", stats.get("generated_rows", ""))),
        ("已匹配", summary.get("matched_rows", stats.get("matched_rows", ""))),
        ("候选待审", summary.get("candidate_only_rows", stats.get("candidate_only_rows", ""))),
        ("未匹配", summary.get("unmatched_rows", stats.get("unmatched_rows", ""))),
    ]

    card_html = "".join(
        f'<div class="card"><div class="label">{_esc(k)}</div><div class="value">{_esc(v)}</div></div>'
        for k, v in cards
    )

    chapter_options = sorted({str(r.get("chapter_root") or r.get("section_path") or "") for r in rows if (r.get("chapter_root") or r.get("section_path"))})
    component_options = sorted({str(r.get("quantity_component") or r.get("resolved_component_name") or "") for r in rows if (r.get("quantity_component") or r.get("resolved_component_name"))})

    payload_json = json.dumps(rows, ensure_ascii=False)
    chapter_options_json = json.dumps(chapter_options, ensure_ascii=False)
    component_options_json = json.dumps(component_options, ensure_ascii=False)

    doc = f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Step3 可视化验收页</title>
  <style>
    :root {{ color-scheme: light dark; }}
    body {{ font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; margin:0; background:#0f172a; color:#e2e8f0; }}
    .wrap {{ max-width: 1700px; margin: 0 auto; padding: 24px; }}
    h1,h2,h3 {{ margin: 0 0 12px; }}
    .muted {{ color:#94a3b8; }}
    .grid {{ display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:12px; margin:20px 0; }}
    .card,.panel {{ background:#111827; border:1px solid #334155; border-radius:14px; padding:16px; }}
    .label {{ font-size:12px; color:#94a3b8; margin-bottom:8px; }}
    .value {{ font-size:28px; font-weight:700; line-height:1.1; word-break:break-word; }}
    .panel {{ margin-top:16px; }}
    .kv {{ display:grid; grid-template-columns: 180px 1fr; gap:8px 12px; }}
    .kv div {{ padding:4px 0; border-bottom:1px dashed #334155; }}
    .filters {{ display:grid; grid-template-columns: 2fr 1fr 1fr 1fr 1fr; gap:12px; margin-top:12px; }}
    input,select {{ width:100%; box-sizing:border-box; border:1px solid #334155; background:#0b1220; color:#e2e8f0; border-radius:10px; padding:10px 12px; }}
    .stats-mini {{ display:grid; grid-template-columns: repeat(6, minmax(0,1fr)); gap:10px; margin-top:14px; }}
    .mini {{ background:#0b1220; border:1px solid #334155; border-radius:12px; padding:12px; }}
    .mini .n {{ font-size:24px; font-weight:700; }}
    .table-wrap {{ overflow:auto; max-height:68vh; border:1px solid #334155; border-radius:12px; margin-top:14px; }}
    table {{ width:100%; border-collapse: collapse; font-size:13px; }}
    th,td {{ border-bottom:1px solid #334155; padding:10px 8px; text-align:left; vertical-align:top; }}
    th {{ position:sticky; top:0; background:#0b1220; z-index:1; }}
    .badge {{ display:inline-block; padding:2px 8px; border-radius:999px; border:1px solid; font-size:12px; font-weight:600; white-space:nowrap; }}
    .toolbar {{ display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; margin-top:10px; }}
    .btn {{ border:1px solid #334155; background:#0b1220; color:#e2e8f0; border-radius:10px; padding:8px 12px; cursor:pointer; }}
    .pager {{ display:flex; align-items:center; gap:8px; }}
    .danger {{ color:#fca5a5; }}
    .warn {{ color:#fdba74; }}
    .ok {{ color:#86efac; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Step3 可视化验收页</h1>
    <div class="muted">用于筛选、搜索和验收 Step3 结果。页面内置客户端筛选，不改原始 JSON；原始结果仍以 JSON 为准。</div>

    <div class="grid">{card_html}</div>

    <div class="panel">
      <h2>元信息</h2>
      <div class="kv">
        <div class="muted">标准文档</div><div>{_esc(meta.get('standard_document'))}</div>
        <div class="muted">生成时间</div><div>{_esc(meta.get('generated_at', summary.get('completed_at')))}</div>
        <div class="muted">输出目录</div><div>{_esc(summary.get('output_dir'))}</div>
        <div class="muted">Step2 状态</div><div>{_esc(summary.get('step2_status'))}</div>
        <div class="muted">本地基线</div><div>{_esc(meta.get('local_rule_baseline'))}</div>
      </div>
    </div>

    <div class="panel">
      <h2>验收筛选</h2>
      <div class="filters">
        <input id="searchInput" placeholder="搜索：项目编码 / 项目名称 / 构件 / 计算项编码 / 特征表达式" />
        <select id="matchStatusFilter"><option value="">全部匹配状态</option></select>
        <select id="reviewStatusFilter"><option value="">全部复核状态</option></select>
        <select id="chapterFilter"><option value="">全部章节</option></select>
        <select id="componentFilter"><option value="">全部构件</option></select>
      </div>

      <div class="stats-mini">
        <div class="mini"><div class="label">当前筛选结果</div><div class="n" id="countFiltered">0</div></div>
        <div class="mini"><div class="label">matched</div><div class="n ok" id="countMatched">0</div></div>
        <div class="mini"><div class="label">candidate_only</div><div class="n warn" id="countCandidate">0</div></div>
        <div class="mini"><div class="label">unmatched</div><div class="n danger" id="countUnmatched">0</div></div>
        <div class="mini"><div class="label">reviewed</div><div class="n" id="countReviewed">0</div></div>
        <div class="mini"><div class="label">pending</div><div class="n" id="countPending">0</div></div>
      </div>

      <div class="toolbar">
        <div class="muted" id="resultHint">正在载入数据…</div>
        <div class="pager">
          <button class="btn" id="prevBtn">上一页</button>
          <span id="pageInfo" class="muted"></span>
          <button class="btn" id="nextBtn">下一页</button>
          <button class="btn" id="resetBtn">重置筛选</button>
        </div>
      </div>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>row_id</th>
              <th>项目编码</th>
              <th>项目名称</th>
              <th>章节</th>
              <th>构件</th>
              <th>匹配状态</th>
              <th>复核状态</th>
              <th>计算项编码</th>
              <th>单位</th>
              <th>置信度</th>
              <th>特征表达式</th>
              <th>推理说明</th>
            </tr>
          </thead>
          <tbody id="tableBody"></tbody>
        </table>
      </div>
    </div>
  </div>

<script>
const allRows = {payload_json};
const chapterOptions = {chapter_options_json};
const componentOptions = {component_options_json};
const pageSize = 100;
let filteredRows = [];
let currentPage = 1;

function esc(v) {{
  if (v === null || v === undefined) return '';
  return String(v)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}}

function badge(status) {{
  const colors = {{ matched:'#16a34a', candidate_only:'#d97706', unmatched:'#dc2626', reviewed:'#2563eb', pending:'#7c3aed' }};
  const color = colors[status] || '#64748b';
  return `<span class="badge" style="background:${{color}}22;color:${{color}};border-color:${{color}}55">${{esc(status)}}</span>`;
}}

function fillSelect(id, values) {{
  const el = document.getElementById(id);
  for (const value of values) {{
    const opt = document.createElement('option');
    opt.value = value;
    opt.textContent = value;
    el.appendChild(opt);
  }}
}}

function initFilters() {{
  const matchStatuses = [...new Set(allRows.map(r => r.match_status).filter(Boolean))].sort();
  const reviewStatuses = [...new Set(allRows.map(r => r.review_status).filter(Boolean))].sort();
  fillSelect('matchStatusFilter', matchStatuses);
  fillSelect('reviewStatusFilter', reviewStatuses);
  fillSelect('chapterFilter', chapterOptions);
  fillSelect('componentFilter', componentOptions);
}}

function applyFilters() {{
  const q = document.getElementById('searchInput').value.trim().toLowerCase();
  const matchStatus = document.getElementById('matchStatusFilter').value;
  const reviewStatus = document.getElementById('reviewStatusFilter').value;
  const chapter = document.getElementById('chapterFilter').value;
  const component = document.getElementById('componentFilter').value;

  filteredRows = allRows.filter(r => {{
    const text = [
      r.row_id, r.project_code, r.project_name, r.section_path, r.chapter_root,
      r.quantity_component, r.resolved_component_name, r.source_component_name,
      r.calculation_item_code, r.feature_expression_text, r.reasoning
    ].filter(Boolean).join(' ').toLowerCase();

    if (q && !text.includes(q)) return false;
    if (matchStatus && r.match_status !== matchStatus) return false;
    if (reviewStatus && r.review_status !== reviewStatus) return false;
    if (chapter && (r.chapter_root || r.section_path) !== chapter) return false;
    const comp = r.quantity_component || r.resolved_component_name || '';
    if (component && comp !== component) return false;
    return true;
  }});

  currentPage = 1;
  updateStats();
  renderTable();
}}

function updateStats() {{
  const counts = {{ matched:0, candidate_only:0, unmatched:0, reviewed:0, pending:0 }};
  for (const r of filteredRows) {{
    if (counts[r.match_status] !== undefined) counts[r.match_status] += 1;
    if (counts[r.review_status] !== undefined) counts[r.review_status] += 1;
  }}
  document.getElementById('countFiltered').textContent = filteredRows.length;
  document.getElementById('countMatched').textContent = counts.matched;
  document.getElementById('countCandidate').textContent = counts.candidate_only;
  document.getElementById('countUnmatched').textContent = counts.unmatched;
  document.getElementById('countReviewed').textContent = counts.reviewed;
  document.getElementById('countPending').textContent = counts.pending;
  document.getElementById('resultHint').textContent = `共 ${{allRows.length}} 行；当前筛出 ${{filteredRows.length}} 行。`;
}}

function renderTable() {{
  const start = (currentPage - 1) * pageSize;
  const pageRows = filteredRows.slice(start, start + pageSize);
  const tbody = document.getElementById('tableBody');
  tbody.innerHTML = pageRows.map(r => `
    <tr>
      <td>${{esc(r.row_id)}}</td>
      <td>${{esc(r.project_code)}}</td>
      <td>${{esc(r.project_name)}}</td>
      <td>${{esc(r.chapter_root || r.section_path)}}</td>
      <td>${{esc(r.quantity_component || r.resolved_component_name)}}</td>
      <td>${{badge(r.match_status || '')}}</td>
      <td>${{badge(r.review_status || '')}}</td>
      <td>${{esc(r.calculation_item_code)}}</td>
      <td>${{esc(r.measurement_unit)}}</td>
      <td>${{esc(r.confidence)}}</td>
      <td>${{esc(r.feature_expression_text)}}</td>
      <td>${{esc(r.reasoning)}}</td>
    </tr>
  `).join('');

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / pageSize));
  document.getElementById('pageInfo').textContent = `第 ${{currentPage}} / ${{totalPages}} 页`;
  document.getElementById('prevBtn').disabled = currentPage <= 1;
  document.getElementById('nextBtn').disabled = currentPage >= totalPages;
}}

function bindEvents() {{
  ['searchInput','matchStatusFilter','reviewStatusFilter','chapterFilter','componentFilter'].forEach(id => {{
    document.getElementById(id).addEventListener('input', applyFilters);
    document.getElementById(id).addEventListener('change', applyFilters);
  }});
  document.getElementById('prevBtn').addEventListener('click', () => {{ if (currentPage > 1) {{ currentPage--; renderTable(); }} }});
  document.getElementById('nextBtn').addEventListener('click', () => {{ const totalPages = Math.max(1, Math.ceil(filteredRows.length / pageSize)); if (currentPage < totalPages) {{ currentPage++; renderTable(); }} }});
  document.getElementById('resetBtn').addEventListener('click', () => {{
    document.getElementById('searchInput').value = '';
    document.getElementById('matchStatusFilter').value = '';
    document.getElementById('reviewStatusFilter').value = '';
    document.getElementById('chapterFilter').value = '';
    document.getElementById('componentFilter').value = '';
    applyFilters();
  }});
}}

initFilters();
bindEvents();
applyFilters();
</script>
</body>
</html>'''

    html_path = output_path / FINAL_HTML_NAME
    html_path.write_text(doc, encoding="utf-8")
    return html_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate HTML report for Step3 results")
    parser.add_argument("output_dir", help="Step3 output directory")
    args = parser.parse_args()
    path = build_step3_html_report(args.output_dir)
    print(path)
