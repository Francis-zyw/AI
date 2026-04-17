# Pipeline V3：Token 优化与准确率提升方案

> 基于 2026-04-15 对当前 Step3 prompt 的完整量化分析

---

## 一、当前 Step3 Token 消耗分析

### 1.1 总量

| 指标 | 数值 |
|------|------|
| 清单行数 | 445 |
| Batch 数 | 23（每批 20 行） |
| 总 prompt 字符 | 19,938,930 |
| **预估总 input tokens** | **~10,000,000** |
| 预估总 output tokens | ~111,000 |
| **总计** | **~10,100,000 tokens** |
| 最大单 batch | Batch 8 = 4.5MB ≈ 1.3M tokens |
| 最小单 batch | Batch 23 = 119KB ≈ 16K tokens |

### 1.2 Prompt 各部分空间占比

```
source_row 合计          3,156,720 chars (39.8%)
  ├── region_text_excerpt      1,676,707 chars (21.1%)  ← 最大浪费
  ├── chapter_rule_hits          606,072 chars ( 7.6%)  ← 重复
  ├── table_raw_text             373,059 chars ( 4.7%)
  └── 其他字段                    500,882 chars ( 6.4%)

local_candidate_rows     3,236,915 chars (40.8%)
  ├── chapter_rule_hits        1,610,124 chars (20.3%)  ← 与 source_row 重复!
  ├── feature_expression_items   579,071 chars ( 7.3%)
  ├── notes                      156,677 chars ( 2.0%)
  └── 其他字段                    891,043 chars (11.2%)

candidate_source_comps   1,437,631 chars (18.1%)
prompt 模板(×23)           103,500 chars ( 1.3%)
```

### 1.3 核心问题

| # | 问题 | 浪费量 | 占总量 |
|---|------|--------|--------|
| 1 | **chapter_rule_hits 双重嵌入** — source_row 和每个 local_row 各带一份完全相同的 chapter_rule_hits | 1,610,124 chars | 20.3% |
| 2 | **region_text_excerpt** — 每行带 ~3.7K 原始 PDF 文本，同表格行高度重叠 | 1,676,707 chars | 21.1% |
| 3 | **候选构件重复嵌入** — Batch 8 中 60 次引用只有 4 个唯一构件（93% 重复） | ~900K chars | ~11% |
| 4 | **table_raw_text** — 整张表原文在每行都出现 | 373,059 chars | 4.7% |
| 5 | **local_rows 字段冗余** — section_path/table_title/chapter_root 等与 source_row 完全重复 | ~100K chars | 1.3% |
| 6 | **prompt 模板 23 次重复** — 4.5K 指令每个 batch 重发一遍 | 103,500 chars | 1.3% |

**理论可节省**: 问题 #1 + #2 + #3 + #4 ≈ **4.5M chars → ~2.25M tokens → 占总量 22.5%**

---

## 二、新方案设计

### 2.1 架构变化：从「全量投喂」到「分层引用」

```
当前架构:
  每个 batch prompt = 模板 + 全量 step1_rows + 全量 local_rows + 全量候选构件
  → 大量重复，模型被迫消化无用信息

新架构:
  Phase 0: 离线构建 → 构件索引 + 规则索引（不消耗 token）
  Phase 1: 本地规则匹配（不消耗 token）
  Phase 2: 按构件分组 → 只对「需模型辅助」的行调模型
  Phase 3: 冲突仲裁（极少量 token）
```

### 2.2 三层优化

#### 层一：数据瘦身（Prompt 结构优化，改代码不改逻辑）

**预计节省: 55-65% tokens**

| 优化点 | 具体做法 | 节省 |
|--------|---------|------|
| 去重 chapter_rule_hits | 每 batch 只放一次 `chapter_rules_context`，按 chapter_root 分组共享 | ~20% |
| 压缩 region_text_excerpt | 只保留与当前行相关的 50 字上下文，不是整个章节 | ~18% |
| 构件摘要去重 | batch 级别的 `component_reference` 只列一次，行内用 `component_ref_id` 引用 | ~11% |
| 去掉 table_raw_text | row 已有 project_code/name/features/unit/rule，原始表文本冗余 | ~5% |
| local_rows 精简 | 只保留 result_id/row_id/match_status/feature_items/calc_code/confidence，其他都可从 source_row 推导 | ~5% |

**示例 — 新 batch prompt 结构:**

