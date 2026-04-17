"""
Wiki 图谱检索引擎 (v3)

基于文件系统直读的轻量级检索，替代旧的向量数据库方案。
从 wiki Markdown 页面中按构件名/章节精准提取极小上下文片段，
供 Step2/Step3/Step4 的 prompt 注入。

核心设计原则：
- 零依赖：仅需标准库 + pathlib，不需要 SQLite/numpy/embedding
- 精准拉取：按构件类型名直接定位 wiki 页面，O(1) 查找
- 极小输出：每次查询返回 500-2000 字符的摘要，不是整页
- 分层缓存：wiki 页面预编译为内存索引，避免重复 IO

目录结构要求：
    wiki/构件类型/{构件名}.md                    — 构件完整定义（属性+计算+同义词）
    wiki/智能提量工具/步骤结果/step2/{构件名}.md  — Step2 匹配历史
    wiki/智能提量工具/步骤结果/step3/{构件名}.md  — Step3 特征模式
    wiki/智能提量工具/步骤结果/step1/{章节名}.md  — Step1 章节摘要
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────────
WIKI_ROOT = Path("/Users/zhangkaiye/AI数据/知识库中心/wiki")
COMPONENT_DIR = WIKI_ROOT / "构件类型"
STEP_RESULTS_DIR = WIKI_ROOT / "智能提量工具" / "步骤结果"

# 摘要长度限制（字符数）
MAX_COMPONENT_SUMMARY = 1500   # 构件定义摘要
MAX_STEP2_SUMMARY = 600        # Step2 匹配摘要
MAX_STEP3_SUMMARY = 800        # Step3 特征模式摘要
MAX_STEP1_SUMMARY = 600        # Step1 章节摘要


# ─────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────
@dataclass
class WikiContext:
    """单个构件的完整 wiki 上下文（用于 prompt 注入）"""
    component_name: str
    component_summary: str = ""     # 属性/计算/同义词精简
    step2_summary: str = ""         # Step2 匹配历史
    step3_summary: str = ""         # Step3 特征模式
    step1_chapters: List[str] = field(default_factory=list)  # 相关章节摘要

    @property
    def total_chars(self) -> int:
        return (len(self.component_summary) + len(self.step2_summary)
                + len(self.step3_summary) + sum(len(c) for c in self.step1_chapters))

    def to_prompt_text(self, include_steps: str = "all") -> str:
        """
        转为 prompt 注入文本。

        Args:
            include_steps: "all" | "2" | "3" | "23" | "component_only"
        """
        parts = [f"【构件: {self.component_name}】"]

        if self.component_summary:
            comp_text = self.component_summary
            # 当 step2_summary 存在时（include_steps="2"/"23"），
            # 只保留 属性:/计算: 结构性行，去掉别名/章节（step2_summary 已包含），
            # 减少 Step3 prompt 中的重复内容
            if include_steps in ("2", "23") and self.step2_summary:
                kept = [
                    line for line in comp_text.split("\n")
                    if line.startswith("属性:") or line.startswith("计算:")
                ]
                comp_text = "\n".join(kept)
            if comp_text:
                parts.append(comp_text)

        if include_steps in ("all", "2", "23") and self.step2_summary:
            parts.append(f"[Step2匹配] {self.step2_summary}")

        if include_steps in ("all", "3", "23") and self.step3_summary:
            parts.append(f"[Step3模式] {self.step3_summary}")

        if include_steps == "all" and self.step1_chapters:
            for ch in self.step1_chapters[:2]:
                parts.append(f"[章节] {ch}")

        return "\n".join(parts)


# ─────────────────────────────────────────────────
# 页面解析工具
# ─────────────────────────────────────────────────
def _read_page(path: Path) -> str:
    """安全读取 wiki 页面"""
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _strip_frontmatter(text: str) -> str:
    """去掉 YAML frontmatter"""
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return text[end + 3:].strip()
    return text.strip()


def _extract_section(text: str, heading: str) -> str:
    """提取 Markdown 指定 ##/### 标题下的内容"""
    pattern = rf"^#{{2,3}}\s+{re.escape(heading)}\s*$"
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        return ""
    start = match.end()
    heading_level = match.group(0).count('#')
    # 找下一个同级或更高级标题
    next_pattern = rf"^#{{1,{heading_level}}}\s+"
    next_heading = re.search(next_pattern, text[start:], re.MULTILINE)
    if next_heading:
        return text[start:start + next_heading.start()].strip()
    return text[start:].strip()


