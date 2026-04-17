from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pipeline_v2.global_knowledge_base import build_global_knowledge_base, query_global_knowledge_base


class GlobalKnowledgeBaseTests(unittest.TestCase):
    def test_build_global_knowledge_base_from_manifest_and_query_with_filters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_dir = root / "notes"
            docs_dir = root / "docs"
            data_dir = root / "data"
            notes_dir.mkdir(parents=True, exist_ok=True)
            docs_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)

            (notes_dir / "llm_wiki.md").write_text(
                "# LLM Wiki\n\nLLM wiki 适合做长期知识编译、向量检索和上下文工程。",
                encoding="utf-8",
            )
            (docs_dir / "prompt_design.txt").write_text(
                "Prompt engineering 应优先给模型结构化上下文，而不是堆砌原文。",
                encoding="utf-8",
            )
            (data_dir / "reviewed_examples.json").write_text(
                json.dumps(
                    [
                        {
                            "title": "Step4 墙厚样本",
                            "summary": "钢筋混凝土墙常见墙厚表达式为墙厚:HD=>200mm",
                            "tags": ["reviewed", "step4"],
                            "category": "costing",
                        }
                    ],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            manifest_path = root / "global_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "default_collection": "general",
                        "sources": [
                            {
                                "path": "notes",
                                "collection": "personal_notes",
                                "source_type": "markdown",
                                "tags": ["notes", "llm"],
                                "recursive": True,
                                "include_globs": ["**/*.md"],
                            },
                            {
                                "path": "docs",
                                "collection": "methods",
                                "source_type": "text",
                                "tags": ["prompt"],
                                "recursive": True,
                                "include_globs": ["**/*.txt"],
                            },
                            {
                                "path": "data/reviewed_examples.json",
                                "collection": "reviewed_examples",
                                "source_type": "json",
                                "tags": ["examples"],
                                "content_fields": ["title", "summary", "category"],
                                "metadata_fields": ["category"],
                            },
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            output_dir = root / "global_kb"
            summary = build_global_knowledge_base(
                output_dir=output_dir,
                manifest_path=manifest_path,
            )

            self.assertEqual(summary["status"], "completed")
            self.assertTrue((output_dir / "global_knowledge.db").exists())
            self.assertTrue((output_dir / "wiki" / "overview.md").exists())
            self.assertTrue((output_dir / "wiki" / "collections" / "personal_notes.md").exists())
            self.assertTrue((output_dir / "wiki" / "tags" / "llm.md").exists())

            query_result = query_global_knowledge_base(
                knowledge_base_path=output_dir,
                query_text="LLM wiki 向量检索 上下文工程",
                collections=["personal_notes"],
                tags=["llm"],
                top_k=3,
                max_context_chars=1500,
            )

            self.assertEqual(query_result["status"], "completed")
            self.assertTrue(query_result["retrieved_documents"])
            self.assertEqual(query_result["retrieved_documents"][0]["collection"], "personal_notes")
            self.assertIn("llm", query_result["retrieved_documents"][0]["tags"])
            self.assertTrue(query_result["retrieved_wiki_pages"])

    def test_build_global_knowledge_base_supports_direct_sources_without_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "source"
            source_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / "knowledge.md").write_text(
                "# Engineering Notes\n\n向量数据库可以作为检索层，wiki 可以作为知识组织层。",
                encoding="utf-8",
            )

            output_dir = root / "kb"
            summary = build_global_knowledge_base(
                output_dir=output_dir,
                source_paths=[str(source_dir)],
                default_collection="engineering",
            )

            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["collections"].get("engineering"), 1)

            query_result = query_global_knowledge_base(
                knowledge_base_path=output_dir,
                query_text="wiki 检索层 知识组织",
                collections=["engineering"],
            )

            self.assertTrue(query_result["retrieved_documents"])
            self.assertEqual(query_result["retrieved_documents"][0]["collection"], "engineering")


if __name__ == "__main__":
    unittest.main()
