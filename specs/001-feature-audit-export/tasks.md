# Tasks: 项目特征审核导出工具

**Input**: Design documents from `specs/001-feature-audit-export/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, quickstart.md ✅

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 创建项目结构和 CLI 骨架

- [x] T001 Create `pipeline_v2/step5_feature_audit.py` with CLI entry point (argparse: `--step3-result`, `--components`, `--component-source-table`, `--output`)
- [x] T002 [P] Register `step5-audit` subcommand in `pipeline_v2/cli.py`
- [x] T003 [P] Add Step5 input/output schema definitions to `pipeline_v2/contracts.py`
- [x] T004 [P] Create output directory `data/output/step5/` with `.gitkeep`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 数据加载和预处理核心逻辑，所有 User Story 均依赖

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T005 Implement `load_step3_results(path)` in `pipeline_v2/step5_feature_audit.py` — load and validate Step3 JSON, return rows list
- [x] T006 Implement `load_components_library(path)` in `pipeline_v2/step5_feature_audit.py` — load `components.json`, return dict keyed by component name
- [x] T007 Implement `load_component_source_table(path)` in `pipeline_v2/step5_feature_audit.py` — load `component_source_table.json`, return dict keyed by component name with attributes list
- [x] T008 Implement `extract_all_feature_items(rows)` in `pipeline_v2/step5_feature_audit.py` — extract ALL `feature_expression_items` (matched + unmatched) from rows, attach `source_component`, `source_row_id`
- [x] T009 Implement `aggregate_by_component(items)` in `pipeline_v2/step5_feature_audit.py` — group by `source_component|label`, compute `occurrence_count`, collect `value_samples` (max 3), detect `intermittent` flag
- [x] T010 Implement `detect_intermittent_failures(aggregated)` in `pipeline_v2/step5_feature_audit.py` — for each `source_component|label`, if both matched=true and matched=false exist, set `intermittent=true`
- [x] T011 Implement `compute_dashboard_stats(aggregated)` in `pipeline_v2/step5_feature_audit.py` — return stats: total, matched, unmatched, per-component counts
- [x] T012 Implement `build_audit_html(data, comp_ref, src_table, stats)` skeleton in `pipeline_v2/step5_feature_audit.py` — generate HTML string with `<head>`, CSS vars, SheetJS inlined, JSON data injection via `<script>const ALL_ITEMS=...; const COMP_REF=...; const SRC_TABLE=...; const STATS=...;</script>`
- [x] T013 Implement `_esc(text)` HTML escape helper and `_data_hash(json_str)` in `pipeline_v2/step5_feature_audit.py`

**Checkpoint**: `python3 -m pipeline_v2 step5-audit --step3-result ... --components ... --component-source-table ... --output /tmp/test.html` produces a valid HTML file that opens in browser with raw JSON data visible in console.

---

## Phase 3: User Story 1 — 查看全部项目特征 (Priority: P1) 🎯 MVP

**Goal**: 产品审计人员打开 HTML 工具，在同一列表中查看所有特征条目（已匹配绿色+未匹配红色），支持按构件类型/特征标签/匹配状态筛选。

**Independent Test**: 加载 `project_component_feature_calc_matching_result.json`，工具展示全部特征条目（含已匹配），切换筛选正常。

### Implementation for User Story 1

- [x] T014 [US1] Implement CSS base styles in `pipeline_v2/step5_feature_audit.py` (inline CSS) — Grid 3-column layout: top dashboard (full-width) + left sidebar (240px) + main content + right panel (280px); color scheme matching step3 tools; `.matched` (green) / `.unmatched` (red) / `.intermittent` (orange⚠️) status styles
- [x] T015 [US1] Implement Dashboard component in `pipeline_v2/step5_feature_audit.py` (inline JS) — 6 stat cards: 总计/已匹配/未匹配/待补充/无需/需沉淀; progress bar; card click triggers filter
- [x] T016 [US1] Implement ComponentTree component in `pipeline_v2/step5_feature_audit.py` (inline JS) — left sidebar; list all component types with matched/unmatched counts; click selects component and filters main list; highlight active component
- [x] T017 [US1] Implement FilterBar component in `pipeline_v2/step5_feature_audit.py` (inline JS) — search input (keyword filter on label/value), status dropdown (all/matched/unmatched), label dropdown; `applyFilters()` function updates visible items
- [x] T018 [US1] Implement FeatureItemList + FeatureItemCard in `pipeline_v2/step5_feature_audit.py` (inline JS) — render all feature items as cards; matched items show green `attribute_name (attribute_code)`; unmatched items show red; intermittent items show ⚠️; display `occurrence_count` and `value_samples`
- [x] T019 [US1] Implement VirtualScroller class in `pipeline_v2/step5_feature_audit.py` (inline JS) — ~80 lines; fixed-height container with `overflow-y:auto`; compute visible range on scroll; render only visible ± 20 buffer; skip if items < 500
- [x] T020 [US1] Implement `initData(rawItems, compRef, srcTable)` in `pipeline_v2/step5_feature_audit.py` (inline JS) — parse injected JSON, build STATE object (allItems, byComponent, byLabel, stats), trigger initial render

**Checkpoint**: HTML 工具展示全部特征条目，绿色/红色/⚠️正确区分，筛选三维度工作正常，虚拟滚动对大列表流畅。

---

## Phase 4: User Story 6 — 查看构件已有属性库 (Priority: P1)

**Goal**: 选中构件后在右侧面板展示该构件完整属性列表（名称、编码、数据类型、可选值）。

**Independent Test**: 选中构件类型"主肋梁"，属性参考面板展示该构件全部属性。

### Implementation for User Story 6

- [x] T021 [US6] Implement AttributeRefPanel component in `pipeline_v2/step5_feature_audit.py` (inline JS) — right sidebar; on component selection, render all attributes from `SRC_TABLE[component]`; show name, code, data_type, values; click attribute highlights matching items in main list
- [x] T022 [US6] Handle missing component_source_table gracefully in `pipeline_v2/step5_feature_audit.py` (inline JS) — if SRC_TABLE empty or component not found, show "属性库未加载" / "该构件属性库为空" message; rest of tool functions normally

**Checkpoint**: 选中构件时右侧面板显示属性列表，点击属性高亮主列表中对应已匹配条目。

---

## Phase 5: User Story 2 — 批量选择并标记待补充特征 (Priority: P1)

**Goal**: 审计人员勾选缺失特征条目，标记状态（待补充/无需补充/待确认/需沉淀），添加批注，保存进度。

**Independent Test**: 勾选多个条目，添加批注，标记状态，保存后重新打开工具应恢复。

### Implementation for User Story 2

- [x] T023 [US2] Add checkbox + status dropdown + note input to FeatureItemCard in `pipeline_v2/step5_feature_audit.py` (inline JS) — each unmatched card gets: checkbox, status dropdown (pending/to_fill/no_need/to_confirm/to_sediment), note textarea; `updateAuditStatus(itemKey, status, note)` updates STATE.auditProgress
- [x] T024 [US2] Implement batch operations in `pipeline_v2/step5_feature_audit.py` (inline JS) — ActionBar component: select-all/deselect/invert for current filtered view; `batchUpdateStatus(selectedKeys, status)` batch update
- [x] T025 [US2] Implement `saveProgress()` / `loadProgress()` in `pipeline_v2/step5_feature_audit.py` (inline JS) — auto-save to `localStorage['feature_audit_' + dataHash]` on every status change; manual export to `feature_audit_progress.json` via download; on load, check localStorage first then prompt file upload
- [x] T026 [US2] Update Dashboard stats reactively in `pipeline_v2/step5_feature_audit.py` (inline JS) — on any audit status change, recompute stats (toFill, noNeed, toConfirm, toSediment) and refresh dashboard cards + progress bar

**Checkpoint**: 勾选、标记、批注正常；保存进度后刷新页面自动恢复；仪表盘数字实时更新。

---

## Phase 6: User Story 3 — 导出项目特征补充文档 (Priority: P1)

**Goal**: 将"待补充"特征导出为 Excel（按构件分 sheet）+ JSON。

**Independent Test**: 选中若干待补充特征，导出 Excel，打开验证按构件分 sheet、含回填列。

### Implementation for User Story 3

- [x] T027 [US3] Implement `exportExcel()` in `pipeline_v2/step5_feature_audit.py` (inline JS) — collect `status='to_fill'` items; group by `source_component`; create workbook with SheetJS; sheet per component: header row (A-L columns per data-model.md AuditExportSheet), data rows sorted by occurrence_count desc; first "总览" sheet with per-component summary; `XLSX.writeFile()` download
- [x] T028 [US3] Implement `exportJSON()` in `pipeline_v2/step5_feature_audit.py` (inline JS) — serialize full audit data (all items + auditProgress) to `feature_audit_export.json`; trigger download
- [x] T029 [US3] Add export buttons to ActionBar in `pipeline_v2/step5_feature_audit.py` (inline JS) — "导出 Excel" + "导出 JSON" buttons; disable Excel export if no items marked `to_fill`

**Checkpoint**: 导出 Excel 可在 WPS/Excel 中打开，每个构件一个 sheet，含 A-L 列；JSON 文件结构正确。

---

## Phase 7: User Story 7 — 匹配失败知识沉淀 Wiki 导出 (Priority: P1)

**Goal**: 标记"匹配失败-需沉淀"的条目，导出 `wiki_patch.json` 兼容 `wiki_patch_import.py`。

**Independent Test**: 标记若干条目为"需沉淀"，导出 `wiki_patch.json`，格式含 `meta.purpose: "wiki_knowledge_patch"` + `components` 按构件分组。

### Implementation for User Story 7

- [x] T030 [US7] Implement `exportWikiPatch()` in `pipeline_v2/step5_feature_audit.py` (inline JS) — collect `status='to_sediment'` items; build `wiki_patch.json` with `meta: {source: "step5_feature_audit", exported_at: ISO, purpose: "wiki_knowledge_patch"}` + `components: {[comp]: [{project_code, project_name, match_status, feature_expression_items, notes, reviewed}]}`; trigger download
- [x] T031 [US7] Add "导出 Wiki 补丁" button to ActionBar in `pipeline_v2/step5_feature_audit.py` (inline JS) — disabled (grey) when no items marked `to_sediment`; hover tooltip "请先标记需沉淀的条目"; enabled when count > 0

**Checkpoint**: `wiki_patch.json` 格式可被 `python3 -m pipeline_v2.wiki_patch_import wiki_patch.json` 接受处理。

---

## Phase 8: User Story 4 — 接收下游回填结果并回写 (Priority: P2)

**Goal**: 导入回填 Excel，展示差异，生成 `components_patch.json`。

**Independent Test**: 导入回填 Excel（J/K/L 列有值），工具展示差异列表，确认后下载 `components_patch.json`。

### Implementation for User Story 4

- [x] T032 [US4] Implement ImportDialog component in `pipeline_v2/step5_feature_audit.py` (inline JS) — file upload button for `.xlsx`; `XLSX.read()` parse; iterate sheets, read J/K/L columns; compare with original export data; display diff list: added/modified/ignored
- [x] T033 [US4] Implement `generateComponentsPatch(diffs)` in `pipeline_v2/step5_feature_audit.py` (inline JS) — from confirmed diffs, build `components_patch.json` per data-model.md ComponentsPatch format; trigger download
- [x] T034 [US4] Add confirm/reject UI to ImportDialog in `pipeline_v2/step5_feature_audit.py` (inline JS) — checkbox per diff item; "确认全部" / "取消" buttons; rejected items marked with reason

**Checkpoint**: 导入回填 Excel → 展示差异 → 确认 → 下载 `components_patch.json`，格式正确。

---

## Phase 9: User Story 5 — 项目特征表达式在线编辑 (Priority: P2)

**Goal**: 审计人员在工具中直接编辑特征的属性绑定。

**Independent Test**: 编辑某条特征的 `attribute_name`，保存后该条 `matched` 变为 true。

### Implementation for User Story 5

- [x] T035 [US5] Implement EditModal component in `pipeline_v2/step5_feature_audit.py` (inline JS) — click "编辑" on a card opens modal; fields: label (text), attribute_name (dropdown from SRC_TABLE[component].attributes), attribute_code (auto-fill on attribute select), value_expression (text); save updates item in STATE, changes card style from red to green if attribute bound
- [x] T036 [US5] Implement batch binding in `pipeline_v2/step5_feature_audit.py` (inline JS) — select multiple items with same label; "批量绑定" button opens EditModal pre-filled; apply attribute binding to all selected items at once

**Checkpoint**: 编辑单条/批量绑定属性后，卡片样式更新，仪表盘 matched 计数增加。

---

## Phase 10: User Story 8 — 手动新增特征条目 (Priority: P2)

**Goal**: 审计人员手动添加新特征条目。

**Independent Test**: 在"砖墙"下点击"添加特征"，填写 label 和属性绑定，新条目出现在列表中。

### Implementation for User Story 8

- [x] T037 [US8] Implement AddFeatureDialog in `pipeline_v2/step5_feature_audit.py` (inline JS) — "添加特征" button per component; opens form: label (required), attribute_name (dropdown), attribute_code (auto-fill), value_expression (optional); on save: add to STATE.allItems with `source: "manual_add"`, dashed card style; duplicate label check with confirmation dialog
- [x] T038 [US8] Update aggregation and stats after manual add in `pipeline_v2/step5_feature_audit.py` (inline JS) — re-compute byComponent/byLabel/stats; refresh ComponentTree counts; refresh Dashboard

**Checkpoint**: 手动添加条目出现在列表中（虚线卡片），聚合统计正确更新。

---

## Phase 11: Polish & Cross-Cutting Concerns

**Purpose**: 边界场景、性能优化、集成验证

- [x] T039 [P] Handle edge case: empty Step3 result (0 rows) — show "无数据" message in `pipeline_v2/step5_feature_audit.py`
- [x] T040 [P] Handle edge case: `feature_expression_items` is empty array — skip row, no display
- [x] T041 [P] Handle edge case: `component_source_table.json` missing or load failure — graceful degradation in `pipeline_v2/step5_feature_audit.py`
- [x] T042 [P] Handle edge case: Excel export >65535 rows per sheet — auto-split or CSV fallback in `pipeline_v2/step5_feature_audit.py`
- [x] T043 [P] Handle edge case: import Excel format mismatch — column validation with specific error messages in `pipeline_v2/step5_feature_audit.py`
- [x] T044 Integration test: load `data/output/step3/run-20260416-full/project_component_feature_calc_matching_result.json` real data, verify HTML renders correctly, export Excel, export wiki_patch.json
- [x] T045 Run quickstart.md validation — verify all CLI commands and workflows documented in `specs/001-feature-audit-export/quickstart.md` work end-to-end

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational — MVP core
- **US6 (Phase 4)**: Depends on Foundational — parallel with US1 (different DOM region)
- **US2 (Phase 5)**: Depends on US1 (needs rendered item cards to add controls)
- **US3 (Phase 6)**: Depends on US2 (needs audit status data to export)
- **US7 (Phase 7)**: Depends on US2 (needs `to_sediment` status)
- **US4 (Phase 8)**: Depends on US3 (needs exported Excel format to compare)
- **US5 (Phase 9)**: Depends on US1 + US6 (needs item cards + attribute ref panel)
- **US8 (Phase 10)**: Depends on US1 (needs rendered list to add items)
- **Polish (Phase 11)**: Depends on all desired user stories being complete

### User Story Dependencies

```
Phase 1 (Setup)
    │
