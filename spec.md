# Feature Specification: 项目特征审核导出工具

**Feature Branch**: `feature/project-feature-audit-export`  
**Created**: 2026-04-16  
**Status**: Draft v2  
**Input**: Step3 匹配结果中大量项目特征未匹配（84.6% 缺口率），需要工具让产品人员**查看全部特征（已匹配+未匹配）**、审核缺失项、导出文档给下游更新，同时将匹配失败的知识沉淀到 Wiki

---

## 背景与问题

### 现状

1. **Step3 匹配流程**产出 `project_component_feature_calc_matching_result.json`，每行含 `feature_expression_items[]`
2. 每个 `feature_expression_item` 有 `matched` 字段：`true` = 已映射到构件属性，`false` = 缺失
3. **当前缺口数据**（run-20260416-full）：894 行，共 3498 个特征条目，其中 **540 已匹配（15.4%）**、**2958 未匹配（84.6%）**，涉及 69 个构件类型
4. **部分特征标签存在"间歇性匹配失败"**：同一个 `component|label` 组合在不同清单行中有时匹配成功、有时失败（算法未识别变体写法），这类知识需要沉淀到 Wiki 以改进后续匹配
5. `step1_gap_analyzer.py` 已能生成缺口报告（MD + JSON），但**只读**——没有交互式选择、审核批注、导出给下游的能力
6. `step3_review_editor.py` 支持修改构件分配和导出 Wiki 补丁，但**不支持**按"缺失特征"维度操作
7. **`wiki_patch_import.py` 已存在**：可将审定结果导入到 `知识库中心/wiki/构件类型/{构件名}.md`，格式为 `wiki_patch.json`
8. `component_source_table.json` 包含每个构件类型的完整属性列表（名称、编码、数据类型、可选值），但审核工具中**不可见**

### 需要解决的核心问题

| # | 问题 | 影响 |
|---|------|------|
| 1 | 缺失项目特征无法交互式选择和批量标记 | 人工逐条查找效率极低 |
| 2 | 无法导出结构化文档给下游更新 | 特征补充依赖口头沟通，易遗漏 |
| 3 | 产品审核无闭环 | 审核结果无法回写系统，下次运行仍重复缺口 |
| 4 | 项目特征表达式无法在工具中直接编辑 | 需要手动改 Excel 再重跑流水线 |
| 5 | 已匹配特征不可见，产品无法掌握全貌 | 审核决策缺乏上下文，不知道哪些已成功匹配 |
| 6 | 同一标签有时匹配有时不匹配，算法失误无法反馈 | 匹配知识不沉淀，重跑仍重复失败 |
| 7 | 无法手动添加新的特征条目 | 发现遗漏特征时无法当场补录 |

---

## User Scenarios & Testing

### User Story 1 - 查看全部项目特征（已匹配+未匹配） (Priority: P1)

产品审计人员打开工具，加载 Step3 结果，在**同一列表**中查看所有 `feature_expression_items`（已匹配+未匹配），已匹配条目绿色显示 `attribute_name` + `attribute_code`，未匹配条目红色。支持按**构件类型**、**特征标签**、**匹配状态**三维筛选。

**Why this priority**: 审核人员需要看到全貌（哪些已成功、哪些缺失），才能做出准确判断。仅看缺失特征缺乏上下文。

**Independent Test**: 加载 `project_component_feature_calc_matching_result.json`，工具应展示全部特征条目（含已匹配），支持切换筛选。

**Acceptance Scenarios**:

1. **Given** Step3 结果文件已生成, **When** 用户打开工具并加载结果, **Then** 展示所有特征条目（已匹配+未匹配），已匹配条目绿色显示属性名和编码（如"砼标号 TBH"），未匹配条目红色
2. **Given** 特征列表已展示, **When** 用户切换筛选为"仅已匹配", **Then** 仅显示 `matched=true` 的条目，仪表盘统计同步更新
3. **Given** 特征列表已展示, **When** 用户切换筛选为"仅未匹配", **Then** 回到传统的缺失特征视图
4. **Given** 特征列表已展示, **When** 用户选中构件类型"砖墙"并搜索"混凝土", **Then** 展示砖墙下所有含"混凝土"的特征条目（含已匹配和未匹配）

---

### User Story 2 - 批量选择并标记待补充特征 (Priority: P1)

审计人员从缺失特征列表中勾选需要补充的条目，可以：
- 全选/反选某个构件类型下所有缺失特征
- 逐条勾选
- 对已选条目添加批注（如"需要甲方确认"、"参考XX标准"）
- 标记处理状态：`待补充` / `无需补充` / `待确认`

