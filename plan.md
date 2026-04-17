# Implementation Plan: 项目特征审核导出工具

**Created**: 2026-04-16  
**Status**: Draft  
**Spec Reference**: [spec.md](spec.md)

---

## 技术栈

| 层 | 技术 | 理由 |
|----|------|------|
| 生成器 | Python 3.11+（`step5_feature_audit.py`） | 与现有 pipeline_v2 一致，复用 JSON 加载/HTML 模板拼接模式 |
| 前端 | 单 HTML + 内嵌 CSS/JS（零框架） | 与 `step3_review_editor.py` / `step3_component_analysis.py` 一致，无需构建工具 |
| Excel 导出 | SheetJS CDN（`xlsx.full.min.js`） | 纯前端，无需 Python 依赖，支持多 sheet |
| Excel 导入 | SheetJS `XLSX.read()` | 同一库，前端解析回填 Excel |
| 数据持久化 | `localStorage` + JSON 文件下载/上传 | 无后端，审核进度存浏览器 + 可导出恢复文件 |

---

## 模块划分

### Module 1: Python 生成器 — `pipeline_v2/step5_feature_audit.py`

**职责**：读取 Step3 结果 + 构件属性库，预处理数据，输出单 HTML 文件。

```
step5_feature_audit.py
├── load_step3_results(path)          # 加载 Step3 JSON
├── load_components_library(path)     # 加载 components.json
├── extract_gap_items(rows)           # 提取 matched=false 的 FeatureGapItem
├── aggregate_by_component(items)     # 按构件类型聚合 + 统计
├── aggregate_by_label(items)         # 按特征标签聚合（跨构件）
├── build_audit_html(gap_data, comp_ref) # 拼接完整 HTML
└── main()                            # CLI 入口
```

**复用策略**：
- 参照 `step3_review_editor.py` 的 `build_review_editor()` 函数结构
- 参照 `step3_component_analysis.py` 的 `_build_component_data()` 聚合逻辑
- `_esc()` HTML 转义辅助函数直接复用

**CLI 接口**：
```bash
python pipeline_v2/step5_feature_audit.py \
  --step3-result data/output/step3/run-20260416-full/project_component_feature_calc_matching_result.json \
  --components data/input/components.json \
  --output data/output/step5/feature_audit_tool.html
```

### Module 2: 前端 — 数据加载与状态管理层（JS）

**职责**：管理 gap items 数据、审核状态、筛选索引。

```javascript
// 核心数据结构
const STATE = {
  gapItems: [],           // FeatureGapItem[] — 所有 matched=false 条目
  byComponent: {},        // { 构件名: FeatureGapItem[] }
  byLabel: {},            // { 标签名: FeatureGapItem[] }
  auditProgress: {},      // { itemKey: { status, note } }
  componentsRef: [],      // 构件属性库（用于下拉绑定）
  filters: {              // 当前筛选条件
    component: '',
    label: '',
    status: 'all',
    search: ''
  },
  stats: {                // 仪表盘统计
    totalGaps: 0,
    pending: 0,
    toFill: 0,
    noNeed: 0,
    toConfirm: 0,
    exported: 0
  }
};
```

**关键函数**：
- `initData(rawRows, componentsRef)` — 从 Python 注入的 JSON 构建 STATE
- `applyFilters()` — 多维筛选后刷新列表
- `updateAuditStatus(itemKey, status, note)` — 更新单条审核状态
- `batchUpdateStatus(itemKeys, status)` — 批量标记
- `saveProgress()` — 序列化到 localStorage + 触发 JSON 下载
- `loadProgress(json)` — 从文件恢复审核进度

### Module 3: 前端 — 视图渲染层（JS + CSS）

**职责**：三栏布局的 UI 渲染。