def _truncate(text: str, max_chars: int) -> str:
    """截断文本到最大字符数"""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit("\n", 1)[0] + "\n…"


# ─────────────────────────────────────────────────
# 构件定义摘要提取
# ─────────────────────────────────────────────────
def _summarize_component_page(text: str, max_chars: int = MAX_COMPONENT_SUMMARY) -> str:
    """
    从构件类型 wiki 页提取精简摘要：
    - 属性定义表（前8行）
    - 计算项目表（前10行）
    - 同义词列表
    """
    body = _strip_frontmatter(text)
    parts = []

    # 提取属性表
    attr_section = _extract_section(body, "属性定义")
    if attr_section:
        lines = attr_section.split("\n")
        # 保留表头 + 前8行数据
        table_lines = [l for l in lines if l.startswith("|")]
        if table_lines:
            parts.append("属性: " + " ".join(table_lines[:10]))

    # 提取计算项目表
    calc_section = _extract_section(body, "计算项目")
    if calc_section:
        lines = calc_section.split("\n")
        table_lines = [l for l in lines if l.startswith("|")]
        if table_lines:
            parts.append("计算: " + " ".join(table_lines[:12]))

    # 提取同义词
    syn_section = _extract_section(body, "同义词") if "同义词" in body else ""
    if not syn_section:
        # 也可能在主页面中
        syn_match = re.search(r"\*\*别名\*\*:\s*(.+)", body)
        if syn_match:
            parts.append(f"别名: {syn_match.group(1)[:200]}")

    # 提取关联章节
    ch_match = re.search(r"\*\*关联国标章节\*\*:\s*\n((?:- .+\n)+)", body)
    if ch_match:
        chapters = ch_match.group(1).strip()
        parts.append(f"章节: {chapters[:200]}")

    result = "\n".join(parts)
    return _truncate(result, max_chars)


def _summarize_step2_page(text: str, max_chars: int = MAX_STEP2_SUMMARY) -> str:
    """从 Step2 结果页提取匹配状态和别名"""
    body = _strip_frontmatter(text)
    parts = []

    # 提取匹配状态行
    for pat in [r"\*\*匹配状态\*\*:\s*(.+)", r"\*\*匹配方式\*\*:\s*(.+)"]:
        m = re.search(pat, body)
        if m:
            parts.append(m.group(0))

    # 提取别名（支持多行）
    alias_match = re.search(r"\*\*别名\*\*:\s*(.+?)(?=\n\n|\n\*\*|$)", body, re.DOTALL)
    if alias_match:
        alias_text = alias_match.group(1).replace("\n", " ").strip()
        parts.append(f"别名: {alias_text[:300]}")

    # 提取关联章节（前5个）
    ch_section = body.split("**关联章节**:")
    if len(ch_section) > 1:
        ch_lines = [l.strip() for l in ch_section[1].split("\n") if l.strip().startswith("-")]
        if ch_lines:
            parts.append("章节: " + " | ".join(ch_lines[:5]))

    return _truncate("\n".join(parts), max_chars)


def _summarize_step3_page(text: str, max_chars: int = MAX_STEP3_SUMMARY) -> str:
    """从 Step3 结果页提取特征表达模式"""
    body = _strip_frontmatter(text)
    parts = []

    # 提取统计行
    stat_match = re.search(r"共 (\d+) 行.+置信度 ([\d.]+)", body)
    if stat_match:
        parts.append(f"共{stat_match.group(1)}行 置信度{stat_match.group(2)}")

    # 提取常用特征表达式（前10行）
    expr_section = _extract_section(body, "常用特征表达式")
    if expr_section:
        table_lines = [l for l in expr_section.split("\n") if l.startswith("|") and "`" in l]
        top_exprs = []
        for l in table_lines[:10]:
            m = re.search(r"`([^`]+)`", l)
            if m:
                top_exprs.append(m.group(1))
        if top_exprs:
            parts.append("特征: " + ", ".join(top_exprs))

    # 提取常用计算项目
    calc_section = _extract_section(body, "常用计算项目")
    if calc_section:
        codes = re.findall(r"`([A-Z]+)`", calc_section)
        if codes:
            parts.append("计算项: " + ", ".join(codes[:8]))

    # 提取计量单位
    unit_section = _extract_section(body, "计量单位分布")
    if unit_section:
        units = re.findall(r"`([^`]+)`", unit_section)
        if units:
            parts.append("单位: " + ", ".join(units[:5]))

    return _truncate("\n".join(parts), max_chars)