**Why this priority**: 不是所有缺失特征都需要补充，审计人员需要决策能力。

**Independent Test**: 勾选多个特征条目，添加批注，标记状态后保存，重新打开应保留状态。

**Acceptance Scenarios**:

1. **Given** 缺失特征列表已展示, **When** 用户勾选砖墙下 5 条缺失特征并标记为"待补充", **Then** 这 5 条状态变为"待补充"，统计数字更新
2. **Given** 已标记部分条目, **When** 用户对某条添加批注"参考GB50300", **Then** 批注保存在该条目上，导出时一并输出
3. **Given** 已标记和批注, **When** 用户点击"保存审核进度", **Then** 生成 `feature_audit_progress.json`，下次打开自动恢复

---

### User Story 3 - 导出项目特征补充文档 (Priority: P1)

将已标记为"待补充"的特征条目导出为**结构化文档**，供下游人员（特征维护团队）按文档更新构件属性库。

**Why this priority**: 这是工具的核心产出物，直接解决"缺失特征无法传递给下游"的问题。

**Independent Test**: 选中若干待补充特征，点击导出，生成 Excel 文档，文档应按构件类型分 sheet，每行含特征标签、值表达式样本、建议属性名、审核批注。

**Acceptance Scenarios**:

1. **Given** 用户已标记 50 条待补充特征（覆盖 8 个构件类型）, **When** 点击"导出补充清单", **Then** 生成 Excel 文件，每个构件类型一个 sheet，包含列：特征标签、出现次数、值表达式样本（最多3个）、建议属性名、建议属性编码、审核批注、处理状态
2. **Given** 导出的 Excel, **When** 下游人员打开, **Then** 每个 sheet 有表头说明、数据行和"回填结果"列（供下游填写实际新增的属性名和编码）
3. **Given** 导出完成, **When** 同时生成 JSON 版本, **Then** `feature_audit_export.json` 包含完整数据，可供程序化回读

---

### User Story 4 - 接收下游回填结果并回写 (Priority: P2)

下游团队在导出的 Excel 中填写"回填结果"（实际新增的属性名、属性编码、值域），产品审计人员将回填 Excel 导入工具，工具：
- 自动比对原始导出与回填内容
- 展示新增/修改/忽略的差异
- 确认后生成构件属性库增量补丁

**Why this priority**: 闭环是长期价值，但第一版可以先做手动更新。

**Independent Test**: 导入回填 Excel，工具展示差异列表，确认后生成 `components_patch.json`。

**Acceptance Scenarios**:

1. **Given** 下游已回填 Excel（砖墙 sheet 新增 3 条属性）, **When** 导入回填文件, **Then** 展示差异：3 条新增属性，含属性名、编码、值域
2. **Given** 差异已展示, **When** 审计人员确认全部接受, **Then** 生成 `components_patch.json`，可直接 merge 到 `components.json`
3. **Given** 部分拒绝, **When** 审计人员取消勾选 1 条, **Then** 仅 2 条写入 patch，被拒绝的标记为"已拒绝"并保留原因

---

### User Story 5 - 项目特征表达式在线编辑 (Priority: P2)

审计人员在工具中直接编辑项目特征表达式（`feature_expression_items`），包括：
- 修改 `label`（重命名特征标签）
- 修改 `attribute_name` / `attribute_code`（手动绑定到已有构件属性）
- 修改 `value_expression`（修正值表达式）
- 将 `matched` 从 false 改为 true（手动确认匹配）

**Why this priority**: 高级用户才需要，大部分场景用 US1-US4 已覆盖。

**Independent Test**: 编辑某条特征的 attribute_name，保存后该条 matched 变为 true。

**Acceptance Scenarios**:

1. **Given** 用户展开某清单行的特征列表, **When** 点击某条未匹配特征的"编辑", **Then** 展示可编辑表单：label、attribute_name（下拉含当前构件的所有属性）、attribute_code、value_expression
2. **Given** 用户从下拉选择已有属性"砼标号(TBH)", **When** 点击保存, **Then** 该条 attribute_name="砼标号"、attribute_code="TBH"、matched=true，行样式从红色变绿色
3. **Given** 用户批量编辑 10 条同标签特征, **When** 使用"批量绑定"功能, **Then** 所有 10 条的属性绑定一次完成

---

### User Story 6 - 查看构件已有属性库 (Priority: P1)

审计人员选中某个构件类型后，在侧面板中查看该构件的**完整属性列表**（来自 `component_source_table.json`），包括属性名、编码、数据类型和可选值。这为审核缺失特征时提供上下文——可以快速判断"这个特征应该绑定到哪个已有属性"。