Phase 2 (Foundational)
    │
    ├──────────────────┐
    ▼                  ▼
Phase 3 (US1)    Phase 4 (US6)
    │                  │
    ├──────────────────┘
    ▼
Phase 5 (US2)
    │
    ├──────────────┐
    ▼              ▼
Phase 6 (US3)  Phase 7 (US7)
    │
    ▼
Phase 8 (US4)

Phase 9 (US5) ← US1 + US6
Phase 10 (US8) ← US1
Phase 11 (Polish) ← all
```

### Within Each User Story

- Models/data before rendering
- Rendering before interaction
- Core implementation before edge cases

### Parallel Opportunities

- T002, T003, T004 can run in parallel (Setup phase, different files)
- Phase 3 (US1) and Phase 4 (US6) can run in parallel (different DOM regions)
- Phase 6 (US3) and Phase 7 (US7) can run in parallel after US2 is complete
- Phase 9 (US5) and Phase 10 (US8) can run in parallel
- All Phase 11 edge case tasks (T039–T043) can run in parallel

---

## Parallel Example: User Story 1

```bash
# After Phase 2 complete, launch US1 tasks:

# Parallel: CSS + Dashboard (different concerns)
Task: T014 [US1] CSS base styles
Task: T015 [US1] Dashboard component

