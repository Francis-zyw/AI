# Tasks: 项目特征审核导出工具

**Created**: 2026-04-16  
**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

---

## Phase 1: 核心审核与导出 (P1)

> 覆盖 US1（查看筛选）+ US2（批量选择标记）+ US3（导出文档）
> 交付物：`pipeline_v2/step5_feature_audit.py` + 生成的 HTML 工具

### T001 — Python 生成器骨架

- [x] 创建 `pipeline_v2/step5_feature_audit.py`
- [x] 实现 CLI 入口（argparse：`--step3-result`, `--components`, `--output`）
- [x] 实现 `load_step3_results(path)` 加载 Step3 JSON
- [x] 实现 `load_components_library(path)` 加载 components.json
- [x] 创建 `data/output/step5/` 输出目录
- [x] 验证：运行 CLI 无报错，打印加载的行数和构件数

**文件**：`pipeline_v2/step5_feature_audit.py`  
**依赖**：无  
**验收**：`python pipeline_v2/step5_feature_audit.py --step3-result data/output/step3/run-20260416-full/project_component_feature_calc_matching_result.json --components data/input/components.json` 输出加载统计

---

### T002 — 数据预处理：提取与聚合

- [x] 实现 `extract_gap_items(rows)` — 遍历所有行的 `feature_expression_items`，提取 `matched=false` 条目
- [x] 实现 `aggregate_by_component(items)` — 按 `source_component|label` 合并，计算 `occurrence_count`，收集 `value_samples`（最多3个）
- [x] 实现 `aggregate_by_label(items)` — 按 label 跨构件聚合统计
- [x] 实现 `build_stats(aggregated)` — 生成仪表盘数据（总缺口数、涉及构件数、top标签等）
- [x] 验证：打印聚合后条目数 vs 原始条目数（应减少 90%+）

**文件**：`pipeline_v2/step5_feature_audit.py`  
**依赖**：T001  
**验收**：聚合后条目数 < 原始未匹配条目总数的 20%

---

### T003 — HTML 模板骨架 + 数据注入

- [x] 实现 `build_audit_html(gap_data, comp_ref, stats)` — 拼接完整 HTML 字符串
- [x] HTML `<head>`：meta charset、viewport、内嵌 CSS 变量、SheetJS CDN script
- [x] JSON 数据注入：`<script>const GAP_DATA = {...}; const COMP_REF = {...}; const STATS = {...};</script>`
- [x] HTML 转义：复用 `_esc()` 辅助函数
- [x] 验证：生成 HTML 可在浏览器打开，控制台无 JS 错误

**文件**：`pipeline_v2/step5_feature_audit.py`  
**依赖**：T002  
**验收**：`open data/output/step5/feature_audit_tool.html` 浏览器打开正常

---

### T004 — 前端：CSS 基础样式 + 三栏布局

- [x] CSS Grid 三栏布局：顶部仪表盘（full-width）+ 左侧栏（240px）+ 主内容区
- [x] 配色方案：与现有 step3 工具保持一致（白底、蓝色主色调、红/绿状态色）
- [x] 响应式：窄屏左侧栏折叠为顶部标签栏
- [x] 卡片样式：`.gap-card`（圆角、阴影、hover 高亮）
- [x] 状态标记样式：`.status-pending`(灰)、`.status-to-fill`(橙)、`.status-no-need`(绿)、`.status-to-confirm`(蓝)

**文件**：`pipeline_v2/step5_feature_audit.py`（内嵌 CSS）  
**依赖**：T003  
**验收**：布局三栏正确，各状态颜色可区分

---

### T005 — 前端：Dashboard 仪表盘

- [x] 4 个统计卡片：总缺口数 | 待补充 | 无需补充 | 待确认
- [x] 进度条：已处理 / 总缺口
- [x] 卡片点击可快速筛选对应状态
- [x] 从 `STATS` 初始化，审核操作时实时更新

**文件**：`pipeline_v2/step5_feature_audit.py`（内嵌 JS）  
**依赖**：T004  
**验收**：仪表盘数字与实际数据一致，点击卡片触发筛选

---

### T006 — 前端：ComponentTree 左侧构件列表

- [x] 渲染所有构件类型，显示缺口数 badge（如"砖墙 (205)"）
- [x] 按缺口数降序排列
- [x] 点击构件切换主内容区筛选
- [x] "全部"选项显示跨构件汇总
- [x] 当前选中构件高亮

**文件**：`pipeline_v2/step5_feature_audit.py`（内嵌 JS）  
**依赖**：T004  
**验收**：点击"砖墙"→主内容区仅显示砖墙缺失特征

---

### T007 — 前端：FilterBar 筛选 + GapItemList 列表