**Why this priority**: 审核人员需要对照属性库才能做出"待补充 vs 无需补充"的判断，缺少参考信息会导致错误决策。

**Independent Test**: 选中构件类型"主肋梁"，属性参考面板应展示该构件的全部属性（如砼标号、模板类型等）。

**Acceptance Scenarios**:

1. **Given** 用户在构件树中选中"主肋梁", **When** 属性面板加载, **Then** 展示该构件的全部属性列表（名称、编码、数据类型、可选值），如"砼标号 TBH text [C10,C15,...C60]"
2. **Given** 属性面板已展示, **When** 用户点击某个属性"砼标号(TBH)", **Then** 高亮主列表中所有 `attribute_code=TBH` 的已匹配特征条目
3. **Given** 构件类型在 `component_source_table.json` 中无属性定义, **When** 用户选中该构件, **Then** 面板显示"该构件属性库为空"提示

---

### User Story 7 - 匹配失败知识沉淀（Wiki 导出） (Priority: P1)

审核人员发现"特征标签在属性库中**已有对应属性**但匹配算法未能识别"的条目（如"砼强度等级"未匹配到"砼标号"），可标记为**"匹配失败-需沉淀"**状态，然后导出 `wiki_patch.json`。该文件格式兼容现有 `wiki_patch_import.py`，导入后自动写入 `知识库中心/wiki/构件类型/{构件名}.md` 的"人工审定记录"段，形成知识闭环。

**Why this priority**: 匹配失败的知识如果不沉淀，下次重跑 Step3 仍会重复失败。这是提升整体匹配率的核心反馈机制。

**Independent Test**: 标记若干"匹配失败"条目，导出 wiki_patch.json，运行 `wiki_patch_import.py` 后验证 wiki 页面已更新。

**Acceptance Scenarios**:

1. **Given** 用户发现"砼强度等级"（unmatched）应对应属性库中的"砼标号(TBH)", **When** 标记为"匹配失败-需沉淀"并添加批注"应匹配到 TBH", **Then** 该条目状态变更，仪表盘"需沉淀"计数+1
2. **Given** 已标记 15 条"匹配失败-需沉淀", **When** 点击"导出 Wiki 补丁", **Then** 生成 `wiki_patch.json`，格式含 `meta.purpose: "wiki_knowledge_patch"` + `components: {按构件分组}`
3. **Given** `wiki_patch.json` 已生成, **When** 运行 `python3 -m pipeline_v2.wiki_patch_import wiki_patch.json`, **Then** 对应构件的 wiki 页面新增"人工审定记录"段，含未匹配特征列表和审核批注
4. **Given** 无任何条目被标记为"匹配失败-需沉淀", **When** 查看工具栏, **Then** "导出 Wiki 补丁"按钮禁用（灰色），hover 提示"请先标记需沉淀的条目"

---

### User Story 8 - 手动新增特征条目 (Priority: P2)

审计人员在审核过程中发现 Step3 遗漏了某个特征条目（如项目名称中暗含的特征未被解析），可手动在当前构件下添加新的 `feature_expression_item`。

**Why this priority**: 自动解析不可能覆盖所有情况，手动补录是兜底手段，但频率较低。

**Independent Test**: 在"砖墙"构件下点击"添加特征"，填写 label 和属性绑定，新条目出现在列表中。

**Acceptance Scenarios**:

1. **Given** 用户选中构件"砖墙", **When** 点击"添加特征"按钮, **Then** 弹出表单：label（必填）、attribute_name（下拉自该构件属性库）、attribute_code（选择属性后联动填充）、value_expression（可选）
2. **Given** 用户填写 label="砌筑砂浆强度等级", **When** 从属性下拉选择"砂浆标号(SJBH)"并保存, **Then** 新条目以虚线卡片出现在列表中，标记 `source: "manual_add"`、`matched: true`
3. **Given** 用户填写 label 与已有条目重复, **When** 点击保存, **Then** 弹出警告"该标签已存在，确认添加？"，用户确认后允许

---

### Edge Cases

