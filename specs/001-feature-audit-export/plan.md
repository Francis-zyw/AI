# Implementation Plan: 项目特征审核导出工具

**Branch**: `feature/001-feature-audit-export` | **Date**: 2026-04-17 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/001-feature-audit-export/spec.md`

## Summary

Step3 匹配结果中 84.6% 的项目特征未匹配到构件属性，需要一个交互式审核导出工具。技术方案：Python 生成器（`step5_feature_audit.py`）读取 Step3 结果 + 构件属性库，输出单 HTML 文件。前端零框架（内嵌 CSS/JS），三栏布局（仪表盘+构件树+特征列表+属性参考），支持筛选、批注、状态标记、Excel/JSON 导出、Wiki 补丁导出、审核进度保存。

## Technical Context

**Language/Version**: Python 3.11+（生成器）+ 原生 JS/CSS/HTML（前端）  
**Primary Dependencies**: SheetJS CDN（xlsx.full.min.js，纯前端 Excel 读写）  
**Storage**: JSON 文件 + localStorage（浏览器端审核进度）  
**Testing**: pytest（Python 生成器）+ 真实数据验证（HTML 工具）  
**Target Platform**: macOS（Python），Chrome 90+ / Safari 15+ / Edge 90+（HTML）  
**Project Type**: CLI tool（Python 生成器）+ 单 HTML 应用（前端工具）  
**Performance Goals**: 1000+ 行结果在 3 秒内完成首屏渲染  
**Constraints**: 零后端服务，数据不上传，单 HTML 可双击打开  
**Scale/Scope**: ~1000 行 Step3 结果，~5000 特征条目，69 个构件类型

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Pipeline-First | ✅ PASS | 新增 `step5_feature_audit.py` 作为独立步骤，输入 Step3 JSON → 输出 HTML + 导出文件 |
| II. Single HTML Tool | ✅ PASS | Python 生成器 + 单 HTML，零外部依赖（仅 SheetJS CDN），可双击打开 |
| III. Data Contract | ✅ PASS | 输入依赖 Step3 结果 JSON 已有 schema；输出定义 FeatureAuditItem / WikiKnowledgePatch / ComponentsPatch 契约 |
| IV. Knowledge Feedback Loop | ✅ PASS | 导出 `wiki_patch.json` 兼容 `wiki_patch_import.py`，闭环回写知识库 |
| V. CLI Entry Point | ✅ PASS | 通过 `python3 -m pipeline_v2 step5-audit` 暴露 CLI |

**GATE RESULT**: All 5 principles pass. No violations.

## Project Structure

### Documentation (this feature)

```text
specs/001-feature-audit-export/
├── plan.md                          # This file
├── spec.md                          # Feature specification
├── spec-feature-mapping-feedback.md # Companion spec (Step5→Step3 feedback)
├── research.md                      # Phase 0: technical decisions
├── data-model.md                    # Phase 1: entity/contract definitions
├── checklists/
│   └── requirements.md              # Spec quality checklist
└── tasks.md                         # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
pipeline_v2/
├── step5_feature_audit.py           # NEW — Python 生成器（CLI + 数据预处理 + HTML 输出）
├── cli.py                           # MODIFY — 注册 step5-audit 子命令
├── contracts.py                     # MODIFY — 新增 Step5 输入/输出 schema
├── wiki_patch_import.py             # EXISTING — wiki_patch.json 消费端（不修改）
├── wiki_retriever.py                # EXISTING — Wiki 知识加载（不修改）
└── step3_review_editor.py           # EXISTING — 参考模式（不修改）

data/output/step5/                   # NEW — Step5 输出目录
├── feature_audit_tool.html          # 生成的工具 HTML（运行时）
├── feature_audit_export.xlsx        # 导出 Excel（运行时）
├── feature_audit_export.json        # 导出 JSON（运行时）
├── feature_audit_progress.json      # 审核进度（运行时）
├── wiki_patch.json                  # Wiki 知识补丁（运行时）
└── components_patch.json            # 属性库增量补丁（Phase 2 运行时）

