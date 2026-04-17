"""
Step3 构件类型分析 HTML 报告生成器

按构件类型维度组织 Step3 结果，揭示：
- 每个构件类型在各清单下的匹配概况
- 未匹配的项目特征（feature_expression_items.matched=false）
- 缺失的计算项目（无 calculation_item_code）
- 全局热力图统计
"""

from __future__ import annotations

import html
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence

RESULT_JSON_NAME = "local_rule_project_component_feature_calc_result.json"
OUTPUT_HTML_NAME = "step3_component_analysis.html"


def _esc(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        v = json.dumps(v, ensure_ascii=False)
    return html.escape(str(v))


def _build_component_data(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """按构件类型聚合分析数据"""
    by_comp: Dict[str, List[Dict]] = defaultdict(list)
    for r in rows:
        comp = r.get("source_component_name", "") or r.get("resolved_component_name", "") or "(无构件)"
        by_comp[comp].append(r)

    components = {}
    for comp, comp_rows in sorted(by_comp.items(), key=lambda x: -len(x[1])):
        total = len(comp_rows)
        matched = sum(1 for r in comp_rows if r.get("match_status") == "matched")
        candidate = sum(1 for r in comp_rows if r.get("match_status") == "candidate_only")
        unmatched = sum(1 for r in comp_rows if r.get("match_status") == "unmatched")
        has_calc = sum(1 for r in comp_rows if r.get("calculation_item_code"))
        pending = sum(1 for r in comp_rows if r.get("review_status") == "pending")

        # Feature analysis
        total_features = 0
        matched_features = 0
        unmatched_labels = Counter()
        matched_labels = Counter()
        for r in comp_rows:
            for item in r.get("feature_expression_items", []):
                total_features += 1
                label = item.get("label", "") or item.get("raw_text", "")
                if item.get("matched"):
                    matched_features += 1
                    matched_labels[label] += 1
                else:
                    unmatched_labels[label] += 1

        # Calc code analysis
        calc_codes = Counter()
        no_calc_rows = []
        for r in comp_rows:
            code = r.get("calculation_item_code", "")
            if code:
                calc_codes[code] += 1
            else:
                no_calc_rows.append({
                    "row_id": r.get("row_id", ""),
                    "project_name": r.get("project_name", ""),
                    "project_code": r.get("project_code", ""),
                })

        # Per-chapter breakdown
        by_chapter: Dict[str, Dict] = defaultdict(lambda: {"total": 0, "matched": 0, "unmatched_features": 0})
        for r in comp_rows:
            ch = r.get("chapter_root", "") or r.get("section_path", "") or "(未知章节)"
            by_chapter[ch]["total"] += 1
            if r.get("match_status") == "matched":
                by_chapter[ch]["matched"] += 1
            for item in r.get("feature_expression_items", []):
                if not item.get("matched"):
                    by_chapter[ch]["unmatched_features"] += 1

        components[comp] = {
            "total": total,
            "matched": matched,
            "candidate": candidate,
            "unmatched": unmatched,
            "has_calc": has_calc,
            "no_calc": total - has_calc,
            "pending": pending,
            "total_features": total_features,
            "matched_features": matched_features,
            "feature_match_rate": round(matched_features / max(total_features, 1) * 100, 1),
            "top_unmatched_labels": unmatched_labels.most_common(20),
            "top_matched_labels": matched_labels.most_common(10),
            "calc_codes": calc_codes.most_common(15),
            "no_calc_rows": no_calc_rows[:10],
            "chapters": dict(by_chapter),
            "rows": comp_rows,
        }
    return components


def build_analysis_html(step3_result_path: str | Path, output_path: str | Path | None = None) -> Path:
    step3_path = Path(step3_result_path)
    with open(step3_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows = data.get("rows", [])
    meta = data.get("meta", {})
    stats = data.get("statistics", {})
    components = _build_component_data(rows)

    if output_path is None:
        output_path = step3_path.parent / OUTPUT_HTML_NAME
    else:
        output_path = Path(output_path)

    # Global stats
    total_rows = len(rows)
    total_comps = len(components)
    global_matched = sum(c["matched"] for c in components.values())
    global_unmatched_features = sum(c["total_features"] - c["matched_features"] for c in components.values())
    global_total_features = sum(c["total_features"] for c in components.values())
    global_no_calc = sum(c["no_calc"] for c in components.values())

    # Embed data as JSON for client-side interactivity
    components_json = json.dumps({
        name: {
            "total": c["total"],
            "matched": c["matched"],
            "candidate": c["candidate"],
            "unmatched": c["unmatched"],
            "has_calc": c["has_calc"],
            "no_calc": c["no_calc"],
            "pending": c["pending"],
            "total_features": c["total_features"],
            "matched_features": c["matched_features"],
            "feature_match_rate": c["feature_match_rate"],
            "top_unmatched_labels": c["top_unmatched_labels"],
            "top_matched_labels": c["top_matched_labels"],
            "calc_codes": c["calc_codes"],
            "no_calc_rows": c["no_calc_rows"],
            "chapters": c["chapters"],
        }
        for name, c in components.items()
    }, ensure_ascii=False)

    rows_json = json.dumps(rows, ensure_ascii=False)

    doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Step3 构件类型匹配分析</title>
<style>
:root {{ color-scheme:light dark; --bg:#0f172a; --card:#111827; --border:#334155; --text:#e2e8f0; --muted:#94a3b8; --ok:#16a34a; --warn:#d97706; --danger:#dc2626; --blue:#3b82f6; --purple:#8b5cf6; }}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; background:var(--bg); color:var(--text); font-size:14px; line-height:1.5; }}
.wrap {{ max-width:1800px; margin:0 auto; padding:24px; }}
h1 {{ font-size:24px; margin-bottom:4px; }}
h2 {{ font-size:18px; margin-bottom:12px; }}
h3 {{ font-size:15px; margin-bottom:8px; }}
.muted {{ color:var(--muted); }}
.small {{ font-size:12px; }}

/* Top summary cards */
.summary-grid {{ display:grid; grid-template-columns:repeat(6,1fr); gap:12px; margin:20px 0; }}
.summary-card {{ background:var(--card); border:1px solid var(--border); border-radius:14px; padding:16px; }}
.summary-card .n {{ font-size:28px; font-weight:700; }}
.summary-card .label {{ font-size:12px; color:var(--muted); margin-top:4px; }}
.ok {{ color:var(--ok); }} .warn {{ color:var(--warn); }} .danger {{ color:var(--danger); }}

/* Component list sidebar + detail */
.main-layout {{ display:grid; grid-template-columns:320px 1fr; gap:16px; margin-top:16px; }}
.sidebar {{ position:sticky; top:24px; align-self:start; max-height:calc(100vh - 48px); overflow-y:auto; }}
.sidebar-search {{ width:100%; padding:10px 12px; border:1px solid var(--border); background:var(--card); color:var(--text); border-radius:10px; margin-bottom:12px; }}
.comp-list {{ list-style:none; }}
.comp-item {{ display:flex; justify-content:space-between; align-items:center; padding:10px 12px; border:1px solid transparent; border-radius:10px; cursor:pointer; margin-bottom:2px; transition:all .15s; }}
.comp-item:hover {{ background:var(--card); border-color:var(--border); }}
.comp-item.active {{ background:var(--card); border-color:var(--blue); }}
.comp-item .name {{ font-weight:600; flex:1; }}
.comp-item .count {{ color:var(--muted); font-size:12px; margin-left:8px; }}
.comp-item .bar {{ height:4px; border-radius:2px; margin-top:4px; }}

/* Detail panel */
.detail {{ background:var(--card); border:1px solid var(--border); border-radius:14px; padding:20px; min-height:60vh; }}
.detail-header {{ display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:16px; }}
.stat-pills {{ display:flex; gap:8px; flex-wrap:wrap; }}
.pill {{ display:inline-flex; align-items:center; gap:4px; padding:4px 12px; border-radius:999px; font-size:13px; font-weight:600; border:1px solid; }}
.pill.ok {{ background:rgba(22,163,74,.12); color:var(--ok); border-color:rgba(22,163,74,.3); }}
.pill.warn {{ background:rgba(217,119,6,.12); color:var(--warn); border-color:rgba(217,119,6,.3); }}
.pill.danger {{ background:rgba(220,38,38,.12); color:var(--danger); border-color:rgba(220,38,38,.3); }}
.pill.blue {{ background:rgba(59,130,246,.12); color:var(--blue); border-color:rgba(59,130,246,.3); }}

/* Sections inside detail */
.section {{ margin-top:20px; }}
.section-title {{ display:flex; align-items:center; gap:8px; cursor:pointer; padding:8px 0; border-bottom:1px solid var(--border); }}
.section-title:hover {{ color:var(--blue); }}
.section-content {{ padding-top:12px; }}

/* Tables */
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th,td {{ border-bottom:1px solid var(--border); padding:8px 6px; text-align:left; vertical-align:top; }}
th {{ position:sticky; top:0; background:var(--card); font-weight:600; color:var(--muted); font-size:12px; }}
tr:hover {{ background:rgba(255,255,255,.03); }}

/* Tags */
.tag {{ display:inline-block; padding:2px 8px; border-radius:6px; font-size:12px; margin:2px; white-space:nowrap; }}
.tag-danger {{ background:rgba(220,38,38,.15); color:#fca5a5; }}
.tag-ok {{ background:rgba(22,163,74,.15); color:#86efac; }}
.tag-muted {{ background:rgba(100,116,139,.15); color:#94a3b8; }}

/* Chapter grid */
.chapter-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:10px; }}
.chapter-card {{ background:rgba(255,255,255,.03); border:1px solid var(--border); border-radius:10px; padding:12px; }}
.chapter-card .ch-name {{ font-weight:600; font-size:13px; margin-bottom:6px; }}
.chapter-card .ch-stats {{ display:flex; gap:12px; font-size:12px; }}

/* Bar chart */
.bar-chart {{ display:flex; flex-direction:column; gap:6px; }}
.bar-row {{ display:flex; align-items:center; gap:8px; }}
.bar-label {{ width:160px; font-size:12px; text-align:right; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.bar-track {{ flex:1; height:18px; background:rgba(255,255,255,.05); border-radius:4px; overflow:hidden; position:relative; }}
.bar-fill {{ height:100%; border-radius:4px; transition:width .3s; }}
.bar-value {{ font-size:11px; color:var(--muted); width:40px; text-align:right; }}

/* Row detail table */
.row-table-wrap {{ overflow:auto; max-height:500px; }}
.feature-cell {{ max-width:300px; }}
.matched-true {{ color:var(--ok); }}
.matched-false {{ color:var(--danger); font-weight:600; }}

/* placeholder */
.placeholder {{ display:flex; align-items:center; justify-content:center; min-height:40vh; color:var(--muted); font-size:16px; }}

/* responsive */
@media (max-width:900px) {{
  .main-layout {{ grid-template-columns:1fr; }}
  .sidebar {{ position:static; max-height:300px; }}
  .summary-grid {{ grid-template-columns:repeat(3,1fr); }}
}}
</style>
</head>
<body>
<div class="wrap">
  <h1>Step3 构件类型匹配分析</h1>
  <p class="muted">按构件类型维度分析匹配结果，揭示未匹配的项目特征和计算项目缺口 &mdash; {_esc(meta.get('standard_document', ''))} &mdash; {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

  <div class="summary-grid">
    <div class="summary-card"><div class="n">{total_rows}</div><div class="label">总清单行数</div></div>
    <div class="summary-card"><div class="n">{total_comps}</div><div class="label">构件类型</div></div>
    <div class="summary-card"><div class="n ok">{global_matched}</div><div class="label">已匹配行</div></div>
    <div class="summary-card"><div class="n warn">{global_total_features-global_unmatched_features}/{global_total_features}</div><div class="label">特征匹配率</div></div>
    <div class="summary-card"><div class="n danger">{global_unmatched_features}</div><div class="label">未匹配特征项</div></div>
    <div class="summary-card"><div class="n danger">{global_no_calc}</div><div class="label">缺计算项目</div></div>
  </div>

  <div class="main-layout">
    <div class="sidebar">
      <input class="sidebar-search" id="compSearch" placeholder="搜索构件类型..." />
      <ul class="comp-list" id="compList"></ul>
    </div>
    <div class="detail" id="detailPanel">
      <div class="placeholder">← 点击左侧构件类型查看分析</div>
    </div>
  </div>
</div>

<script>
const COMPONENTS = {components_json};
const ALL_ROWS = {rows_json};

const compNames = Object.keys(COMPONENTS);
const compListEl = document.getElementById('compList');
const detailEl = document.getElementById('detailPanel');
const searchEl = document.getElementById('compSearch');

function renderCompList(filter) {{
  const f = (filter || '').toLowerCase();
  compListEl.innerHTML = '';
  compNames.forEach(name => {{
    if (f && !name.toLowerCase().includes(f)) return;
    const c = COMPONENTS[name];
    const li = document.createElement('li');
    li.className = 'comp-item';
    li.dataset.name = name;
    const matchRate = c.total ? Math.round(c.matched / c.total * 100) : 0;
    const featRate = c.feature_match_rate;
    // color of bar based on feature match rate
    const barColor = featRate > 60 ? 'var(--ok)' : featRate > 30 ? 'var(--warn)' : 'var(--danger)';
    li.innerHTML = `
      <div style="flex:1">
        <div class="name">${{esc(name)}}</div>
        <div class="bar" style="background:rgba(255,255,255,.08)">
          <div style="width:${{featRate}}%;background:${{barColor}};height:4px;border-radius:2px"></div>
        </div>
      </div>
      <div class="count">${{c.total}}行<br><span style="color:${{barColor}}">${{featRate}}%</span></div>
    `;
    li.onclick = () => selectComponent(name);
    compListEl.appendChild(li);
  }});
}}

function esc(s) {{ const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }}

function compKey(r) {{
  return r.source_component_name || r.resolved_component_name || '(无构件)';
}}

function selectComponent(name) {{
  document.querySelectorAll('.comp-item').forEach(el => el.classList.toggle('active', el.dataset.name === name));
  renderDetail(name);
}}

function renderDetail(name) {{
  const c = COMPONENTS[name];
  const compRows = ALL_ROWS.filter(r => compKey(r) === name);

  let h = `<div class="detail-header">
    <h2>${{esc(name)}}</h2>
    <div class="stat-pills">
      <span class="pill ok">已匹配 ${{c.matched}}</span>
      <span class="pill warn">候选 ${{c.candidate}}</span>
      <span class="pill danger">未匹配 ${{c.unmatched}}</span>
      <span class="pill blue">特征率 ${{c.feature_match_rate}}%</span>
      <span class="pill ${{c.no_calc ? 'danger' : 'ok'}}">缺计算 ${{c.no_calc}}</span>
    </div>
  </div>`;

  // 1. Unmatched features section
  h += `<div class="section">
    <div class="section-title"><h3>🔴 未匹配项目特征 (${{c.total_features - c.matched_features}}项)</h3></div>
    <div class="section-content">`;
  if (c.top_unmatched_labels.length) {{
    const maxCount = c.top_unmatched_labels[0][1];
    h += '<div class="bar-chart">';
    c.top_unmatched_labels.forEach(([label, count]) => {{
      const pct = Math.round(count / maxCount * 100);
      h += `<div class="bar-row">
        <div class="bar-label" title="${{esc(label)}}">${{esc(label)}}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${{pct}}%;background:var(--danger)"></div></div>
        <div class="bar-value">${{count}}</div>
      </div>`;
    }});
    h += '</div>';
  }} else {{
    h += '<p class="muted">全部特征已匹配 ✓</p>';
  }}
  h += '</div></div>';

  // 2. Matched features section
  h += `<div class="section">
    <div class="section-title"><h3>🟢 已匹配特征 (${{c.matched_features}}项)</h3></div>
    <div class="section-content">`;
  if (c.top_matched_labels.length) {{
    h += '<div style="display:flex;flex-wrap:wrap;gap:4px">';
    c.top_matched_labels.forEach(([label, count]) => {{
      h += `<span class="tag tag-ok">${{esc(label)}} (${{count}})</span>`;
    }});
    h += '</div>';
  }}
  h += '</div></div>';

  // 3. Calculation codes
  h += `<div class="section">
    <div class="section-title"><h3>📊 计算项目分布</h3></div>
    <div class="section-content">`;
  if (c.calc_codes.length) {{
    const maxCalc = c.calc_codes[0][1];
    h += '<div class="bar-chart">';
    c.calc_codes.forEach(([code, count]) => {{
      const pct = Math.round(count / maxCalc * 100);
      h += `<div class="bar-row">
        <div class="bar-label" title="${{esc(code)}}">${{esc(code)}}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${{pct}}%;background:var(--blue)"></div></div>
        <div class="bar-value">${{count}}</div>
      </div>`;
    }});
    h += '</div>';
  }}
  if (c.no_calc_rows.length) {{
    h += `<h3 style="margin-top:12px;color:var(--danger)">缺失计算项目的行 (${{c.no_calc}})</h3>
    <table><thead><tr><th>row_id</th><th>项目编码</th><th>项目名称</th></tr></thead><tbody>`;
    c.no_calc_rows.forEach(r => {{
      h += `<tr><td>${{esc(r.row_id)}}</td><td>${{esc(r.project_code)}}</td><td>${{esc(r.project_name)}}</td></tr>`;
    }});
    if (c.no_calc > c.no_calc_rows.length) h += `<tr><td colspan="3" class="muted">…共 ${{c.no_calc}} 行</td></tr>`;
    h += '</tbody></table>';
  }}
  h += '</div></div>';

  // 4. Chapter breakdown
  h += `<div class="section">
    <div class="section-title"><h3>📖 章节分布</h3></div>
    <div class="section-content"><div class="chapter-grid">`;
  Object.entries(c.chapters).sort((a,b) => b[1].total - a[1].total).forEach(([ch, st]) => {{
    h += `<div class="chapter-card">
      <div class="ch-name">${{esc(ch)}}</div>
      <div class="ch-stats">
        <span>行数 <b>${{st.total}}</b></span>
        <span class="ok">匹配 <b>${{st.matched}}</b></span>
        <span class="danger">特征缺 <b>${{st.unmatched_features}}</b></span>
      </div>
    </div>`;
  }});
  h += '</div></div></div>';

  // 5. Row detail table
  h += `<div class="section">
    <div class="section-title"><h3>📋 逐行详情 (${{compRows.length}}行)</h3></div>
    <div class="section-content"><div class="row-table-wrap">
    <table>
      <thead><tr>
        <th>row_id</th><th>项目编码</th><th>项目名称</th><th>章节</th>
        <th>匹配状态</th><th>置信度</th><th>计算项目</th><th>单位</th>
        <th>项目特征</th>
      </tr></thead><tbody>`;
  compRows.forEach(r => {{
    const statusColor = r.match_status === 'matched' ? 'ok' : r.match_status === 'unmatched' ? 'danger' : 'warn';
    // Build feature tags
    let featHtml = '';
    (r.feature_expression_items || []).forEach(item => {{
      const label = item.label || item.raw_text || '';
      const cls = item.matched ? 'tag-ok' : 'tag-danger';
      const title = item.expression || label;
      featHtml += `<span class="tag ${{cls}}" title="${{esc(title)}}">${{esc(label)}}</span>`;
    }});
    h += `<tr>
      <td>${{esc(r.row_id)}}</td>
      <td>${{esc(r.project_code)}}</td>
      <td>${{esc(r.project_name)}}</td>
      <td class="small muted">${{esc(r.chapter_root || r.section_path || '')}}</td>
      <td><span class="${{statusColor}}">${{esc(r.match_status)}}</span></td>
      <td>${{r.confidence != null ? r.confidence.toFixed(2) : ''}}</td>
      <td>${{esc(r.calculation_item_code || '')}} ${{esc(r.calculation_item_name || '')}}</td>
      <td>${{esc(r.measurement_unit || '')}}</td>
      <td class="feature-cell">${{featHtml}}</td>
    </tr>`;
  }});
  h += '</tbody></table></div></div></div>';

  detailEl.innerHTML = h;
}}

searchEl.addEventListener('input', () => renderCompList(searchEl.value));
renderCompList('');

// Auto-select first component
if (compNames.length) selectComponent(compNames[0]);
</script>
</body>
</html>"""

    output_path.write_text(doc, encoding="utf-8")
    print(f"Report: {output_path} ({output_path.stat().st_size / 1024:.0f} KB)")
    return output_path


def main():
    import sys
    base = Path(__file__).resolve().parent.parent
    if len(sys.argv) > 1:
        step3_path = Path(sys.argv[1])
    else:
        step3_dir = base / "data" / "output" / "step3"
        candidates = sorted(step3_dir.glob("*/" + RESULT_JSON_NAME))
        if not candidates:
            print(f"未找到 Step3 结果: {step3_dir}")
            sys.exit(1)
        step3_path = candidates[-1]

    build_analysis_html(step3_path)


if __name__ == "__main__":
    main()
