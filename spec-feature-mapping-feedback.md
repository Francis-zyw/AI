# Feature Specification: Step5→Step3 项目特征映射反馈闭环

**Created**: 2026-04-16  
**Status**: Draft  
**Depends On**: `spec.md`（Step5 审核工具已实现）  
**核心目标**: Step5 导出 `feature_mapping.json` 配置文件，Step3 加载后用于提升项目特征匹配率

---

## 背景与问题

### 现状

1. **Step3** 通过 `score_attribute_match()` 将清单行的**项目特征标签**（如"混凝土强度等级"）匹配到构件**属性库**（如 `TBH 砼标号`）
2. 匹配依赖两个硬编码源：
   - `ATTRIBUTE_HINTS`（api.py L66-82）：`{属性编码: [同义词列表]}`，如 `"TBH": ["混凝土强度等级", "砼强度等级", ...]`
   - `score_attribute_match()` 中的字符相似度计算（阈值 0.55）
3. **Step5** 审核工具能发现匹配失败/间歇性失败的特征，但其导出物（Excel、JSON、Wiki 补丁）**都是给人看的报告**，不能被 Step3 程序化消费
4. 清单项的"项目特征"与构件的"项目特征"**本质是同一概念**，但：
   - 清单用"混凝土强度等级"，构件属性库用"砼标号"
   - 清单用"墙体厚度"，构件属性库用"HD"（厚度）
   - 同一特征在不同清单行可能有不同写法（"砼种类" vs "混凝土类型"）
5. 当前 `ATTRIBUTE_HINTS` 是硬编码的静态字典，每次发现新的同义词需要改代码重新部署

### 核心缺口

| # | 缺口 | 影响 |
|---|------|------|
| 1 | Step5 审核结果无法回流到 Step3 | 审完一轮，下次重跑匹配率不变 |
| 2 | `ATTRIBUTE_HINTS` 硬编码，不可配置 | 新同义词需要改代码 |
| 3 | 特征映射无"按构件分级"能力 | "厚度"在墙是 HD，在板是 BH，全局映射有歧义 |
| 4 | 没有"清单特征标签→构件属性"的显式关联配置 | 匹配全靠字符相似度，容易遗漏或误配 |

---

## User Scenarios & Testing

### User Story 1 - Step5 导出特征映射配置 (Priority: P0)

审核人员在 Step5 工具中完成特征审核后，点击**"导出特征映射"**按钮，生成 `feature_mapping.json`。该文件记录所有**已确认的**清单特征标签→构件属性映射关系，包括：
- 已匹配且审核通过的（保持原映射）
- 原未匹配但审核人员手动绑定的（新映射）
- 间歇性失败审核人员确认应匹配的（修复映射）

**Acceptance Scenarios**:

1. **Given** Step5 审核完成，30 条特征被手动绑定属性, **When** 点击"导出特征映射", **Then** 生成 `feature_mapping.json`，含 30 条新映射 + 已有匹配中被确认的映射
2. **Given** 导出的 JSON, **When** 检查内容, **Then** 每条映射含 `source_component`、`label`（清单特征标签）、`attribute_name`、`attribute_code`、`confidence: "human_verified"`
3. **Given** 同一 label 在不同构件下绑定不同属性（如"厚度"→墙 HD，板 BH）, **When** 导出, **Then** 两条映射分别记录在各自的 component scope 下
4. **Given** 审核人员未做任何审核, **When** 点击导出, **Then** 仅导出 Step3 已匹配的映射（作为 baseline 快照）

---

### User Story 2 - Step3 加载特征映射配置 (Priority: P0)

Step3 运行时，如果 `runtime_config.ini` 中配置了 `feature_mapping` 路径，或在输出目录下检测到 `feature_mapping.json`，则加载该文件，将其中的映射规则**注入**到 `score_attribute_match()` 的评分逻辑中。

**Acceptance Scenarios**:

1. **Given** `feature_mapping.json` 存在且配置在 ini 中, **When** Step3 启动, **Then** 加载映射规则，日志输出"已加载特征映射: N 条全局规则, M 条构件级规则"
2. **Given** 映射中有 `砖墙|墙体厚度 → HD`, **When** Step3 处理砖墙的行且特征标签为"墙体厚度", **Then** `score_attribute_match()` 对 HD 属性返回 ≥ 0.99（人工确认级别），高于字符相似度
3. **Given** 映射中有全局规则 `*|混凝土强度等级 → TBH`, **When** 任意构件的行有该特征, **Then** TBH 属性得分 ≥ 0.98
4. **Given** `feature_mapping.json` 不存在, **When** Step3 启动, **Then** 静默跳过，行为与当前完全一致（向后兼容）
5. **Given** 映射文件格式错误, **When** Step3 加载, **Then** 打印警告并跳过，不中断流程

---

### User Story 3 - 映射配置的迭代积累 (Priority: P1)

每次 Step5 导出的 `feature_mapping.json` 可以与**上一轮的映射文件合并**，形成累积效应。多轮审核后映射覆盖率持续提升。

**Acceptance Scenarios**:

1. **Given** 第一轮导出 50 条映射, **When** 第二轮 Step5 加载新 Step3 结果并导出, **Then** 新映射文件包含第一轮 50 条 + 第二轮新增的 N 条（去重合并）
2. **Given** 第一轮映射 `砖墙|厚度→HD`，第二轮审核人员改为 `砖墙|厚度→QH`, **When** 合并, **Then** 以第二轮为准（后覆盖前），记录 `updated_at` 时间戳
3. **Given** Step5 打开时检测到已有 `feature_mapping.json`, **When** 加载, **Then** 在 UI 中标记哪些映射来自上一轮配置，哪些是本轮新增

---

### User Story 4 - 特征映射合并到 ATTRIBUTE_HINTS (Priority: P2)

当积累足够稳定后，可将 `feature_mapping.json` 中高频、跨构件通用的映射条目**提升为 ATTRIBUTE_HINTS 硬编码**（通过脚本辅助），减少运行时依赖。

**Acceptance Scenarios**:

1. **Given** `feature_mapping.json` 中有 15 条全局规则均出现 10+ 次, **When** 运行 `python3 -m pipeline_v2.merge_feature_hints`, **Then** 输出建议新增到 `ATTRIBUTE_HINTS` 的条目列表，含依据统计

---

## `feature_mapping.json` Schema

```jsonc
{
  "meta": {
    "version": "1.0",
    "created_at": "2026-04-16T14:30:00+08:00",
    "updated_at": "2026-04-16T14:30:00+08:00",
    "source": "step5_feature_audit",
    "base_step3_run": "run-20260416-full",
    "total_rules": 120,
    "global_rules": 25,
    "component_rules": 95
  },

  // 全局映射：不区分构件，label → attribute 的通用映射
  "global_rules": [
    {
      "label": "混凝土强度等级",           // 清单中的特征标签（原始写法）
      "label_aliases": ["砼强度等级", "强度等级", "砼标号", "混凝土等级"],  // 同义写法
      "attribute_name": "砼标号",          // 构件属性库中的正式属性名
      "attribute_code": "TBH",            // 属性编码
      "confidence": "human_verified",      // human_verified | auto_matched | inferred
      "occurrence_count": 156,             // 在 Step3 结果中出现的总次数
      "verified_at": "2026-04-16T14:30:00+08:00"
    }
  ],

  // 构件级映射：按构件类型分组，处理"同标签不同属性"的歧义
  "component_rules": {
    "砖墙": [
      {
        "label": "墙体厚度",
        "label_aliases": ["墙厚", "厚度"],
        "attribute_name": "墙厚",
        "attribute_code": "QH",
        "confidence": "human_verified",
        "occurrence_count": 42,
        "verified_at": "2026-04-16T14:30:00+08:00"
      },
      {
        "label": "砌筑砂浆强度等级",
        "label_aliases": ["砂浆等级", "砂浆标号"],
        "attribute_name": "砂浆标号",
        "attribute_code": "SJBH",
        "confidence": "human_verified",
        "occurrence_count": 38,
        "verified_at": "2026-04-16T14:30:00+08:00"
      }
    ],
    "砼墙": [
      {
        "label": "墙体厚度",
        "label_aliases": ["墙厚", "厚度"],
        "attribute_name": "墙厚",
        "attribute_code": "HD",           // 同"墙体厚度"在砼墙中 → HD，砖墙中 → QH
        "confidence": "human_verified",
        "occurrence_count": 28,
        "verified_at": "2026-04-16T14:30:00+08:00"
      }
    ]
  }
}
```

