# 当前正式入口

当前正式工作区已经收口到最外层目录 `gb_pipeline_v2/`。

以后只需要进入这个目录执行：

```bash
cd gb_pipeline_v2
```

在这个工作区内部，唯一正式代码入口是 `pipeline_v2`。

## 命令入口

### Step 1

```bash
python3 -m pipeline_v2 step1-extract --pdf <pdf_path> --output <output_dir>
```

### Step 2

```bash
python3 -m pipeline_v2 step2-prepare --components <components.json> --step1-source <step1_dir> --output <step2_dir>
python3 -m pipeline_v2 step2-execute --components <components.json> --step1-source <step1_dir> --output <step2_dir>
python3 -m pipeline_v2 step2-synthesize --output <step2_dir>
```

如需直接调用底层预处理引擎：

```bash
python3 -m pipeline_v2 step2-legacy-preprocess --components <components.json> --step1-source <step1_dir> --output <step2_dir>
```

### Step 3

```bash
python3 -m pipeline_v2 step3-execute --step1-table-regions <table_regions.json> --step2-result <component_matching_result.json> --components <components.json> --output <step3_dir>
python3 -m pipeline_v2 step3-build-review-queue --step3-result <step3_result.json> --output <review_ledger.json>
python3 -m pipeline_v2 step3-forced-match --items-file <items.json> --component-type <name> --components <components.json>
```

默认配置文件位置：

```text
pipeline_v2/step3_engine/runtime_config.ini
```

### Step 4

```bash
python3 -m pipeline_v2 step4-direct-match --step3-result <step3_result.json> --components <components.json> --output <step4_dir>
```

## 当前实现目录

- `pipeline_v2/step1_chapter_ocr/`
- `pipeline_v2/step2_engine/`
- `pipeline_v2/step2_v2.py`
- `pipeline_v2/step3_engine/`
- `pipeline_v2/step3_v2.py`
- `pipeline_v2/step4_direct_match.py`

## 当前工作区目录

- `pipeline_v2/`：唯一正式执行入口
- `data/`：当前工作区自己的输入、输出、人工复核和运行缓存
- `docs/`：当前主线说明与变更记录
- `scripts/`：主线辅助脚本
- `tools/`：构件库与人工复核工具
- `tests/`：主线测试

## 已废弃

以下旧入口已移除，不再作为主线使用：

- 根目录 `step2_component_match/`
- 根目录 `step3_filter_condition_match/`
- 旧的 Step1/Step2/Step3 启动脚本
- 旧的分步操作文档 `docs/step1/`、`docs/step2/`、`docs/step3/`

仓库根目录中遗留的历史运行产物仅作为历史保留，不再作为正式执行位置。