tests/
└── test_step5_feature_audit.py      # NEW — 生成器单元测试
```

**Structure Decision**: 遵循 Pipeline-First 原则，新增 `step5_feature_audit.py` 在 `pipeline_v2/` 内，与 Step1–4 保持一致的扁平结构。无需子目录（`step5_engine/`），因为生成器逻辑不复杂（数据预处理 + HTML 模板拼接）。

## Key Technical Decisions

### D1: 单 HTML vs 前后端分离

**Decision**: 单 HTML 文件（Python 生成）  
**Rationale**: 与现有 `step3_review_editor.py` 和 `step3_component_analysis.py` 完全一致。产品人员双击即开，无需启动服务。数据量（~5000 条目）浏览器端处理无压力。  
**Alternatives rejected**: Flask/FastAPI 后端（增加部署复杂度，违背 Constitution II）

### D2: 数据注入方式

**Decision**: Python 将 JSON 序列化后嵌入 `<script>` 标签  
**Rationale**: 参照 `step3_review_editor.py` 现有模式（`bill_json` / `comp_ref_json` 内嵌）  

### D3: 特征条目聚合

**Decision**: `itemKey = source_component + '|' + label`，合并同构件同标签条目  
**Rationale**: 审核人员关心"砖墙缺少'规格'"而非逐行重复条目，合并后减少 90%+ 重复  

### D4: 全部特征展示（已匹配+未匹配）

**Decision**: 同时展示 `matched=true` 和 `matched=false` 条目，已匹配绿色、未匹配红色  
**Rationale**: 审核人员需要全貌上下文才能做出准确判断（spec US1 核心需求）  

### D5: Excel 库

**Decision**: SheetJS CDN (`xlsx.full.min.js`)  
**Rationale**: 纯前端，单文件引入，支持多 sheet 读写，无需 npm 构建  

### D6: 审核进度双重持久化

**Decision**: localStorage 自动保存 + JSON 文件手动导出  
**Rationale**: localStorage 频繁保存无感知，JSON 文件支持跨浏览器迁移  

### D7: 虚拟滚动

**Decision**: 对特征列表实现轻量虚拟滚动（仅渲染可见区域 ± buffer）  
**Rationale**: 缺失特征超过 2000 条时 DOM 节点过多会卡顿，~80 行 JS 实现  

### D8: 构件属性参考面板

**Decision**: 加载 `component_source_table.json`，选中构件时侧面板展示全部属性  
**Rationale**: 审核人员需对照属性库判断"待补充 vs 无需补充"（spec US6）

## Module Architecture

### Module 1: Python 生成器 — `pipeline_v2/step5_feature_audit.py`

读取 Step3 结果 + 构件属性库 + 构件来源表，预处理数据，输出单 HTML 文件。

```
step5_feature_audit.py
├── load_step3_results(path)              # 加载 Step3 JSON
├── load_components_library(path)         # 加载 components.json
├── load_component_source_table(path)     # 加载 component_source_table.json
├── extract_all_feature_items(rows)       # 提取所有 feature_expression_items（matched + unmatched）
├── detect_intermittent_failures(items)   # 检测同 label 部分匹配部分不匹配
├── aggregate_by_component(items)         # 按构件×标签聚合 + 统计
├── compute_dashboard_stats(aggregated)   # 计算仪表盘数据
├── build_audit_html(data, comp_ref, src_table)  # 拼接完整 HTML
└── main()                                # CLI 入口 (argparse)
```

**CLI 接口**:
```bash
python3 -m pipeline_v2 step5-audit \
  --step3-result data/output/step3/run-*/project_component_feature_calc_matching_result.json \
  --components data/input/components.json \
  --component-source-table data/output/step3/run-*/component_source_table.json \
  --output data/output/step5/feature_audit_tool.html
