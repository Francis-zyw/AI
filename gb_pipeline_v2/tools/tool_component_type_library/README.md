# 构件类型-属性库维护工具

当前目录是“构件类型-属性库”的正式维护入口，用于平时空闲时补充、校正和重新导出构件库数据。

主说明文档已统一维护在：

- [系统整体说明-System-Overview.md](/Users/zhangkaiye/AI数据/AI智能提量/智能提量处理流程/国标解析-文本分析/docs/architecture/系统整体说明-System-Overview.md)

当前工具默认约定：

- 源 Excel 目录：`data/input/component_type_attribute_excels/`
- 主输出 JSONL：`data/input/components.jsonl`
- 主输出 JSON：`data/input/components.json`

常用方式：

```bash
python3 tools/tool_component_type_library/batch_convert.py
```

```bash
./tools/tool_component_type_library/start.sh
```

```python
from tools.tool_component_type_library import build_component_library

components = build_component_library()
```
