# 全局通用知识库使用指南

## 1. 目标

这套全局知识库不是为某一个项目单独准备的，而是为“你长期沉淀和复用所有知识”准备的。

它适合承载：

- 个人长期知识
- 项目方法论
- 行业规范
- 文档、笔记、代码说明
- 历史项目总结
- 人工确认后的高质量样本

你可以把它理解成：

- `全局库`：你的长期知识大脑
- `项目库`：某个具体任务的局部工作记忆

推荐关系：

1. 全局库长期维护
2. 项目执行时优先查项目库
3. 项目库缺内容时再回退查全局库

---

## 2. 当前实现能力

新增命令：

1. `global-kb-build`
   - 从任意文件、目录、manifest 构建全局库
2. `global-kb-query`
   - 按 query + collection/tag 检索

输出：

- `global_knowledge.db`
- `wiki/overview.md`
- `wiki/collections/*.md`
- `wiki/tags/*.md`
- `wiki/source_types/*.md`
- `global_knowledge_ingest_summary.json`
- `global_knowledge_query_result.json`

---

## 3. 全局库的数据模型

### 3.1 document 层

底层存的是 `global_documents`，每条记录包含：

- `collection`
- `source_type`
- `title`
- `content`
- `source_path`
- `source_ref`
- `tags`
- `metadata`
- `vector`

这层是检索证据层。

### 3.2 wiki 层

系统会自动从 document 层编译 wiki 页面：

- `overview`
- `collection pages`
- `tag pages`
- `source type pages`

这层是知识组织层。

---

## 4. 推荐目录组织

建议长期固定一套目录：

```text
data/
  knowledge/
    global/
      global_knowledge.db
      global_knowledge_ingest_summary.json
      global_knowledge_query_result.json
      wiki/
    manifests/
      global_kb_manifest.example.json
```

如果你想再细分，也可以：

```text
data/knowledge/global/personal/
data/knowledge/global/work/
data/knowledge/global/engineering/
```

---

## 5. 最简单的用法

### 5.1 直接 ingest 目录

```bash
python3 -m pipeline_v2 global-kb-build \
  --source /Users/zhangkaiye/Notes \
  --source /Users/zhangkaiye/Projects \
  --output-dir data/knowledge/global \
  --default-collection general
```

### 5.2 查询

```bash
python3 -m pipeline_v2 global-kb-query \
  --knowledge-base data/knowledge/global \
  --query "向量数据库 LLM wiki 上下文工程"
```

---

## 6. 推荐用 manifest 驱动

长期使用建议改成 manifest。

原因：

- collection 更清晰
- tags 更稳定
- 可控哪些目录递归
- 可控包含和排除规则
- 后续维护不会越来越乱

示例：

```bash
python3 -m pipeline_v2 global-kb-build \
  --manifest docs/knowledge/global_kb_manifest.example.json \
  --output-dir data/knowledge/global
```

---

## 7. manifest 结构说明

manifest 顶层结构：

```json
{
  "default_collection": "general",
  "sources": [
    {
      "path": "...",
      "collection": "personal_notes",
      "source_type": "markdown",
      "tags": ["personal", "notes"],
      "recursive": true,
      "include_globs": ["**/*.md"],
      "exclude_globs": ["**/.git/**", "**/node_modules/**"]
    }
  ]
}
```

字段说明：

- `path`
  - 文件或目录
- `collection`
  - 逻辑知识域，例如 `personal_notes`、`engineering_rules`
- `source_type`
  - 来源类型，例如 `markdown`、`json`、`code`
- `tags`
  - 主题标签
- `recursive`
  - 是否递归读取目录
- `include_globs`
  - 只 ingest 符合规则的文件
- `exclude_globs`
  - 排除文件
- `content_fields`
  - 用于 JSON/JSONL 字段抽取
- `metadata_fields`
  - 用于 JSON/JSONL 元数据抽取

---

## 8. collection 应该怎么设计

推荐按“知识域”分，而不是按文件夹名分。

例如：

- `personal_notes`
- `engineering_rules`
- `project_postmortems`
- `llm_methods`
- `building_costing`
- `reviewed_examples`

不要分得太碎。

经验上：

- 5 到 15 个 collection 最容易维护
- 太少会混
- 太多会查不准

---

## 9. tag 应该怎么设计

tag 用来做横向切片。

例如：

- `llm`
- `rag`
- `vector-db`
- `wiki`
- `costing`
- `step4`
- `reviewed`
- `prompt-engineering`

推荐规则：

- tag 表示主题
- collection 表示知识域

---

## 10. 文件 ingest 规则

当前全局库支持：

- Markdown
- Text
- JSON
- JSONL
- CSV/TSV
- YAML/INI/CFG
- 常见代码文件

处理方式：

1. 文本类文件
   - 读取文本
   - 自动分 chunk
   - 每个 chunk 存成 document
2. JSON/JSONL
   - 尝试按 item 拆分
   - 或按顶层 key 拆分
   - 再切 chunk

这意味着它非常适合 ingest：

- 读书笔记
- Markdown 知识卡片
- 项目总结
- 结构化样本库
- 配置说明
- 工程输出 JSON

---

## 11. 查询机制

查询时支持：

- query 文本
- collection 过滤
- tag 过滤

命令示例：

```bash
python3 -m pipeline_v2 global-kb-query \
  --knowledge-base data/knowledge/global \
  --query "建筑清单 墙厚 体积规则" \
  --collection building_costing \
  --tag reviewed
```

系统会返回两类结果：

1. `retrieved_documents`
   - 具体证据
2. `retrieved_wiki_pages`
   - 组织性摘要页

---

## 12. 如何持续补充你的全局知识

推荐维护模式：

### 模式 A：重建式

每次更新知识源后重新执行：

```bash
python3 -m pipeline_v2 global-kb-build \
  --manifest docs/knowledge/global_kb_manifest.example.json \
  --output-dir data/knowledge/global
```

优点：

- 最稳
- 不容易积累脏数据
- 结果可重复

### 模式 B：定期批量更新

例如每周或每完成一个项目：

1. 把新资料放进固定目录
2. 统一重建一次全局库

### 模式 C：高质量样本回灌

把人工确认过的内容单独放到一个 collection：

- `reviewed_examples`
- `project_postmortems`
- `best_practices`

这类内容通常价值最高。

---

## 13. 推荐你马上这样用

如果你是想把它变成“长期总知识库”，建议第一批先 ingest 这些：

1. 你的长期 Markdown 笔记
2. 历史项目总结
3. 高质量规范文档
4. 当前这个工程的 Step1-Step4 结果摘要
5. 人工确认过的业务样本

不要第一天就把所有杂乱文件全灌进去。

先保证“高质量、可复用、结构相对清晰”。

---

## 14. 如何和当前项目知识库配合

推荐用法不是二选一，而是分层：

1. `global-kb`
   - 负责长期通用知识
2. `project step knowledge`
   - 负责当前工程的短中期知识

未来最理想的调用链是：

1. 先查项目知识库
2. 如果召回不足，再查全局知识库
3. 把两者合并给任务模型

这样既能保证准确，也能保证长期复用。

---

## 15. 后续增强建议

下一阶段最值得做的不是继续堆功能，而是三件事：

1. 增加 `review_status / source_run_id / updated_at`
2. 引入真正 embedding
3. 做“项目库优先、全局库回退”的双层路由

---

## 16. 一句话建议

把这套全局知识库当成“你长期知识资产的操作系统”，不要当成“某个项目顺手做的缓存”。

