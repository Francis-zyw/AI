<!--
Sync Impact Report
- Version: 0.0.0 → 1.0.0 (MAJOR: initial constitution)
- Added principles: Pipeline-First, Single HTML Tool, Data Contract, Knowledge Feedback Loop, CLI Entry Point
- Added sections: Technology Constraints, Development Workflow
- Templates requiring updates: ✅ none (first constitution, templates are stock)
- Follow-up TODOs: none
-->

# 智能提量工具 Constitution

## Core Principles

### I. Pipeline-First

每个功能 MUST 作为 `pipeline_v2/` 中的独立步骤实现。
- 步骤之间通过 JSON 文件传递数据，禁止内存共享或隐式耦合
- 每个步骤 MUST 有明确的输入路径和输出路径
- 步骤可独立运行和调试，支持中断后从断点续跑
- 新步骤命名遵循 `stepN_<功能>.py` 约定

### II. Single HTML Tool

面向产品/业务人员的交互式工具 MUST 采用"Python 生成器 + 单 HTML"模式。
- Python 脚本负责数据预处理并生成自包含 HTML 文件
- HTML 文件零外部依赖（CSS/JS 内联），可直接双击打开
- 仅允许通过 CDN 引入 SheetJS 等纯前端库用于导出功能
- 禁止引入前端框架（React/Vue/Angular）

### III. Data Contract

步骤间的 JSON 数据结构 MUST 有明确契约。
- `contracts.py` 定义所有步骤的输入/输出 schema
- 字段名使用 snake_case，值类型在契约中显式声明
- 破坏性变更 MUST 递增 schema 版本号并提供迁移说明
- 步骤启动时 SHOULD 校验输入数据是否符合契约

### IV. Knowledge Feedback Loop

匹配结果和人工审核 MUST 沉淀到知识库中心 Wiki。
- 审核工具产出的补丁通过 `wiki_patch_import.py` 导入 Wiki
- 同义词、特征映射等知识写入 `知识库中心/wiki/构件类型/` 下对应页面
- Wiki 知识在下次流水线运行时 MUST 被自动加载（通过 `wiki_retriever.py`）
- 禁止人工审核结果仅保留在本地而不回写知识库

### V. CLI Entry Point

所有可执行功能 MUST 通过 `python3 -m pipeline_v2 <command>` 统一入口暴露。
- `cli.py` 注册所有子命令，禁止绕过 CLI 直接调用内部模块
- 输入参数支持命令行参数和 `.ini` 配置文件两种方式
- 错误信息输出到 stderr，结构化结果输出到 stdout 或文件
- 长时运行任务 MUST 输出进度信息

## Technology Constraints

- **语言**: Python 3.11+，禁止引入其他后端语言
- **LLM 调用**: 通过 `model_runtime.py` 统一管理，支持 OpenAI/Gemini provider 切换
- **依赖管理**: 仅允许标准库 + 已在项目中使用的第三方包；新增依赖需说明理由
- **数据存储**: 所有中间结果和最终产物以 JSON 文件持久化到 `data/output/`
- **前端**: 纯 HTML + 内嵌 CSS/JS，localStorage 用于用户状态持久化
- **测试**: `tests/` 目录，pytest 框架

## Development Workflow

- 每个功能变更从 `spec.md` 开始，经 `plan.md` → `tasks.md` 拆解后实施
- 代码变更 MUST 在对应步骤的输出上验证通过后再提交
- 人工审核工具的变更 MUST 用真实数据（`data/output/` 下的实际运行结果）验证
- `分析工具/` 目录已归档，禁止新增或修改其中内容
- Git 提交消息遵循 Conventional Commits 格式

## Governance

本 Constitution 是智能提量工具项目的最高开发准则。所有 spec、plan、task
和代码变更 MUST 遵守上述原则。

- 修订 MUST 更新版本号并记录变更内容
- 原则冲突时，Pipeline-First 和 Data Contract 优先级最高
- 参考 `README.md` 获取运行时命令和目录结构说明

**Version**: 1.0.0 | **Ratified**: 2026-04-17 | **Last Amended**: 2026-04-17