```

### Module 2: 前端数据层（JS）

管理所有特征条目、审核状态、筛选索引。

```javascript
const STATE = {
  allItems: [],           // 全部特征条目（matched + unmatched）
  byComponent: {},        // { 构件名: items[] }
  byLabel: {},            // { 标签名: items[] }
  auditProgress: {},      // { itemKey: { status, note } }
  componentSourceTable: {},// 构件属性参考
  filters: { component: '', label: '', status: 'all', search: '' },
  stats: { total: 0, matched: 0, unmatched: 0, toFill: 0, noNeed: 0, toConfirm: 0, toSediment: 0 }
};
```

### Module 3: 前端视图层（JS + CSS）

三栏布局 + 仪表盘：

```
┌──────────────────────────────────────────────────────────────────────┐
│  仪表盘: 总计 | 已匹配 | 未匹配 | 待补充 | 无需 | 需沉淀           │
├──────────┬─────────────────────────────────────┬────────────────────┤
│  构件树   │  筛选栏 + 特征列表                   │  属性参考面板      │
│  砖墙 (51)│  ☐ [绿] 砼标号 TBH ✓ matched       │  砖墙属性列表:     │
│  主肋梁(23)│  ☐ [红] 规格 (191次) ✗ unmatched   │  · 砼标号 TBH text │
│  ...      │    批注: [______] 状态: [待补充 ▼]   │  · 砂浆标号 SJBH   │
│           │  ☐ [红⚠] 砼种类 (间歇性失败)        │  · 厚度 HD number  │
│           │  [全选] [导出Excel] [导出Wiki补丁]    │  ...               │
└──────────┴─────────────────────────────────────┴────────────────────┘
```

### Module 4: 前端导出层（JS）

- **Excel 导出**: SheetJS 多 sheet（按构件分组，含回填列）
- **JSON 导出**: `feature_audit_export.json`
- **Wiki 补丁导出**: `wiki_patch.json`（仅"匹配失败-需沉淀"条目，兼容 `wiki_patch_import.py`）
- **Excel 导入** (Phase 2): 解析回填列，展示差异，生成 `components_patch.json`

## Implementation Phases

### Phase 1 (P1): 核心审核 — US1 + US2 + US3 + US6 + US7

| Step | Content | Complexity |
|------|---------|-----------|
| 1.1 | Python 生成器骨架（CLI + JSON 加载 + HTML 模板框架） | Low |
| 1.2 | 数据预处理：extract_all_feature_items + 间歇性失败检测 + 聚合 | Low |
| 1.3 | 前端：Dashboard 仪表盘（6 个统计卡片） | Low |
| 1.4 | 前端：ComponentTree 构件列表（含已匹配/未匹配计数） | Medium |
| 1.5 | 前端：FilterBar 多维筛选 + 搜索 | Medium |
| 1.6 | 前端：FeatureItemList 全部特征展示（绿/红/⚠标记） | Medium |
| 1.7 | 前端：属性参考面板（component_source_table 展示） | Low |
| 1.8 | 前端：选择/批注/状态标记 + 审核进度保存恢复 | Medium |
| 1.9 | 前端：Excel 导出（SheetJS 多 sheet + 回填列） | Medium |
| 1.10 | 前端：JSON 导出 + Wiki 补丁导出 | Low |
| 1.11 | 集成测试：加载 run-20260416-full 真实数据验证 | Low |

### Phase 2 (P2): 回填闭环与编辑 — US4 + US5 + US8

| Step | Content | Complexity |
|------|---------|-----------|
| 2.1 | Excel 导入 + 回填列解析 | Medium |
| 2.2 | 差异展示 UI（ImportDialog） | Medium |
| 2.3 | 生成 components_patch.json | Low |
| 2.4 | EditModal 在线属性绑定编辑 | Medium |
| 2.5 | 批量绑定 + 手动新增特征条目 | Medium |

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Step3 结果格式变更 | 工具无法加载 | 版本号检查 + contracts.py schema 校验 |
| SheetJS CDN 不可用 | 导出失败 | HTML 内嵌 SheetJS（~500KB）作为 fallback |
| 审核进度丢失 | 重复工作 | 双重持久化（localStorage + JSON 文件） |
| 缺口条目 >5000 | UI 卡顿 | 虚拟滚动 + 分页降级 |
| component_source_table.json 缺失 | 属性参考不可用 | 优雅降级：面板显示"未加载"，其余功能正常 |

## Complexity Tracking

> No Constitution violations. No complexity justifications needed.
