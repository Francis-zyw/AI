# Step3 人工审定工具

本目录存放 Step3（清单-构件匹配）结果的人工审定和分析 HTML 工具。

每次 `python3 -m pipeline_v2 step3-execute` 完成后，会自动更新这里的 HTML 文件。

## 文件说明

| 文件 | 作用 |
|------|------|
| `step3_review_editor.html` | **人工审定编辑器** — 按清单条目逐一查看、修改构件匹配结果，支持导出审定 JSON 和 Wiki 补丁 |
| `step3_component_analysis.html` | **构件分析报告** — 按构件类型维度统计匹配概况、缺失特征、缺失计算项目 |

## 使用流程

1. 直接在浏览器中打开对应 HTML（无需服务器，纯 HTML 内嵌数据）
2. 在审定编辑器中完成人工确认，点击"导出审定结果"
3. 若有 Wiki 知识补充，点击"导出 Wiki 补丁"后导入知识库

## 数据来源

- 数据 inline 在 HTML 中，默认优先来源于最近一次 Step3 的 `project_component_feature_calc_matching_result.json`（匹配完成后的最终结果）；若最终结果不存在，再回退到 `local_rule_project_component_feature_calc_result.json`（本地规则阶段预览）
- 文件为自包含快照，不依赖外部 JSON 文件
- 清单头部优先展示 Step3 结果中的 `feature_expression_items` 汇总特征，原始 `project_features_raw` 仅作为补充回看信息保留
