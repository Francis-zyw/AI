# 构件匹配结果人工修订工具

这是一个独立的补充工具，用于：

- 读取 AI 产出的构件匹配结果 JSON
- 以表格方式在线查看和修改
- 人工调整后重新导出为 JSON

该工具不属于主分析流程，只用于结果修订。

## 推荐输入格式

推荐使用以下结构：

```json
{
  "meta": {
    "task_name": "component_standard_name_matching",
    "standard_document": "房屋建筑与装饰工程工程量计算标准",
    "generated_at": "2026-03-19T00:00:00+08:00",
    "review_stage": "pre_parse"
  },
  "mappings": [
    {
      "source_component_name": "砼墙",
      "source_aliases": ["砼墙", "混凝土墙"],
      "selected_standard_name": "钢筋混凝土墙",
      "standard_aliases": ["钢筋混凝土墙", "混凝土墙", "现浇混凝土墙"],
      "candidate_standard_names": ["钢筋混凝土墙", "现浇混凝土墙"],
      "match_type": "alias_bridge",
      "match_status": "matched",
      "confidence": 0.93,
      "review_status": "pending",
      "evidence_paths": ["附录G 混凝土及钢筋混凝土工程 > G.2 现浇混凝土墙"],
      "evidence_texts": ["章节中存在高相关名称证据。"],
      "reasoning": "基于行业简称与章节上下文完成匹配。",
      "manual_notes": ""
    }
  ]
}
```

工具也兼容以下根节点：

- 直接传入数组
- `mappings`
- `matches`
- `匹配结果`
- `data`

## 启动

Mac 双击运行：

```text
scripts/tool_component_match_review_mac.command
```

Windows 双击运行：

```text
scripts/tool_component_match_review.bat
```

终端方式：

```bash
cd /Users/zhangkaiye/AI数据/AI智能提量/智能提量处理流程/国标解析-文本分析
bash tools/tool_component_match_review/start.sh
```

环境说明：

- 优先复用主项目 `分析工具/venv`
- 如果主项目虚拟环境不存在，则退回系统 `python3` 或 `python`
- 不再在 `tool_component_match_review` 目录下单独创建新的 `venv`

启动后浏览器访问：

```text
http://localhost:8502
```

## 主要能力

- 上传 JSON 文件
- 直接粘贴 JSON 文本
- 从工作区路径读取 JSON
- 表格化编辑
- 支持新增行、删除行
- 实时预览导出的 JSON
- 下载修订后的 JSON
- 保存到工作区文件

## 字段说明

- `meta.task_name`
  - 任务名称，通常是 `component_standard_name_matching`

- `meta.standard_document`
  - 当前结果对应的国标文档名

- `meta.generated_at`
  - 结果生成时间

- `meta.review_stage`
  - 结果来源阶段
  - 常见值：
    - `pre_parse`
    - `local_fallback`

- `source_component_name`
  - 原始构件名称

- `source_aliases`
  - 原始构件别名数组

- `selected_standard_name`
  - 当前最终选定的国标构件名
  - 为空时说明当前没有可靠唯一解

- `standard_aliases`
  - 国标侧别名数组

- `candidate_standard_names`
  - 候选国标名称数组
  - 多个候选时通常要人工确认

- `match_type`
  - 匹配方式
  - 常见值：
    - `exact`
    - `alias_bridge`
    - `contextual_inference`
    - `hierarchical`
    - `manual_override`

- `match_status`
  - 匹配状态
  - 常见值：
    - `matched`
    - `candidate_only`
    - `unmatched`
    - `conflict`

- `confidence`
  - 置信度，范围 `0 ~ 1`

- `review_status`
  - 人工复核状态
  - 常见值：
    - `pending`
    - `confirmed`
    - `adjusted`
    - `rejected`

- `evidence_paths`
  - 章节路径证据

- `evidence_texts`
  - 文本证据或脚本规则说明

- `reasoning`
  - 当前匹配结论的解释说明

- `manual_notes`
  - 人工备注或脚本附加说明
  - 例如 `local_fallback` 表示该条记录来自本地规则兜底

## 建议用法

1. 先让 AI 产出预解析 JSON。
2. 将 JSON 丢进本工具。
3. 重点检查低置信度、冲突项、未匹配项。
4. 导出修订后的 JSON，作为后续词库沉淀或业务确认输入。
