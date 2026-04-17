#!/usr/bin/env python3
"""
预编译智能提量 Agent 知识库。

从 components.json + wiki 页面提取关键知识，生成一份紧凑的 Markdown 知识文件，
供智能提量 Agent 作为上下文注入。

用法:
    python3 scripts/compile_agent_knowledge.py

输出:
    data/output/agent_knowledge_compiled.md   ← Agent 预编译知识
"""

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # 智能提量工具/
COMPONENTS_PATH = ROOT / "data" / "input" / "components.json"
WIKI_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "知识库中心" / "wiki"
OUTPUT_PATH = ROOT / "data" / "output" / "agent_knowledge_compiled.md"

# 内部建模属性，不参与项目特征匹配
INTERNAL_ATTRS = {"GJLX", "GJMC", "REGMC", "LAYMC", "LAYFW", "NBZ"}
# 通用属性阈值：出现在 >=40 个构件中的提取为通用
COMMON_THRESHOLD = 40


def load_components():
    with open(COMPONENTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def analyze_common_attrs(comps):
    """统计高频属性，提取为通用模板。"""
    counter = Counter()
    info = {}
    for c in comps:
        for a in c.get("properties", {}).get("attributes", []):
            code = a["code"]
            if code not in INTERNAL_ATTRS:
                counter[code] += 1
                if code not in info:
                    info[code] = {
                        "name": a["name"],
                        "values": a.get("values", []),
                    }
    common = {}
    for code, cnt in counter.items():
        if cnt >= COMMON_THRESHOLD:
            common[code] = {**info[code], "count": cnt}
    return common


def format_attr(a, common_codes):
    """格式化单个属性为紧凑字符串。"""
    name, code = a["name"], a["code"]
    if code in INTERNAL_ATTRS or code in common_codes:
        return None
    vals = a.get("values", [])
    if vals and len(vals) <= 6:
        return f'{name}({code})[{",".join(str(v) for v in vals)}]'
    elif vals:
        return f"{name}({code})[{len(vals)}项]"
    return f"{name}({code})"


def format_calc(calc):
    return f'{calc["name"]}({calc["code"]},{calc.get("unit", "")})'


def compile_component_library(comps, common_attrs):
    """编译构件库为紧凑 Markdown。"""
    common_codes = set(common_attrs.keys())
    lines = []

    # 通用属性模板
    lines.append("## 通用属性模板")
    lines.append("")
    lines.append("以下属性在大部分构件中通用，构件条目中用 `通用:` 行标记哪些适用：")
    lines.append("")
    for code, info in sorted(common_attrs.items(), key=lambda x: -x[1]["count"]):
        vals = info["values"]
        v_str = f'[{",".join(str(v) for v in vals[:8])}]' if vals else ""
        lines.append(f"- **{info['name']}**(`{code}`) — {info['count']}/99 构件适用 {v_str}")
    lines.append("")

    # 逐构件
    lines.append("## 构件库（99 个）")
    lines.append("")
    for c in comps:
        ct = c["component_type"]
        all_attrs = [
            a
            for a in c.get("properties", {}).get("attributes", [])
            if a["code"] not in INTERNAL_ATTRS
        ]
        common_present = sorted(
            [a["code"] for a in all_attrs if a["code"] in common_codes]
        )
        specific = [format_attr(a, common_codes) for a in all_attrs]
        specific = [s for s in specific if s]
        calcs = c.get("properties", {}).get("calculations", [])

        lines.append(f"### {ct}")
        lines.append(f'通用: {",".join(common_present) if common_present else "无"}')
        if specific:
            lines.append(f"专属: {' | '.join(specific)}")
        lines.append(f"计算: {' | '.join(format_calc(calc) for calc in calcs)}")
        lines.append("")

    return "\n".join(lines)


def load_wiki_section(rel_path, max_lines=60):
    """从 wiki 加载指定页面的核心内容（跳过 frontmatter）。"""
    fp = WIKI_DIR / rel_path
    if not fp.exists():
        return f"<!-- {rel_path} not found -->"
    text = fp.read_text(encoding="utf-8")
    # Strip frontmatter
    if text.startswith("---"):
        end = text.find("---", 3)
        if end > 0:
            text = text[end + 3 :].strip()
    # Limit length
    lines = text.split("\n")[:max_lines]
    return "\n".join(lines)


def build_knowledge():
    comps = load_components()
    common_attrs = analyze_common_attrs(comps)

    sections = []

    # Header
    sections.append(
        f"# 智能提量 Agent 预编译知识库\n\n"
        f"> 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"> 来源: components.json ({len(comps)} 构件) + wiki 关键页面\n"
        f"> 重新生成: `python3 scripts/compile_agent_knowledge.py`\n"
    )

    # Data contract summary
    sections.append("# 数据契约\n")
    sections.append(load_wiki_section("智能提量工具/专题/智能提量数据契约.md", max_lines=80))
    sections.append("")

    # Step3 matching logic summary
    sections.append("# Step3 匹配逻辑\n")
    sections.append(
        load_wiki_section(
            "智能提量工具/专题/Step3数据流与构件匹配.md", max_lines=100
        )
    )
    sections.append("")

    # Component library
    sections.append("# 构件库\n")
    sections.append(compile_component_library(comps, common_attrs))

    content = "\n".join(sections)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(content, encoding="utf-8")

    print(f"✅ 知识库编译完成: {OUTPUT_PATH}")
    print(f"   字符数: {len(content):,}")
    print(f"   估计 token: ~{len(content) // 2:,}")
    print(f"   构件数: {len(comps)}")
    print(f"   通用属性: {len(common_attrs)} 个")


if __name__ == "__main__":
    build_knowledge()
