# 智能提量工具

面向国标 (GB) PDF 文档的四步结构化解析流水线，将原始标准文档逐步转化为构件—清单—特征—计算项目的匹配结果。

## 快速开始

```bash
cd /Users/zhangkaiye/AI数据/AI智能提量/智能提量处理流程/智能提量工具
python3 -m pipeline_v2 --help
```

## 流水线概览

| 步骤 | 命令 | 功能 |
|------|------|------|
| Step1 | `step1-extract` | PDF 章节识别 + 表格区域提取 |
| Step2 | `step2-execute` | 构件名称匹配 + 同义词库沉淀 |
| Step3 | `step3-execute` | 清单项→构件→特征→计算项目匹配 |
| Step4 | `step4-direct-match` | 指定构件后的直匹配 + 模型精修 |

### 当前执行进度

- ✅ Step1 完成 — `data/output/step1/run-20260327-1810-newentry-full/`
- ✅ Step2 完成（含人工复核） — `data/output/step2/run-20260330-step2/`
- ⏳ Step3 待执行
- ⏳ Step4 待执行

## 目录结构

```
智能提量工具/
├── pipeline_v2/            # 唯一正式代码包（Step1–4 + CLI）
├── data/
│   ├── input/              # 构件库、PDF、Excel 源数据
│   ├── output/             # 各步骤运行结果
│   ├── reference/          # 参考数据
│   └── source/             # 原始来源
├── docs/                   # 文档、架构说明、计划、报告
├── tools/                  # 构件库维护工具、匹配复核工具
├── scripts/                # 辅助脚本
├── tests/                  # 单元测试、集成测试
└── 分析工具/               # ⚠️ 已归档，请勿使用
```

## 常用命令

### Step1 — PDF 结构化

```bash
python3 -m pipeline_v2 step1-extract \
  --pdf data/input/房屋建筑与装饰工程工程量计算标准.pdf \
  --output data/output/step1/run-xxx
```

### Step2 — 构件匹配

```bash
# 首次执行
python3 -m pipeline_v2 step2-execute \
  --components data/input/components.json \
  --step1-source data/output/step1/run-20260327-1810-newentry-full \
  --output data/output/step2/run-xxx

# 中断后恢复：直接重新运行同一命令（自动续跑）
# 结果损坏后重新合成
python3 -m pipeline_v2 step2-synthesize --output data/output/step2/run-xxx
```

### Step3 — 清单匹配

```bash
# 使用配置文件（推荐）
python3 -m pipeline_v2 step3-execute --config pipeline_v2/step3_engine/runtime_config.ini

# 或完整参数
python3 -m pipeline_v2 step3-execute \
  --step1-table-regions data/output/step1/run-20260327-1810-newentry-full/table_regions.json \
  --step2-result data/output/step2/run-20260330-step2/component_matching_result.json \
  --components data/input/components.json \
  --output data/output/step3/run-xxx

# 仅本地规则（不调模型）
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

# 仅查表，不调模型
python3 -m pipeline_v2 step4-direct-match ... --local-only
```

### 知识库

```bash
# 构建知识库（Step3 完成后）
python3 -m pipeline_v2 knowledge-build \
  --step1-source data/output/step1/run-20260327-1810-newentry-full \
  --step2-source data/output/step2/run-20260330-step2 \
  --step3-result data/output/step3/run-xxx/project_component_feature_calc_matching_result.json \
  --output-dir data/output/knowledge/step4_context

# 查询知识库
python3 -m pipeline_v2 knowledge-query \
  --knowledge-base data/output/knowledge/step4_context \
  --query "钢筋混凝土墙 墙厚" --component-type 砼墙
```

### 审计与维护

```bash
python3 -m pipeline_v2 audit --format markdown
python3 -m pipeline_v2 plan --format markdown
```

## 运行时配置

配置文件：`pipeline_v2/runtime_models.ini`

当前默认使用 Codex 订阅态（无需设置 API Key）。如需切换：

```bash
# Codex 模式（默认）
provider_mode = codex

# OpenAI 兼容模式
export OPENAI_API_KEY="sk-..."
# 并在 runtime_models.ini 中将 provider_mode 改为 env_api_key
```

环境变量优先级：CLI 参数 > 环境变量 > 配置文件 > 代码默认值

## 关键设计原则

- **先边界，再切分，再结构，最后智能**
- **允许不确定，拒绝伪确定** — 匹配结果保留 `candidate_only` / `unmatched` / `conflict`
- **阶段化输出** — 每步独立可验证，不依赖后续步骤

## 文档索引

| 文档 | 说明 |
|------|------|
| [完整使用说明](docs/完整使用说明.md) | 详细教程和参数说明 |
| [系统架构](docs/architecture/系统整体说明-System-Overview.md) | 架构设计和目录约定 |
| [Step3 检索增强](docs/step3_retrieval_usage.md) | RAG 版 Step3 说明 |
| [Step4 知识库](docs/step4/KNOWLEDGE_BASE_GUIDE.md) | 三层知识库设计 |
| [运行环境配置](docs/runtime-env-example.md) | 环境变量和 Provider 模式 |

## 知识库中心集成

本项目的结构化知识已沉淀到 `知识库中心/wiki/`，通过 Obsidian 浏览：

- [[智能提量工具概览]] — 整体架构
- [[智能提量四步流水线]] — Step1–4 流程
- [[智能提量数据契约]] — 数据结构
- [[智能提量知识库架构]] — 三层知识库
- [[智能提量运行时配置]] — 配置说明
- [[智能提量质量控制]] — 审计与复核
