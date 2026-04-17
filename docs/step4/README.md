# 第四步 指定构件类型后的直匹配与模型精修

Step4 面向这样的输入：

- 上游已经明确指定了某条清单项要落到哪个 `component_type`
- 需要在这个固定构件类型内，继续生成项目特征表达式、计算项目、计量单位
- 允许在本地直匹配结果基础上，再用模型做一次结构化精修
- 现在还支持接入 `step1-step3` 知识库，把历史章节依据、同义词桥接、历史匹配样本一起补进 prompt

这一步不会推翻“指定构件类型”本身。模型只负责在该构件的属性、别名和计算项目范围内修正表达式、计量单位、计算项目和复核说明。

## 代码位置

- `pipeline_v2/step4_direct_match.py`
- `pipeline_v2/knowledge_base.py`
- `pipeline_v2/cli.py`

## 新增知识底座

参考 karpathy 的 `llm-wiki` 思路，当前实现拆成两层：

- 底层：`SQLite` 向量知识库
  - 把 `step1/step2/step3` 产物统一编译成 `knowledge_entries`
  - 使用轻量 hash 向量做本地相似度检索，无需额外依赖
- 表层：`wiki markdown`
  - 自动生成 `overview`、`component wiki`、`chapter wiki`、`step3 pattern wiki`
  - Step4 在调用模型前，会把检索到的 wiki 摘要和行级历史证据一起送进 prompt

这样 Step4 不再只依赖“当前批次 + 当前构件属性”，还能复用：

- Step1 的章节原文与非表格规则
- Step2 的构件映射和同义词桥接
- Step3 的历史表达式/计算项目样本

## 先构建知识库

```bash
python3 -m pipeline_v2 knowledge-build \
  --step1-source data/output/step1/run-20260327-1810-newentry-full \
  --step2-source data/output/step2/run-20260330-step2 \
  --step3-result data/output/step3/<你的step3输出目录或结果json> \
  --output-dir data/output/knowledge/step4_context
```

输出：

- `data/output/knowledge/step4_context/knowledge.db`
- `data/output/knowledge/step4_context/wiki/*.md`
- `data/output/knowledge/step4_context/knowledge_ingest_summary.json`

如需调试召回：

```bash
python3 -m pipeline_v2 knowledge-query \
  --knowledge-base data/output/knowledge/step4_context \
  --component-type 砼墙 \
  --query "钢筋混凝土墙 墙厚 体积"
```

## 运行模式

- `local_only`
  - 只跑本地直匹配，不调用模型
- `prepare_only`
  - 生成本地结果、提示词和批次输入，不真正发起模型请求
- 默认模型模式
  - 先生成本地候选，再调用模型精修

## 配置入口

Step4 支持：

1. CLI 参数
2. `pipeline_v2/step4_runtime_config.ini`
3. 环境变量 `OPENAI_API_KEY` / `OPENAI_BASE_URL`

推荐做法：

- 运行输入 `--items-file` / `--item-json` 放在命令行
- 模型和默认路径放在 `pipeline_v2/step4_runtime_config.ini`
- 真正的密钥优先放环境变量

示例配置见：

- `docs/step4/runtime_config.example.ini`

## 典型命令

只跑本地直匹配：

```bash
python3 -m pipeline_v2 step4-direct-match \
  --items-file data/input/sample_step4_items.json \
  --component-type 砼墙 \
  --components data/input/components.json \
  --synonym-library data/output/step2/房屋建筑与装饰工程工程量计算标准/synonym_library.json \
  --local-only
```

只准备提示词，不调用模型：

```bash
python3 -m pipeline_v2 step4-direct-match \
  --items-file data/input/sample_step4_items.json \
  --component-type 砼墙 \
  --config pipeline_v2/step4_runtime_config.ini \
  --prepare-only
```

用默认配置加模型精修：

```bash
python3 -m pipeline_v2 step4-direct-match \
  --items-file data/input/sample_step4_items.json \
  --component-type 砼墙 \
  --config pipeline_v2/step4_runtime_config.ini
```

直接消费 Step 3 结果并按构件类型分组跑 Step 4：

```bash
python3 -m pipeline_v2 step4-direct-match \
  --step3-result data/output/step3/房屋建筑与装饰工程工程量计算标准/project_component_feature_calc_matching_result.json \
  --synonym-library data/output/step2/房屋建筑与装饰工程工程量计算标准/synonym_library.json \
  --local-only
```

这个模式会：

- 读取 Step 3 `rows`
- 使用每行的 `quantity_component / resolved_component_name`
- 自动按构件类型分组
- 分别生成各构件类型子目录结果
- 在根输出目录额外写一份聚合后的 `step4_from_step3_result.json`

## 主要输出

默认输出目录：

```text
data/output/step4/<component_type>/
```

关键文件：

- `step4_local_direct_match_result.json`
  - 本地直匹配结果
- `batch_001_prompt_input.json`
  - 每批送模型前的结构化输入
- `batch_001_prompt.txt`
  - 实际提示词
- `batch_001_model_output.txt`
  - 模型原始输出
- `batch_001_result.json`
  - 单批模型融合结果
- `step4_direct_match_result.json`
  - 最终结果
- `step4_direct_match_result.md`
  - Markdown 复核视图
- `run_summary.json`
  - 运行摘要

如果配置了知识库，`batch_001_prompt_input.json` 里还会包含：

- `knowledge_context.wiki_pages`
- `knowledge_context.row_contexts`

## 输出结构

最终结果中的核心字段包括：

- `row_id`
- `project_code`
- `project_name`
- `component_type`
- `source_component_name`
- `feature_expression_items`
- `feature_expression_text`
- `calculation_item_name`
- `calculation_item_code`
- `measurement_unit`
- `match_status`
- `match_basis`
- `confidence`
- `review_status`
- `reasoning`
- `manual_notes`

## 对外交付建议

- 不提交真实密钥
- 把模型、base URL、默认路径写进配置文件
- 让外部使用者自己设置 `OPENAI_API_KEY`
- 默认把 `local_only = true`，先保证无密钥也能跑

## 推荐用法

推荐把 Step4 升级成下面这条链路：

1. 跑完 `step1-step3`
2. 执行一次 `knowledge-build`
3. Step4 使用 `--knowledge-base` 或配置文件里的 `knowledge_base`
4. 需要时再周期性重建知识库，让 wiki 和向量层一起增量沉淀

## 测试

```bash
cd 智能提量工具
分析工具/venv/bin/python -m unittest tests.unit.test_pipeline_v2_step4 -v
```
