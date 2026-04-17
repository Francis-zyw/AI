"""
Step3→Step1 缺失特征反馈报告生成器

分析 Step3 结果中 feature_expression_items 的 matched=false 项，
与 Step1 清单的 project_features_raw 对比，生成缺口报告:
- 哪些构件类型有最多未匹配特征
- 哪些特征标签在 Step1 清单中缺失
- 建议补充到 Step1 的属性列表
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence


def load_step3_results(step3_path: Path) -> Dict[str, Any]:
    with open(step3_path, "r", encoding="utf-8") as f:
        return json.load(f)


def analyze_gaps(
    step3_rows: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """分析未匹配特征，按构件类型归类"""
    by_component: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "total_items": 0,
        "unmatched_items": 0,
        "unmatched_labels": Counter(),
        "sample_raw_texts": defaultdict(list),
        "affected_rows": set(),
    })

    global_labels = Counter()
    total_rows = len(step3_rows)
    rows_with_gaps = 0

    for row in step3_rows:
        comp = (
            row.get("source_component_name", "")
            or row.get("component_type", "")
            or "(无构件)"
        )
        row_id = row.get("row_id", "")
        fei = row.get("feature_expression_items", [])
        has_gap = False

        for item in fei:
            by_component[comp]["total_items"] += 1
            if not item.get("matched", True):
                has_gap = True
                label = item.get("label", "") or item.get("raw_text", "")
                by_component[comp]["unmatched_items"] += 1
                by_component[comp]["unmatched_labels"][label] += 1
                by_component[comp]["affected_rows"].add(row_id)
                global_labels[label] += 1
                # 保留样本 raw_text
                samples = by_component[comp]["sample_raw_texts"][label]
                raw = item.get("raw_text", "")
                if raw and len(samples) < 3:
                    samples.append(raw)

        if has_gap:
            rows_with_gaps += 1

    return {
        "total_rows": total_rows,
        "rows_with_gaps": rows_with_gaps,
        "components": {
            comp: {
                "total_items": data["total_items"],
                "unmatched_items": data["unmatched_items"],
                "gap_rate": round(data["unmatched_items"] / max(data["total_items"], 1), 3),
                "affected_row_count": len(data["affected_rows"]),
                "top_unmatched_labels": data["unmatched_labels"].most_common(20),
                "sample_raw_texts": dict(data["sample_raw_texts"]),
            }
            for comp, data in sorted(
                by_component.items(),
                key=lambda x: x[1]["unmatched_items"],
                reverse=True,
            )
        },
        "global_top_labels": global_labels.most_common(30),
    }


def build_gap_report_markdown(analysis: Dict[str, Any]) -> str:
    lines = [
        "# Step3→Step1 缺失特征反馈报告",
        "",
        f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 总览",
        "",
        f"- 总行数: {analysis['total_rows']}",
        f"- 有缺口行数: {analysis['rows_with_gaps']}",
        f"- 缺口率: {analysis['rows_with_gaps'] / max(analysis['total_rows'], 1):.1%}",
        f"- 涉及构件类型: {len(analysis['components'])}",
        "",
        "## 全局高频未匹配特征标签",
        "",
        "| 排名 | 特征标签 | 出现次数 |",
        "|---:|---|---:|",
    ]
    for i, (label, count) in enumerate(analysis["global_top_labels"], 1):
        lines.append(f"| {i} | {label} | {count} |")

    lines.extend(["", "## 各构件类型缺口详情", ""])

    for comp, data in analysis["components"].items():
        if data["unmatched_items"] == 0:
            continue
        lines.append(f"### {comp}")
        lines.append("")
        lines.append(
            f"- 未匹配/总数: {data['unmatched_items']}/{data['total_items']} "
            f"({data['gap_rate']:.1%})"
        )
        lines.append(f"- 影响行数: {data['affected_row_count']}")
        lines.append("")
        lines.append("**高频缺失标签:**")
        lines.append("")
        lines.append("| 特征标签 | 次数 | 样本原文 |")
        lines.append("|---|---:|---|")
        for label, count in data["top_unmatched_labels"]:
            samples = data["sample_raw_texts"].get(label, [])
            sample_text = "; ".join(s[:30] for s in samples[:2])
            lines.append(f"| {label} | {count} | {sample_text} |")
        lines.append("")

    return "\n".join(lines)


def run_gap_analysis(
    step3_result_path: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> Dict[str, Any]:
    """运行缺口分析并输出报告"""
    base = Path(__file__).resolve().parent.parent

    if step3_result_path is None:
        # 自动发现最新 Step3 结果
        step3_dir = base / "data" / "output" / "step3"
        candidates = sorted(step3_dir.glob("*/local_rule_project_component_feature_calc_result.json"))
        if not candidates:
            raise FileNotFoundError(f"未找到 Step3 结果: {step3_dir}")
        step3_result_path = candidates[-1]
    else:
        step3_result_path = Path(step3_result_path)

    if output_dir is None:
        output_dir = base / "data" / "output" / "step1_gap_report"
    else:
        output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    data = load_step3_results(step3_result_path)
    rows = data.get("rows", [])
    analysis = analyze_gaps(rows)

    # 输出 JSON
    json_path = output_dir / "step1_gap_analysis.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2, default=str)

    # 输出 Markdown 报告
    md_path = output_dir / "step1_gap_report.md"
    md_text = build_gap_report_markdown(analysis)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_text)

    print(f"Gap analysis: {len(analysis['components'])} components, "
          f"{analysis['rows_with_gaps']}/{analysis['total_rows']} rows with gaps")
    print(f"Report: {md_path}")
    print(f"JSON:   {json_path}")

    return analysis


if __name__ == "__main__":
    run_gap_analysis()
