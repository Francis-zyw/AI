from __future__ import annotations

import json
import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from pipeline_v2.step3_engine.api import (
    CHAPTER_RULE_JSON_NAME,
    FINAL_JSON_NAME,
    LOCAL_JSON_NAME,
    apply_runtime_environment,
    ensure_complete_step2_outputs,
    load_step1_rows,
    resolve_runtime_options,
    run_filter_condition_match,
    run_filter_condition_pipeline,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TABLE_REGIONS_PATH = PROJECT_ROOT / "tests" / "fixtures" / "step3" / "sample_table_regions.json"
SYNONYM_LIBRARY_PATH = PROJECT_ROOT / "tests" / "fixtures" / "step3" / "sample_synonym_library.json"
COMPONENTS_PATH = PROJECT_ROOT / "tests" / "fixtures" / "step3" / "sample_components.json"


class Step3FilterConditionMatchTests(unittest.TestCase):
    def test_load_step1_rows_repairs_shared_features_and_rule(self) -> None:
        rows = load_step1_rows(TABLE_REGIONS_PATH)

        wall_row = next(row for row in rows if row["project_code"] == "010502010")
        self.assertEqual(wall_row["project_name"], "钢筋混凝土墙")
        self.assertIn("1.混凝土种类", wall_row["project_features"])
        self.assertIn("2.混凝土强度等级", wall_row["project_features"])
        self.assertIn("3.墙厚>200mm", wall_row["project_features"])
        self.assertIn("按设计图示尺寸以体积计算", wall_row["quantity_rule"])
        self.assertIn("内、外墙高度均算至板顶", wall_row["quantity_rule"])
        self.assertIn("墙厚", wall_row["chapter_feature_hints"])
        self.assertIn("TJ", wall_row["chapter_calculation_codes"])
        self.assertTrue(wall_row["chapter_rule_hits"])

    def test_run_filter_condition_match_builds_feature_expression_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            summary = run_filter_condition_match(
                step1_table_regions_path=TABLE_REGIONS_PATH,
                components_path=COMPONENTS_PATH,
                synonym_library_path=SYNONYM_LIBRARY_PATH,
                output_dir=Path(temp_dir),
                max_components_per_item=2,
            )

            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["total_source_rows"], 4)
            self.assertEqual(summary["generated_rows"], 4)
            self.assertEqual(summary["matched_rows"], 4)
            self.assertTrue((Path(temp_dir) / CHAPTER_RULE_JSON_NAME).exists())

            payload = json.loads((Path(temp_dir) / FINAL_JSON_NAME).read_text(encoding="utf-8"))
            rows = payload["rows"]

            wall_row = next(row for row in rows if row["project_code"] == "010502010")
            self.assertEqual(wall_row["quantity_component"], "砼墙")
            self.assertEqual(wall_row["calculation_item_code"], "TJ")
            self.assertIn("1. 混凝土种类:TLX", wall_row["feature_expression_text"])
            self.assertIn("2. 混凝土强度等级:TBH", wall_row["feature_expression_text"])
            self.assertIn("3. 墙厚:HD=>200mm", wall_row["feature_expression_text"])
            self.assertTrue(wall_row["chapter_rule_hits"])
            self.assertIn("钢筋混凝土墙", wall_row["chapter_target_terms"])
            self.assertIn("按体积计算", wall_row["notes"])

            template_row = next(row for row in rows if row["project_code"] == "010505005")
            self.assertEqual(template_row["quantity_component"], "砼墙")
            self.assertEqual(template_row["calculation_item_code"], "MBMJ")
            self.assertIn("1. 模板形式:MBLX", template_row["feature_expression_text"])

            beam_row = next(row for row in rows if row["project_code"] == "010502011")
            self.assertEqual(beam_row["quantity_component"], "梁")
            self.assertEqual(beam_row["calculation_item_code"], "TJ")

    def test_run_filter_condition_pipeline_prepare_only_writes_prompt_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            summary = run_filter_condition_pipeline(
                step1_table_regions_path=TABLE_REGIONS_PATH,
                components_path=COMPONENTS_PATH,
                synonym_library_path=SYNONYM_LIBRARY_PATH,
                output_dir=Path(temp_dir),
                max_rows_per_batch=2,
                max_components_per_item=2,
                prepare_only=True,
            )

            self.assertEqual(summary["status"], "prepared_only")
            self.assertTrue((Path(temp_dir) / LOCAL_JSON_NAME).exists())
            self.assertTrue((Path(temp_dir) / "batch_001_prompt.txt").exists())
            self.assertTrue((Path(temp_dir) / "batch_001_prompt_input.json").exists())
            self.assertTrue((Path(temp_dir) / "batch_002_prompt.txt").exists())

    @patch("pipeline_v2.step2_engine.api.run_openai_startup_check")
    @patch("pipeline_v2.step3_engine.api.call_openai_model")
    def test_run_filter_condition_pipeline_calls_model_and_merges_rows(
        self,
        mock_call_openai_model,
        mock_run_openai_startup_check,
    ) -> None:
        mock_run_openai_startup_check.return_value = {"status": "passed"}
        mock_call_openai_model.return_value = json.dumps(
            {
                "meta": {
                    "task_name": "project_component_feature_calc_matching",
                    "standard_document": "sample",
                    "generated_at": "2026-03-20T12:00:00+08:00",
                    "review_stage": "model_refine",
                },
                "rows": [
                    {
                        "result_id": "M000002",
                        "row_id": "R0002",
                        "project_code": "010502010",
                        "project_name": "钢筋混凝土墙",
                        "quantity_component": "砼墙",
                        "resolved_component_name": "砼墙",
                        "source_component_name": "砼墙",
                        "match_status": "matched",
                        "match_basis": "alias_bridge",
                        "confidence": 0.99,
                        "feature_expression_items": [
                            {
                                "order": 1,
                                "raw_text": "混凝土种类",
                                "label": "混凝土种类",
                                "attribute_name": "混凝土种类",
                                "attribute_code": "TLX",
                                "value_expression": "",
                                "expression": "混凝土种类:TLX",
                                "matched": True,
                            },
                            {
                                "order": 2,
                                "raw_text": "混凝土强度等级",
                                "label": "混凝土强度等级",
                                "attribute_name": "混凝土强度等级",
                                "attribute_code": "TBH",
                                "value_expression": "",
                                "expression": "混凝土强度等级:TBH",
                                "matched": True,
                            },
                            {
                                "order": 3,
                                "raw_text": "墙厚>200mm",
                                "label": "墙厚",
                                "attribute_name": "墙厚",
                                "attribute_code": "HD",
                                "value_expression": ">200mm",
                                "expression": "墙厚:HD=>200mm",
                                "matched": True,
                            },
                        ],
                        "feature_expression_text": "1. 混凝土种类:TLX<br>2. 混凝土强度等级:TBH<br>3. 墙厚:HD=>200mm",
                        "calculation_item_name": "体积",
                        "calculation_item_code": "TJ",
                        "measurement_unit": "m3",
                        "review_status": "confirmed",
                        "reasoning": "模型确认墙项目应使用砼墙和体积计算。",
                        "notes": "model_checked",
                    }
                ],
            },
            ensure_ascii=False,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            summary = run_filter_condition_pipeline(
                step1_table_regions_path=TABLE_REGIONS_PATH,
                components_path=COMPONENTS_PATH,
                synonym_library_path=SYNONYM_LIBRARY_PATH,
                output_dir=Path(temp_dir),
                max_rows_per_batch=10,
                max_components_per_item=2,
            )

            self.assertEqual(summary["status"], "completed")
            self.assertEqual(mock_call_openai_model.call_count, 1)

            payload = json.loads((Path(temp_dir) / FINAL_JSON_NAME).read_text(encoding="utf-8"))
            self.assertEqual(payload["meta"]["generation_mode"], "model")
            self.assertEqual(len(payload["rows"]), 4)

            wall_row = next(row for row in payload["rows"] if row["result_id"] == "M000002")
            self.assertEqual(wall_row["review_status"], "confirmed")
            self.assertEqual(wall_row["reasoning"], "模型确认墙项目应使用砼墙和体积计算。")
            self.assertEqual(wall_row["feature_expression_text"], "1. 混凝土种类:TLX<br>2. 混凝土强度等级:TBH<br>3. 墙厚:HD=>200mm")

    def test_resolve_runtime_options_reads_config_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "runtime_config.ini"
            config_path.write_text(
                "\n".join(
                    [
                        "[paths]",
                        f"step1_table_regions = {TABLE_REGIONS_PATH}",
                        f"step2_result = {PROJECT_ROOT / 'tests' / 'fixtures' / 'step3' / 'sample_component_matching_result.json'}",
                        f"components = {COMPONENTS_PATH}",
                        f"synonym_library = {SYNONYM_LIBRARY_PATH}",
                        "output = /tmp/step3_config_output",
                        "",
                        "[model]",
                        "model = gpt-5.4-mini",
                        "reasoning_effort = low",
                        "request_timeout_seconds = 150",
                        "connection_retries = 4",
                        "",
                        "[run]",
                        "prepare_only = true",
                        "local_only = false",
                        "max_rows_per_batch = 12",
                        "max_components_per_item = 4",
                    ]
                ),
                encoding="utf-8",
            )

            options = resolve_runtime_options(
                Namespace(
                    config=str(config_path),
                    step1_table_regions=None,
                    step2_result=None,
                    components=None,
                    synonym_library=None,
                    output=None,
                    model=None,
                    reasoning_effort=None,
                    max_rows_per_batch=None,
                    max_components_per_item=None,
                    prepare_only=None,
                    local_only=None,
                )
            )

            self.assertEqual(options["model"], "gpt-5.4-mini")
            self.assertEqual(options["reasoning_effort"], "low")
            self.assertEqual(options["request_timeout_seconds"], 150.0)
            self.assertEqual(options["connection_retries"], 4)
            self.assertTrue(options["prepare_only"])
            self.assertFalse(options["local_only"])
            self.assertEqual(options["max_rows_per_batch"], 12)
            self.assertEqual(options["max_components_per_item"], 4)
            self.assertEqual(options["synonym_library_path"], str(SYNONYM_LIBRARY_PATH))

    def test_apply_runtime_environment_defaults_to_openai_base_url(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "existing-openai-key",
                "OPENROUTER_API_KEY": "legacy-openrouter-key",
                "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
            },
            clear=False,
        ):
            previous = apply_runtime_environment({"openai_api_key": None, "openai_base_url": None})

            self.assertEqual(previous["OPENAI_API_KEY"], "existing-openai-key")
            self.assertIsNone(previous["OPENAI_BASE_URL"])
            self.assertEqual(os.environ["OPENAI_API_KEY"], "existing-openai-key")
            self.assertEqual(os.environ["OPENAI_BASE_URL"], "https://api.openai.com/v1")

    def test_run_filter_condition_pipeline_requires_completed_step2_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            synonym_path = Path(temp_dir) / "synonym_library.json"
            synonym_path.write_text(SYNONYM_LIBRARY_PATH.read_text(encoding="utf-8"), encoding="utf-8")

            with self.assertRaises(FileNotFoundError):
                run_filter_condition_pipeline(
                    step1_table_regions_path=TABLE_REGIONS_PATH,
                    components_path=COMPONENTS_PATH,
                    synonym_library_path=synonym_path,
                    output_dir=Path(temp_dir) / "step3_output",
                    prepare_only=True,
                )

    def test_ensure_complete_step2_outputs_recovers_failed_run_summary_from_existing_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            step1_dir = root / "data" / "output" / "step1" / "sample-standard"
            chapter_dir = step1_dir / "chapter_regions"
            chapter_dir.mkdir(parents=True, exist_ok=True)
            (chapter_dir / "001_附录A_土石方工程.json").write_text(
                json.dumps(
                    {
                        "chapter": {"title": "附录A 土石方工程"},
                        "regions": [{"title": "附录A 土石方工程", "path_text": "附录A 土石方工程"}],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (chapter_dir / "chapter_index.json").write_text(
                json.dumps(
                    {"chapters": [{"title": "附录A 土石方工程", "relative_path": "chapter_regions/001_附录A_土石方工程.json"}]},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            step2_dir = root / "data" / "output" / "step2" / "sample-standard"
            step2_dir.mkdir(parents=True, exist_ok=True)
            (step2_dir / "execute_manifest.json").write_text(
                json.dumps(
                    {
                        "standard_document": "sample-standard",
                        "components_path": str(COMPONENTS_PATH),
                        "step1_source_path": str(step1_dir),
                        "chapter_count": 1,
                        "component_batch_count_per_chapter": 1,
                        "total_component_batch_count_per_chapter": 1,
                        "components_per_chapter_batch": 5,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (step2_dir / "run_summary.json").write_text(
                json.dumps({"status": "failed", "error": "network"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            chapter_output_dir = step2_dir / "chapter_001_附录A_土石方工程"
            chapter_output_dir.mkdir(parents=True, exist_ok=True)
            (chapter_output_dir / "chapter_result.json").write_text(
                json.dumps(
                    {
                        "meta": {
                            "task_name": "component_standard_name_matching",
                            "standard_document": "sample-standard",
                            "chapter_title": "附录A 土石方工程",
                            "chapter_index": 1,
                        },
                        "mappings": [
                            {
                                "source_component_name": "砼墙",
                                "source_aliases": ["砼墙"],
                                "selected_standard_name": "附录A 土石方工程 > A.1 单独土石方",
                                "standard_aliases": ["附录A 土石方工程 > A.1 单独土石方"],
                                "candidate_standard_names": ["附录A 土石方工程 > A.1 单独土石方"],
                                "match_type": "chapter_serial_precheck",
                                "match_status": "matched",
                                "confidence": 0.9,
                                "review_status": "suggested",
                                "evidence_paths": ["附录A 土石方工程"],
                                "evidence_texts": ["用于验证 Step3 自动恢复。"],
                                "reasoning": "章节结果已存在。",
                                "manual_notes": "",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            summary = ensure_complete_step2_outputs(
                step2_result_path=step2_dir / "component_matching_result.json",
                synonym_library_path=step2_dir / "synonym_library.json",
            )

            self.assertEqual(summary["status"], "completed_from_existing")
            self.assertTrue((step2_dir / "component_matching_result.json").exists())
            self.assertTrue((step2_dir / "synonym_library.json").exists())


if __name__ == "__main__":
    unittest.main()
