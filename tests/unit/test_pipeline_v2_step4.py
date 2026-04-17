from __future__ import annotations

import json
import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from pipeline_v2.knowledge_base import build_knowledge_base, query_knowledge_base
from pipeline_v2.step4_direct_match import (
    LOCAL_RESULT_JSON_NAME,
    apply_runtime_environment,
    direct_match_bill_item,
    direct_match_bill_items,
    resolve_runtime_options,
    run_step4_from_step3_result_pipeline,
    run_step4_pipeline,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPONENTS_PATH = PROJECT_ROOT / "tests" / "fixtures" / "step3" / "sample_components.json"
SYNONYM_LIBRARY_PATH = PROJECT_ROOT / "tests" / "fixtures" / "step3" / "sample_synonym_library.json"
STEP1_TABLE_REGIONS_PATH = PROJECT_ROOT / "tests" / "fixtures" / "step3" / "sample_table_regions.json"
STEP2_LEGACY_RESULT_PATH = PROJECT_ROOT / "tests" / "fixtures" / "step3" / "sample_step2_result.json"


class PipelineV2Step4Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.components_payload = json.loads(COMPONENTS_PATH.read_text(encoding="utf-8"))
        self.synonym_payload = json.loads(SYNONYM_LIBRARY_PATH.read_text(encoding="utf-8"))
        self.sample_items = [
            {
                "project_code": "010502010",
                "project_name": "钢筋混凝土墙",
                "project_features": "1.混凝土种类、强度等级",
                "measurement_unit": "m3",
                "quantity_rule": "按设计图示尺寸以体积计算",
            },
            {
                "project_code": "010502011",
                "project_name": "混凝土梁",
                "project_features": "1.混凝土种类、强度等级",
                "measurement_unit": "m3",
                "quantity_rule": "按设计图示尺寸以体积计算",
            },
        ]

    def test_direct_match_splits_combined_features_and_selects_tlx_tbh(self) -> None:
        result = direct_match_bill_item(
            {
                "project_code": "010502010",
                "project_name": "钢筋混凝土墙",
                "project_features": "1.混凝土种类、强度等级",
                "measurement_unit": "m3",
                "quantity_rule": "按设计图示尺寸以体积计算",
                "component_type": "砼墙",
            },
            self.components_payload,
            self.synonym_payload,
        )

        self.assertEqual(result["component_type"], "砼墙")
        self.assertEqual(result["quantity_component"], "砼墙")
        self.assertEqual(result["calculation_item_code"], "TJ")
        self.assertEqual(result["calculation_item_name"], "体积")
        self.assertEqual(result["match_status"], "matched")
        self.assertEqual(result["review_status"], "suggested")
        self.assertEqual(
            result["feature_expression_text"],
            "1. 混凝土种类:TLX<br>2. 强度等级:TBH",
        )
        self.assertEqual(
            [item["expression"] for item in result["feature_expression_items"]],
            ["混凝土种类:TLX", "强度等级:TBH"],
        )
        self.assertTrue(all(item["matched"] for item in result["feature_expression_items"]))

    def test_batch_direct_match_keeps_order_and_supports_multiple_items(self) -> None:
        results = direct_match_bill_items(
            [
                {
                    "project_code": "010502010",
                    "project_name": "钢筋混凝土墙",
                    "project_features": "1.混凝土种类、强度等级",
                    "measurement_unit": "m3",
                    "quantity_rule": "按设计图示尺寸以体积计算",
                    "component_type": "砼墙",
                },
                {
                    "project_code": "010502011",
                    "project_name": "混凝土梁",
                    "project_features": "1.混凝土种类、强度等级",
                    "measurement_unit": "m3",
                    "quantity_rule": "按设计图示尺寸以体积计算",
                    "component_type": "梁",
                },
            ],
            self.components_payload,
            self.synonym_payload,
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["row_id"], "S4-0001")
        self.assertEqual(results[1]["row_id"], "S4-0002")
        self.assertEqual(results[0]["quantity_component"], "砼墙")
        self.assertEqual(results[1]["quantity_component"], "梁")
        self.assertEqual(results[1]["calculation_item_code"], "TJ")
        self.assertEqual(results[1]["feature_expression_text"], "1. 混凝土种类:TLX<br>2. 强度等级:TBH")

    def test_resolve_runtime_options_reads_config_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "step4_runtime_config.ini"
            config_path.write_text(
                "\n".join(
                    [
                        "[paths]",
                        f"components = {COMPONENTS_PATH}",
                        f"synonym_library = {SYNONYM_LIBRARY_PATH}",
                        "output = /tmp/step4_config_output",
                        "",
                        "[model]",
                        "model = gpt-5.4-mini",
                        "reasoning_effort = low",
                        "provider_mode = env_api_key",
                        "api_key_env = STEP4_TEST_OPENAI_API_KEY",
                        "base_url_env = STEP4_TEST_OPENAI_BASE_URL",
                        "openai_base_url = https://example.invalid/v1",
                        "",
                        "[run]",
                        "component_type = 砼墙",
                        "prepare_only = true",
                        "local_only = false",
                        "max_items_per_batch = 7",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "STEP4_TEST_OPENAI_API_KEY": "step4-config-key",
                    "STEP4_TEST_OPENAI_BASE_URL": "https://model-gateway.example/v1",
                },
                clear=False,
            ):
                options = resolve_runtime_options(
                    Namespace(
                        config=str(config_path),
                        models_config=str(Path(temp_dir) / "missing_runtime_models.ini"),
                        component_type=None,
                        components=None,
                        synonym_library=None,
                        output=None,
                        model=None,
                        reasoning_effort=None,
                        openai_api_key=None,
                        openai_base_url=None,
                        max_items_per_batch=None,
                        prepare_only=None,
                        local_only=None,
                    )
                )

            self.assertEqual(options["component_type"], "砼墙")
            self.assertEqual(options["model"], "gpt-5.4-mini")
            self.assertEqual(options["reasoning_effort"], "low")
            self.assertEqual(options["provider_mode"], "env_api_key")
            self.assertEqual(options["max_items_per_batch"], 7)
            self.assertTrue(options["prepare_only"])
            self.assertFalse(options["local_only"])
            self.assertEqual(options["components_path"], str(COMPONENTS_PATH))
            self.assertEqual(options["synonym_library_path"], str(SYNONYM_LIBRARY_PATH))
            self.assertEqual(options["openai_api_key"], "step4-config-key")
            self.assertEqual(options["openai_base_url"], "https://model-gateway.example/v1")

    def test_resolve_runtime_options_reads_models_config_step4_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            models_config_path = Path(temp_dir) / "runtime_models.ini"
            models_config_path.write_text(
                "\n".join(
                    [
                        "[step4]",
                        "model = openai-codex/gpt-5.4-mini",
                        "reasoning_effort = low",
                        "provider_mode = codex",
                    ]
                ),
                encoding="utf-8",
            )

            options = resolve_runtime_options(
                Namespace(
                    config=None,
                    models_config=str(models_config_path),
                    component_type="砼墙",
                    components=str(COMPONENTS_PATH),
                    synonym_library=str(SYNONYM_LIBRARY_PATH),
                    output=None,
                    model=None,
                    reasoning_effort=None,
                    openai_api_key=None,
                    openai_base_url=None,
                    max_items_per_batch=None,
                    prepare_only=None,
                    local_only=None,
                )
            )

            self.assertEqual(options["model"], "gpt-5.4-mini")
            self.assertEqual(options["reasoning_effort"], "low")
            self.assertEqual(options["provider_mode"], "codex")
            self.assertTrue(options["use_codex_subscription"])

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

    def test_apply_runtime_environment_codex_keeps_missing_openai_key(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "existing-openai-key",
                "OPENAI_BASE_URL": "https://api.openai.com/v1",
            },
            clear=False,
        ):
            previous = apply_runtime_environment(
                {
                    "provider_mode": "codex",
                    "openai_api_key": None,
                    "openai_base_url": None,
                }
            )

            self.assertEqual(previous["OPENAI_API_KEY"], "existing-openai-key")
            self.assertEqual(previous["OPENAI_BASE_URL"], "https://api.openai.com/v1")
            self.assertNotIn("OPENAI_API_KEY", os.environ)
            self.assertNotIn("OPENAI_BASE_URL", os.environ)

    def test_run_step4_pipeline_prepare_only_writes_prompt_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_step4_pipeline(
                bill_items=self.sample_items,
                component_type="砼墙",
                components_path=COMPONENTS_PATH,
                synonym_library_path=SYNONYM_LIBRARY_PATH,
                output_dir=Path(temp_dir),
                max_items_per_batch=1,
                prepare_only=True,
            )

            self.assertEqual(result["run_summary"]["status"], "prepared_only")
            self.assertTrue((Path(temp_dir) / LOCAL_RESULT_JSON_NAME).exists())
            self.assertTrue((Path(temp_dir) / "batch_001_prompt.txt").exists())
            self.assertTrue((Path(temp_dir) / "batch_001_prompt_input.json").exists())
            self.assertTrue((Path(temp_dir) / "batch_002_prompt.txt").exists())
            self.assertEqual(result["result_payload"]["meta"]["generation_mode"], "prepare_only")

    def test_run_step4_pipeline_local_only_returns_local_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_step4_pipeline(
                bill_items=self.sample_items,
                component_type="砼墙",
                components_path=COMPONENTS_PATH,
                synonym_library_path=SYNONYM_LIBRARY_PATH,
                output_dir=Path(temp_dir),
                local_only=True,
            )

            self.assertEqual(result["run_summary"]["status"], "completed_local_only")
            self.assertEqual(result["result_payload"]["meta"]["generation_mode"], "local_direct")
            self.assertEqual(len(result["result_payload"]["rows"]), 2)
            self.assertTrue((Path(temp_dir) / "step4_direct_match_result.json").exists())

    @patch("pipeline_v2.step4_direct_match.call_openai_model")
    def test_run_step4_pipeline_calls_model_and_merges_rows(self, mock_call_openai_model) -> None:
        mock_call_openai_model.return_value = json.dumps(
            {
                "meta": {
                    "task_name": "step4_direct_match",
                    "review_stage": "model_refine",
                },
                "rows": [
                    {
                        "row_id": "S4-0001",
                        "project_code": "010502010",
                        "project_name": "钢筋混凝土墙",
                        "component_type": "砼墙",
                        "source_component_name": "砼墙",
                        "project_features_raw": "1.混凝土种类、强度等级",
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
                                "raw_text": "强度等级",
                                "label": "强度等级",
                                "attribute_name": "混凝土强度等级",
                                "attribute_code": "TBH",
                                "value_expression": "",
                                "expression": "强度等级:TBH",
                                "matched": True,
                            },
                        ],
                        "feature_expression_text": "1. 混凝土种类:TLX<br>2. 强度等级:TBH",
                        "quantity_rule": "按设计图示尺寸以体积计算",
                        "work_content": "",
                        "quantity_component": "砼墙",
                        "resolved_component_name": "砼墙",
                        "calculation_item_name": "体积",
                        "calculation_item_code": "TJ",
                        "measurement_unit": "m3",
                        "match_status": "matched",
                        "review_status": "confirmed",
                        "confidence": 0.98,
                        "reasoning": "模型确认该清单项与砼墙直匹配结果一致。",
                        "manual_notes": "model_checked",
                    }
                ],
            },
            ensure_ascii=False,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_step4_pipeline(
                bill_items=self.sample_items[:1],
                component_type="砼墙",
                components_path=COMPONENTS_PATH,
                synonym_library_path=SYNONYM_LIBRARY_PATH,
                output_dir=Path(temp_dir),
                provider_mode="codex",
                max_items_per_batch=5,
            )

            self.assertEqual(result["run_summary"]["status"], "completed")
            self.assertEqual(result["run_summary"]["model_requests"], 1)
            self.assertEqual(result["run_summary"]["provider_mode"], "codex")
            self.assertEqual(mock_call_openai_model.call_count, 1)
            self.assertEqual(mock_call_openai_model.call_args.kwargs["provider_mode"], "codex")
            self.assertEqual(result["result_payload"]["meta"]["generation_mode"], "model_refine")
            row = result["result_payload"]["rows"][0]
            self.assertEqual(row["review_status"], "confirmed")
            self.assertEqual(row["confidence"], 0.98)
            self.assertEqual(row["reasoning"], "模型确认该清单项与砼墙直匹配结果一致。")
            self.assertTrue((Path(temp_dir) / "batch_001_model_output.txt").exists())
            self.assertTrue((Path(temp_dir) / "step4_direct_match_result.json").exists())

    def test_run_step4_from_step3_result_pipeline_groups_rows_and_preserves_row_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            step3_result_path = Path(temp_dir) / "step3_result.json"
            step3_result_path.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "row_id": "R0002",
                                "project_code": "010502010",
                                "project_name": "钢筋混凝土墙",
                                "project_features_raw": "1.混凝土种类、强度等级",
                                "measurement_unit": "m3",
                                "quantity_rule": "按设计图示尺寸以体积计算",
                                "quantity_component": "砼墙",
                                "resolved_component_name": "砼墙",
                                "match_status": "candidate_only",
                            },
                            {
                                "row_id": "R0003",
                                "project_code": "010502011",
                                "project_name": "混凝土梁",
                                "project_features_raw": "1.混凝土种类、强度等级",
                                "measurement_unit": "m3",
                                "quantity_rule": "按设计图示尺寸以体积计算",
                                "quantity_component": "梁",
                                "resolved_component_name": "梁",
                                "match_status": "matched",
                            },
                            {
                                "row_id": "R0004",
                                "project_code": "010502012",
                                "project_name": "未定构件项",
                                "project_features_raw": "1.待人工判断",
                                "measurement_unit": "m3",
                                "quantity_rule": "",
                                "quantity_component": "",
                                "resolved_component_name": "",
                                "match_status": "unmatched",
                            },
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = run_step4_from_step3_result_pipeline(
                step3_result_path=step3_result_path,
                components_path=COMPONENTS_PATH,
                synonym_library_path=SYNONYM_LIBRARY_PATH,
                output_dir=Path(temp_dir) / "step4_from_step3",
                local_only=True,
            )

            self.assertEqual(result["run_summary"]["status"], "completed_local_only")
            self.assertEqual(result["run_summary"]["selected_item_count"], 2)
            self.assertEqual(result["run_summary"]["component_group_count"], 2)
            self.assertEqual(result["run_summary"]["skipped_rows_without_component_type"], 1)
            self.assertEqual(
                [row["row_id"] for row in result["result_payload"]["rows"]],
                ["R0002", "R0003"],
            )
            self.assertTrue((Path(temp_dir) / "step4_from_step3" / "step4_from_step3_result.json").exists())

    def test_build_knowledge_base_and_query_support_step4_prompt_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            step2_dir = temp_root / "step2"
            step2_dir.mkdir(parents=True, exist_ok=True)
            (step2_dir / "result.json").write_text(STEP2_LEGACY_RESULT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
            (step2_dir / "synonym_library.json").write_text(SYNONYM_LIBRARY_PATH.read_text(encoding="utf-8"), encoding="utf-8")

            step3_result_path = temp_root / "step3_result.json"
            step3_result_path.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "row_id": "R0101",
                                "project_code": "010502010",
                                "project_name": "钢筋混凝土墙",
                                "project_features_raw": "1.混凝土种类\n2.混凝土强度等级\n3.墙厚>200mm",
                                "feature_expression_text": "1. 混凝土种类:TLX<br>2. 强度等级:TBH<br>3. 墙厚:HD=>200mm",
                                "measurement_unit": "m3",
                                "quantity_rule": "按设计图示尺寸以体积计算",
                                "quantity_component": "砼墙",
                                "resolved_component_name": "砼墙",
                                "calculation_item_name": "体积",
                                "calculation_item_code": "TJ",
                                "match_status": "matched",
                                "match_basis": "chapter_rule",
                                "chapter_rule_hits": ["钢筋混凝土墙应按相关项目编码列项"],
                            }
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            knowledge_dir = temp_root / "knowledge"
            summary = build_knowledge_base(
                step1_source=STEP1_TABLE_REGIONS_PATH,
                step2_source=step2_dir,
                step3_source=step3_result_path,
                output_dir=knowledge_dir,
            )

            self.assertEqual(summary["status"], "completed")
            self.assertTrue((knowledge_dir / "knowledge.db").exists())
            self.assertTrue((knowledge_dir / "wiki" / "overview.md").exists())
            self.assertTrue((knowledge_dir / "wiki" / "components" / "砼墙.md").exists())

            query_result = query_knowledge_base(
                knowledge_base_path=knowledge_dir,
                query_text="钢筋混凝土墙 墙厚 体积",
                component_type="砼墙",
                top_k=3,
                max_context_chars=1600,
            )

            self.assertTrue(query_result["retrieved_entries"])
            self.assertTrue(
                any(
                    "钢筋混凝土墙" in json.dumps(item, ensure_ascii=False)
                    or "墙厚" in json.dumps(item, ensure_ascii=False)
                    for item in query_result["retrieved_entries"]
                )
            )
            self.assertTrue(query_result["retrieved_wiki_pages"])

            step4_output_dir = temp_root / "step4_prepare"
            result = run_step4_pipeline(
                bill_items=self.sample_items[:1],
                component_type="砼墙",
                components_path=COMPONENTS_PATH,
                synonym_library_path=SYNONYM_LIBRARY_PATH,
                knowledge_base_path=knowledge_dir,
                output_dir=step4_output_dir,
                prepare_only=True,
            )

            prompt_text = (step4_output_dir / "batch_001_prompt.txt").read_text(encoding="utf-8")
            self.assertEqual(result["run_summary"]["status"], "prepared_only")
            self.assertIn("KNOWLEDGE_BASE_WIKI", prompt_text)
            self.assertIn("KNOWLEDGE_BASE_RETRIEVAL", prompt_text)
            self.assertIn("钢筋混凝土墙", prompt_text)


if __name__ == "__main__":
    unittest.main()
