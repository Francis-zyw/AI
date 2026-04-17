# Research: 项目特征审核导出工具

**Phase 0 Output** | **Date**: 2026-04-17

## R1: 单 HTML 工具模式可行性

**Decision**: 采用 Python 生成器 + 单 HTML 文件模式  
**Rationale**: 项目中已有 3 个同模式工具（`step3_review_editor.py`、`step3_component_analysis.py`、`step3_result_viewer.py`），模式已验证成熟。数据量在浏览器可承受范围内（~5000 条目，JSON 嵌入 ~2MB）。  
**Alternatives considered**:
- Flask/FastAPI 后端：增加部署复杂度，违背 Constitution II，用户需启动服务
- Electron 桌面应用：过度工程化，打包体积大

## R2: SheetJS CDN vs 本地内嵌

**Decision**: 优先 CDN 加载，失败时降级到本地内嵌  
**Rationale**: CDN 版本（`xlsx.full.min.js` ~500KB）减小 HTML 文件体积。但考虑到离线场景频繁，HTML 内嵌一份 minified 版本作为 fallback。  
**实现方式**:
```javascript
if (typeof XLSX === 'undefined') {
  // CDN 加载失败，使用内嵌版本（Python 生成时已嵌入）
}
```
**最终决策**: 全量内嵌。CDN 方案在离线环境（用户常见场景）不可用，且 500KB 对于 HTML 文件可接受。

## R3: 虚拟滚动实现方案

**Decision**: 自实现轻量虚拟滚动（~80 行 JS）  
**Rationale**: 无需引入第三方库。核心思路：
1. 容器固定高度 + `overflow-y: auto`
2. 内部 spacer 撑起总高度
3. `scroll` 事件计算可见范围 → 仅渲染该范围 ± 20 行 buffer
4. 每项固定高度（或取首项实际高度作为估算）

**参考**: `step3_review_editor.py` 的分页方案（每页 50 条），但虚拟滚动体验更流畅。  
**降级方案**: 若条目 <500，直接全量渲染不启用虚拟滚动。

## R4: 特征聚合策略

**Decision**: 以 `source_component|label` 为键聚合  
**Rationale**:
- 原始数据中同一 `label` 在同一构件下可能出现 191 次（如"规格"在"砖墙"下）
- 审核人员关心的维度是"砖墙缺少规格"而非逐行审核
- 聚合后保留 `occurrence_count`（出现次数）和 `value_samples[]`（最多 3 个不重复值）
- 聚合可将 ~5000 原始条目压缩到 ~1000 审核行

**额外发现**: 需检测"间歇性失败"（同 label 在同构件下部分 matched=true 部分 matched=false），标记为⚠供审核参考。

## R5: Wiki 补丁导出格式

**Decision**: 复用现有 `wiki_patch_import.py` 的输入格式  
**Rationale**: 已有工具链支持 `wiki_patch.json` → 知识库更新，无需重新定义格式。  
**格式参考**:
```json
[
  {
    "component_type": "砖墙",
    "attribute_name": "规格",
    "attribute_code": "GG",
    "value_pattern": "300×200×…",
    "source": "step5-audit",
    "action": "add"
  }
]
```

## R6: 数据输入源确认

**Decision**: 使用 Step3 最终结果 `project_component_feature_calc_matching_result.json`  
**Rationale**: 该文件包含完整的 `feature_expression_items`（含 `matched` 字段），是 Step3 管线的最终输出。已确认字段结构：
- `rows[].feature_expression_items[].matched` (bool)
- `rows[].feature_expression_items[].label` (str)
- `rows[].feature_expression_items[].value_expression` (str)
- `rows[].source_component_name` / `resolved_component_name` (str)

**补充**: 同时加载 `component_source_table.json` 作为属性参考，该文件在 Step3 run 目录中已生成。

## R7: localStorage 键名策略

**Decision**: `feature_audit_{dataHash}` 作为 localStorage 键  
**Rationale**: 用数据内容的 hash 作为后缀，确保不同 Step3 运行结果的审核进度互不干扰。`dataHash` 在 Python 端计算（取 JSON 前 1000 字符的 MD5 前 8 位）并嵌入 HTML。

## Summary

所有技术决策均已确认，无 NEEDS CLARIFICATION 项。关键约束：
1. 全量内嵌 SheetJS（不依赖 CDN）
2. 虚拟滚动仅在条目 >500 时启用
3. 聚合键为 `source_component|label`
4. Wiki 补丁格式兼容 `wiki_patch_import.py`
5. 使用 Step3 最终结果 JSON（非中间产物）