### Schema 字段说明

| 字段 | 类型 | 必须 | 说明 |
|------|------|------|------|
| `meta.version` | string | Y | Schema 版本号，当前 `"1.0"` |
| `meta.created_at` | ISO8601 | Y | 首次创建时间 |
| `meta.updated_at` | ISO8601 | Y | 最后更新时间（合并时更新） |
| `meta.source` | string | Y | 生成来源，固定 `"step5_feature_audit"` |
| `meta.base_step3_run` | string | Y | 基于哪次 Step3 运行结果生成 |
| `global_rules[].label` | string | Y | 清单中的特征标签主写法 |
| `global_rules[].label_aliases` | string[] | N | 标签的其他同义写法 |
| `global_rules[].attribute_name` | string | Y | 目标构件属性名 |
| `global_rules[].attribute_code` | string | Y | 目标构件属性编码 |
| `global_rules[].confidence` | enum | Y | `human_verified` / `auto_matched` / `inferred` |
| `global_rules[].occurrence_count` | int | N | 出现次数（用于评估重要度） |
| `global_rules[].verified_at` | ISO8601 | N | 人工确认时间 |
| `component_rules` | object | Y | key=构件名，value=映射规则数组 |
| `component_rules[*][]` | 同 global_rules 结构 | — | 构件级规则结构与全局一致 |

---

## 数据流设计

```
                    ┌──────────────────────────────────────────────┐
                    │           Step5 审核工具                      │
                    │                                              │
Step3 结果 ────────→│  1. 加载全部特征 (matched + unmatched)        │
                    │  2. 审核人员标记/绑定属性                      │
                    │  3. 导出特征映射                              │
                    │                                              │
                    └──────────┬───────────────────────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ feature_mapping.json  │ ← 新产出物
                    └──────────┬───────────┘
                               │
            ┌──────────────────┼──────────────────┐
            │                  │                  │
            ▼                  ▼                  ▼
  ┌─────────────────┐  ┌─────────────┐   ┌──────────────────┐
  │ Step3 下次运行    │  │ 累积合并     │   │ 提升为硬编码      │
  │ 加载映射 →       │  │ (多轮叠加)   │   │ ATTRIBUTE_HINTS  │
  │ 注入评分逻辑     │  └─────────────┘   │ (脚本辅助, P2)   │
  └─────────────────┘                     └──────────────────┘
```

### Step3 注入点

在 `score_attribute_match(label, attribute)` 中增加查询：

```python
def score_attribute_match(label, attribute, *, component_name=None, feature_mapping=None):
    # ... 现有逻辑 ...

    # === 新增：特征映射配置查询 ===
    if feature_mapping:
        # 1. 先查构件级规则（更精确）
        comp_rules = feature_mapping.get("component_rules", {}).get(component_name, [])
        for rule in comp_rules:
            if _label_matches_rule(normalized_label, rule):
                if attribute_code == rule["attribute_code"]:
                    return 0.99  # 人工确认级别
        # 2. 再查全局规则
        for rule in feature_mapping.get("global_rules", []):
            if _label_matches_rule(normalized_label, rule):
                if attribute_code == rule["attribute_code"]:
                    return 0.98  # 全局映射级别

    return round(score, 4)
```

### Step3 加载入口

#### 文件存放位置

`feature_mapping.json` 有两个推荐存放位置，按优先级：

| 位置 | 路径 | 适用场景 |
|------|------|----------|
| **持久化配置**（推荐） | `data/input/feature_mapping.json` | 与 `components.json` 同级，跨运行复用，审核积累的稳定映射 |
| Step5 输出目录 | `data/output/step5/feature_mapping.json` | Step5 首次导出的原始位置，需手动/脚本拷贝到 `data/input/` |

**约定**：Step5 导出到 `data/output/step5/feature_mapping.json`，用户确认稳定后拷贝到 `data/input/feature_mapping.json`。Step3 默认读取 `data/input/` 下的版本。