```
┌──────────────────────────────────────────────────────────┐
│  仪表盘（顶部）：总缺口 | 待补充 | 无需补充 | 待确认     │
├──────────┬───────────────────────────────────────────────┤
│  左侧栏   │  主内容区                                     │
│  构件列表  │  ┌─ 搜索/筛选栏 ──────────────────────────┐ │
│  (树形)   │  │ [搜索框] [状态筛选] [标签筛选]           │ │
│           │  ├──────────────────────────────────────────┤ │
│  砖墙 (51)│  │  ☐ 规格 (191次)  "300×200×…" "C30…"    │ │
│  主肋梁(23)│  │    批注: [______]  状态: [待补充 ▼]      │ │
│  ...      │  │  ☐ 防护材料种类 (126次) "防水涂…"       │ │
│           │  │    批注: [______]  状态: [待确认 ▼]      │ │
│           │  │  ...                                     │ │
│           │  ├──────────────────────────────────────────┤ │
│           │  │ [全选] [反选] [导出Excel] [保存进度]     │ │
└──────────┴──┴──────────────────────────────────────────┘ │
```

**组件清单**：
1. **Dashboard** — 4 个统计卡片 + 进度条
2. **ComponentTree** — 左侧构件列表（显示缺口数），点击切换
3. **FilterBar** — 搜索框 + 状态下拉 + 标签下拉
4. **GapItemList** — 缺失特征卡片列表（虚拟滚动，1000+条不卡顿）
5. **GapItemCard** — 单条特征：checkbox + 标签 + 值样本 + 批注输入 + 状态选择
6. **ActionBar** — 底部操作栏：全选/反选/导出/保存/导入回填
7. **ExportDialog** — 导出预览对话框
8. **ImportDialog** — 回填导入 + 差异展示
9. **EditModal** — 单条/批量属性绑定编辑（P2）

### Module 4: 前端 — Excel 导出/导入层（JS）

**职责**：SheetJS 操作。

**导出流程**：
```
1. 收集 STATUS.auditProgress 中 status='待补充' 的条目
2. 按 source_component 分组
3. 每组生成一个 sheet：
   - 行1: 表头说明（构件类型 + 缺口统计）
   - 行2: 列标题
   - 行3+: 数据行
   - 最后3列为空白回填列（实际属性名 | 属性编码 | 值域）
4. 添加一个"总览"sheet（按构件汇总统计）
5. XLSX.writeFile() 下载
6. 同时生成 feature_audit_export.json 下载
```

**导出 Excel 列定义**：

| 列号 | 列名 | 来源 |
|------|------|------|
| A | 特征标签 | `label` |
| B | 出现次数 | `occurrence_count` |
| C | 值表达式样本1 | `value_samples[0]` |
| D | 值表达式样本2 | `value_samples[1]` |
| E | 值表达式样本3 | `value_samples[2]` |
| F | 建议属性名 | `suggested_attribute_name`（可能为空） |
| G | 建议属性编码 | `suggested_attribute_code`（可能为空） |
| H | 审核批注 | `audit_note` |
| I | 处理状态 | `audit_status` |
| J | 🔽回填：实际属性名 | （空，下游填写） |
| K | 🔽回填：属性编码 | （空，下游填写） |
| L | 🔽回填：值域 | （空，下游填写） |

**导入回填流程**（P2）：
```
1. 用户上传回填 Excel
2. XLSX.read() 解析
3. 遍历每个 sheet（构件类型），读取 J/K/L 列
4. 与原始导出数据比对：
   - J/K/L 非空 = 有回填
   - 与原始 F/G 不同 = 有修改
5. 展示差异列表（新增 / 修改 / 忽略）
6. 用户确认后生成 components_patch.json
```

---

## 实现分阶段

### Phase 1 (P1): 核心审核与导出 — US1 + US2 + US3

**交付物**：`step5_feature_audit.py` + 生成的 HTML 工具

