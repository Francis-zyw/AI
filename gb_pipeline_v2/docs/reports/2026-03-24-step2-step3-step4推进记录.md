# 2026-03-24 Step2 / Step3 / Step4 推进记录

## 当前编排

- Step2 已切换为 `单章节 + 最多 5 个构件类型` 的串行策略。
- Step2 全量续跑已在后台启动，官方输出目录为：
  - `data/output/step2/房屋建筑与装饰工程工程量计算标准`
- Step3 约定在 Step2 全部章节完成后再执行，避免使用半成品同义词库。
- Step4 与 Step3 一样，需要保留模型调用能力，但必须支持他人配置自己的模型，不依赖开发者本机私有密钥。

## Step2 续跑约束

- 运行入口：
  - `分析工具/venv/bin/python -m pipeline_v2 step2-execute`
- 当前关键参数：
  - `--components data/input/components.json`
  - `--step1-source data/output/step1/房屋建筑与装饰工程工程量计算标准`
  - `--output data/output/step2/房屋建筑与装饰工程工程量计算标准`
  - `--component-batch-size 5`
- 续跑规则：
  - 同一章节必须先跑完全部构件批次，再进入下一章节。
  - `resume_existing=true` 时复用已有 `batch_*_result.json`，并在读取旧结果时自动做归一化清洗。
  - `selected_standard_name` 中的 `"None" / "null" / "无" / "未匹配"` 必须视为空值，不能进入 `synonym_library`。

## Step2 监控方式

- 看全量运行配置：
  - `data/output/step2/房屋建筑与装饰工程工程量计算标准/execute_manifest.json`
- 看已完成批次数：
  - 统计 `chapter_*/batch_*_result.json`
- 看章节级合并结果：
  - `chapter_*/chapter_result.json`
- 看最终合并结果：
  - `component_matching_result.json`
  - `synonym_library.json`
  - `run_summary.json`

## Step3 启动条件

满足以下条件后再启动 Step3：

- Step2 已完成全部章节。
- `component_matching_result.json` 与 `synonym_library.json` 已完整生成。
- `run_summary.json.status = completed`。

推荐显式传入以下输入，避免依赖默认推断：

- Step1:
  - `data/output/step1/房屋建筑与装饰工程工程量计算标准/table_regions.json`
- Step2:
  - `data/output/step2/房屋建筑与装饰工程工程量计算标准/component_matching_result.json`
  - `data/output/step2/房屋建筑与装饰工程工程量计算标准/synonym_library.json`
- Components:
  - `data/input/components.json`

额外要求：

- Step3 执行真实模型时必须显式关闭 `local_only`。
- Step3 先完成测试和输入检查，再开始模型执行。

## Step4 开发约束

Step4 当前目标不是只做本地直匹配，而是要具备以下能力：

- 保留“指定构件类型后的本地直匹配”作为基线能力。
- 增加可选模型精修能力，用于补强项目特征表达式、计算项目和结果说明。
- 支持外部使用者配置自己的模型，不把开发期密钥固化进仓库。
- 配置优先级保持一致：
  - CLI 参数优先
  - 运行配置文件次之
  - 环境变量兜底

Step4 对外交付时至少要说明这些可配置项：

- `model`
- `reasoning_effort`
- `openai_api_key`
- `openai_base_url`
- `prepare_only`
- `local_only`
- 输入数据路径
- 输出目录

## 测试与评审要求

在 Step4 正式接入前，至少完成：

- Step2 单元测试通过。
- Step3 单元测试通过。
- Step4 单元测试补齐并通过。
- 对 Step2 续跑、Step3 配置读取、Step4 外用配置能力做一次只读审查，重点看：
  - 结果归一化是否会污染下游。
  - `resume_existing` 是否会吞掉历史脏结果。
  - 模型配置是否允许他人无侵入替换。
  - 文档是否足够让他人按自己的模型配置运行。

## 密钥约束

- 开发期允许使用当前提供的开发密钥做验证。
- 不在仓库文件中落真实密钥。
- 文档与配置样例只保留占位值，由使用者自行填写。
