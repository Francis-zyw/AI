from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pipeline_v2.step2_engine.step1_source import load_step1_regions_source


class Step1SourceLoaderTests(unittest.TestCase):
    def test_rejects_flat_regions_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "data" / "output" / "step1" / "示例标准"
            base.mkdir(parents=True, exist_ok=True)
            flat_regions_path = base / "flat_regions.json"
            flat_regions_path.write_text(
                json.dumps([{"title": "附录A", "path_text": "附录A"}], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "不再支持 flat_regions.json"):
                load_step1_regions_source(flat_regions_path)

    def test_loads_first_bill_chapter_from_chapter_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "data" / "output" / "step1" / "示例标准"
            chapter_dir = base / "chapter_regions"
            chapter_dir.mkdir(parents=True, exist_ok=True)

            chapter_a = chapter_dir / "001_附录A.json"
            chapter_b = chapter_dir / "002_附录B.json"
            chapter_a.write_text(
                json.dumps(
                    {
                        "chapter": {"title": "附录A"},
                        "regions": [{"title": "附录A", "path_text": "附录A"}],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            chapter_b.write_text(
                json.dumps(
                    {
                        "chapter": {"title": "附录B"},
                        "regions": [{"title": "附录B", "path_text": "附录B"}],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            chapter_index_path = chapter_dir / "chapter_index.json"
            chapter_index_path.write_text(
                json.dumps(
                    {
                        "chapters": [
                            {"title": "附录A", "relative_path": "chapter_regions/001_附录A.json"},
                            {"title": "附录B", "relative_path": "chapter_regions/002_附录B.json"},
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            payload = load_step1_regions_source(chapter_index_path)

            self.assertEqual(payload["source_type"], "chapter_package")
            self.assertEqual(payload["standard_document"], "示例标准")
            self.assertEqual(payload["chapters"], ["附录A"])
            self.assertEqual(len(payload["regions"]), 1)
            self.assertTrue(str(payload["source_path"]).endswith("001_附录A.json"))

    def test_chapter_index_filters_non_bill_chapters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "data" / "output" / "step1" / "示例标准"
            chapter_dir = base / "chapter_regions"
            chapter_dir.mkdir(parents=True, exist_ok=True)

            appendix_path = chapter_dir / "001_附录A.json"
            appendix_path.write_text(
                json.dumps(
                    {
                        "chapter": {"title": "附录A"},
                        "regions": [{"title": "附录A", "path_text": "附录A"}],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            useless_path = chapter_dir / "002_1_总则.json"
            useless_path.write_text(
                json.dumps(
                    {
                        "chapter": {"title": "1 总则"},
                        "regions": [{"title": "1 总则", "path_text": "1 总则"}],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            chapter_index_path = chapter_dir / "chapter_index.json"
            chapter_index_path.write_text(
                json.dumps(
                    {
                        "chapters": [
                            {"title": "1 总则", "relative_path": "chapter_regions/002_1_总则.json"},
                            {"title": "附录A", "relative_path": "chapter_regions/001_附录A.json"},
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            payload = load_step1_regions_source(chapter_index_path)

            self.assertEqual(payload["chapters"], ["附录A"])
            self.assertEqual(len(payload["regions"]), 1)
            self.assertEqual(payload["regions"][0]["path_text"], "附录A")

    def test_loads_single_chapter_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "data" / "output" / "step1" / "示例标准" / "chapter_regions"
            base.mkdir(parents=True, exist_ok=True)
            chapter_path = base / "001_附录A.json"
            chapter_path.write_text(
                json.dumps(
                    {
                        "chapter": {"title": "附录A"},
                        "regions": [{"title": "附录A", "path_text": "附录A"}],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            payload = load_step1_regions_source(chapter_path)

            self.assertEqual(payload["source_type"], "chapter_package")
            self.assertEqual(payload["standard_document"], "示例标准")
            self.assertEqual(payload["chapters"], ["附录A"])
            self.assertEqual(len(payload["regions"]), 1)


if __name__ == "__main__":
    unittest.main()