```json
{
  "chapter_rules_context": {
    "附录E 混凝土及钢筋混凝土工程": [
      {"rule_id": "CR001", "paragraph": "...", "target_terms": [...]}
    ]
  },
  "component_references": {
    "REF_柱": {
      "component_name": "柱",
      "attributes": [{"name":"砼标号","code":"TBH","values":["C20","C25",...]}],
      "calculations": [{"name":"体积","code":"TJ","unit":"m3"}]
    }
  },
  "rows": [
    {
      "row_id": "R0123",
      "project_code": "010505001",
      "project_name": "矩形柱",
      "project_features": "1.砼强度等级\n2.截面尺寸\n3.浇筑方式",
      "measurement_unit": "m3",
      "quantity_rule": "以体积计算",
      "chapter_rule_refs": ["CR001"],
      "local_result": {
        "match_status": "candidate_only",
        "component_ref": "REF_柱",
        "feature_items": [{"label":"砼强度等级","code":"TBH","expression":"砼强度等级:TBH"}],
        "calc_code": "TJ",
        "confidence": 0.72
      },
      "candidate_refs": ["REF_柱"]
    }
  ]
}
```

#### 层二：智能分流（按置信度分级处理）

**预计额外节省: 30-50% tokens**

当前做法：445 行全部发给模型校正。\
新做法：只把真正需要模型判断的行发给模型。

```
Step3 本地规则匹配后，按结果分三档:

A档 (高置信 ≥ 0.85, exact/normalized/alias_bridge)
  → 直接接受本地结果，不调模型
  → 预计占 40-50% 的行

B档 (中置信 0.65-0.85, 有候选但不确定)
  → 调模型校正
  → 预计占 30-40% 的行

C档 (低置信 < 0.65 或 unmatched)
  → 调模型 + 补充更多上下文
  → 预计占 10-20% 的行
```

如果只对 B+C 档调模型（~250 行 vs 当前 445 行），token 消耗直接砍掉 ~40%。

#### 层三：按构件分组批次（消除同批重复）

当前做法：按 row_id 顺序切 20 行一批，同一批可能涉及 15+ 个不同构件。\
新做法：按 `chapter_root + resolved_component_name` 分组批次。

好处：
- 同组行共享同一套构件属性和章节规则 → 只需放一次
- 模型看到同类行可以做交叉验证 → 准确率提升
- Batch 8 这种 20 行全是楼梯的情况，构件摘要从 84K chars 降到 ~6K chars

### 2.3 token 节省汇总

| 阶段 | 当前消耗 | 优化后预估 | 节省比例 |
|------|---------|-----------|---------|
| 数据瘦身 | ~10M tokens | ~4M tokens | ~60% |
| 智能分流 (仅 B+C 档调模型) | 4M tokens | ~2M tokens | ~50% |
| 按构件分组去重 | 2M tokens | ~1.2M tokens | ~40% |
| **最终** | **~10M tokens** | **~1.2M tokens** | **~88%** |

### 2.4 准确率提升策略

当前问题：prompt 太长，高价值信息被噪音淹没。

| 策略 | 原理 | 预估提升 |
|------|------|---------|
| 信息密度提升 | 删除冗余后，有效信息占比从 ~30% 提升到 ~80% | +10-15% |
| 按构件分组上下文 | 模型看到同类行做交叉校验 | +5-10% |
| 输出约束简化 | 高置信行不需要 reasoning/notes，减少输出错误 | +3-5% |
| 多轮校验 | C 档用两轮：第一轮给候选，第二轮精修 | +5-8% |
| 单位预过滤 | 在 prompt 前用代码做硬过滤，只给模型单位一致的候选 | +5% |

---

## 三、重新设计的 Step1-Step4 全流程

### 3.0 原始架构 vs 新架构对比

```
=== 当前 V2 架构 ===
Step1: PDF→章节→表格区域 (纯 OCR + 规则, 不耗 token)
Step2: 构件名→国标名映射 + 同义词库 (LLM, ~200K tokens)
Step3: 445行 × 23 batch × 100K+/batch (LLM, ~10M tokens)  ← 瓶颈
Step4: 按构件精修特征+计算项目 (LLM, ~2M tokens)
总计: ~12.2M tokens

=== V3 新架构 ===
Step1: 不变 (0 tokens)
Step2: 不变 (200K tokens)
Step3-local: 纯代码本地匹配 + 置信度分档 (0 tokens)
Step3-model: 仅 B+C 档，按构件分组，瘦身 prompt (1.2M tokens)
Step4: 合并到 Step3-model 的 C 档处理 (0 额外 tokens)
总计: ~1.4M tokens (节省 88%)
```