- [x] 搜索框：模糊匹配 label、raw_text、value_expression
- [x] 状态筛选下拉：全部 | 未处理 | 待补充 | 无需补充 | 待确认
- [x] 标签筛选下拉：Top 30 高频标签 + "其他"
- [x] `applyFilters()` 联动三个筛选条件 + ComponentTree 选中
- [x] GapItemList 渲染筛选后条目，显示匹配计数
- [x] 虚拟滚动：仅渲染可见区域 ± 20 条 buffer（VirtualScroller 类，~80行 JS）

**文件**：`pipeline_v2/step5_feature_audit.py`（内嵌 JS）  
**依赖**：T005, T006  
**验收**：搜索"混凝土"→跨构件显示含该关键词的条目；列表 2000+ 条无卡顿

---

### T008 — 前端：GapItemCard 选择/批注/状态

- [x] 每条卡片包含：checkbox + 特征标签（粗体）+ 出现次数 badge + 值样本（灰色小字，最多3个）
- [x] 状态选择下拉：未处理 → 待补充 / 无需补充 / 待确认
- [x] 批注输入框（单行，blur 时自动保存到 STATE）
- [x] 关联清单行展开（点击"查看来源"→弹出该标签在哪些 row_id 出现）
- [x] `updateAuditStatus(itemKey, status, note)` 同步更新 STATE + Dashboard 统计
- [x] 状态变更时自动 localStorage 保存

**文件**：`pipeline_v2/step5_feature_audit.py`（内嵌 JS）  
**依赖**：T007  
**验收**：修改状态→Dashboard 数字实时变化；刷新页面→状态保留（localStorage）

---

### T009 — 前端：ActionBar 批量操作

- [x] 全选/反选当前筛选结果
- [x] 批量设置状态（对所有已勾选条目）
- [x] 选中计数实时显示："已选 23 / 共 156 条"
- [x] "保存审核进度"按钮：导出 `feature_audit_progress.json`
- [x] "恢复审核进度"按钮：上传 JSON 文件恢复

**文件**：`pipeline_v2/step5_feature_audit.py`（内嵌 JS）  
**依赖**：T008  
**验收**：全选→批量标记"待补充"→Dashboard 更新→导出 JSON→重新打开→上传恢复→状态一致

---

### T010 — 前端：Excel 导出 + JSON 导出

- [x] 引入 SheetJS CDN（`xlsx.full.min.js`）
- [x] "导出 Excel"按钮：收集 `status='待补充'` 的条目
- [x] 按 `source_component` 分组，每组一个 sheet
- [x] Sheet 格式：行1=表头说明，行2=列标题（A-L 12列），行3+=数据行
- [x] 添加"总览" sheet：按构件汇总统计表
- [x] 列宽自适应
- [x] J/K/L 列（回填列）设置黄色背景标记
- [x] `XLSX.writeFile()` 下载为 `feature_audit_export.xlsx`
- [x] 同步生成 `feature_audit_export.json` 下载
- [x] 导出计数更新到 Dashboard

**文件**：`pipeline_v2/step5_feature_audit.py`（内嵌 JS）  
**依赖**：T009  
**验收**：导出 Excel 可在 WPS/Excel 打开，多 sheet 正确，回填列有黄色标记

---

### T011 — 集成测试：真实数据验证

- [ ] 用 `run-20260416-full` 的真实数据运行完整流程
- [ ] 验证 Python 生成器输出 HTML 大小合理（< 5MB）
- [ ] 验证浏览器加载 < 3 秒（894 行数据）
- [ ] 验证筛选/选择/批注/导出全流程可走通
- [ ] 验证 Excel 导出格式正确（打开不报错，列对齐，中文无乱码）
- [ ] 验证 localStorage 进度保存/恢复正常
- [ ] 记录发现的问题并修复

**文件**：无新文件  
**依赖**：T001-T010  
**验收**：全流程可走通，无阻塞性问题

---

## Phase 2: 回填闭环与在线编辑 (P2)

> 覆盖 US4（回填导入）+ US5（在线编辑）
> 交付物：Phase 1 HTML 工具的功能扩展

### T012 — 前端：Excel 回填导入

- [ ] "导入回填"按钮：文件选择器，仅接受 `.xlsx`
- [ ] SheetJS `XLSX.read()` 解析上传文件
- [ ] 遍历每个 sheet（按 sheet 名匹配构件类型）
- [ ] 读取 J/K/L 列（回填：实际属性名、属性编码、值域）
- [ ] 列名校验：缺少必要列时提示具体错误
- [ ] 与原始导出数据比对：非空回填 = 有效条目

**文件**：`pipeline_v2/step5_feature_audit.py`（内嵌 JS 扩展）  
**依赖**：T010  
**验收**：上传回填 Excel 后解析无报错，识别出有回填的条目数

---

