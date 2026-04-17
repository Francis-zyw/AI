# Step3 检索增强版使用说明

## 概述

Step3 检索增强版基于知识库中心（Knowledge Base Center）为 Step3 提供检索增强（RAG）能力。相比传统版本，检索增强版能够：

1. **自动检索相关知识**：从知识库中检索 Step1 原始清单、Step2 构件映射、构件 Wiki、章节 Wiki 等相关知识
2. **提供证据链**：每个判断都有检索证据支持，可追溯可验证
3. **减少幻觉**：基于真实检索结果而非模型记忆进行判断

## 文件结构

```
pipeline_v2/
├── step3_v2_retrieval.py              # 检索增强版主模块
└── step3_engine/
    ├── retrieval_context.py           # 检索上下文构建器
    ├── step3_retrieval_api.py         # 检索增强版 API
    └── prompt_template_retrieval_v1.txt  # 检索增强版 Prompt 模板
```

知识库中心（独立于项目代码）：

```
/Users/zhangkaiye/AI数据/知识库中心/
├── global/                            # 全局知识库
├── manifests/                         # 构建清单
└── projects/智能提量工具/
    ├── project_knowledge_v1/
    │   ├── knowledge.db               # SQLite 向量数据库
    │   ├── wiki/                      # Wiki 页面
    │   │   ├── components/            # 构件知识页
    │   │   ├── chapters/              # 章节知识页
    │   │   └── summaries/             # 摘要页
    │   └── knowledge_ingest_summary.json
    ├── sources/                       # 源文档
    └── step3_retrieval_prompt_v1.txt  # Prompt 模板源文件
```

## 快速开始

### 1. 命令行使用

```bash
cd /Users/zhangkaiye/AI数据/AI智能提量/智能提量处理流程/智能提量工具

python3 -m pipeline_v2.step3_engine.step3_retrieval_api \
    --step1 data/output/step1/run-20260327-1810-newentry-full/structured_bill_items.json \
    --local data/output/step3/run-20260330/local_rule_project_component_feature_calc_result.json \
    --output data/output/step3/run-$(date +%Y%m%d)-retrieval \
    --standard "GB50500-2024" \
    --model gpt-4o \
    --batch-size 20
```

### 2. Python API 使用

```python
from pipeline_v2.step3_v2_retrieval import run_step3_retrieval

result = run_step3_retrieval(
    step1_json_path="data/output/step1/run-20260327-1810-newentry-full/structured_bill_items.json",
    local_result_json_path="data/output/step3/run-20260330/local_rule_project_component_feature_calc_result.json",
    output_dir="data/output/step3/run-20260414-retrieval",
    standard_document="GB50500-2024",
    model="gpt-4o",
    batch_size=20,
)

print(f"Processed {len(result['rows'])} rows")
```

### 3. 仅使用检索上下文构建

```python
from pipeline_v2.step3_v2_retrieval import build_retrieval_context_batch

context_by_row_id = build_retrieval_context_batch(
    knowledge_db_path="/Users/zhangkaiye/AI数据/知识库中心/projects/智能提量工具/project_knowledge_v1/knowledge.db",
    step1_rows=[
        {
            "row_id": "R0001",
            "project_code": "010501003",
            "project_name": "直行墙",
            "project_features": "混凝土强度等级:C30",
            "chapter_title": "混凝土及钢筋混凝土工程",
        }
    ],
    local_rows_by_row_id={
        "R0001": [{"row_id": "R0001", "resolved_component_name": "砼墙"}]
    },
)

# 查看检索结果
context = context_by_row_id["R0001"]
print(f"Step1 hits: {len(context['step1_entry_hits'])}")
print(f"Component wiki hits: {len(context['component_wiki_hits'])}")
```

## 检索上下文结构

检索增强版会为每行清单构建以下上下文：

```json
{
  "database_principles": {
    "title": "AI 对量核心执行理念",
    "content": "..."
  },
  "step1_entry_hits": [
    {
      "entry_id": "step1_row_xxx",
      "stage": "step1_row",
      "title": "Step1 清单行 | 010501003 直行墙",
      "content": "...",
      "similarity": 0.85
    }
  ],
  "step2_entry_hits": [
    {
      "entry_id": "step2_mapping_xxx",
      "stage": "step2_mapping",
      "title": "Step2 构件映射 | 砼墙",
      "component_type": "砼墙",
      "similarity": 0.72
    }
  ],
  "component_wiki_hits": [
    {
      "slug": "component-砼墙",
      "title": "砼墙 构件知识页",
      "component_type": "砼墙",
      "similarity": 0.68
    }
  ],
  "chapter_wiki_hits": [
    {
      "slug": "chapter-混凝土工程",
      "title": "混凝土及钢筋混凝土工程",
      "similarity": 0.75
    }
  ],
  "component_catalog_hits": [
    {
      "entry_id": "component_catalog_xxx",
      "component_type": "砼墙",
      "content": "属性: 墙厚(HD), 混凝土强度等级(TBH)...",
      "similarity": 0.91
    }
  ]
}
```

## 环境变量

- `OPENAI_API_KEY`: OpenAI API 密钥
- `OPENAI_BASE_URL`: OpenAI API 基础 URL（可选，用于第三方代理）

## 模型配置

检索增强版支持通过 `pipeline_v2/model_runtime.py` 中的配置加载模型设置：

```python
# config/step3_model.json
{
  "model": "gpt-4o",
  "reasoning_effort": "high",
  "openai_api_key": "sk-...",
  "openai_base_url": "https://api.openai.com/v1"
}
```

## 与原版 Step3 的区别

| 特性 | 原版 Step3 | 检索增强版 Step3 |
|------|-----------|----------------|
| 知识来源 | 本地规则 + 模型记忆 | 知识库检索 + 本地规则 + 模型推理 |
| 证据可追溯 | 有限 | 每条判断都有检索证据 |
| Prompt 复杂度 | 中等 | 较高（包含检索上下文） |
| 处理速度 | 较快 | 稍慢（需要检索） |
| 幻觉风险 | 中等 | 较低 |
| 适用场景 | 快速处理、标准场景 | 高精度、复杂场景 |

## 故障排查

### 知识库不存在

```
FileNotFoundError: Knowledge database not found: ...
```

**解决**: 先运行知识库构建脚本：

```bash
cd /Users/zhangkaiye/AI数据/知识库中心/projects/智能提量工具
python3 build_first_project_wiki.py
```

### 检索结果为空

**检查**: 
1. 知识库是否已正确构建
2. 查询文本是否正确编码
3. 向量维度是否匹配（默认 192）

### 模型调用失败

**检查**:
1. API 密钥是否正确设置
2. 模型名称是否有效
3. 网络连接是否正常

## 更新知识库

当 Step1/Step2 数据更新后，需要重新构建知识库：

```bash
cd /Users/zhangkaiye/AI数据/知识库中心/projects/智能提量工具
python3 build_first_project_wiki.py \
    --step1 /path/to/new/step1/output \
    --step2 /path/to/new/step2/output \
    --components /path/to/components.json
```

## 扩展知识库

如需添加新的知识源，编辑 `manifests/project_智能提量工具_manifest.json`：

```json
{
  "sources": [
    {
      "path": "/path/to/new/source",
      "collection": "new_collection",
      "source_type": "documentation",
      "tags": ["new", "source"]
    }
  ]
}
```

然后重新运行构建脚本。
