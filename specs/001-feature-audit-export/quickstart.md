# Quickstart: 项目特征审核导出工具

**Phase 1 Output** | **Date**: 2026-04-17

## Prerequisites

- Python 3.11+
- Step3 已执行完毕，存在结果文件
- 构件属性库 `components.json` 已就位

## 生成审核工具

```bash
# 从项目根目录执行
python3 -m pipeline_v2 step5-audit \
  --step3-result data/output/step3/run-20260416-full/project_component_feature_calc_matching_result.json \
  --components data/input/components.json \
  --component-source-table data/output/step3/run-20260416-full/component_source_table.json \
  --output data/output/step5/feature_audit_tool.html
```

输出: `data/output/step5/feature_audit_tool.html`

## 使用审核工具

1. **打开**: 双击 `feature_audit_tool.html`，在浏览器中打开
2. **浏览**: 左侧构件树选择构件 → 中间区域查看所有特征（绿=已匹配，红=未匹配，⚠=间歇性失败）
3. **筛选**: 搜索框输入关键词，或使用状态/标签下拉筛选
4. **审核**: 勾选条目 → 选择状态（待补充 / 无需补充 / 待确认 / 需沉淀）→ 填写批注
5. **保存**: 审核进度自动保存到 localStorage，也可点击"保存进度"导出 JSON

## 导出

- **Excel**: 点击"导出 Excel" → 按构件分 sheet 导出，含回填列
- **JSON**: 点击"导出 JSON" → 导出全量审核数据
- **Wiki 补丁**: 点击"导出 Wiki 补丁" → 生成 `wiki_patch.json`，可用 `wiki_patch_import.py` 导入知识库

## 常用命令

```bash
# 查看 CLI 帮助
python3 -m pipeline_v2 step5-audit --help

# 导入 wiki 补丁到知识库
python3 pipeline_v2/wiki_patch_import.py --patch data/output/step5/wiki_patch.json
```

## 开发调试

```bash
# 运行单元测试
pytest tests/test_step5_feature_audit.py -v

# 用小数据集快速测试
python3 -m pipeline_v2 step5-audit \
  --step3-result tests/fixtures/step3_sample.json \
  --components tests/fixtures/components_sample.json \
  --output /tmp/test_audit.html
```