| 步骤 | 内容 | 预估复杂度 |
|------|------|-----------|
| 1.1 | Python 生成器骨架（CLI + JSON 加载 + HTML 模板） | 低 |
| 1.2 | 数据预处理：extract_gap_items + 聚合统计 | 低 |
| 1.3 | 前端：Dashboard 仪表盘 | 低 |
| 1.4 | 前端：ComponentTree 构件列表 | 中 |
| 1.5 | 前端：FilterBar 筛选 + GapItemList 列表渲染 | 中 |
| 1.6 | 前端：GapItemCard 选择/批注/状态 | 中 |
| 1.7 | 前端：审核进度保存/恢复（localStorage + JSON） | 低 |
| 1.8 | 前端：Excel 导出（SheetJS 多 sheet） | 中 |
| 1.9 | 前端：JSON 导出 | 低 |
| 1.10 | 集成测试：加载真实数据验证 | 低 |

### Phase 2 (P2): 回填闭环与在线编辑 — US4 + US5

| 步骤 | 内容 | 预估复杂度 |
|------|------|-----------|
| 2.1 | Excel 导入 + 解析回填列 | 中 |
| 2.2 | 差异展示 UI（ImportDialog） | 中 |
| 2.3 | 生成 components_patch.json | 低 |
| 2.4 | EditModal 属性绑定编辑 | 中 |
| 2.5 | 批量绑定功能 | 中 |
| 2.6 | patch 合并脚本（components_patch → components.json） | 低 |

---

## 文件结构

```
pipeline_v2/
├── step5_feature_audit.py          # Python 生成器（新建）
├── step5_engine/                   # 如有复杂逻辑可拆子模块
│   └── (暂不需要，先全放 step5)
├── step3_review_editor.py          # 现有，不修改
├── step3_component_analysis.py     # 现有，不修改
└── step1_gap_analyzer.py           # 现有，不修改

data/output/step5/                  # 输出目录（新建）
├── feature_audit_tool.html         # 生成的工具 HTML
├── feature_audit_export.xlsx       # 导出的 Excel（运行时产物）
├── feature_audit_export.json       # 导出的 JSON（运行时产物）
├── feature_audit_progress.json     # 审核进度（运行时产物）
└── components_patch.json           # 属性库增量补丁（Phase 2）
```

---

## 关键技术决策

### D1: 单 HTML vs 前后端分离

**决策**：单 HTML 文件（Python 生成）

**理由**：
- 与现有 `step3_review_editor.py` 和 `step3_component_analysis.py` 完全一致
- 产品审计人员只需双击打开 HTML，无需启动服务
- 数据量（~1000行，~5000 gap items）在浏览器端处理无性能问题
- 数据安全：不上传任何数据

### D2: 数据注入方式

**决策**：Python 将 JSON 序列化后嵌入 `<script>` 标签

```python
# step5_feature_audit.py
gap_json = json.dumps(gap_data, ensure_ascii=False)
comp_json = json.dumps(comp_ref, ensure_ascii=False)
html = f"""
<script>
const GAP_DATA = {gap_json};
const COMP_REF = {comp_json};
</script>
"""
```

**理由**：参照 `step3_review_editor.py` 现有模式，`bill_json` 和 `comp_ref_json` 同样内嵌。

### D3: 虚拟滚动

**决策**：对 GapItemList 实现简易虚拟滚动（仅渲染可见区域 ± buffer）

**理由**：当缺失特征数超过 2000 条时，DOM 节点过多会导致卡顿。实现一个轻量 `VirtualScroller` 类（~80行 JS），参考 `step3_review_editor` 的分页方案但改用滚动。

### D4: FeatureGapItem 唯一键

**决策**：`itemKey = source_component + '|' + label`（合并统计维度）

每个 `itemKey` 对应一个"构件×标签"组合，`occurrence_count` 记录出现次数，`value_samples[]` 保留最多 3 个不重复的值表达式。

**理由**：审核人员关心的是"砖墙缺少'规格'这个属性"而非逐行审核，合并后减少 90%+ 的重复条目。

### D5: Excel 库选型

**决策**：SheetJS CDN（`https://cdn.sheetjs.com/xlsx-0.20.3/package/dist/xlsx.full.min.js`）

