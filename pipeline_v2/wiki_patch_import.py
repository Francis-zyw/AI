"""
将 Step3 人工审定的 Wiki 补丁导入到知识库中心

读取 wiki_patch_*.json（由编辑器的"导出 Wiki 补丁"生成），
将人工审定的匹配结果写入对应构件 Wiki 页面。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


WIKI_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "知识库中心"
WIKI_DIR = WIKI_ROOT / "wiki"


def import_wiki_patch(patch_path: str | Path) -> None:
    patch_path = Path(patch_path)
    with open(patch_path, "r", encoding="utf-8") as f:
        patch = json.load(f)

    components = patch.get("components", {})
    if not components:
        print("补丁中无构件数据")
        return

    updated = 0
    created = 0
    for comp_name, items in components.items():
        wiki_page = WIKI_DIR / "构件类型" / f"{comp_name}.md"
        if not wiki_page.exists():
            print(f"  跳过 {comp_name}: wiki 页面不存在")
            continue

        content = wiki_page.read_text(encoding="utf-8")

        # Build reviewed section
        section_header = "## 人工审定记录"
        reviewed_lines = [
            "",
            section_header,
            "",
            f"> 来源: `{patch_path.name}` | 导入时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "| 项目编码 | 项目名称 | 匹配状态 | 计算项目 | 单位 | 备注 |",
            "|---|---|---|---|---|---|",
        ]
        for item in items:
            reviewed_lines.append(
                f"| {item.get('project_code','')} "
                f"| {item.get('project_name','')} "
                f"| {item.get('match_status','')} "
                f"| {item.get('calculation_item_code','')} {item.get('calculation_item_name','')} "
                f"| {item.get('measurement_unit','')} "
                f"| {item.get('notes','')} |"
            )

        # Feature summary
        all_feat_labels = set()
        matched_labels = set()
        for item in items:
            for f in item.get("feature_expression_items", []):
                label = f.get("label", "")
                if label:
                    all_feat_labels.add(label)
                    if f.get("matched"):
                        matched_labels.add(label)

        unmatched_labels = all_feat_labels - matched_labels
        if unmatched_labels:
            reviewed_lines.append("")
            reviewed_lines.append(f"**未匹配特征**: {', '.join(sorted(unmatched_labels))}")
        if matched_labels:
            reviewed_lines.append(f"**已匹配特征**: {', '.join(sorted(matched_labels))}")

        reviewed_text = "\n".join(reviewed_lines) + "\n"

        # Replace existing review section or append
        if section_header in content:
            # Find and replace the entire section
            idx = content.index(section_header)
            # Find next ## or end of file
            next_section = content.find("\n## ", idx + len(section_header))
            if next_section == -1:
                content = content[:idx] + reviewed_text.lstrip("\n")
            else:
                content = content[:idx] + reviewed_text.lstrip("\n") + "\n" + content[next_section:]
            updated += 1
        else:
            content = content.rstrip() + "\n\n" + reviewed_text
            updated += 1

        wiki_page.write_text(content, encoding="utf-8")
        print(f"  ✓ {comp_name}: {len(items)} 条审定记录")

    print(f"\n导入完成: 更新 {updated} 个 wiki 页面")


def main():
    import sys
    if len(sys.argv) < 2:
        # Auto-find latest patch file
        base = Path(__file__).resolve().parent.parent
        patches = sorted(base.glob("data/output/step3/*/wiki_patch_*.json"))
        if not patches:
            print("用法: python3 -m pipeline_v2.wiki_patch_import <wiki_patch_*.json>")
            sys.exit(1)
        patch_path = patches[-1]
    else:
        patch_path = Path(sys.argv[1])

    import_wiki_patch(patch_path)


if __name__ == "__main__":
    main()
