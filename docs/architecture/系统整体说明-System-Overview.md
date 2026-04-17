# 系统整体说明 System Overview

## 0. 文档定位 Document Purpose

本文档是当前项目的统一总说明文档，也是后续功能补充、架构调整、模块扩展、运行方式更新的主维护文档。

This document is the single source of truth for the project. Future feature notes, architecture changes, module extensions, and runbook updates should be added here first.

后续维护约定：

- 新功能增加时，先更新本文档，再更新对应模块文档
- 重大结构调整时，在本文档中补充“变更记录 Change Log”
- 分阶段能力说明，以本文档为总入口，再链接到子文档

## 1. 项目目标 Project Goal

本项目用于对国标类 PDF 文档进行分阶段解析，将原始标准文档逐步转换为适合后续规则抽取、表格提取、构件识别和知识整理的结构化数据。

The project is designed to parse GB-standard PDF documents in stages and progressively transform raw documents into structured data for downstream rule extraction, table parsing, component recognition, and knowledge organization.

当前核心目标：

1. 识别文档正文有效范围 Valid body range detection
2. 按章节切分文档 Chapter-aware segmentation
3. 为后续表格和规则抽取提供筛选数据 Structured filtering data for later parsing
4. 逐步扩展 OCR、表格、规则和构件识别能力 Progressive extension for OCR, table extraction, rule parsing, and component matching

## 2. 当前系统状态 Current Status

当前已完成第一步功能 Step 1：

- 根据 PDF 页签 / 目录识别正文范围
- 排除封面、公告、前言、目录等前置无效内容
- 按任意层级目录递归切分文本
- 生成区域树与文本的映射结果
- 支持代码调用 Python API
- 支持命令行运行 CLI
- 支持 Windows / macOS 启动脚本
- 已预留 PaddleOCR fallback provider 接口
- 已纳入构件类型-属性库维护工具，并统一输出到 `data/input/`

当前已补充第二步功能 Step 2：

- 自动读取构件列表与 Step 1 章节索引 / 区域结果
- 自动组装构件名称预解析提示词
- 调用大模型生成“构件列表名称 -> 国标实际构件名称”的匹配结果
- 从匹配结果进一步聚合同义词库
- 输出到 `data/output/step2/`

当前已补充第三步功能 Step 3：

- 读取 Step 1 的 `table_regions.json`
- 同时拆解章节非表格说明、表格间补充说明、章节末尾“其他规定”
- 读取 Step 2 的 `synonym_library.json`
- 读取 `components.json` 自动沉淀构件来源表
- 生成 Step 3 正式提示词文档
- 调用模型校正“清单-构件-项目特征表达式-计算项目”中间表
- 将清单项目匹配到候选构件类型、项目特征表达式与计算项目代码
- 支持把章节补充规则挂接到清单行，参与额外构件归属、项目特征补充和计算项目判断
- 输出最终中间匹配结果到 `data/output/step3/`

Current implementation status:

- Step 1 is available and usable
- The system can process a PDF by path input
- The result can be returned in memory or written to structured output folders
- OCR fallback architecture is reserved for future use

## 3. 系统处理流程 Processing Flow

推荐的整体处理链路如下：

```text
Input PDF / Image
    ↓
Document Detection 文档检测
    ↓
Body Range Detection 正文范围识别
    ↓
Chapter Segmentation 章节切分
    ↓
Section-level Text Mapping 章节文本映射
    ↓
Region Tree Export 区域树输出
    ↓
Table Extraction 表格抽取
    ↓
Rule Parsing 规则解析
    ↓
Component Matching 构件匹配
    ↓
Structured Output 结构化输出
```

当前主线已经落地的是：

- `Body Range Detection`
- `Chapter Segmentation`
- `Section-level Text Mapping`
- `Component Matching Preprocess`
- `Filter Condition Matching`

当前已纳入的辅助维护链路：

- `Component Type Attribute Library Maintenance`
  - 用于持续更新构件类型库数据
  - 作为后续构件识别、属性筛选和规则匹配的基础输入

- `Component Matching Review Tool`
  - 用于查看和人工修订 Step 2 的匹配结果 JSON
  - 作为主流程之外的后置补充修订工具

## 4. 当前架构 Architecture

### 4.1 代码主线 Main Code Path

当前主线代码包：

- `step1_chapter_ocr/`
- `step2_component_match/`
- `step3_filter_condition_match/`

模块职责：

- `api.py`
  - 对外统一入口 Unified public entry
  - 提供代码调用和 CLI 调用

- `core.py`
  - 主流程 orchestration
  - 负责正文识别、章节切分、结果组装

- `providers.py`
  - 文本获取适配层 text extraction provider layer
  - 当前包含 `TextLayerProvider`
  - 已预留 `PaddleOCRProvider`

- `models.py`
  - 结构化结果模型 structured result models

- `chapter_ocr_pipeline.py`
  - 兼容脚本入口 backward-compatible script entry

