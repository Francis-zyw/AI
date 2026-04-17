# 2026-03-27 Pipeline V2 单入口收口记录

## 本次目标

- 不再保留旧的 Step1/Step2/Step3 兼容入口
- 统一以 `pipeline_v2` 作为唯一正式入口
- 把仍然需要使用的 Step1/2/3 实现目录收口到 `pipeline_v2/`
- 删除旧启动脚本、旧分步操作文档和历史原型目录

## 目录调整

### 保留并迁入主线

- `step1_chapter_ocr/` -> `pipeline_v2/step1_chapter_ocr/`
- `pipeline_v2/reused_step2_component_match/` -> `pipeline_v2/step2_engine/`
- `pipeline_v2/reused_step3_filter_condition_match/` -> `pipeline_v2/step3_engine/`
- `step3_filter_condition_match/runtime_config.ini` -> `pipeline_v2/step3_engine/runtime_config.ini`

### 新增正式说明

- `docs/current-pipeline.md`

## CLI 收口

当前正式入口全部改为：

```bash
python3 -m pipeline_v2 step1-extract ...
python3 -m pipeline_v2 step2-prepare ...
python3 -m pipeline_v2 step2-execute ...
python3 -m pipeline_v2 step2-synthesize ...
python3 -m pipeline_v2 step3-execute ...
python3 -m pipeline_v2 step3-build-review-queue ...
python3 -m pipeline_v2 step3-forced-match ...
python3 -m pipeline_v2 step4-direct-match ...
```

## 已删除

- 根目录 `step2_component_match/`
- 根目录 `step3_filter_condition_match/`
- `docs/step1/`
- `docs/step2/`
- `docs/step3/`
- `legacy/`
- 旧 Step1/Step2/Step3 启动脚本
- 仓库中的 `.DS_Store`
- `pipeline_v2/step1_chapter_ocr/chapter_ocr_pipeline.py`
- `pipeline_v2/step1_chapter_ocr/__main__.py`

## 代码同步

- 主线代码与测试导入路径统一切到 `pipeline_v2.*`
- Step3 默认配置审计位置改到 `pipeline_v2/step3_engine/runtime_config.ini`
- Step2/Step3 运行提示文案改成新主线路径

## Git 收尾建议

- 只 stage 本次代码与文档收口相关文件
- 不把 `data/output/`、`data/workspaces_v2/` 下现有业务运行产物混进本次提交
- 建议提交信息：

```text
refactor: consolidate GB pipeline into pipeline_v2 single entry
```