#### runtime_config.ini 配置

在 `[paths]` 段新增（已添加到实际配置文件中）：

```ini
[paths]
# ... 已有路径 ...
; Step5 审核导出的特征映射配置（可选，不存在时静默跳过）
feature_mapping = data/input/feature_mapping.json
```

#### load_runtime_config() 新增解析

```python
"feature_mapping_path": resolve_path_from_config(
    parser.get("paths", "feature_mapping", fallback=""),
    resolved_path,
    must_exist=False,  # 不强制存在，向后兼容
),
```

#### resolve_runtime_options() 新增合并

```python
"feature_mapping_path": merge_runtime_value(
    getattr(args, "feature_mapping", None),
    config_values.get("feature_mapping_path"),
    None,
),
```

#### run_filter_condition_match() / run_filter_condition_pipeline() 加载

```python
# 在加载 synonym_payload 之后、build_local_match_payload 之前
feature_mapping = load_feature_mapping(feature_mapping_path)  # 新函数
```

#### load_feature_mapping() 新函数

```python
def load_feature_mapping(path: str | Path | None) -> Dict[str, Any] | None:
    """加载特征映射配置。文件不存在时返回 None（向后兼容）。"""
    if not path:
        return None
    resolved = Path(path)
    if not resolved.exists():
        return None
    with open(resolved, "r", encoding="utf-8") as f:
        data = json.load(f)
    global_count = len(data.get("global_rules", []))
    comp_count = sum(len(v) for v in data.get("component_rules", {}).values())
    print(f"  已加载特征映射: {global_count} 条全局规则, {comp_count} 条构件级规则")
    return data
```

#### build_local_match_payload() 签名变更

```python
def build_local_match_payload(
    step1_rows, source_table, alias_index, standard_document,
    max_components_per_item,
    feature_mapping=None,  # 新增参数
) -> Dict[str, Any]:
```

`feature_mapping` 向下传递到 `build_feature_expression_items()` → `match_feature_to_attribute()` → `score_attribute_match()`。

### Step5 导出逻辑

在 `step5_feature_audit.py` 的 HTML 中新增 `exportFeatureMapping()` 函数：

```javascript
function exportFeatureMapping() {
  const globalRules = [];
  const componentRules = {};

  for (const g of AUDIT_DATA) {
    // 只导出：已匹配 + 审核确认的 + 手动绑定的
    const status = getStatus(g.item_key);
    const attrName = g.attribute_name;
    const attrCode = g.attribute_code;
    if (!attrName || !attrCode) continue;

    const rule = {
      label: g.label,
      label_aliases: collectAliases(g),
      attribute_name: attrName,
      attribute_code: attrCode,
      confidence: g.match_type === 'matched' ? 'auto_matched' :
                  status === 'match-fail-wiki' ? 'human_verified' : 'inferred',
      occurrence_count: g.occurrence_count,
      verified_at: new Date().toISOString(),
    };

    // 判断是全局还是构件级：
    // 如果同一 label→code 在 3+ 个构件中都出现，归为全局规则
    // 否则归为构件级规则
    if (isGlobalPattern(g.label, attrCode)) {
      globalRules.push(rule);
    } else {
      if (!componentRules[g.source_component]) componentRules[g.source_component] = [];
      componentRules[g.source_component].push(rule);
    }
  }

  const mapping = {
    meta: {
      version: "1.0",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      source: "step5_feature_audit",
      base_step3_run: INIT_STATS.base_run || "",
      total_rules: globalRules.length + Object.values(componentRules).flat().length,
      global_rules: globalRules.length,
      component_rules: Object.values(componentRules).flat().length,
    },
    global_rules: globalRules,
    component_rules: componentRules,
  };

  downloadJSON(mapping, 'feature_mapping.json');
}
```

---

## Requirements

### Functional Requirements

