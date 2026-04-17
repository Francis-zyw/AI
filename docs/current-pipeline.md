# 当前正式入口

唯一正式代码入口是 `pipeline_v2`，所有执行都在项目根目录下完成。

```bash
cd /Users/zhangkaiye/AI数据/AI智能提量/智能提量处理流程/智能提量工具
python3 -m pipeline_v2 --help
```

## 当前执行进度

| 步骤 | 状态 | 最新运行 |
|------|------|---------|
| Step1 | ✅ 完成 | `data/output/step1/run-20260327-1810-newentry-full/` |
| Step2 | ✅ 完成（含人工复核） | `data/output/step2/run-20260330-step2/` |
| Step3 | ⏳ 待执行 | — |
| Step4 | ⏳ 待执行 | — |

## 命令速查

### Step1 — PDF 章节识别

```bash
python3 -m pipeline_v2 step1-extract \
  --pdf data/input/房屋建筑与装饰工程工程量计算标准.pdf \
  --output data/output/step1/run-xxx
```

### Step2 — 构件匹配

```bash
# 首次执行（推荐）
python3 -m pipeline_v2 step2-execute \
  --components data/input/components.json \
  --step1-source data/output/step1/run-20260327-1810-newentry-full \
  --output data/output/step2/run-xxx

# 仅预处理（不调模型）
python3 -m pipeline_v2 step2-prepare ...

# 从已有批次重新合成结果
python3 -m pipeline_v2 step2-synthesize --output data/output/step2/run-xxx
```

### Step3 — 清单匹配

```bash
# 使用配置文件（推荐）
python3 -m pipeline_v2 step3-execute \
  --config pipeline_v2/step3_engine/runtime_config.ini

# 完整参数
python3 -m pipeline_v2 step3-execute \
  --step1-table-regions data/output/step1/run-20260327-1810-newentry-full/table_regions.json \
  --step2-result data/output/step2/run-20260330-step2/component_matching_result.json \
  --components data/input/components.json \
  --output data/output/step3/run-xxx

# 仅本地规则
python3 -m pipeline_v2 step3-execute --config pipeline_v2/step3_engine/runtime_config.ini --local-only

# 生成复核队列
python3 -m pipeline_v2 step3-build-review-queue \
  --step3-result data/output/step3/run-xxx/project_component_feature_calc_matching_result.json \
  --output data/manual_reviews/review_queue.json
```

### Step4 — 指定构件直匹配

```bash
# 消费 Step3 结果（自动按构件分组）
python3 -m pipeline_v2 step4-direct-match \
  --step3-result data/output/step3/run-xxx/project_component_feature_calc_matching_result.json \
  --synonym-library data/output/step2/run-20260330-step2/synonym_library.json \
  --components data/input/components.json

# 仅查表
python3 -m pipeline_v2 step4-direct-match ... --local-only
```

### 审计与维护

```bash
python3 -m pipeline_v2 audit --format markdown
python3 -m pipeline_v2 plan --format markdown
```

## 配置文件

| 文件 | 用途 |
|------|------|
| `pipeline_v2/runtime_models.ini` | 各步骤的模型和 Provider 配置 |
| `pipeline_v2/step3_engine/runtime_config.ini` | Step3 路径和运行参数 |
| `pipeline_v2/step4_runtime_config.ini` | Step4 路径和运行参数 |

默认 Provider 模式为 `codex`（无需设置 API Key）。

## 实现目录

| 模块 | 说明 |
|------|------|
| `pipeline_v2/step1_chapter_ocr/` | Step1 PDF 解析 |
| `pipeline_v2/step2_engine/` + `step2_v2.py` | Step2 构件匹配 |
| `pipeline_v2/step3_engine/` + `step3_v2.py` | Step3 清单匹配 |
| `pipeline_v2/step4_direct_match.py` | Step4 直匹配 |
| `pipeline_v2/cli.py` | 统一 CLI 入口 |
| `pipeline_v2/model_runtime.py` | 模型配置加载 |
| `pipeline_v2/review_queue.py` | 复核队列 |
| `pipeline_v2/audit.py` | 项目审计 |

## 知识沉淀

每次任务完成后，AI 自动将产生的知识沉淀到 `知识库中心/wiki/`，通过 Obsidian 浏览。
详见 [[智能提量工具概览]]。

## 已废弃

- 根目录 `step2_component_match/`、`step3_filter_condition_match/`（已删除）
- 旧的分步文档 `docs/step1/`、`docs/step2/`、`docs/step3/`（已删除）
- `分析工具/构件类型-属性/` 代码副本（已归档，仅保留 README 指引）
- `data/config/runtime_models.ini`（旧版 Gemini 配置，已删除）