- Step3 结果文件为空（0 行）时：工具显示"无数据"提示，不报错
- `feature_expression_items` 为空数组的行：跳过，不显示在列表中
- 构件属性库中某构件无任何属性定义：标注"属性库为空，需先建立属性"
- 回填 Excel 格式不匹配（列缺失/顺序错）：导入时校验并给出具体列名错误提示
- 导出超过 65535 行（Excel 限制）：自动分卷或提示切换到 CSV/JSON
- 同一 `label` 在同一构件下既有 matched=true 又有 matched=false：自动标注"间歇性失败"，在卡片上显示⚠️图标
- `component_source_table.json` 缺失或加载失败：属性参考面板显示"属性库未加载"，其余功能正常可用
- 手动新增的特征条目 label 与已有条目完全重复：弹出确认对话框，允许但不强制
- `wiki_patch.json` 导出时无任何"匹配失败-需沉淀"条目：导出按钮禁用，tooltip 提示原因

---

## Requirements

### Functional Requirements

- **FR-001**: 工具 MUST 加载 Step3 结果 JSON（`project_component_feature_calc_matching_result.json`），解析 `feature_expression_items[]` 中**所有条目**（`matched=true` + `matched=false`），在同一列表中按构件类型分组展示
- **FR-002**: 工具 MUST 支持按构件类型、特征标签、特征值、**匹配状态**四个维度筛选特征
- **FR-003**: 工具 MUST 支持多选/全选/反选缺失特征条目
- **FR-004**: 工具 MUST 支持为每条特征添加处理状态（`待补充` / `无需补充` / `待确认`）和自由文本批注
- **FR-005**: 工具 MUST 导出"待补充"特征为 Excel（`.xlsx`），按构件类型分 sheet，含以下列：
  - 特征标签 | 出现次数 | 值表达式样本（最多3个）| 建议属性名 | 建议属性编码 | 审核批注 | 处理状态 | 回填：实际属性名 | 回填：属性编码 | 回填：值域
- **FR-006**: 工具 MUST 同时导出 JSON 版本 `feature_audit_export.json`
- **FR-007**: 工具 MUST 保存审核进度到 `feature_audit_progress.json`，支持断点续审
- **FR-008**: 工具 SHOULD 支持导入回填 Excel，展示差异并生成 `components_patch.json`
- **FR-009**: 工具 SHOULD 支持在线编辑 `feature_expression_items` 的属性绑定
- **FR-010**: 工具 MUST 统计并展示仪表盘：总特征数、已匹配数、未匹配数、已处理数、待补充数、需沉淀数
- **FR-011**: 工具 MUST 对已匹配特征（`matched=true`）显示其绑定的 `attribute_name` 和 `attribute_code`，绿色样式区分
- **FR-012**: 工具 MUST 加载 `component_source_table.json`，在选中构件时展示该构件的完整属性列表（名称、编码、数据类型、可选值）
- **FR-013**: 工具 SHOULD 支持手动新增特征条目，标记 `source: "manual_add"`，支持从属性库下拉绑定
- **FR-014**: 工具 MUST 支持导出 `wiki_patch.json`（格式兼容 `wiki_patch_import.py`），仅包含标记为"匹配失败-需沉淀"的条目
- **FR-015**: 工具 SHOULD 对同一 `label` 既有匹配成功又有匹配失败的条目自动标注"间歇性失败"标记，提示审核人员重点关注

### Non-Functional Requirements

- **NFR-001**: 工具以单 HTML 文件 + 内嵌 JS 实现（与现有 `step3_review_editor.py` 一致），无需后端服务
- **NFR-002**: 加载 1000+ 行结果应在 3 秒内完成渲染
- **NFR-003**: 导出 Excel 使用 SheetJS (xlsx) 库，纯前端生成
- **NFR-004**: 所有数据操作在浏览器端完成，不上传任何数据
- **NFR-005**: 兼容 Chrome 90+ / Safari 15+ / Edge 90+

### Key Entities

- **FeatureAuditItem**: 单条特征审核条目（来自 `feature_expression_items`，含已匹配和未匹配）
  - `label`: 特征标签
  - `raw_text`: 原始文本
  - `value_expression`: 值表达式
  - `matched`: 匹配状态（true/false）
  - `attribute_name`: 目标属性名（已匹配时有值，未匹配时初始为空）
  - `attribute_code`: 目标属性编码
  - `source_component`: 所属构件类型
  - `source_row_id`: 来源清单行 ID
  - `audit_status`: 处理状态（待补充/无需补充/待确认/匹配失败-需沉淀）
  - `audit_note`: 审核批注
  - `occurrence_count`: 出现次数（同标签合并统计）
  - `source`: 来源标记（`step3_result` / `manual_add`）
  - `intermittent_failure`: 是否为间歇性匹配失败（同 label 部分匹配部分不匹配）