### T013 — 前端：ImportDialog 差异展示

- [ ] 模态对话框展示差异列表
- [ ] 每条显示：构件类型 | 特征标签 | 原建议属性名 → 回填属性名 | 回填编码 | 回填值域
- [ ] 差异类型标记：🆕 新增 | ✏️ 修改 | ⏭️ 忽略（回填为空）
- [ ] 每条有 checkbox 可取消选择
- [ ] "确认接受"按钮

**文件**：`pipeline_v2/step5_feature_audit.py`（内嵌 JS 扩展）  
**依赖**：T012  
**验收**：差异列表正确区分新增/修改/忽略

---

### T014 — 生成 components_patch.json

- [ ] 从确认的差异条目生成 patch JSON
- [ ] 格式：`{ patches: [{ component_type, added_attributes: [{ name, code, data_type, values }], source, audit_date }] }`
- [ ] 下载为 `components_patch.json`
- [ ] 可选：提供 "一键合并到 components.json" 功能预览（显示合并后的 diff）

**文件**：`pipeline_v2/step5_feature_audit.py`（内嵌 JS 扩展）  
**依赖**：T013  
**验收**：生成的 JSON 格式与 `components.json` 的 attributes 结构兼容

---

### T015 — 前端：EditModal 属性绑定编辑

- [ ] 点击某条缺失特征的"编辑"按钮 → 弹出 EditModal
- [ ] 表单字段：label（只读展示）、attribute_name（下拉 + 自由输入）、attribute_code（联动自动填充）、value_expression（可编辑）
- [ ] 属性下拉从 `COMP_REF` 中加载该构件的所有属性
- [ ] 保存后：`matched` 标记为 true、卡片样式变绿
- [ ] 编辑结果保存到 STATE，可通过"保存进度"导出

**文件**：`pipeline_v2/step5_feature_audit.py`（内嵌 JS 扩展）  
**依赖**：T008  
**验收**：编辑属性绑定后 matched 状态更新，Dashboard 缺口数减少

---

### T016 — 前端：批量属性绑定

- [ ] 勾选多条同标签特征 → "批量绑定"按钮可用
- [ ] 弹出简化 EditModal：选择 attribute_name → 所有已勾选条目统一绑定
- [ ] 绑定完成后所有条目 matched=true，统计更新

**文件**：`pipeline_v2/step5_feature_audit.py`（内嵌 JS 扩展）  
**依赖**：T015  
**验收**：勾选 10 条同标签→批量绑定→10 条全部变绿

---

### T017 — Python 脚本：patch 合并到 components.json

- [ ] 创建 `pipeline_v2/step5_apply_patch.py`
- [ ] CLI：`--patch components_patch.json --components data/input/components.json --output data/input/components_patched.json`
- [ ] 逻辑：遍历 patch，找到对应构件类型，追加 `added_attributes` 到 `attributes[]`
- [ ] 去重：如果 attribute_code 已存在则跳过并警告
- [ ] 不直接覆盖原文件，输出到 `_patched.json`，由用户决定是否替换

**文件**：`pipeline_v2/step5_apply_patch.py`（新建）  
**依赖**：T014  
**验收**：合并后 components_patched.json 格式正确，新增属性可在构件属性库中找到

---

## 任务依赖关系

```
T001 ──→ T002 ──→ T003 ──→ T004 ──→ T005 ──┐
                                              ├──→ T007 ──→ T008 ──→ T009 ──→ T010 ──→ T011
                                    T006 ────┘                                   │
                                                                                 ├──→ T012 ──→ T013 ──→ T014 ──→ T017
                                                                                 └──→ T015 ──→ T016
```

- T001-T004：顺序依赖（Python 骨架 → 数据 → HTML → CSS）
- T005 + T006：可并行（Dashboard 和 ComponentTree 互不依赖）
- T007：依赖 T005 + T006（筛选需要两者的交互）
- T008-T010：顺序依赖（卡片 → 批量操作 → 导出）
- T011：Phase 1 集成测试
- T012-T014：Phase 2 回填链路（顺序）
- T015-T016：Phase 2 编辑链路（可与 T012-T014 并行）
- T017：依赖 T014（需要 patch JSON）

---

## 完成标准

### Phase 1 完成标准
- [x] T001-T010 全部完成
- [ ] T011 集成测试通过
- [ ] 产品审计人员可独立完成：加载 → 筛选 → 标记 → 导出 Excel 全流程
- [ ] Excel 可被下游团队正常打开并理解

### Phase 2 完成标准
- [ ] T012-T017 全部完成
- [ ] 回填闭环可走通：导出 → 下游填写 → 导入 → 审核差异 → 生成 patch
- [ ] patch 可正确合并到 components.json
- [ ] 重跑 Step3 后缺口数有明显下降
