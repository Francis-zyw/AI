"""
Wiki 结果回写引擎

将 Step2/Step3/Step4 的运行结果按构件类型回写到 wiki 步骤结果页面。
每次运行后调用 writeback() 即可自动更新 wiki/智能提量工具/步骤结果/ 目录下的对应页面。
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence

WIKI_ROOT = Path("/Users/zhangkaiye/AI数据/知识库中心/wiki")
STEP_RESULTS_DIR = WIKI_ROOT / "智能提量工具" / "步骤结果"


def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', '_', name)


def _write_page(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def writeback_step2(synonym_library_path: str | Path) -> int:
    """从 synonym_library.json 回写 Step2 结果页"""
    data = json.loads(Path(synonym_library_path).read_text(encoding="utf-8"))
    entries = data if isinstance(data, list) else data.get("synonym_library", [])
    output_dir = STEP_RESULTS_DIR / "step2"
    count = 0

    for entry in entries:
        name = entry.get("canonical_name", "")
        if not name:
            continue
        aliases = entry.get("aliases", [])
        chapter_nodes = entry.get("chapter_nodes", [])
        match_status = entry.get("match_status", "")
        match_method = entry.get("match_method", "")

        lines = [
            "---",
            f'title: "Step2结果：{name}"',
            "type: step2_result",
            f'component: "{name}"',
            f"alias_count: {len(aliases)}",
            f"chapter_count: {len(chapter_nodes)}",
            "---",
            "",
            f"# Step2 同义词匹配：{name}",
            "",
        ]
        if match_status:
            lines.append(f"**匹配状态**: {match_status}")
        if match_method:
            lines.append(f"**匹配方式**: {match_method}")
        lines.append("")

        if aliases:
            lines.append(f"**别名**: {'、'.join(f'`{a}`' for a in aliases[:30])}")
        else:
            lines.append("**别名**: 无")
        lines.append("")

        valid_chapters = [
            c for c in chapter_nodes
            if c and len(c) < 100 and "未出现" not in c and "未找到" not in c
        ]
        if valid_chapters:
            lines.append("**关联章节**:")
            for ch in valid_chapters[:15]:
                lines.append(f"- {ch}")
        lines.append("")
        lines.append(f"_更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}_")

        _write_page(output_dir / f"{_safe_filename(name)}.md", "\n".join(lines))
        count += 1

    return count


def writeback_step3(step3_result_path: str | Path) -> int:
    """从 Step3 结果回写按构件类型的结果页"""
    data = json.loads(Path(step3_result_path).read_text(encoding="utf-8"))
    rows = data.get("rows", [])
    output_dir = STEP_RESULTS_DIR / "step3"

    by_component: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        comp = row.get("source_component_name", "") or row.get("component_type", "")
        if comp:
            by_component[comp].append(row)

    count = 0
    for comp, comp_rows in sorted(by_component.items()):
        matched = sum(1 for r in comp_rows if r.get("match_status") in ("matched", "confirmed"))
        pending = sum(1 for r in comp_rows if r.get("review_status") == "pending")

        lines = [
            "---",
            f'title: "Step3结果：{comp}"',
            "type: step3_result",
            f'component: "{comp}"',
            f"row_count: {len(comp_rows)}",
            f"matched_count: {matched}",
            "---",
            "",
            f"# Step3 特征匹配：{comp}",
            "",
            f"**总行数**: {len(comp_rows)} | **已匹配**: {matched} | **待审核**: {pending}",
            "",
            "## 匹配详情",
            "",
            "| row_id | 项目名称 | 状态 | 置信度 | 计算项目 |",
            "|---|---|---|---|---|",
        ]

        for r in comp_rows[:30]:
            row_id = r.get("row_id", "")
            pname = str(r.get("project_name", ""))[:20]
            status = r.get("match_status", "")
            conf = r.get("confidence", 0)
            calc = r.get("calculation_item_code", "") or r.get("calculation_item_name", "")
            lines.append(f"| {row_id} | {pname} | {status} | {conf} | {calc} |")

        if len(comp_rows) > 30:
            lines.append(f"\n> …共 {len(comp_rows)} 行")

        # 高频特征模式
        from collections import Counter
        feature_labels = Counter()
        for r in comp_rows:
            for item in r.get("feature_expression_items", []):
                label = item.get("label", "")
                if label:
                    feature_labels[label] += 1

        if feature_labels:
            lines.extend(["", "## 高频特征标签", ""])
            for label, cnt in feature_labels.most_common(15):
                lines.append(f"- `{label}`: {cnt}次")

        lines.append("")
        lines.append(f"_更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}_")

        _write_page(output_dir / f"{_safe_filename(comp)}.md", "\n".join(lines))
        count += 1

    return count


def writeback_all(
    synonym_library_path: str | Path | None = None,
    step3_result_path: str | Path | None = None,
) -> Dict[str, int]:
    """一次性回写所有步骤结果"""
    base = Path(__file__).resolve().parent.parent
    results = {}

    if synonym_library_path is None:
        syn_dir = base / "data" / "output" / "step2"
        candidates = sorted(syn_dir.glob("*/synonym_library.json"))
        if candidates:
            synonym_library_path = candidates[-1]

    if synonym_library_path:
        results["step2"] = writeback_step2(synonym_library_path)
        print(f"Step2 writeback: {results['step2']} pages")

    if step3_result_path is None:
        s3_dir = base / "data" / "output" / "step3"
        candidates = sorted(s3_dir.glob("*/local_rule_project_component_feature_calc_result.json"))
        if candidates:
            step3_result_path = candidates[-1]

    if step3_result_path:
        results["step3"] = writeback_step3(step3_result_path)
        print(f"Step3 writeback: {results['step3']} pages")

    return results


if __name__ == "__main__":
    writeback_all()
