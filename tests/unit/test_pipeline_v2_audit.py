from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pipeline_v2.audit import audit_project, build_redesign_plan, render_markdown_report


class PipelineV2AuditTests(unittest.TestCase):
    def test_audit_reports_step2_failure_step3_partial_and_duplicate_tool_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "国标解析-文本分析"
            step1_dir = root / "data" / "output" / "step1" / "sample"
            step2_dir = root / "data" / "output" / "step2" / "sample"
            step3_dir = root / "data" / "output" / "step3" / "sample"
            step1_dir.mkdir(parents=True, exist_ok=True)
            step2_dir.mkdir(parents=True, exist_ok=True)
            step3_dir.mkdir(parents=True, exist_ok=True)
            (root / "tools" / "tool_component_type_library").mkdir(parents=True, exist_ok=True)
            (root / "分析工具" / "构件类型-属性").mkdir(parents=True, exist_ok=True)
            (root.parent / "构件类型-属性").mkdir(parents=True, exist_ok=True)

            (step1_dir / "catalog_summary.json").write_text(
                json.dumps(
                    {
                        "total_pdf_pages": 122,
                        "region_counts": {"total": 119},
                        "table_counts": {"regions_with_tables": 105, "rows": 1290},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (step2_dir / "run_summary.json").write_text(
                json.dumps(
                    {
                        "status": "failed",
                        "model": "gpt-5.4",
                        "total_batches": 57,
                        "failed_batch": 1,
                        "error": "Invalid 'input[0].content[0].file_data'.",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (step3_dir / "run_summary.json").write_text(
                json.dumps(
                    {
                        "status": "completed_local_only",
                        "total_source_rows": 445,
                        "generated_rows": 699,
                        "matched_rows": 198,
                        "candidate_only_rows": 348,
                        "unmatched_rows": 153,
                        "synonym_library_path": "",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            audit = audit_project(root)
            issue_codes = {issue.code for issue in audit.issues}

            self.assertEqual(audit.steps[0].name, "step1")
            self.assertEqual(audit.steps[1].name, "step2")
            self.assertEqual(audit.steps[2].name, "step3")
            self.assertIn("STEP2_REQUEST_FORMAT", issue_codes)
            self.assertIn("STEP3_LOCAL_ONLY", issue_codes)
            self.assertIn("DUPLICATE_COMPONENT_LIBRARY", issue_codes)

    def test_build_redesign_plan_contains_five_work_units(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            audit = audit_project(Path(temp_dir))
            plan = build_redesign_plan(audit)

            self.assertEqual(plan.title, "国标解析主流程 V2 重构方案")
            self.assertEqual(len(plan.work_units), 8)
            self.assertEqual(plan.work_units[0].identifier, "WU-01")
            self.assertEqual(plan.work_units[4].identifier, "WU-05")
            self.assertEqual(plan.work_units[7].identifier, "WU-08")
            self.assertEqual(len(plan.review_contracts), 2)
            self.assertEqual(len(plan.cutover_gates), 2)

    def test_render_markdown_report_contains_current_risks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "国标解析-文本分析"
            (root / "data" / "output" / "step1" / "sample").mkdir(parents=True, exist_ok=True)
            (root / "data" / "output" / "step1" / "sample" / "catalog_summary.json").write_text(
                json.dumps({"total_pdf_pages": 10, "region_counts": {"total": 1}, "table_counts": {"rows": 1}}, ensure_ascii=False),
                encoding="utf-8",
            )
            audit = audit_project(root)
            plan = build_redesign_plan(audit)
            markdown = render_markdown_report(audit, plan)

            self.assertIn("# 国标解析项目 V2 审计与重构建议", markdown)
            self.assertIn("## V2 流程", markdown)
            self.assertIn("## Work Units", markdown)
            self.assertIn("## Review Contracts", markdown)
            self.assertIn("## Cutover Gates", markdown)


if __name__ == "__main__":
    unittest.main()
