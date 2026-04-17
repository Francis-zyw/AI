# Data Model: 项目特征审核导出工具

**Phase 1 Output** | **Date**: 2026-04-17

## Core Entities

### FeatureItem

从 Step3 结果提取的单条特征记录（聚合后）。

| Field | Type | Description | Source |
|-------|------|-------------|--------|
| `item_key` | string | 唯一键 `{source_component}\|{label}` | computed |
| `label` | string | 特征标签（如"规格""砼标号"） | `feature_expression_items[].label` |
| `source_component` | string | 构件类型名称 | `source_component_name` / `resolved_component_name` |
| `matched` | boolean | 是否匹配到属性 | `feature_expression_items[].matched` |
| `occurrence_count` | number | 出现次数 | computed (count) |
| `value_samples` | string[] | 值表达式样本（最多 3 个不重复） | `feature_expression_items[].value_expression` |
| `source_row_ids` | string[] | 来源行 ID 列表 | `rows[].row_id` |
| `attribute_name` | string \| null | 匹配到的属性名（matched=true 时有值） | `feature_expression_items[].attribute_name` |
| `attribute_code` | string \| null | 匹配到的属性编码 | `feature_expression_items[].attribute_code` |
| `intermittent` | boolean | 间歇性失败标记（同 label 部分匹配部分不匹配） | computed |

**Validation rules**:
- `item_key` must be unique across all items
- `label` cannot be empty
- `occurrence_count` >= 1
- `value_samples` max length 3

### AuditProgress

审核人员对单条 FeatureItem 的审核记录。

| Field | Type | Description |
|-------|------|-------------|
| `item_key` | string | 关联 FeatureItem.item_key |
| `status` | enum | `'pending'` \| `'to_fill'` \| `'no_need'` \| `'to_confirm'` \| `'to_sediment'` |
| `note` | string | 审核批注 |
| `updated_at` | string | ISO 8601 时间戳 |

**Status transitions**:
```
pending → to_fill      (需补充到属性库)
pending → no_need      (无需补充，非标准属性)
pending → to_confirm   (需进一步确认)
pending → to_sediment  (需沉淀到知识库 wiki)
to_fill → to_confirm   (回退到待确认)
to_confirm → to_fill   (确认后改为需补充)
* → pending            (重置)
```

### ComponentAttributeRef

构件属性参考数据（从 `component_source_table.json` 加载）。

| Field | Type | Description |
|-------|------|-------------|
| `component_type` | string | 构件类型名称 |
| `attributes` | AttributeRef[] | 该构件的全部属性列表 |

### AttributeRef

单条属性参考。

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | 属性名称 |
| `code` | string | 属性编码 |
| `value_type` | string | 值类型（text / number / enum） |
| `value_domain` | string \| null | 值域描述 |

### WikiKnowledgePatch

导出的知识库补丁条目（兼容 `wiki_patch_import.py`）。

| Field | Type | Description |
|-------|------|-------------|
| `component_type` | string | 构件类型 |
| `attribute_name` | string | 属性名称 |
| `attribute_code` | string | 属性编码 |
| `value_pattern` | string | 值表达式模式 |
| `source` | string | 固定值 `"step5-audit"` |
| `action` | enum | `"add"` \| `"update"` |

### AuditExportSheet

Excel 导出的单个 Sheet 结构。

| Column | Header | Source |
|--------|--------|--------|
| A | 特征标签 | `FeatureItem.label` |
| B | 出现次数 | `FeatureItem.occurrence_count` |
| C | 值样本1 | `FeatureItem.value_samples[0]` |
| D | 值样本2 | `FeatureItem.value_samples[1]` |
| E | 值样本3 | `FeatureItem.value_samples[2]` |
| F | 建议属性名 | `FeatureItem.attribute_name` |
| G | 建议属性编码 | `FeatureItem.attribute_code` |
| H | 审核批注 | `AuditProgress.note` |
| I | 处理状态 | `AuditProgress.status` |
| J | 🔽回填：实际属性名 | (空，下游填写) |
| K | 🔽回填：属性编码 | (空，下游填写) |
| L | 🔽回填：值域 | (空，下游填写) |

**Sheet 组织**: 每个 `source_component` 一个 Sheet + 第一个"总览" Sheet。

### ComponentsPatch (Phase 2)

Excel 回填后生成的属性库增量补丁。

| Field | Type | Description |
|-------|------|-------------|
| `component_type` | string | 构件类型 |
| `additions` | PatchEntry[] | 新增属性列表 |

### PatchEntry

| Field | Type | Description |
|-------|------|-------------|
| `attribute_name` | string | J 列回填值 |
| `attribute_code` | string | K 列回填值 |
| `value_domain` | string \| null | L 列回填值 |
| `original_label` | string | 原始特征标签 |

## Entity Relationships

```
FeatureItem ──1:0..1──▶ AuditProgress        (by item_key)
FeatureItem ──N:1──────▶ ComponentAttributeRef (by source_component)
AuditProgress ──1:0..1──▶ WikiKnowledgePatch  (status='to_sediment' → export)
AuditProgress ──1:0..1──▶ AuditExportSheet    (status='to_fill' → export)
AuditExportSheet ──▶ ComponentsPatch           (Phase 2: J/K/L 回填)
```

## Data Flow

```
Step3 JSON ─────────────────┐
                            ▼
components.json ──▶ step5_feature_audit.py ──▶ feature_audit_tool.html
                            ▲                         │
component_source_table.json─┘                         ▼
                                              ┌── Excel 导出 (.xlsx)
                                              ├── JSON 导出 (.json)
                                              ├── Wiki 补丁 (wiki_patch.json)
                                              ├── 审核进度 (localStorage + .json)
                                              └── 属性补丁 (components_patch.json) [P2]
```