# Parallel: ComponentTree + FilterBar (different DOM regions)
Task: T016 [US1] ComponentTree
Task: T017 [US1] FilterBar

# Sequential: FeatureItemList depends on FilterBar
Task: T018 [US1] FeatureItemList + FeatureItemCard

# Sequential: VirtualScroller depends on FeatureItemList
Task: T019 [US1] VirtualScroller

# Sequential: initData ties everything together
Task: T020 [US1] initData
```

---

## Implementation Strategy

### MVP First (US1 Only)

1. Complete Phase 1: Setup (T001–T004)
2. Complete Phase 2: Foundational (T005–T013)
3. Complete Phase 3: US1 — 查看全部特征 (T014–T020)
4. **STOP and VALIDATE**: Open HTML, verify all features display with green/red/⚠️ styling, filters work
5. Deliverable: read-only audit tool

### Incremental Delivery

1. Setup + Foundational → CLI works, HTML generates
2. Add US1 → 查看全部特征 (read-only, filterable) → **MVP!**
3. Add US6 → 属性参考面板 (context for auditors)
4. Add US2 → 批量选择标记 (interactive audit)
5. Add US3 + US7 → 导出 Excel + Wiki 补丁 (output)
6. Add US4 → 回填闭环 (P2)
7. Add US5 + US8 → 在线编辑 + 手动新增 (P2)
8. Polish → edge cases + integration test

### Single Developer Strategy

Follow phases sequentially: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11

---

## Notes

- All tasks operate on a single file: `pipeline_v2/step5_feature_audit.py` (Python generator with inline HTML/CSS/JS)
- [P] tasks = different DOM regions or independent concerns, safe to parallelize
- [Story] label maps task to user story for traceability
- Commit after each phase completion
- Stop at any checkpoint to validate independently
- SheetJS is inlined in HTML (not CDN) per research.md R2
