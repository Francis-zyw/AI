from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pipeline_v2.step2_review_html import (
    apply_step2_review_package,
    build_step2_review_html,
    build_step2_review_package,
)


class Step2ReviewHtmlTests(unittest.TestCase):
    def _write_step2_fixture(self, root: Path) -> Path:
        step2_dir = root / "data" / "output" / "step2" / "sample-run"
        step2_dir.mkdir(parents=True, exist_ok=True)

        (step2_dir / "component_matching_result.json").write_text(
            json.dumps(
                {
                    "meta": {
                        "task_name": "component_standard_name_matching",
                        "standard_document": "样例标准",
                        "generated_at": "2026-04-13T10:00:00+08:00",
                        "review_stage": "pre_parse",
                    },
                    "mappings": [
                        {
                            "source_component_name": "砼墙",
                            "source_aliases": ["砼墙", "混凝土墙"],
                            "selected_standard_name": "混凝土墙",
                            "standard_aliases": ["混凝土墙", "现浇混凝土墙"],
                            "candidate_standard_names": ["混凝土墙"],
                            "match_type": "exact",
                            "match_status": "matched",
                            "confidence": 0.92,
                            "review_status": "pending",
                            "evidence_paths": ["附录G > 混凝土墙"],
                            "evidence_texts": ["章节中存在直接命中。"],
                            "reasoning": "构件名称可直接对应。",
                            "manual_notes": "",
                        },
                        {
                            "source_component_name": "保温层",
                            "source_aliases": ["保温层"],
                            "selected_standard_name": "",
                            "standard_aliases": [],
                            "candidate_standard_names": ["保温、隔热"],
                            "match_type": "candidate_only",
                            "match_status": "candidate_only",
                            "confidence": 0.35,
                            "review_status": "pending",
                            "evidence_paths": ["附录K > 保温、隔热"],
                            "evidence_texts": ["章节主题高度相关。"],
                            "reasoning": "需要人工确认是否按保温、隔热归并。",
                            "manual_notes": "",
                        },
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        (step2_dir / "synonym_library.json").write_text(
            json.dumps(
                {
                    "meta": {
                        "task_name": "component_standard_name_synonym_library",
                        "standard_document": "样例标准",
                        "generated_at": "2026-04-13T10:00:00+08:00",
                        "source_review_stage": "pre_parse",
                    },
                    "synonym_library": [
                        {
                            "canonical_name": "混凝土墙",
                            "aliases": ["混凝土墙", "砼墙"],
                            "source_component_names": ["砼墙"],
                            "match_types": ["exact"],
                            "review_statuses": ["pending"],
                            "evidence_paths": ["附录G > 混凝土墙"],
                            "notes": ["构件名称可直接对应。"],
                        }
                    ],
                    "unmatched_components": ["保温层"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        (step2_dir / "run_summary.json").write_text(
            json.dumps(
                {
                    "task_name": "step2_v2_execute",
                    "generated_at": "2026-04-13T10:00:00+08:00",
                    "status": "completed",
                    "standard_document": "样例标准",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return step2_dir

    def test_build_step2_review_html_writes_self_contained_page(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            step2_dir = self._write_step2_fixture(root)
            html_path = root / "manual_reviews" / "sample-run.html"

            result = build_step2_review_html(step2_dir, output_html_path=html_path)

            self.assertEqual(result["mapping_count"], 2)
            self.assertTrue(html_path.exists())
            html_text = html_path.read_text(encoding="utf-8")
            self.assertIn("第二步人工修订页", html_text)
            self.assertIn("砼墙", html_text)
            self.assertIn("样例标准", html_text)

    def test_apply_step2_review_package_writes_reviewed_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            step2_dir = self._write_step2_fixture(root)
            review_package = build_step2_review_package(step2_dir)

            review_package["component_matching_result"]["mappings"][1]["selected_standard_name"] = "保温、隔热"
            review_package["component_matching_result"]["mappings"][1]["standard_aliases"] = ["保温、隔热", "保温层"]
            review_package["component_matching_result"]["mappings"][1]["candidate_standard_names"] = ["保温、隔热"]
            review_package["component_matching_result"]["mappings"][1]["match_status"] = "matched"
            review_package["component_matching_result"]["mappings"][1]["review_status"] = "confirmed"
            review_package["component_matching_result"]["mappings"][1]["confidence"] = 0.88
            review_package["component_matching_result"]["mappings"][1]["manual_notes"] = "产品经理已确认。"

            review_package["synonym_library"]["synonym_library"].append(
                {
                    "record_id": "S0002",
                    "canonical_name": "保温、隔热",
                    "aliases": ["保温、隔热", "保温层"],
                    "source_component_names": ["保温层"],
                    "match_types": ["manual_override"],
                    "review_statuses": ["confirmed"],
                    "evidence_paths": ["附录K > 保温、隔热"],
                    "notes": ["人工确认补充。"],
                }
            )
            review_package["synonym_library"]["unmatched_components"] = []

            review_json_path = root / "manual_reviews" / "step2_manual_review_package.json"
            review_json_path.parent.mkdir(parents=True, exist_ok=True)
            review_json_path.write_text(json.dumps(review_package, ensure_ascii=False, indent=2), encoding="utf-8")

            final_dir = root / "manual_reviews" / "final"
            result = apply_step2_review_package(step2_dir, review_json_path, output_dir=final_dir)

            component_payload = json.loads(Path(result["component_matching_result_path"]).read_text(encoding="utf-8"))
            synonym_payload = json.loads(Path(result["synonym_library_path"]).read_text(encoding="utf-8"))
            run_summary = json.loads(Path(result["run_summary_path"]).read_text(encoding="utf-8"))

            self.assertEqual(component_payload["meta"]["review_stage"], "manual_review_applied")
            self.assertEqual(component_payload["mappings"][1]["selected_standard_name"], "保温、隔热")
            self.assertEqual(component_payload["mappings"][1]["match_status"], "matched")
            self.assertEqual(run_summary["matched_count"], 2)
            self.assertEqual(run_summary["unmatched_count"], 0)
            self.assertEqual(synonym_payload["meta"]["matched_canonical_count"], 2)
            self.assertEqual(synonym_payload["unmatched_components"], [])


if __name__ == "__main__":
    unittest.main()