### 4.2 构件预匹配模块 Step 2

- `step2_component_match/api.py`
  - 自动读取构件列表与 Step 1 输出
  - 生成预处理后的组件/章节输入
  - 以 `instructions + components.txt + chapter.txt` 形式逐章调用大模型
  - 输出构件匹配结果与同义词库

- `step2_component_match/chapter_match_instructions.txt`
  - Step 2 章节匹配说明模板

### 4.3 筛选条件匹配模块 Step 3

- `step3_filter_condition_match/api.py`
  - 读取步骤二主表结果
  - 构建自动套来源表
  - 生成提示词并调用模型
  - 将“量筋构件”匹配为筛选条件结果
  - 输出 JSON、Markdown 和 prompt 文档

- `step3_filter_condition_match/prompt_template.txt`
  - Step 3 使用的正式提示词模板

### 4.4 数据分层 Data Layout

当前数据目录：

- `data/input/`
  - 输入 PDF、样例文件、构件基础库数据 input files and shared library data
  - 当前同时放置：
    - PDF input files
    - `components.json`
    - `components.jsonl`
    - `component_type_attribute_excels/`

- `data/output/step1/`
  - 第一步章节识别输出 step 1 outputs

- `data/output/step2/`
  - 第二步构件预匹配输出 step 2 outputs

- `data/output/step3/`
  - 第三步筛选条件匹配输出 step 3 outputs

- `data/cache/`
  - 运行缓存 runtime cache

- `data/temp/`
  - 临时文件 temporary files

- `data/logs/`
  - 日志 logs

### 4.5 文档分层 Documentation Layout

- `docs/architecture/`
  - 系统说明、目录设计、总体架构

- `docs/plans/`
  - 流程方案、阶段计划

- `docs/step1/`
  - 第一步实现说明、运行说明

- `docs/step2/`
  - 第二步构件预匹配说明

- `docs/step3/`
  - 第三步筛选条件匹配说明

### 4.6 辅助工具层 Support Tools

- `tools/tool_component_type_library/`
  - 构件类型-属性库维护工具
  - 用于平时空闲时批量更新构件库
  - 默认将结果写回 `data/input/`

- `tools/tool_component_match_review/`
  - 构件匹配结果人工修订工具
  - 用于对 Step 2 输出 JSON 做可视化查看、修改与重新导出

## 5. 目录结构 Folder Structure

```text
智能提量工具/
├── data/
│   ├── input/
│   ├── output/
│   │   ├── step1/
│   │   ├── step2/
│   │   └── step3/
│   ├── cache/
│   ├── temp/
│   └── logs/
├── docs/
│   ├── architecture/
│   ├── plans/
│   ├── step1/
│   ├── step2/
│   └── step3/
├── scripts/
├── step1_chapter_ocr/
├── step2_component_match/
├── step3_filter_condition_match/
├── tools/
│   ├── tool_component_match_review/
│   └── tool_component_type_library/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/
│   └── manual/
├── legacy/
│   ├── prototypes/
│   └── reference_data/
└── 分析工具/venv/
```

说明：

- `legacy/` 中保存历史原型，不作为当前主开发区
- `step1_chapter_ocr/` 是当前正式主线
- `tools/tool_component_type_library/` 是当前正式的构件库维护入口
- 后续新阶段建议继续分层扩展，而不是把新能力直接堆到旧脚本中

## 6. 调用方式 How To Use

### 6.1 Python API

```python
from step1_chapter_ocr import process_pdf

result = process_pdf(
    "data/input/房屋建筑与装饰工程工程量计算标准.pdf"
)

data = result.to_dict()
print(data["summary"])
```

### 6.2 CLI

```bash
../分析工具/venv/bin/python -m step1_chapter_ocr \
  --pdf data/input/房屋建筑与装饰工程工程量计算标准.pdf
```

### 6.3 Script Launcher

- Windows: `scripts/step1_select_pdf.bat`
- macOS: `scripts/step1_select_pdf_mac.command`

这两个启动脚本都支持先弹窗选择 PDF，再自动调用主流程。

Both launchers open a file chooser first and then call the main pipeline automatically.

### 6.4 Component Library Maintenance

命令行更新构件类型-属性库：

```bash
python3 tools/tool_component_type_library/batch_convert.py
```

代码调用方式：

```python
from tools.tool_component_type_library import build_component_library

components = build_component_library()
```

默认路径约定：

- Source Excel directory: `data/input/component_type_attribute_excels/`
- Output JSONL: `data/input/components.jsonl`
- Output JSON: `data/input/components.json`

## 7. OCR 策略 OCR Strategy

当前策略 Current strategy：

- 优先使用文本层 Text-layer first
- 当后续启用 OCR 时，再走 provider fallback

推荐主方案 Recommended primary OCR:

- `PaddleOCR`

推荐原因：

- 对中文文档更友好 better Chinese OCR support
- 更适合版面、表格、文档场景 better for document layout and table-related tasks
- 更容易与后续步骤集成 easier integration with later stages