- **FR-M01**: Step5 工具 MUST 新增"导出特征映射"按钮，生成 `feature_mapping.json`
- **FR-M02**: `feature_mapping.json` MUST 包含 `global_rules`（跨构件通用）和 `component_rules`（按构件分级）两层映射
- **FR-M03**: 每条映射规则 MUST 包含 `label`、`attribute_name`、`attribute_code`、`confidence`
- **FR-M04**: `label_aliases` SHOULD 从 Step5 聚合数据中自动提取（同一 component|attribute_code 下的不同 label 写法）
- **FR-M05**: Step3 MUST 支持通过 `runtime_config.ini` 的 `feature_mapping` 路径加载映射配置
- **FR-M06**: Step3 加载映射后，`score_attribute_match()` MUST 优先查询映射规则：构件级 → 0.99，全局 → 0.98
- **FR-M07**: `feature_mapping.json` 不存在时，Step3 MUST 静默跳过，保持向后兼容
- **FR-M08**: Step5 SHOULD 支持加载上一轮 `feature_mapping.json` 并与本轮审核结果**合并导出**
- **FR-M09**: 合并时同一 `component|label|attribute_code` 以最新轮为准，更新 `updated_at`
- **FR-M10**: 映射文件 SHOULD 支持 `confidence` 分级（`human_verified` > `auto_matched` > `inferred`），Step3 可按 confidence 级别过滤

### Non-Functional Requirements

- **NFR-M01**: `feature_mapping.json` 大小 SHOULD < 500KB（预估 1000 条规则 ≈ 150KB）
- **NFR-M02**: Step3 加载映射的耗时 MUST < 100ms
- **NFR-M03**: 映射查询 MUST 不影响现有匹配性能（单行 < 1ms 开销）

---

## 与现有机制的关系

| 机制 | 作用域 | 来源 | 可维护性 | 本方案定位 |
|------|--------|------|----------|-----------|
| `ATTRIBUTE_HINTS`（api.py 硬编码） | 全局 | 开发者手写 | 需改代码 | **不替代**，作为底线兜底 |
| `synonym_library.json`（Step2 输出） | 构件名称级 | Step2 自动生成 | 每次运行刷新 | **不冲突**，那个映射构件名，这个映射特征标签 |
| `component_source_table.json` | 构件属性定义 | Step3 生成 | 随构件库更新 | **互补**，是映射的目标端 |
| **`feature_mapping.json`（本方案）** | 特征标签→属性 | Step5 审核导出 | 可累积迭代 | **新增层**，填补清单特征→构件属性的显式关联 |

### 优先级层次（Step3 评分时）

```
1. feature_mapping 构件级规则 → 0.99（最精确，人工为特定构件确认的）
2. feature_mapping 全局规则   → 0.98（人工确认的跨构件通用映射）
3. ATTRIBUTE_HINTS 命中       → 0.98（开发者硬编码的已知同义词）
4. 名称精确匹配              → 1.0 （label 与 attribute_name 完全一致）
5. 包含关系                  → 0.9-0.92
6. 字符相似度                → 计算值
```

---

## 实施计划

### Phase 1（本轮实现）

1. 定义 `feature_mapping.json` schema（本文档）
2. Step5 HTML 新增"导出特征映射"按钮 + `exportFeatureMapping()` JS 函数
3. Step3 `load_runtime_config()` 新增 `feature_mapping` 路径解析
4. Step3 新增 `load_feature_mapping(path)` 函数
5. Step3 `score_attribute_match()` 增加 `feature_mapping` + `component_name` 参数
6. Step3 `build_feature_expression_items()` 传递 `feature_mapping` 和 `component_name`

### Phase 2（后续迭代）

7. Step5 支持加载上一轮 `feature_mapping.json` 并合并
8. 累积合并工具 `merge_feature_mapping.py`
9. `merge_feature_hints.py`：将高频全局规则提升为 `ATTRIBUTE_HINTS` 硬编码

---

## 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `step5_feature_audit.py` | 修改 | HTML 中新增导出特征映射按钮和 JS 函数 |
| `step3_engine/api.py` | 修改 | `load_runtime_config()` 新增路径；新增 `load_feature_mapping()`；`score_attribute_match()` 增加参数 |
| `step3_engine/runtime_config.ini` | 修改 | `[paths]` 新增 `feature_mapping` 配置项 |
| `data/output/step5/feature_mapping.json` | 新增（运行时） | Step5 导出的映射配置 |