**理由**：
- 纯前端，单文件引入
- 支持多 sheet 写入 + 读取
- 广泛使用，兼容性好
- 无需 npm 构建

### D6: 审核进度持久化

**决策**：双重保存 — localStorage 自动保存 + JSON 文件手动导出

```javascript
// 自动保存（每次状态变更时）
localStorage.setItem('feature_audit_' + dataHash, JSON.stringify(STATE.auditProgress));

// 手动导出
function exportProgress() {
  downloadJSON(STATE.auditProgress, 'feature_audit_progress.json');
}

// 恢复（优先 localStorage，其次文件上传）
function loadProgress() {
  const saved = localStorage.getItem('feature_audit_' + dataHash);
  if (saved) return JSON.parse(saved);
  // else: prompt file upload
}
```

**理由**：localStorage 方便频繁保存，JSON 文件支持跨浏览器/跨机器迁移。

---

## 数据处理流程（Python 侧）

```python
def extract_gap_items(rows: List[Dict]) -> List[Dict]:
    """从 Step3 结果提取所有 matched=false 的特征条目"""
    items = []
    for row in rows:
        comp = row.get("source_component_name") or row.get("resolved_component_name") or "(无构件)"
        row_id = row.get("row_id", "")
        project_code = row.get("project_code", "")
        for fi in row.get("feature_expression_items", []):
            if not fi.get("matched", True):
                items.append({
                    "label": fi.get("label", "") or fi.get("raw_text", ""),
                    "raw_text": fi.get("raw_text", ""),
                    "value_expression": fi.get("value_expression", ""),
                    "attribute_name": fi.get("attribute_name", ""),
                    "attribute_code": fi.get("attribute_code", ""),
                    "source_component": comp,
                    "source_row_id": row_id,
                    "source_project_code": project_code,
                })
    return items

def aggregate_by_component(items: List[Dict]) -> Dict[str, Dict]:
    """按 构件×标签 聚合，生成合并后的审核条目"""
    merged = {}  # key: comp|label -> {..., occurrence_count, value_samples}
    for item in items:
        key = f"{item['source_component']}|{item['label']}"
        if key not in merged:
            merged[key] = {
                "item_key": key,
                "label": item["label"],
                "source_component": item["source_component"],
                "occurrence_count": 0,
                "value_samples": [],
                "source_row_ids": [],
                "suggested_attribute_name": "",
                "suggested_attribute_code": "",
            }
        m = merged[key]
        m["occurrence_count"] += 1
        m["source_row_ids"].append(item["source_row_id"])
        v = item["value_expression"]
        if v and v not in m["value_samples"] and len(m["value_samples"]) < 3:
            m["value_samples"].append(v)
    return merged
```

---

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Step3 结果格式变更 | 工具无法加载 | 版本号检查 + 兼容多版本 schema |
| SheetJS CDN 不可用 | 导出失败 | HTML 内嵌 SheetJS（~500KB），或提供本地 fallback |
| 审核进度丢失 | 重复工作 | 双重持久化 + 自动保存间隔 |
| 缺口条目过多（>5000） | UI 卡顿 | 虚拟滚动 + 分页降级 |
| 回填 Excel 被下游篡改格式 | 导入解析失败 | 列名校验 + 容错解析 |

---

## 与现有工具的关系

```
step1_gap_analyzer.py ──→ gap 报告（只读，已有）
                              │
                              ▼
step5_feature_audit.py ──→ 审核导出工具（交互式，本次新建）◄── 复用 gap 分析逻辑
                              │
                              ▼
step3_review_editor.py        │  （并行工具，不互相依赖）
step3_component_analysis.py   │  （并行工具，不互相依赖）
```

- `step5` 可独立运行，不修改任何现有工具
- `step5` 的 Python 数据提取逻辑可考虑从 `step1_gap_analyzer.py` 提取公共函数，但 Phase 1 先独立实现，Phase 2 再重构