备用方案 Backup option:

- `Tesseract`

当前状态：

- `PaddleOCRProvider` 已保留接口
- 自动安装逻辑已接入
- 真正的生产级 OCR fallback 仍建议在后续阶段中继续完善

## 8. 当前输出结果 Current Outputs

对于单个 PDF，当前 Step 1 输出包括：

- `catalog_summary.json`
  - 目录范围、正文范围、章节统计
  - 包含 `table_counts`

- `outline_entries.json`
  - PDF 页签 / 目录结构映射

- `flat_regions.json`
  - 所有层级区域的扁平映射
  - 每个区域还包含：
    - `content_blocks`
    - `non_table_text`
    - `tables`
  - 表格行默认仅保留主字段
  - 已补充对列内换行、跨行和跨页合并内容的处理

- `chapter_regions/chapter_index.json`
  - Step 1 按顶级章节拆分后的统一索引
  - Step 2 默认优先读取这个文件

- `chapter_regions/*.json`
  - 每个顶级章节单独一份 JSON
  - 内部包含该章节下所有子区域，便于按章节分批调用

- `region_tree.json`
  - 按父子关系组织的区域树

- `table_regions.json`
  - 仅保留包含表格的区域
  - 适合后续直接做项目编码、项目名称、项目特征等字段解析

- `region_texts/`
  - 每个区域节点对应的文本文件

辅助维护输出 additional maintained inputs:

- `data/input/components.json`
  - 构件类型-属性库主 JSON 文件

- `data/input/components.jsonl`
  - 构件类型-属性库主 JSONL 文件

当前 Step 3 输出包括：

- `normalized_step1_rows.json`
  - 归一化并做过基础修复的 Step 1 清单行数据

- `chapter_rule_catalog.json`
  - 从章节说明中抽取出的补充规则目录

- `component_source_table.json`
  - 从构件库与 Step 2 同义词库沉淀出的构件来源表

- `local_rule_project_component_feature_calc_result.json`
  - 本地规则生成的中间匹配结果

- `project_component_feature_calc_matching_result.json`
  - 最终“清单-构件-项目特征表达式-计算项目”结果

- `project_component_feature_calc_matching_result.md`
  - 便于人工复核的 Markdown 表格版本

## 9. 后续开发路线 Roadmap

建议后续按阶段扩展：

### Step 2. 表格识别 Table Extraction

- 章节内表格区域定位
- 表格文本与结构抽取
- 表格和章节的对应关系建立

### Step 3. 规则解析 Rule Parsing

- 项目编码 parsing
- 项目名称 parsing
- 项目特征 parsing
- 计量单位 parsing
- 计算规则 parsing

### Step 4. 构件匹配 Component Matching

- 构件词典匹配 dictionary-based matching
- 同义词归并 synonym normalization
- 章节 / 条目 / 构件映射构建

### Step 5. 结构化输出 Structured Export

- JSON / JSONL output
- 检索友好结构 search-friendly format
- 后续知识库或图谱输入 downstream knowledge base input

## 10. 开发约束 Development Principles

后续继续开发时建议遵循：

1. 入口统一 Unified entry
   - 对外优先通过 `api.py` 暴露

2. 方法可替换 Replaceable providers
   - 不把 OCR、文本层、远程接口写死到主流程

3. 输出路径统一 Unified output layout
   - 统一写入 `data/output/<stage>/`

4. 文档先行 Documentation first
   - 新能力先补本文档，再补子模块说明

5. 历史代码隔离 Legacy isolation
   - 不把旧原型重新混回主开发区

## 11. 后续补充维护方式 Future Update Rules

从现在开始，后续涉及本系统的补充说明，统一优先更新本文档，再按需要更新对应子文档。

Maintenance rule from now on:

- Update this overview first for any major functional or architectural change
- Then update module-specific documents if needed

建议后续在本文档持续补充以下内容：

- 新功能说明 New features
- 目录变更 Structure changes
- 接口变更 API changes
- 依赖变更 Dependency updates
- OCR 策略变化 OCR strategy updates
- 输出格式变化 Output format updates

## 12. 变更记录 Change Log

- 2026-03-24
  - Step 4 从纯本地直匹配扩展为“本地候选 + 可选模型精修”双阶段流程
  - 新增 `pipeline_v2/step4_runtime_config.ini`
  - 新增 `docs/step4/README.md`
  - 新增 `docs/step4/runtime_config.example.ini`

- 2026-03-20
  - 新增 `step3_filter_condition_match/`
  - 新增 `docs/step3/README.md`
  - 新增 `data/output/step3/` 输出约定

### 2026-03-19

- 完成 Step 1 主线功能
- 建立统一目录结构
- 清理旧测试数据和主开发区无关原型
- 增加 Windows / macOS 启动脚本
- 建立本文档作为后续统一维护入口
- 将 Step 1 从固定两级切分改为任意层级区域树导出