def _summarize_step1_page(text: str, max_chars: int = MAX_STEP1_SUMMARY) -> str:
    """从 Step1 章节页提取清单行摘要"""
    body = _strip_frontmatter(text)
    # 只返回路径+行数统计
    parts = []
    path_match = re.search(r"\*\*路径\*\*:\s*(.+)", body)
    if path_match:
        parts.append(path_match.group(1).strip())
    count_match = re.search(r"\*\*清单行数\*\*:\s*(\d+)", body)
    if count_match:
        parts.append(f"共{count_match.group(1)}行")
    return _truncate("\n".join(parts), max_chars)


# ─────────────────────────────────────────────────
# 检索引擎
# ─────────────────────────────────────────────────
class WikiRetriever:
    """
    Wiki 图谱检索引擎。

    使用方式：
        retriever = WikiRetriever()
        ctx = retriever.query("砖墙")
        prompt_text = ctx.to_prompt_text()  # → 500-2000 chars

        # 批量查询（高效，共享缓存）
        contexts = retriever.query_batch(["砖墙", "砼墙", "现浇板"])
    """

    def __init__(self, wiki_root: Path = WIKI_ROOT):
        self.wiki_root = wiki_root
        self.component_dir = wiki_root / "构件类型"
        self.step_results_dir = wiki_root / "智能提量工具" / "步骤结果"
        self._cache: Dict[str, WikiContext] = {}
        self._step1_cache: Dict[str, str] = {}
        self._available_components: Optional[set] = None

    @property
    def available_components(self) -> set:
        """列出所有有 wiki 页面的构件类型"""
        if self._available_components is None:
            self._available_components = set()
            if self.component_dir.exists():
                for f in self.component_dir.glob("*.md"):
                    if not f.name.startswith("_"):
                        self._available_components.add(f.stem)
        return self._available_components

    def query(self, component_name: str, include_steps: str = "all") -> WikiContext:
        """
        查询单个构件的完整 wiki 上下文。

        Args:
            component_name: 构件类型名称（如 "砖墙"）
            include_steps: "all" | "component_only" | "2" | "3" | "23"

        Returns:
            WikiContext 对象，通过 .to_prompt_text() 获取 prompt 注入文本
        """
        cache_key = f"{component_name}:{include_steps}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        ctx = WikiContext(component_name=component_name)

        # 1. 构件定义
        comp_page = _read_page(self.component_dir / f"{component_name}.md")
        if comp_page:
            ctx.component_summary = _summarize_component_page(comp_page)
        else:
            logger.debug("Wiki page missing for component: %s", component_name)

        # 2. Step2 匹配历史
        if include_steps in ("all", "2", "23"):
            step2_page = _read_page(self.step_results_dir / "step2" / f"{component_name}.md")
            if step2_page:
                ctx.step2_summary = _summarize_step2_page(step2_page)

        # 3. Step3 特征模式
        if include_steps in ("all", "3", "23"):
            step3_page = _read_page(self.step_results_dir / "step3" / f"{component_name}.md")
            if step3_page:
                ctx.step3_summary = _summarize_step3_page(step3_page)

        self._cache[cache_key] = ctx
        return ctx

    def query_batch(
        self,
        component_names: Sequence[str],
        include_steps: str = "all",
        max_total_chars: int = 8000,
    ) -> List[WikiContext]:
        """
        批量查询多个构件的 wiki 上下文，带总字符数限制。

        会按构件名去重，并在达到 max_total_chars 时截断。
        """
        seen = set()
        results = []
        total = 0
        for name in component_names:
            if not name or name in seen:
                continue
            seen.add(name)
            ctx = self.query(name, include_steps)
            if total + ctx.total_chars > max_total_chars and results:
                break
            results.append(ctx)
            total += ctx.total_chars
        return results

    def query_for_step2(
        self,
        component_names: Sequence[str],
        max_total_chars: int = 4000,
    ) -> str:
        """
        为 Step2 prompt 生成 wiki 注入文本。
        只需要构件定义摘要（属性+计算+同义词），不需要步骤结果。
        """
        contexts = self.query_batch(
            component_names,
            include_steps="component_only",
            max_total_chars=max_total_chars,
        )
        if not contexts:
            return ""
        parts = ["【Wiki 构件参考】"]
        for ctx in contexts:
            parts.append(ctx.to_prompt_text("component_only"))
        return "\n\n".join(parts)

    def query_for_step3(
        self,
        component_names: Sequence[str],
        max_total_chars: int = 9000,
    ) -> str:
        """
        为 Step3 prompt 生成 wiki 注入文本。
        需要构件定义 + Step2 匹配历史。
        """
        contexts = self.query_batch(
            component_names,
            include_steps="2",
            max_total_chars=max_total_chars,
        )
        if not contexts:
            return ""
        parts = ["【Wiki 构件+Step2参考】"]
        for ctx in contexts:
            parts.append(ctx.to_prompt_text("2"))
        return "\n\n".join(parts)

    def query_for_step4(
        self,
        component_name: str,
        max_chars: int = 3000,
    ) -> str:
        """
        为 Step4 prompt 生成 wiki 注入文本。
        Step4 已经按构件分组，所以只查询单个构件。
        需要完整信息：定义 + Step2 + Step3 模式。
        """
        ctx = self.query(component_name, include_steps="all")
        text = ctx.to_prompt_text("all")
        return _truncate(text, max_chars)

    def query_chapter(self, chapter_title: str) -> str:
        """查询 Step1 章节摘要"""
        if chapter_title in self._step1_cache:
            return self._step1_cache[chapter_title]

        # 尝试精确匹配
        page_path = self.step_results_dir / "step1" / f"{chapter_title}.md"
        if page_path.exists():
            text = _read_page(page_path)
            summary = _summarize_step1_page(text)
            self._step1_cache[chapter_title] = summary
            return summary

        # 模糊匹配：chapter_title 可能是部分名
        if (self.step_results_dir / "step1").exists():
            for f in (self.step_results_dir / "step1").glob("*.md"):
                if chapter_title in f.stem:
                    text = _read_page(f)
                    summary = _summarize_step1_page(text)
                    self._step1_cache[chapter_title] = summary
                    return summary

        return ""

    def get_stats(self) -> Dict[str, Any]:
        """返回检索引擎统计信息"""
        return {
            "available_components": len(self.available_components),
            "cached_queries": len(self._cache),
            "wiki_root": str(self.wiki_root),
            "component_dir_exists": self.component_dir.exists(),
            "step_results_dir_exists": self.step_results_dir.exists(),
        }


# ─────────────────────────────────────────────────
# 便捷函数（不需要实例化 WikiRetriever）
# ─────────────────────────────────────────────────
_default_retriever: Optional[WikiRetriever] = None


def get_retriever(wiki_root: Path = WIKI_ROOT) -> WikiRetriever:
    """获取全局单例检索器"""
    global _default_retriever
    if _default_retriever is None or _default_retriever.wiki_root != wiki_root:
        _default_retriever = WikiRetriever(wiki_root)
    return _default_retriever


def query_wiki_for_prompt(
    component_names: Sequence[str],
    step: str = "step3",
    max_chars: int = 9000,
) -> str:
    """
    一步式查询 wiki 并返回 prompt 注入文本。

    Args:
        component_names: 构件类型名称列表
        step: "step2" | "step3" | "step4"
        max_chars: 最大字符数限制

    Returns:
        可直接注入 prompt 的文本（500-6000 字符）
    """
    retriever = get_retriever()
    if step == "step2":
        return retriever.query_for_step2(component_names, max_chars)
    elif step == "step3":
        return retriever.query_for_step3(component_names, max_chars)
    elif step == "step4" and component_names:
        return retriever.query_for_step4(component_names[0], max_chars)
    return ""
