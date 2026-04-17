# 2026-03-27 官方工作区收口记录

## 本次目标

- 在仓库最外层新增 `gb_pipeline_v2/` 官方工作区
- 以后所有新执行统一在 `gb_pipeline_v2/` 内进行
- 把主线代码、主线说明、主线工具和主线测试收进同一个目录
- 给新工作区补齐独立的数据骨架，避免继续依赖仓库根目录

## 收口结果

- `gb_pipeline_v2/pipeline_v2/`：唯一正式执行入口
- `gb_pipeline_v2/data/input/`：迁入当前稳定输入文件和构件库
- `gb_pipeline_v2/data/reference/`：迁入参考目录
- `gb_pipeline_v2/data/source/`：迁入源数据目录
- `gb_pipeline_v2/data/manual_reviews/`：迁入人工复核结果
- `gb_pipeline_v2/data/published/`：迁入发布目录
- `gb_pipeline_v2/data/output/`：新建干净输出目录
- `gb_pipeline_v2/data/workspaces_v2/`：新建干净运行工作区目录
- `gb_pipeline_v2/docs/`、`gb_pipeline_v2/scripts/`、`gb_pipeline_v2/tools/`、`gb_pipeline_v2/tests/`：统一迁入官方工作区

## 执行原则

以后运行命令统一从 `gb_pipeline_v2/` 目录开始，例如：

```bash
cd gb_pipeline_v2
python3 -m pipeline_v2 --help
```

## 历史数据说明

仓库根目录下旧的 `data/output/`、`data/workspaces_v2/` 等历史运行产物保留为历史参考，不再作为当前主线工作区使用。