### 3.1 Step1 — PDF 章节识别（不变）

保持原状。Step1 是纯本地 OCR + 规则，不消耗 token。

### 3.2 Step2 — 构件匹配与同义词库（微调）

当前 Step2 已经很高效。可做的微调：
- 同义词库的 `chapter_nodes` 字段过于冗长（平均 28 chars × 1870 条 = 52K chars），很多是"本章节未找到"的负面说明 → 清理掉没匹配到的 chapter_nodes 可节省 ~30K chars

### 3.3 Step3 — 三阶段匹配（核心重构）

```
Step3-Phase0: 构建索引 (纯代码)
  输入: components.json + synonym_library.json + chapter_rules
  输出: component_index.json + rule_index.json
  → 按 chapter_root 分组的构件候选池
  → 按构件名的属性/计算项目快速查表

Step3-Phase1: 本地规则匹配 (纯代码, 不变)
  输入: step1_rows + component_index
  输出: local_match_result.json (带置信度分档)
  → A档: confidence ≥ 0.85 → 标记 auto_accepted
  → B档: 0.65 ≤ confidence < 0.85 → 标记 needs_review
  → C档: confidence < 0.65 或 unmatched → 标记 needs_model

Step3-Phase2: 模型校正 (核心 LLM 消耗)
  只处理 B+C 档行
  按 chapter_root + resolved_component_name 分组
  每组的 prompt = 瘦身结构:
    - 共享: chapter_rules (组级别, 不重复)
    - 共享: component_reference (组级别, 不重复)
    - 逐行: row_id + project_code + name + features + unit + rule + local_result
    - 指令: 精简版 (不重复已解释的规则)
```

### 3.4 Step4 — 合并到 Step3

当前 Step4 的职能（补齐项目特征表达式和计算项目）可以合并到 Step3-Phase2：
- B 档行在 Step3-Phase2 一次性完成构件确认 + 特征映射 + 计算项目选择
- C 档行在 Step3-Phase2 做第一轮，如果还有 unmatched 再做第二轮精修
- **节省整个 Step4 的 token 消耗**

### 3.5 最终流程

```
python3 -m pipeline_v2 step1-extract --pdf input.pdf --output step1/
python3 -m pipeline_v2 step2-execute --step1-source step1/ --output step2/
python3 -m pipeline_v2 step3-execute --config runtime_config.ini --output step3/
  ↳ Phase 0: 构建索引 (code)
  ↳ Phase 1: 本地匹配 + 分档 (code)
  ↳ Phase 2: B+C 档模型校正 (LLM, 精简 prompt)
  ↳ Phase 3: 合并结果 + 输出
```

不再需要单独的 Step4 命令。

---

## 四、实施计划

### Phase 1: Prompt 瘦身（最快见效）

修改 `build_prompt_batch_payload()` 和 `build_prompt_text()`:
1. chapter_rule_hits 提取为 batch 级共享上下文
2. region_text_excerpt 截断到 50 字
3. candidate_source_components 去重为 component_reference
4. 删除 table_raw_text / canonical_table_title 等冗余字段
5. local_rows 只保留 diff 字段

预计工作量: 修改 1 个文件 + 1 个模板\
预计效果: **10M → 4M tokens (60% 节省)**

### Phase 2: 智能分流

修改 `run_filter_condition_pipeline()`:
1. 本地匹配后加置信度分档逻辑
2. A 档直接写入最终结果
3. B+C 档进入模型校正队列

预计工作量: 修改 1 个函数\
预计效果: **4M → 2M tokens (再节省 50%)**

### Phase 3: 按构件分组

修改批次构建逻辑:
1. 改 `chunk_list` 为按 chapter_root + component 分组
2. 更新 prompt 模板适配新结构

预计工作量: 新增 1 个分组函数 + 修改模板\
预计效果: **2M → 1.2M tokens (再节省 40%)**

---

## 五、风险与应对

| 风险 | 应对 |
|------|------|
| A 档自动接受可能有少量错误 | 设置 audit 阶段随机抽样 5% A 档行做模型验证 |
| 按构件分组后 batch 大小不均 | 设置 max_rows_per_group = 30，超出拆分 |
| 瘦身 prompt 可能丢失必要上下文 | 保留 region_text_excerpt 的关键 50 字 + 建立 wiki 查询补充机制 |
| Step4 合并后复杂度增加 | Step3-Phase2 模板分 B/C 两种难度级别 |