- **ComponentAttributeRef**: 构件属性参考（来自 `component_source_table.json`）
  - `component_name`: 构件类型名
  - `attributes[]`: 属性列表
    - `name`: 属性名
    - `code`: 属性编码
    - `data_type`: 数据类型
    - `values[]`: 可选值列表
    - `source_sheet`: 来源表

- **WikiKnowledgePatch**: Wiki 知识补丁（导出给 `wiki_patch_import.py`）
  - `meta.source`: "step5_feature_audit"
  - `meta.exported_at`: ISO 时间戳
  - `meta.purpose`: "wiki_knowledge_patch"
  - `components`: `{[构件名]: [{project_code, project_name, match_status, feature_expression_items, notes, reviewed}]}`

- **AuditExportSheet**: 导出 Excel 的单个 sheet
  - `component_type`: 构件类型名
  - `items[]`: FeatureGapItem 列表（按出现次数降序）
  - `summary`: 该构件的缺口统计

- **ComponentsPatch**: 属性库增量补丁
  - `component_type`: 构件类型
  - `added_attributes[]`: 新增属性（name, code, data_type, values）
  - `source`: "feature_audit_backfill"
  - `audit_date`: 审核日期

---

## 数据流设计

```
Step3 结果 JSON ──────────────────────────→ ┌─────────────────────────┐
                                            │  项目特征审核导出工具    │
构件属性库 components.json ──────────────→  │                         │
                                            │  1. 加载 & 解析          │
构件来源表 component_source_table.json ──→  │  2. 筛选 & 展示          │
                                            │     (全部特征+属性参考)  │
                                            │  3. 选择 & 批注          │
                                            │  4. 导出 Excel/JSON      │
                                            │  5. 导出 Wiki 补丁       │
                                            │  6. 导入回填 & 生成 patch│
                                            └──────┬──────────────────┘
                                                   │
                         ┌──────────────┬──────────┼────────────┬──────────────┐
                         ▼              ▼          ▼            ▼              ▼
               feature_audit_  feature_audit_  wiki_patch.  components_  feature_audit_
               export.xlsx     progress.json   json         patch.json   export.json
               (给下游更新)    (断点续审)      (→wiki导入)  (回写属性库)  (程序化版本)
```

---

## 输入输出文件清单

### 输入

| 文件 | 路径 | 说明 |
|------|------|------|
| Step3 匹配结果 | `data/output/step3/run-*/project_component_feature_calc_matching_result.json` | 主数据源 |
| 构件属性库 | `data/input/components.json` | 用于属性下拉和绑定 |
| 构件来源表 | `data/output/step3/run-*/component_source_table.json` | 构件名称映射 |
| 回填 Excel（可选） | 用户上传 | 下游回填后的补充清单 |

### 输出

| 文件 | 格式 | 说明 |
|------|------|------|
| `feature_audit_export.xlsx` | Excel | 按构件类型分 sheet 的待补充清单，含回填列 |
| `feature_audit_export.json` | JSON | 同上的程序化版本 |
| `feature_audit_progress.json` | JSON | 审核进度快照（可恢复） |
| `wiki_patch.json` | JSON | Wiki 知识补丁（兼容 `wiki_patch_import.py`，含匹配失败知识） |
| `components_patch.json` | JSON | 属性库增量补丁（回写用） |

---

## 产品审核工作流

```
产品审计人员                        下游特征维护团队                  系统
    │                                    │                           │
    ├─── 1. 打开工具，加载 Step3 结果 ──→│                           │
    │                                    │                           │
    ├─── 2. 查看全部特征（已匹配+未匹配），│                          │
    │       参考构件属性库 ─────────────→│                           │
    │                                    │                           │
    ├─── 3. 标记缺失特征：               │                           │
    │       "待补充" / "匹配失败-需沉淀" │                           │
    │       / "无需补充" / 手动新增 ────→│                           │
    │                                    │                           │
    ├─── 4a. 导出 Excel ────────────────→├─── 6. 填写回填列 ──────→│
    │                                    │     （属性名/编码/值域）   │
    ├─── 4b. 导出 Wiki 补丁 ───────────→│                           │
    │                                    │            ┌──── wiki_patch_import.py
    │                                    │            ▼
    │                                    │     知识库中心/wiki/构件类型/
    │                                    │                           │
    │←── 7. 收到回填 Excel ─────────────┤                           │
    │                                    │                           │
    ├─── 8. 导入回填文件，审核差异 ────→│                           │
    │                                    │                           │
    ├─── 9. 确认后生成 patch ───────────→├───────────────────────────├─ 10. merge 到 components.json
    │                                    │                           │
    └─── 11. 重跑 Step3，验证缺口收敛 ─→│                           │
```
