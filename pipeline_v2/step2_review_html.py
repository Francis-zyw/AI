from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence

from .step2_engine.api import build_synonym_library

COMPONENT_RESULT_NAME = "component_matching_result.json"
SYNONYM_LIBRARY_NAME = "synonym_library.json"
RUN_SUMMARY_NAME = "run_summary.json"
STEP2_REVIEW_HTML_NAME = "step2_manual_review.html"
STEP2_REVIEW_PACKAGE_NAME = "step2_manual_review_package.json"
APP_VERSION = "1.0.0"

MAPPING_ARRAY_FIELDS = [
    "source_aliases",
    "standard_aliases",
    "candidate_standard_names",
    "evidence_paths",
    "evidence_texts",
]
SYNONYM_ARRAY_FIELDS = [
    "aliases",
    "source_component_names",
    "match_types",
    "review_statuses",
    "evidence_paths",
    "notes",
]

HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__TITLE__</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f1e8;
      --surface: #fffdf8;
      --surface-2: #f7f3ea;
      --text: #1f2937;
      --muted: #6b7280;
      --line: #ddd3c1;
      --accent: #8b5e3c;
      --accent-2: #245d66;
      --ok: #27724c;
      --warn: #a16018;
      --danger: #a63d32;
      --shadow: 0 16px 36px rgba(72, 49, 28, 0.08);
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      background:
        radial-gradient(circle at top right, rgba(139, 94, 60, 0.08), transparent 28%),
        linear-gradient(180deg, #f8f4ec 0%, var(--bg) 100%);
      color: var(--text);
    }

    .wrap {
      max-width: 1700px;
      margin: 0 auto;
      padding: 28px 24px 56px;
    }

    h1, h2, h3, p { margin: 0; }

    .hero {
      background: linear-gradient(135deg, rgba(139, 94, 60, 0.96), rgba(36, 93, 102, 0.95));
      color: #fffaf1;
      border-radius: 24px;
      padding: 28px;
      box-shadow: var(--shadow);
    }

    .hero h1 {
      font-size: 32px;
      font-weight: 800;
      margin-bottom: 10px;
    }

    .hero p {
      line-height: 1.7;
      max-width: 1100px;
      color: rgba(255, 250, 241, 0.92);
    }

    .hero-meta {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 16px;
    }

    .chip {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px 12px;
      border-radius: 999px;
      background: rgba(255, 250, 241, 0.12);
      border: 1px solid rgba(255, 250, 241, 0.24);
      font-size: 13px;
    }

    .section {
      margin-top: 18px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 22px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }

    .section-head {
      padding: 20px 24px 6px;
    }

    .section-head h2 {
      font-size: 22px;
      margin-bottom: 6px;
    }

    .section-head p {
      color: var(--muted);
      line-height: 1.7;
    }

    .cards {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 14px;
      padding: 18px 24px 24px;
    }

    .card {
      background: var(--surface-2);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
    }

    .card .label {
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 8px;
    }

    .card .value {
      font-size: 24px;
      font-weight: 800;
      line-height: 1.2;
      word-break: break-word;
    }

    .toolbar {
      display: flex;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      padding: 0 24px 20px;
    }

    .toolbar-left,
    .toolbar-right {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }

    button,
    .button-like {
      border: 1px solid var(--line);
      background: var(--surface-2);
      color: var(--text);
      border-radius: 12px;
      padding: 10px 14px;
      font-size: 14px;
      cursor: pointer;
      transition: transform 0.12s ease, box-shadow 0.12s ease;
      box-shadow: 0 4px 12px rgba(72, 49, 28, 0.06);
    }

    button:hover,
    .button-like:hover {
      transform: translateY(-1px);
    }

    button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }

    button.secondary {
      background: var(--accent-2);
      border-color: var(--accent-2);
      color: #fff;
    }

    button.ghost {
      background: transparent;
    }

    .tabs {
      display: flex;
      gap: 10px;
      padding: 0 24px 16px;
      flex-wrap: wrap;
    }

    .tab {
      border-radius: 999px;
      padding: 9px 16px;
      border: 1px solid var(--line);
      background: var(--surface-2);
      font-size: 14px;
      cursor: pointer;
    }

    .tab.active {
      background: #f0e5d2;
      border-color: #d5b998;
      color: #6f4320;
      font-weight: 700;
    }

    .filters {
      display: grid;
      grid-template-columns: 2fr 1fr 1fr 1fr;
      gap: 12px;
      padding: 0 24px 16px;
    }

    input[type="text"],
    input[type="number"],
    select,
    textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
      font-size: 14px;
      background: #fff;
      color: var(--text);
    }

    textarea {
      min-height: 80px;
      resize: vertical;
      line-height: 1.5;
    }

    .inline-stats {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      padding: 0 24px 16px;
      color: var(--muted);
      font-size: 13px;
    }

    .inline-stats strong {
      color: var(--text);
    }

    .hint {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.7;
      padding: 0 24px 18px;
    }

    .table-wrap {
      overflow: auto;
      border-top: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(247, 243, 234, 0.45), rgba(255, 253, 248, 0.98));
    }

    table {
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      min-width: 1480px;
    }

    th,
    td {
      padding: 12px 10px;
      border-bottom: 1px solid #e9decc;
      vertical-align: top;
      background: rgba(255, 253, 248, 0.88);
    }

    th {
      position: sticky;
      top: 0;
      z-index: 2;
      background: #efe4d2;
      color: #5d4024;
      font-size: 13px;
      text-align: left;
      white-space: nowrap;
    }

    td.index-col,
    th.index-col {
      position: sticky;
      left: 0;
      z-index: 3;
      background: #f8f1e4;
      min-width: 68px;
    }

    td.index-col {
      font-weight: 700;
      color: #7a5a37;
    }

    td.small,
    th.small {
      min-width: 90px;
    }

    td.medium,
    th.medium {
      min-width: 160px;
    }

    td.large,
    th.large {
      min-width: 240px;
    }

    td.xlarge,
    th.xlarge {
      min-width: 320px;
    }

    .status {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 12px;
      border: 1px solid transparent;
      font-weight: 700;
    }

    .status.matched,
    .status.confirmed {
      color: var(--ok);
      background: rgba(39, 114, 76, 0.08);
      border-color: rgba(39, 114, 76, 0.24);
    }

    .status.candidate_only,
    .status.pending {
      color: var(--warn);
      background: rgba(161, 96, 24, 0.08);
      border-color: rgba(161, 96, 24, 0.22);
    }

    .status.unmatched,
    .status.rejected {
      color: var(--danger);
      background: rgba(166, 61, 50, 0.08);
      border-color: rgba(166, 61, 50, 0.22);
    }

    .status.adjusted,
    .status.conflict {
      color: var(--accent-2);
      background: rgba(36, 93, 102, 0.08);
      border-color: rgba(36, 93, 102, 0.2);
    }

    .footer-note {
      padding: 18px 24px 24px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.7;
    }

    .empty {
      padding: 36px 24px 40px;
      text-align: center;
      color: var(--muted);
    }

    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      border: 0;
    }

    @media (max-width: 1280px) {
      .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .filters { grid-template-columns: 1fr 1fr; }
    }

    @media (max-width: 720px) {
      .wrap { padding: 18px 12px 40px; }
      .hero { padding: 20px; }
      .hero h1 { font-size: 26px; }
      .cards { grid-template-columns: 1fr; padding: 16px; }
      .toolbar, .tabs, .filters, .inline-stats, .hint, .section-head, .footer-note { padding-left: 16px; padding-right: 16px; }
      .filters { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>第二步人工修订页</h1>
      <p>这个页面用于把第二步产出的匹配总结果和源构件词库交给产品经理做人工优化。修订完成后，请点击“导出修订包 JSON”，把导出的 JSON 回传给命令行回写为最终结果。</p>
      <div class="hero-meta">
        __HERO_CHIPS__
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <h2>总体概览</h2>
        <p>先看整体规模和状态，再进入表格修订。建议优先检查候选待定、未匹配、冲突待核和低置信度项。</p>
      </div>
      <div class="cards">__SUMMARY_CARDS__</div>
      <div class="toolbar">
        <div class="toolbar-left">
          <button id="exportBtn" class="primary">导出修订包 JSON</button>
          <button id="importBtn" class="secondary">导入已修订 JSON</button>
          <label class="button-like" for="importInput">选择 JSON 文件</label>
          <input id="importInput" class="sr-only" type="file" accept=".json,application/json" />
        </div>
        <div class="toolbar-right">
          <button id="addRowBtn">新增当前表行</button>
          <button id="rebuildSynonymsBtn" class="ghost">按匹配结果重建源构件词库</button>
          <button id="resetBtn" class="ghost">恢复初始数据</button>
        </div>
      </div>

      <div class="tabs">
        <button id="tabMappings" class="tab active">匹配总结果</button>
        <button id="tabSynonyms" class="tab">源构件词库</button>
      </div>

      <div class="filters">
        <input id="searchInput" type="text" placeholder="搜索：构件名 / 标准名 / 候选名 / 证据 / 推理说明" />
        <select id="matchStatusFilter">
          <option value="">全部匹配状态</option>
        </select>
        <select id="reviewStatusFilter">
          <option value="">全部复核状态</option>
        </select>
        <select id="rowVisibilityFilter">
          <option value="active">仅显示未删除行</option>
          <option value="all">显示全部</option>
          <option value="deleted">仅显示已删除行</option>
        </select>
      </div>

      <div class="inline-stats" id="inlineStats"></div>
      <div class="hint" id="tabHint"></div>

      <div class="table-wrap">
        <table>
          <thead id="tableHead"></thead>
          <tbody id="tableBody"></tbody>
        </table>
        <div id="emptyState" class="empty" style="display:none;">当前筛选条件下没有记录。</div>
      </div>

      <div class="footer-note">
        说明：数组类字段使用“每行一个值”的方式编辑；删除行只会在导出的修订包中标记并过滤，不会修改你本地的原始 Step2 结果文件。若产品经理主要调整了“匹配总结果”，可以在导出前点击“按匹配结果重建源构件词库”，用最新匹配结果生成词库草稿。
      </div>
    </section>
  </div>

  <script id="reviewData" type="application/json">__REVIEW_DATA__</script>
  <script>
    const optionSets = {
      match_status: ["matched", "candidate_only", "conflict", "unmatched"],
      review_status: ["pending", "confirmed", "adjusted", "rejected", "unreviewed", "suggested"]
    };

    const labelMap = {
      matched: "已匹配",
      candidate_only: "候选待定",
      conflict: "冲突待核",
      unmatched: "未匹配",
      pending: "待复核",
      confirmed: "已确认",
      adjusted: "已调整",
      rejected: "已驳回",
      unreviewed: "未复核",
      suggested: "建议确认"
    };

    const initialState = JSON.parse(document.getElementById("reviewData").textContent);
    let activeTab = "mappings";
    let state = deepClone(initialState);

    const mappingColumns = [
      { key: "record_id", label: "ID", type: "readonly", cls: "small" },
      { key: "source_component_name", label: "来源构件名", type: "text", cls: "medium" },
      { key: "source_aliases", label: "来源别名", type: "textarea", cls: "large" },
      { key: "selected_standard_name", label: "当前标准名", type: "text", cls: "medium" },
      { key: "standard_aliases", label: "标准别名", type: "textarea", cls: "large" },
      { key: "candidate_standard_names", label: "候选标准名", type: "textarea", cls: "large" },
      { key: "match_type", label: "匹配方式", type: "text", cls: "medium" },
      { key: "match_status", label: "匹配状态", type: "select", options: optionSets.match_status, cls: "small" },
      { key: "confidence", label: "置信度", type: "number", cls: "small" },
      { key: "review_status", label: "复核状态", type: "select", options: optionSets.review_status, cls: "small" },
      { key: "evidence_paths", label: "证据路径", type: "textarea", cls: "xlarge" },
      { key: "evidence_texts", label: "证据文本", type: "textarea", cls: "xlarge" },
      { key: "reasoning", label: "推理说明", type: "textarea", cls: "xlarge" },
      { key: "manual_notes", label: "人工备注", type: "textarea", cls: "large" },
      { key: "delete_row", label: "删除", type: "checkbox", cls: "small" }
    ];

    const synonymColumns = [
      { key: "record_id", label: "ID", type: "readonly", cls: "small" },
      { key: "source_component_name", label: "源构件", type: "text", cls: "medium" },
      { key: "aliases", label: "同义词别名", type: "textarea", cls: "large" },
      { key: "chapter_nodes", label: "章节/节点", type: "textarea", cls: "large" },
      { key: "selected_standard_name", label: "当前匹配结果", type: "text", cls: "medium" },
      { key: "match_status", label: "匹配状态", type: "text", cls: "small" },
      { key: "delete_row", label: "删除", type: "checkbox", cls: "small" }
    ];

    function deepClone(value) {
      return JSON.parse(JSON.stringify(value));
    }

    function nowIso() {
      return new Date().toISOString();
    }

    function esc(value) {
      if (value === null || value === undefined) return "";
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function displayLabel(value) {
      const key = String(value || "").trim();
      return labelMap[key] || key;
    }

    function arrayFromValue(value) {
      if (Array.isArray(value)) {
        return dedupe(value.map(item => String(item || "").trim()).filter(Boolean));
      }
      if (typeof value === "string") {
        return dedupe(
          value
            .replaceAll("；", ";")
            .replaceAll("，", ",")
            .split(/\\n|;|,/)
            .map(item => item.trim())
            .filter(Boolean)
        );
      }
      if (value === null || value === undefined || value === "") {
        return [];
      }
      return [String(value).trim()].filter(Boolean);
    }

    function arrayText(value) {
      return arrayFromValue(value).join("\\n");
    }

    function dedupe(values) {
      const seen = new Set();
      const result = [];
      for (const raw of values || []) {
        const item = String(raw || "").trim();
        if (!item || seen.has(item)) continue;
        seen.add(item);
        result.push(item);
      }
      return result;
    }

    function normalizeNumber(value) {
      if (value === null || value === undefined || value === "") return "";
      const num = Number(value);
      if (!Number.isFinite(num)) return "";
      return Math.max(0, Math.min(1, num));
    }

    function normalizeMappingRow(row, index) {
      const normalized = { ...row };
      normalized.record_id = String(row.record_id || `M${String(index + 1).padStart(4, "0")}`);
      normalized.source_component_name = String(row.source_component_name || "");
      normalized.selected_standard_name = String(row.selected_standard_name || "");
      normalized.match_type = String(row.match_type || "");
      normalized.match_status = String(row.match_status || "unmatched");
      normalized.review_status = String(row.review_status || "pending");
      normalized.reasoning = String(row.reasoning || "");
      normalized.manual_notes = String(row.manual_notes || "");
      normalized.delete_row = Boolean(row.delete_row);
      normalized.confidence = normalizeNumber(row.confidence);
      normalized.source_aliases = arrayFromValue(row.source_aliases);
      normalized.standard_aliases = arrayFromValue(row.standard_aliases);
      normalized.candidate_standard_names = arrayFromValue(row.candidate_standard_names);
      normalized.evidence_paths = arrayFromValue(row.evidence_paths);
      normalized.evidence_texts = arrayFromValue(row.evidence_texts);
      return normalized;
    }

    function normalizeSynonymRow(row, index) {
      const normalized = { ...row };
      normalized.record_id = String(row.record_id || `S${String(index + 1).padStart(4, "0")}`);
      normalized.canonical_name = String(row.canonical_name || row.source_component_name || "");
      normalized.source_component_name = String(row.source_component_name || row.canonical_name || "");
      normalized.delete_row = Boolean(row.delete_row);
      normalized.aliases = arrayFromValue(row.aliases);
      normalized.chapter_nodes = arrayFromValue(row.chapter_nodes);
      normalized.selected_standard_name = String(row.selected_standard_name || "");
      normalized.match_status = String(row.match_status || "unmatched");
      normalized.source_component_names = arrayFromValue(row.source_component_names);
      normalized.match_types = arrayFromValue(row.match_types);
      normalized.review_statuses = arrayFromValue(row.review_statuses);
      normalized.evidence_paths = arrayFromValue(row.evidence_paths);
      normalized.notes = arrayFromValue(row.notes);
      return normalized;
    }

    function hydrateState(target) {
      target.component_matching_result = target.component_matching_result || { meta: {}, mappings: [] };
      target.synonym_library = target.synonym_library || { meta: {}, synonym_library: [], unmatched_components: [] };
      target.component_matching_result.mappings = (target.component_matching_result.mappings || []).map(normalizeMappingRow);
      target.synonym_library.synonym_library = (target.synonym_library.synonym_library || []).map(normalizeSynonymRow);
      target.synonym_library.unmatched_components = arrayFromValue(target.synonym_library.unmatched_components);
      return target;
    }

    function setState(nextState) {
      state = hydrateState(nextState);
      syncFilterOptions();
      render();
    }

    function statusBadge(status) {
      const cls = esc(String(status || "").trim());
      if (!cls) return "";
      return `<div class="status ${cls}">${esc(displayLabel(status))}</div>`;
    }

    function syncFilterOptions() {
      const matchFilter = document.getElementById("matchStatusFilter");
      const reviewFilter = document.getElementById("reviewStatusFilter");
      const mappingReviewStatuses = dedupe(state.component_matching_result.mappings.map(row => row.review_status));
      const matchStatuses = dedupe(state.component_matching_result.mappings.map(row => row.match_status));

      refillSelect(matchFilter, matchStatuses, "全部匹配状态");
      refillSelect(reviewFilter, mappingReviewStatuses, "全部复核状态");
    }

    function refillSelect(selectEl, values, defaultText) {
      const currentValue = selectEl.value;
      selectEl.innerHTML = "";
      const defaultOption = document.createElement("option");
      defaultOption.value = "";
      defaultOption.textContent = defaultText;
      selectEl.appendChild(defaultOption);
      for (const value of values) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = displayLabel(value);
        selectEl.appendChild(option);
      }
      if ([...selectEl.options].some(option => option.value === currentValue)) {
        selectEl.value = currentValue;
      }
    }

    function getActiveRows() {
      return activeTab === "mappings"
        ? state.component_matching_result.mappings
        : state.synonym_library.synonym_library;
    }

    function getColumns() {
      return activeTab === "mappings" ? mappingColumns : synonymColumns;
    }

    function rowMatches(row, search, visibility) {
      if (visibility === "active" && row.delete_row) return false;
      if (visibility === "deleted" && !row.delete_row) return false;
      if (visibility === "all") {
      } else if (visibility !== "deleted" && row.delete_row) {
        return false;
      }

      if (activeTab === "mappings") {
        const matchStatus = document.getElementById("matchStatusFilter").value;
        const reviewStatus = document.getElementById("reviewStatusFilter").value;
        if (matchStatus && row.match_status !== matchStatus) return false;
        if (reviewStatus && row.review_status !== reviewStatus) return false;
      }

      if (!search) return true;
      const text = JSON.stringify(row).toLowerCase();
      return text.includes(search);
    }

    function visibleIndices() {
      const search = document.getElementById("searchInput").value.trim().toLowerCase();
      const visibility = document.getElementById("rowVisibilityFilter").value;
      return getActiveRows()
        .map((row, index) => ({ row, index }))
        .filter(item => rowMatches(item.row, search, visibility))
        .map(item => item.index);
    }

    function render() {
      const columns = getColumns();
      const rows = getActiveRows();
      const indices = visibleIndices();
      const tableHead = document.getElementById("tableHead");
      const tableBody = document.getElementById("tableBody");
      const emptyState = document.getElementById("emptyState");
      const inlineStats = document.getElementById("inlineStats");
      const tabHint = document.getElementById("tabHint");

      document.getElementById("tabMappings").classList.toggle("active", activeTab === "mappings");
      document.getElementById("tabSynonyms").classList.toggle("active", activeTab === "synonyms");
      document.getElementById("rebuildSynonymsBtn").style.display = activeTab === "mappings" ? "inline-flex" : "inline-flex";
      document.getElementById("addRowBtn").textContent = activeTab === "mappings" ? "新增匹配行" : "新增源构件词库行";

      tableHead.innerHTML = `<tr><th class="index-col">序号</th>${columns.map(col => `<th class="${col.cls || ""}">${esc(col.label)}</th>`).join("")}</tr>`;

      if (!indices.length) {
        tableBody.innerHTML = "";
        emptyState.style.display = "block";
      } else {
        emptyState.style.display = "none";
        tableBody.innerHTML = indices.map((rowIndex, visibleIndex) => renderRow(rows[rowIndex], rowIndex, visibleIndex, columns)).join("");
      }

      if (activeTab === "mappings") {
        const mappingRows = state.component_matching_result.mappings.filter(row => !row.delete_row);
        const matched = mappingRows.filter(row => row.match_status === "matched").length;
        const candidateOnly = mappingRows.filter(row => row.match_status === "candidate_only").length;
        const unmatched = mappingRows.filter(row => row.match_status === "unmatched").length;
        const conflict = mappingRows.filter(row => row.match_status === "conflict").length;
        inlineStats.innerHTML = [
          `<span><strong>${mappingRows.length}</strong> 条有效匹配记录</span>`,
          `<span>${statusBadge("matched")} ${matched}</span>`,
          `<span>${statusBadge("candidate_only")} ${candidateOnly}</span>`,
          `<span>${statusBadge("conflict")} ${conflict}</span>`,
          `<span>${statusBadge("unmatched")} ${unmatched}</span>`
        ].join("");
        tabHint.textContent = "匹配总结果是主回写产物，后续会生成最终匹配结果文件。";
      } else {
        const synonymRows = state.synonym_library.synonym_library.filter(row => !row.delete_row);
        inlineStats.innerHTML = [
          `<span><strong>${synonymRows.length}</strong> 条源构件词库记录</span>`,
          `<span><strong>${synonymRows.filter(row => row.selected_standard_name).length}</strong> 条已匹配源构件</span>`
        ].join("");
        tabHint.textContent = "源构件词库会单独回写为最终词库文件；如与匹配总结果不一致，可先返回“匹配总结果”页重建。";
      }
    }

    function renderRow(row, rowIndex, visibleIndex, columns) {
      return `<tr>
        <td class="index-col">${visibleIndex + 1}</td>
        ${columns.map(col => renderCell(row, rowIndex, col)).join("")}
      </tr>`;
    }

    function renderCell(row, rowIndex, column) {
      const field = column.key;
      const tab = activeTab;
      const value = row[field];
      const cls = column.cls || "";

      if (column.type === "readonly") {
        return `<td class="${cls}">${esc(value)}</td>`;
      }

      if (field === "match_status" || field === "review_status") {
        return `<td class="${cls}">
          ${statusBadge(value)}
          <select data-tab="${tab}" data-index="${rowIndex}" data-field="${field}">
            ${column.options.map(option => `<option value="${esc(option)}" ${String(value) === option ? "selected" : ""}>${esc(displayLabel(option))}</option>`).join("")}
          </select>
        </td>`;
      }

      if (column.type === "select") {
        return `<td class="${cls}">
          <select data-tab="${tab}" data-index="${rowIndex}" data-field="${field}">
            ${column.options.map(option => `<option value="${esc(option)}" ${String(value) === option ? "selected" : ""}>${esc(displayLabel(option))}</option>`).join("")}
          </select>
        </td>`;
      }

      if (column.type === "textarea") {
        return `<td class="${cls}">
          <textarea data-tab="${tab}" data-index="${rowIndex}" data-field="${field}">${esc(arrayText(value))}</textarea>
        </td>`;
      }

      if (column.type === "number") {
        const displayValue = value === "" ? "" : Number(value);
        return `<td class="${cls}">
          <input type="number" min="0" max="1" step="0.01" data-tab="${tab}" data-index="${rowIndex}" data-field="${field}" value="${esc(displayValue)}" />
        </td>`;
      }

      if (column.type === "checkbox") {
        return `<td class="${cls}">
          <label><input type="checkbox" data-tab="${tab}" data-index="${rowIndex}" data-field="${field}" ${value ? "checked" : ""} /> 标记删除</label>
        </td>`;
      }

      return `<td class="${cls}">
        <input type="text" data-tab="${tab}" data-index="${rowIndex}" data-field="${field}" value="${esc(value || "")}" />
      </td>`;
    }

    function updateField(tab, index, field, rawValue, inputType) {
      const collection = tab === "mappings"
        ? state.component_matching_result.mappings
        : state.synonym_library.synonym_library;
      const row = collection[index];
      if (!row) return;

      if (inputType === "checkbox") {
        row[field] = Boolean(rawValue);
      } else if (field === "confidence") {
        row[field] = normalizeNumber(rawValue);
      } else if (MAPPING_ARRAY_FIELDS.includes(field) || SYNONYM_ARRAY_FIELDS.includes(field)) {
        row[field] = arrayFromValue(rawValue);
      } else {
        row[field] = String(rawValue || "");
      }
      render();
    }

    function buildPackage() {
      const reviewedMappings = state.component_matching_result.mappings
        .filter(row => !row.delete_row)
        .map((row, index) => {
          const normalized = normalizeMappingRow(row, index);
          delete normalized.delete_row;
          return normalized;
        });

      const reviewedSynonyms = state.synonym_library.synonym_library
        .filter(row => !row.delete_row)
        .map((row, index) => {
          const normalized = normalizeSynonymRow(row, index);
          delete normalized.delete_row;
          return normalized;
        });

      const matchStatusCount = reviewedMappings.reduce((acc, row) => {
        const key = row.match_status || "unknown";
        acc[key] = (acc[key] || 0) + 1;
        return acc;
      }, {});

      const componentMeta = {
        ...(state.component_matching_result.meta || {}),
        generated_at: nowIso(),
        review_stage: "manual_review_html",
        mapping_count: reviewedMappings.length,
        matched_count: matchStatusCount.matched || 0,
        candidate_only_count: matchStatusCount.candidate_only || 0,
        conflict_count: matchStatusCount.conflict || 0,
        unmatched_count: matchStatusCount.unmatched || 0
      };

      const unmatchedComponents = dedupe(state.synonym_library.unmatched_components || []);
      const synonymMeta = {
        ...(state.synonym_library.meta || {}),
        generated_at: nowIso(),
        source_review_stage: componentMeta.review_stage || "manual_review_html",
        matched_canonical_count: reviewedSynonyms.length,
        unmatched_component_count: unmatchedComponents.length
      };

      return {
        meta: {
          task_name: "step2_manual_review_package",
          generated_at: nowIso(),
          app_version: "APP_VERSION_PLACEHOLDER",
          standard_document: componentMeta.standard_document || synonymMeta.standard_document || "",
          source_step2_dir: initialState.meta?.source_step2_dir || "",
          source_component_result_path: initialState.meta?.source_component_result_path || "",
          source_synonym_library_path: initialState.meta?.source_synonym_library_path || "",
          source_run_summary_path: initialState.meta?.source_run_summary_path || ""
        },
        component_matching_result: {
          meta: componentMeta,
          mappings: reviewedMappings
        },
        synonym_library: {
          meta: synonymMeta,
          synonym_library: reviewedSynonyms,
          unmatched_components: unmatchedComponents
        }
      };
    }

    function downloadJson(payload, filename) {
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    }

    function addCurrentRow() {
      if (activeTab === "mappings") {
        state.component_matching_result.mappings.push(normalizeMappingRow({}, state.component_matching_result.mappings.length));
      } else {
        state.synonym_library.synonym_library.push(normalizeSynonymRow({}, state.synonym_library.synonym_library.length));
      }
      render();
    }

    function rebuildSynonymsFromMappings() {
      const rows = state.component_matching_result.mappings.filter(row => !row.delete_row);
      const grouped = new Map();

      for (const row of rows) {
        const sourceName = String(row.source_component_name || "").trim();
        if (!sourceName) continue;

        if (!grouped.has(sourceName)) {
          grouped.set(sourceName, {
            canonical_name: sourceName,
            source_component_name: sourceName,
            aliases: [],
            chapter_nodes: [],
            selected_standard_name: "",
            match_status: "unmatched",
            source_component_names: [],
            match_types: [],
            review_statuses: [],
            evidence_paths: [],
            notes: []
          });
        }

        const entry = grouped.get(sourceName);
        const selectedStandardName = String(row.selected_standard_name || "").trim();
        if (selectedStandardName && !entry.selected_standard_name) {
          entry.selected_standard_name = selectedStandardName;
        }
        entry.match_status = String(row.match_status || entry.match_status || "unmatched");
        entry.aliases = dedupe([
          ...entry.aliases,
          ...arrayFromValue(row.standard_aliases),
          ...arrayFromValue(row.source_aliases).filter(item => item !== sourceName)
        ]);
        entry.chapter_nodes = dedupe([
          ...entry.chapter_nodes,
          ...arrayFromValue(row.candidate_standard_names),
          ...arrayFromValue(row.evidence_texts).filter(item => item.includes("附录") || item.includes(">") || /^[A-Z]\\.\\d+/i.test(item))
        ]);
        entry.source_component_names = dedupe([...entry.source_component_names, sourceName]);
        entry.match_types = dedupe([...entry.match_types, String(row.match_type || "").trim()]);
        entry.review_statuses = dedupe([...entry.review_statuses, String(row.review_status || "").trim()]);
      }

      state.synonym_library.synonym_library = [...grouped.values()]
        .map((row, index) => normalizeSynonymRow(row, index))
        .sort((a, b) => a.source_component_name.localeCompare(b.source_component_name, "zh-CN"));
      state.synonym_library.unmatched_components = [];
      activeTab = "synonyms";
      render();
    }

    document.getElementById("tableBody").addEventListener("input", event => {
      const target = event.target;
      if (!target.dataset || !target.dataset.field) return;
      updateField(target.dataset.tab, Number(target.dataset.index), target.dataset.field, target.value, target.type);
    });

    document.getElementById("tableBody").addEventListener("change", event => {
      const target = event.target;
      if (!target.dataset || !target.dataset.field) return;
      const value = target.type === "checkbox" ? target.checked : target.value;
      updateField(target.dataset.tab, Number(target.dataset.index), target.dataset.field, value, target.type);
    });

    document.getElementById("searchInput").addEventListener("input", render);
    document.getElementById("matchStatusFilter").addEventListener("change", render);
    document.getElementById("reviewStatusFilter").addEventListener("change", render);
    document.getElementById("rowVisibilityFilter").addEventListener("change", render);

    document.getElementById("tabMappings").addEventListener("click", () => {
      activeTab = "mappings";
      render();
    });

    document.getElementById("tabSynonyms").addEventListener("click", () => {
      activeTab = "synonyms";
      render();
    });

    document.getElementById("exportBtn").addEventListener("click", () => {
      const payload = buildPackage();
      downloadJson(payload, "step2_manual_review_package.json");
    });

    document.getElementById("importBtn").addEventListener("click", () => {
      document.getElementById("importInput").click();
    });

    document.getElementById("importInput").addEventListener("change", async event => {
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      const text = await file.text();
      const payload = JSON.parse(text);
      setState(payload);
    });

    document.getElementById("addRowBtn").addEventListener("click", addCurrentRow);
    document.getElementById("rebuildSynonymsBtn").addEventListener("click", rebuildSynonymsFromMappings);
    document.getElementById("resetBtn").addEventListener("click", () => {
      activeTab = "mappings";
      document.getElementById("searchInput").value = "";
      document.getElementById("matchStatusFilter").value = "";
      document.getElementById("reviewStatusFilter").value = "";
      document.getElementById("rowVisibilityFilter").value = "active";
      setState(deepClone(initialState));
    });

    setState(deepClone(initialState));
  </script>
</body>
</html>
"""


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def _json_for_html(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def _normalize_array_value(value: Any) -> List[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
    elif isinstance(value, str):
        normalized = value.replace("；", ";").replace("，", ",")
        items = []
        for chunk in normalized.splitlines():
            for part in chunk.replace(";", ",").split(","):
                text = part.strip()
                if text:
                    items.append(text)
    else:
        items = [str(value).strip()]

    seen = set()
    result: List[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _normalize_confidence(value: Any) -> float | str:
    if value in (None, ""):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return max(0.0, min(1.0, number))


def _normalize_mapping_row(row: Dict[str, Any], index: int) -> Dict[str, Any]:
    normalized = {
        "record_id": str(row.get("record_id") or f"M{index:04d}"),
        "source_component_name": str(row.get("source_component_name", "") or ""),
        "source_aliases": _normalize_array_value(row.get("source_aliases", [])),
        "selected_standard_name": str(row.get("selected_standard_name", "") or ""),
        "standard_aliases": _normalize_array_value(row.get("standard_aliases", [])),
        "candidate_standard_names": _normalize_array_value(row.get("candidate_standard_names", [])),
        "match_type": str(row.get("match_type", "") or ""),
        "match_status": str(row.get("match_status", "") or "unmatched"),
        "confidence": _normalize_confidence(row.get("confidence", "")),
        "review_status": str(row.get("review_status", "") or "pending"),
        "evidence_paths": _normalize_array_value(row.get("evidence_paths", [])),
        "evidence_texts": _normalize_array_value(row.get("evidence_texts", [])),
        "reasoning": str(row.get("reasoning", "") or ""),
        "manual_notes": str(row.get("manual_notes", "") or ""),
        "delete_row": bool(row.get("delete_row", False)),
    }
    return normalized


def _normalize_synonym_row(row: Dict[str, Any], index: int) -> Dict[str, Any]:
    return {
        "record_id": str(row.get("record_id") or f"S{index:04d}"),
        "canonical_name": str(row.get("canonical_name", "") or ""),
        "source_component_name": str(row.get("source_component_name", "") or row.get("canonical_name", "") or ""),
        "aliases": _normalize_array_value(row.get("aliases", [])),
        "chapter_nodes": _normalize_array_value(row.get("chapter_nodes", [])),
        "selected_standard_name": str(row.get("selected_standard_name", "") or ""),
        "match_status": str(row.get("match_status", "") or "unmatched"),
        "source_component_names": _normalize_array_value(row.get("source_component_names", [])),
        "match_types": _normalize_array_value(row.get("match_types", [])),
        "review_statuses": _normalize_array_value(row.get("review_statuses", [])),
        "evidence_paths": _normalize_array_value(row.get("evidence_paths", [])),
        "notes": _normalize_array_value(row.get("notes", [])),
        "delete_row": bool(row.get("delete_row", False)),
    }


def normalize_component_matching_result(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, list):
        mappings = payload
        meta: Dict[str, Any] = {}
    elif isinstance(payload, dict):
        mappings = payload.get("mappings", [])
        meta = dict(payload.get("meta", {}) or {})
    else:
        raise ValueError("component_matching_result 必须是对象或数组。")

    if not isinstance(mappings, list):
        raise ValueError("component_matching_result.mappings 必须是数组。")

    normalized_rows = [
        _normalize_mapping_row(item, index)
        for index, item in enumerate(mappings, start=1)
        if isinstance(item, dict)
    ]

    meta.setdefault("task_name", "component_standard_name_matching")
    meta.setdefault("generated_at", _now_iso())
    meta.setdefault("review_stage", "pre_parse")
    meta["mapping_count"] = len(normalized_rows)
    return {"meta": meta, "mappings": normalized_rows}


def normalize_synonym_library_payload(payload: Any, component_meta: Dict[str, Any] | None = None) -> Dict[str, Any]:
    component_meta = component_meta or {}

    if payload in (None, ""):
        meta: Dict[str, Any] = {}
        synonym_rows: List[Dict[str, Any]] = []
        unmatched_components: List[str] = []
    elif isinstance(payload, list):
        meta = {}
        synonym_rows = payload
        unmatched_components = []
    elif isinstance(payload, dict):
        meta = dict(payload.get("meta", {}) or {})
        synonym_rows = payload.get("synonym_library", [])
        unmatched_components = _normalize_array_value(payload.get("unmatched_components", []))
    else:
        raise ValueError("synonym_library 必须是对象、数组或空。")

    if not isinstance(synonym_rows, list):
        raise ValueError("synonym_library.synonym_library 必须是数组。")

    normalized_rows = [
        _normalize_synonym_row(item, index)
        for index, item in enumerate(synonym_rows, start=1)
        if isinstance(item, dict)
    ]

    meta.setdefault("task_name", "component_standard_name_synonym_library")
    meta.setdefault("standard_document", component_meta.get("standard_document", ""))
    meta.setdefault("generated_at", _now_iso())
    meta.setdefault("source_review_stage", component_meta.get("review_stage", "pre_parse"))
    active_rows = [item for item in normalized_rows if not item.get("delete_row")]
    matched_rows = [item for item in active_rows if str(item.get("selected_standard_name", "")).strip()]
    meta.setdefault("library_mode", "source_component_first")
    meta["component_count"] = len(active_rows)
    meta["matched_component_count"] = len(matched_rows)
    meta["matched_canonical_count"] = len(active_rows)
    meta["unmatched_component_count"] = max(
        len([item for item in active_rows if str(item.get("match_status", "")).strip() == "unmatched"]),
        len(unmatched_components),
    )

    return {
        "meta": meta,
        "synonym_library": normalized_rows,
        "unmatched_components": unmatched_components,
    }


def _count_match_statuses(rows: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"matched": 0, "candidate_only": 0, "conflict": 0, "unmatched": 0}
    for row in rows:
        status = str(row.get("match_status", "")).strip()
        if status in counts:
            counts[status] += 1
    return counts


def _default_review_root(step2_output_dir: str | Path) -> Path:
    step2_dir = Path(step2_output_dir).expanduser().resolve()
    project_root = Path(__file__).resolve().parents[1]
    return project_root / "data" / "manual_reviews" / "step2" / step2_dir.name


def build_step2_review_package(step2_output_dir: str | Path) -> Dict[str, Any]:
    step2_dir = Path(step2_output_dir).expanduser().resolve()
    component_result_path = step2_dir / COMPONENT_RESULT_NAME
    synonym_library_path = step2_dir / SYNONYM_LIBRARY_NAME
    run_summary_path = step2_dir / RUN_SUMMARY_NAME

    if not component_result_path.exists():
        raise FileNotFoundError(f"未找到 Step2 主结果：{component_result_path}")
    if not synonym_library_path.exists():
        raise FileNotFoundError(f"未找到 Step2 同义词库：{synonym_library_path}")

    component_result = normalize_component_matching_result(_load_json(component_result_path))
    synonym_library = normalize_synonym_library_payload(_load_json(synonym_library_path), component_result.get("meta", {}))
    run_summary = _load_json(run_summary_path) if run_summary_path.exists() else {}

    return {
        "meta": {
            "task_name": "step2_manual_review_package",
            "generated_at": _now_iso(),
            "app_version": APP_VERSION,
            "standard_document": component_result["meta"].get("standard_document", ""),
            "source_step2_dir": str(step2_dir),
            "source_component_result_path": str(component_result_path),
            "source_synonym_library_path": str(synonym_library_path),
            "source_run_summary_path": str(run_summary_path),
        },
        "component_matching_result": component_result,
        "synonym_library": synonym_library,
        "source_run_summary": run_summary if isinstance(run_summary, dict) else {},
    }


def build_step2_review_html(
    step2_output_dir: str | Path,
    *,
    output_html_path: str | Path | None = None,
) -> Dict[str, Any]:
    package = build_step2_review_package(step2_output_dir)
    component_rows = package["component_matching_result"]["mappings"]
    synonym_rows = package["synonym_library"]["synonym_library"]
    matched_synonym_rows = sum(1 for row in synonym_rows if str(row.get("selected_standard_name", "")).strip())
    unmatched_synonym_rows = sum(1 for row in synonym_rows if str(row.get("match_status", "")).strip() == "unmatched")
    counts = _count_match_statuses([row for row in component_rows if not row.get("delete_row")])

    if output_html_path:
        html_path = Path(output_html_path).expanduser().resolve()
    else:
        html_path = _default_review_root(step2_output_dir) / STEP2_REVIEW_HTML_NAME

    hero_chips = "".join(
        [
            f'<span class="chip">标准文档：{_esc(package["meta"].get("standard_document", ""))}</span>',
            f'<span class="chip">匹配记录：{len(component_rows)}</span>',
            f'<span class="chip">源构件词库：{len(synonym_rows)}</span>',
            f'<span class="chip">已匹配源构件：{matched_synonym_rows}</span>',
            f'<span class="chip">未匹配源构件：{unmatched_synonym_rows}</span>',
            f'<span class="chip">页面版本：{APP_VERSION}</span>',
        ]
    )
    summary_cards = "".join(
        [
            f'<div class="card"><div class="label">已匹配</div><div class="value">{counts["matched"]}</div></div>',
            f'<div class="card"><div class="label">候选待定</div><div class="value">{counts["candidate_only"]}</div></div>',
            f'<div class="card"><div class="label">冲突待核</div><div class="value">{counts["conflict"]}</div></div>',
            f'<div class="card"><div class="label">未匹配</div><div class="value">{counts["unmatched"]}</div></div>',
            f'<div class="card"><div class="label">第二步结果目录</div><div class="value" style="font-size:16px;">{_esc(Path(step2_output_dir).expanduser().resolve())}</div></div>',
        ]
    )

    html_content = (
        HTML_TEMPLATE.replace("__TITLE__", "第二步人工修订页")
        .replace("__HERO_CHIPS__", hero_chips)
        .replace("__SUMMARY_CARDS__", summary_cards)
        .replace("__REVIEW_DATA__", _json_for_html(package))
        .replace("APP_VERSION_PLACEHOLDER", APP_VERSION)
    )
    _write_text(html_path, html_content)

    return {
        "html_path": str(html_path),
        "step2_output_dir": str(Path(step2_output_dir).expanduser().resolve()),
        "mapping_count": len(component_rows),
        "synonym_count": len(synonym_rows),
        "unmatched_component_count": unmatched_synonym_rows,
    }


def _load_review_package(review_json_path: str | Path) -> Dict[str, Any]:
    payload = _load_json(Path(review_json_path).expanduser().resolve())
    if not isinstance(payload, dict):
        raise ValueError("修订包 JSON 根节点必须是对象。")
    return payload


def apply_step2_review_package(
    step2_output_dir: str | Path,
    review_json_path: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> Dict[str, Any]:
    step2_dir = Path(step2_output_dir).expanduser().resolve()
    review_path = Path(review_json_path).expanduser().resolve()
    review_payload = _load_review_package(review_path)

    component_payload = normalize_component_matching_result(review_payload.get("component_matching_result", {}))
    component_rows = [row for row in component_payload["mappings"] if not row.get("delete_row")]
    component_counts = _count_match_statuses(component_rows)

    component_meta = dict(component_payload.get("meta", {}) or {})
    component_meta["generated_at"] = _now_iso()
    component_meta["review_stage"] = "manual_review_applied"
    component_meta["source_step2_dir"] = str(step2_dir)
    component_payload = {"meta": component_meta, "mappings": component_rows}

    synonym_payload_raw = review_payload.get("synonym_library")
    if synonym_payload_raw:
        synonym_payload = normalize_synonym_library_payload(synonym_payload_raw, component_meta)
        synonym_rows = [row for row in synonym_payload["synonym_library"] if not row.get("delete_row")]
        synonym_payload = {
            "meta": dict(synonym_payload.get("meta", {}) or {}),
            "synonym_library": synonym_rows,
            "unmatched_components": _normalize_array_value(synonym_payload.get("unmatched_components", [])),
        }
        synonym_payload["meta"]["generated_at"] = _now_iso()
        synonym_payload["meta"]["source_review_stage"] = component_meta.get("review_stage", "manual_review_applied")
        synonym_payload["meta"]["library_mode"] = "source_component_first"
        synonym_payload["meta"]["component_count"] = len(synonym_rows)
        synonym_payload["meta"]["matched_component_count"] = sum(
            1 for row in synonym_rows if str(row.get("selected_standard_name", "")).strip()
        )
        synonym_payload["meta"]["matched_canonical_count"] = len(synonym_rows)
        synonym_payload["meta"]["unmatched_component_count"] = max(
            sum(1 for row in synonym_rows if str(row.get("match_status", "")).strip() == "unmatched"),
            len(synonym_payload["unmatched_components"]),
        )
    else:
        synonym_payload = build_synonym_library(component_rows, component_meta)

    if output_dir:
        final_output_dir = Path(output_dir).expanduser().resolve()
    else:
        final_output_dir = _default_review_root(step2_output_dir) / "final"

    final_output_dir.mkdir(parents=True, exist_ok=True)
    copied_review_package_path = final_output_dir / STEP2_REVIEW_PACKAGE_NAME
    final_component_path = final_output_dir / COMPONENT_RESULT_NAME
    final_synonym_path = final_output_dir / SYNONYM_LIBRARY_NAME
    final_summary_path = final_output_dir / RUN_SUMMARY_NAME

    run_summary = {
        "task_name": "step2_manual_review_apply",
        "generated_at": _now_iso(),
        "status": "manual_review_applied",
        "source_step2_output_dir": str(step2_dir),
        "review_package_path": str(review_path),
        "output_dir": str(final_output_dir),
        "mapping_count": len(component_rows),
        "matched_count": component_counts["matched"],
        "candidate_only_count": component_counts["candidate_only"],
        "conflict_count": component_counts["conflict"],
        "unmatched_count": component_counts["unmatched"],
        "synonym_component_count": len(synonym_payload.get("synonym_library", [])),
        "matched_synonym_component_count": sum(
            1 for row in synonym_payload.get("synonym_library", []) if str(row.get("selected_standard_name", "")).strip()
        ),
        "synonym_canonical_count": len(synonym_payload.get("synonym_library", [])),
        "unmatched_component_count": max(
            sum(
                1
                for row in synonym_payload.get("synonym_library", [])
                if str(row.get("match_status", "")).strip() == "unmatched"
            ),
            len(synonym_payload.get("unmatched_components", [])),
        ),
        "source_component_result_path": str(step2_dir / COMPONENT_RESULT_NAME),
        "source_synonym_library_path": str(step2_dir / SYNONYM_LIBRARY_NAME),
    }

    _write_json(copied_review_package_path, review_payload)
    _write_json(final_component_path, component_payload)
    _write_json(final_synonym_path, synonym_payload)
    _write_json(final_summary_path, run_summary)

    return {
        "output_dir": str(final_output_dir),
        "component_matching_result_path": str(final_component_path),
        "synonym_library_path": str(final_synonym_path),
        "run_summary_path": str(final_summary_path),
        "review_package_copy_path": str(copied_review_package_path),
        "run_summary": run_summary,
    }
