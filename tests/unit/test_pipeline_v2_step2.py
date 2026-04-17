from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline_v2.step2_engine.api import build_synonym_library
from pipeline_v2.step2_v2 import (
    build_openai_request_payload,
    build_step2_prompt_text,
    coerce_model_payload,
    execute,
    load_all_bill_chapters,
    prepare,
    synthesize_existing_step2_outputs,
)


class Step2V2Tests(unittest.TestCase):
    def _write_step1_fixture(self, root: Path) -> Path:
        step1_dir = root / "data" / "output" / "step1" / "sample-standard"
        chapter_dir = step1_dir / "chapter_regions"
        chapter_dir.mkdir(parents=True, exist_ok=True)

        (chapter_dir / "001_1_总则.json").write_text(
            json.dumps({"chapter": {"title": "1 总则"}, "regions": [{"title": "1 总则", "path_text": "1 总则"}]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (chapter_dir / "002_附录A_土石方工程.json").write_text(
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
        (chapter_dir / "003_附录B_砌筑工程.json").write_text(
            json.dumps(
                {
                    "chapter": {"title": "附录B 砌筑工程"},
                    "regions": [{"title": "附录B 砌筑工程", "path_text": "附录B 砌筑工程"}],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (chapter_dir / "chapter_index.json").write_text(
            json.dumps(
                {
                    "chapters": [
                        {"title": "1 总则", "relative_path": "chapter_regions/001_1_总则.json"},
                        {"title": "附录A 土石方工程", "relative_path": "chapter_regions/002_附录A_土石方工程.json"},
                        {"title": "附录B 砌筑工程", "relative_path": "chapter_regions/003_附录B_砌筑工程.json"},
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return step1_dir

    def _write_components_fixture(self, root: Path) -> Path:
        components_path = root / "data" / "input" / "components.json"
        components_path.parent.mkdir(parents=True, exist_ok=True)
        components_path.write_text(
            json.dumps(
                [
                    {
                        "component_type": "砼墙",
                        "properties": {
                            "attributes": [
                                {"name": "混凝土种类", "code": "TLX", "values": ["商品砼"]},
                                {"name": "混凝土强度等级", "code": "TBH", "values": ["C30"]},
                            ],
                            "calculations": [{"name": "体积", "code": "TJ", "unit": "m3"}],
                        },
                    }
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return components_path

    def _write_components_fixture_with_many_items(self, root: Path, total: int = 6) -> Path:
        components_path = root / "data" / "input" / "components.json"
        components_path.parent.mkdir(parents=True, exist_ok=True)
        components = []
        for index in range(1, total + 1):
            components.append(
                {
                    "component_type": f"构件{index}",
                    "properties": {
                        "attributes": [{"name": "构件类别", "code": "GJLB", "values": [f"类型{index}"]}],
                        "calculations": [{"name": "体积", "code": "TJ", "unit": "m3"}],
                    },
                }
            )
        components_path.write_text(json.dumps(components, ensure_ascii=False, indent=2), encoding="utf-8")
        return components_path

    def _write_step1_fixture_with_many_chapters(self, root: Path) -> Path:
        step1_dir = root / "data" / "output" / "step1" / "sample-standard"
        chapter_dir = step1_dir / "chapter_regions"
        chapter_dir.mkdir(parents=True, exist_ok=True)

        chapters = [
            ("001_附录A_土石方工程.json", "附录A 土石方工程"),
            ("002_附录B_砌筑工程.json", "附录B 砌筑工程"),
            ("003_附录C_桩基工程.json", "附录C 桩基工程"),
        ]
        index_payload = {"chapters": []}
        for file_name, title in chapters:
            (chapter_dir / file_name).write_text(
                json.dumps(
                    {
                        "chapter": {"title": title},
                        "regions": [{"title": title, "path_text": title}],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            index_payload["chapters"].append({"title": title, "relative_path": f"chapter_regions/{file_name}"})

        (chapter_dir / "chapter_index.json").write_text(
            json.dumps(index_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return step1_dir

    def _contains_disallowed_key(self, value: object, disallowed_keys: set[str]) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in disallowed_keys:
                    return True
                if self._contains_disallowed_key(item, disallowed_keys):
                    return True
            return False
        if isinstance(value, list):
            return any(self._contains_disallowed_key(item, disallowed_keys) for item in value)
        return False

    def test_load_all_bill_chapters_loads_every_bill_chapter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            step1_dir = self._write_step1_fixture(root)

            chapters = load_all_bill_chapters(step1_dir)

            self.assertEqual([chapter["title"] for chapter in chapters], ["附录A 土石方工程", "附录B 砌筑工程"])
            self.assertEqual(len(chapters), 2)

    def test_prepare_writes_manifest_and_plain_text_request_without_file_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            step1_dir = self._write_step1_fixture(root)
            components_path = self._write_components_fixture(root)
            output_dir = root / "data" / "output" / "step2_v2"

            result = prepare(components_path=components_path, step1_source_path=step1_dir, output_dir=output_dir)

            self.assertEqual(result["manifest"]["chapter_count"], 2)
            self.assertIn("附录A 土石方工程", result["prompt_text"])
            self.assertIn("附录B 砌筑工程", result["prompt_text"])
            self.assertIsInstance(result["request_payload"]["input"], str)
            self.assertFalse(self._contains_disallowed_key(result["request_payload"], {"file_data", "input_file"}))
            self.assertTrue((output_dir / "prepare_manifest.json").exists())
            self.assertTrue((output_dir / "prepare_prompt.txt").exists())
            self.assertTrue((output_dir / "prepare_request.json").exists())

    def test_build_openai_request_payload_is_plain_text(self) -> None:
        payload = build_openai_request_payload("hello world")

        self.assertEqual(payload["input"], "hello world")
        self.assertNotIn("file_data", payload)
        self.assertEqual(payload["text"]["format"]["type"], "json_object")

    def test_coerce_model_payload_supports_results_shape(self) -> None:
        payload = coerce_model_payload(
            {
                "document": "sample-standard",
                "results": [
                    {
                        "component_name": "构件A",
                        "candidate_standard_names": ["标准A"],
                        "synonym_library": ["构件A", "别名A"],
                        "evidence": {
                            "chapters": ["附录A 土石方工程"],
                            "component": ["构件名: 构件A"],
                            "reason": "章节名称可直接对应。",
                        },
                    },
                    {
                        "构件名称": "土石方",
                        "候选标准名": ["附录A 土石方工程 > A.1 单独土石方"],
                        "同义词库": ["土石方", "单独土石方"],
                        "证据": {
                            "构件证据": ["构件名: 土石方"],
                            "章节证据": ["附录A 土石方工程 > A.1 单独土石方"],
                            "match_conclusion": "章节直接对应。",
                        },
                    },
                ],
            },
            "sample-standard",
        )

        self.assertEqual(payload["meta"]["standard_document"], "sample-standard")
        self.assertEqual(payload["mappings"][0]["source_component_name"], "构件A")
        self.assertEqual(payload["mappings"][0]["match_status"], "matched")
        self.assertIn("别名A", payload["mappings"][0]["source_aliases"])
        self.assertIn("附录A 土石方工程", payload["mappings"][0]["evidence_paths"])
        self.assertEqual(payload["mappings"][1]["source_component_name"], "土石方")
        self.assertEqual(
            payload["mappings"][1]["selected_standard_name"],
            "附录A 土石方工程 > A.1 单独土石方",
        )
        self.assertEqual(payload["mappings"][1]["match_status"], "matched")

    def test_build_step2_prompt_text_supports_a_single_chapter_batch_with_five_components(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            step1_dir = self._write_step1_fixture_with_many_chapters(root)
            components_path = self._write_components_fixture_with_many_items(root, total=5)

            chapters = load_all_bill_chapters(step1_dir)[:1]
            components = json.loads(components_path.read_text(encoding="utf-8"))
            prompt_text = build_step2_prompt_text(components, chapters, "sample-standard")

            self.assertIn("章节: 附录A 土石方工程", prompt_text)
            self.assertEqual(prompt_text.count("构件名:"), 5)
            self.assertNotIn("附录B 砌筑工程", prompt_text)
            self.assertNotIn("附录C 桩基工程", prompt_text)

    def test_coerce_model_payload_treats_sentinel_selected_standard_names_as_unmatched(self) -> None:
        payload = coerce_model_payload(
            {
                "document": "sample-standard",
                "results": [
                    {"component_name": "构件1", "selected_standard_name": "None"},
                    {"component_name": "构件2", "selected_standard_name": "null"},
                    {"component_name": "构件3", "selected_standard_name": "无"},
                    {"component_name": "构件4", "selected_standard_name": "未匹配"},
                ],
            },
            "sample-standard",
        )

        self.assertEqual([item["selected_standard_name"] for item in payload["mappings"]], ["", "", "", ""])
        self.assertEqual([item["match_status"] for item in payload["mappings"]], ["unmatched", "unmatched", "unmatched", "unmatched"])
        self.assertEqual([item["review_status"] for item in payload["mappings"]], ["pending", "pending", "pending", "pending"])

    def test_synthesize_existing_step2_outputs_recovers_partial_main_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            step1_dir = self._write_step1_fixture(root)
            components_path = self._write_components_fixture(root)
            output_dir = root / "data" / "output" / "step2_v2"
            chapter_dir = output_dir / "chapter_001_附录A_土石方工程"
            chapter_dir.mkdir(parents=True, exist_ok=True)

            (output_dir / "execute_manifest.json").write_text(
                json.dumps(
                    {
                        "standard_document": "sample-standard",
                        "components_path": str(components_path),
                        "step1_source_path": str(step1_dir),
                        "chapter_count": 2,
                        "component_batch_count_per_chapter": 1,
                        "total_component_batch_count_per_chapter": 1,
                        "components_per_chapter_batch": 5,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (output_dir / "run_summary.json").write_text(
                json.dumps({"status": "failed", "error": "network"}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            chapter_payload = coerce_model_payload(
                {
                    "document": "sample-standard",
                    "results": [
                        {
                            "component_name": "砼墙",
                            "selected_standard_name": "附录A 土石方工程 > A.1 单独土石方",
                            "synonym_library": ["砼墙", "混凝土墙"],
                            "evidence": {
                                "chapters": ["附录A 土石方工程"],
                                "reason": "用于验证恢复聚合。",
                            },
                        }
                    ],
                },
                "sample-standard",
            )
            chapter_payload["meta"].update({"chapter_title": "附录A 土石方工程", "chapter_index": 1})
            (chapter_dir / "chapter_result.json").write_text(
                json.dumps(chapter_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            result = synthesize_existing_step2_outputs(output_dir=output_dir)

            self.assertEqual(result["run_summary"]["status"], "partial_from_existing")
            self.assertEqual(result["run_summary"]["recovered_chapter_count"], 1)
            self.assertTrue((output_dir / "component_matching_result.json").exists())
            self.assertTrue((output_dir / "synonym_library.json").exists())

            merged_payload = json.loads((output_dir / "component_matching_result.json").read_text(encoding="utf-8"))
            self.assertEqual(merged_payload["mappings"][0]["source_component_name"], "砼墙")
            self.assertEqual(
                merged_payload["mappings"][0]["selected_standard_name"],
                "附录A 土石方工程 > A.1 单独土石方",
            )

            synonym_payload = json.loads((output_dir / "synonym_library.json").read_text(encoding="utf-8"))
            self.assertEqual(synonym_payload["synonym_library"][0]["canonical_name"], "砼墙")
            self.assertEqual(
                synonym_payload["synonym_library"][0]["selected_standard_name"],
                "附录A 土石方工程 > A.1 单独土石方",
            )

    def test_build_synonym_library_keeps_unmatched_components_as_self_entries(self) -> None:
        synonym_payload = build_synonym_library(
            [
                {
                    "source_component_name": "平整场地",
                    "source_aliases": ["平整场地", "场地平整"],
                    "selected_standard_name": "A.3 平整场地及其他",
                    "standard_aliases": ["A.3 平整场地及其他"],
                    "match_type": "chapter_heading",
                    "review_status": "auto",
                    "evidence_paths": ["chapter_A.json"],
                    "reasoning": "直接命中章节标题。",
                },
                {
                    "source_component_name": "天井",
                    "source_aliases": ["天井"],
                    "selected_standard_name": "",
                    "standard_aliases": [],
                    "match_type": "unmatched",
                    "review_status": "pending",
                    "evidence_paths": [],
                    "reasoning": "当前章节范围内未匹配。",
                },
            ],
            {"standard_document": "sample-standard", "review_stage": "pre_parse"},
        )

        rows_by_name = {item["canonical_name"]: item for item in synonym_payload["synonym_library"]}
        self.assertIn("平整场地", rows_by_name)
        self.assertIn("天井", rows_by_name)
        self.assertEqual(rows_by_name["天井"]["source_component_names"], ["天井"])
        self.assertEqual(rows_by_name["天井"]["source_component_name"], "天井")
        self.assertEqual(rows_by_name["天井"]["aliases"], [])
        self.assertEqual(rows_by_name["天井"]["chapter_nodes"], [])
        self.assertEqual(rows_by_name["平整场地"]["source_component_name"], "平整场地")
        self.assertIn("场地平整", rows_by_name["平整场地"]["aliases"])
        self.assertIn("A.3 平整场地及其他", rows_by_name["平整场地"]["chapter_nodes"])
        self.assertEqual(synonym_payload["unmatched_components"], [])
        self.assertEqual(synonym_payload["meta"]["passthrough_component_count"], 1)
        self.assertEqual(synonym_payload["meta"]["library_mode"], "source_component_first")

    def test_synthesize_existing_step2_outputs_prefers_stronger_chapter_match_over_weak_semantic_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            step1_dir = self._write_step1_fixture(root)
            components_path = self._write_components_fixture(root)
            output_dir = root / "data" / "output" / "step2_v2"
            output_dir.mkdir(parents=True, exist_ok=True)

            (output_dir / "execute_manifest.json").write_text(
                json.dumps(
                    {
                        "standard_document": "sample-standard",
                        "components_path": str(components_path),
                        "step1_source_path": str(step1_dir),
                        "chapter_count": 2,
                        "component_batch_count_per_chapter": 1,
                        "total_component_batch_count_per_chapter": 1,
                        "components_per_chapter_batch": 5,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            chapter_a_dir = output_dir / "chapter_001_附录A_土石方工程"
            chapter_a_dir.mkdir(parents=True, exist_ok=True)
            chapter_a_payload = {
                "meta": {"chapter_title": "附录A 土石方工程", "chapter_index": 1},
                "mappings": [
                    {
                        "source_component_name": "砼墙",
                        "source_aliases": ["砼墙"],
                        "selected_standard_name": "A.3 平整场地及其他",
                        "standard_aliases": ["A.3 平整场地及其他"],
                        "candidate_standard_names": ["A.3 平整场地及其他"],
                        "match_type": "chapter_heading",
                        "match_status": "matched",
                        "confidence": 0.99,
                        "review_status": "auto",
                        "evidence_paths": ["chapter_A.json"],
                        "evidence_texts": ["附录A 土石方工程 > A.3 平整场地及其他"],
                        "reasoning": "章节标题直接命中。",
                        "manual_notes": "",
                    }
                ],
            }
            (chapter_a_dir / "chapter_result.json").write_text(
                json.dumps(chapter_a_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            chapter_b_dir = output_dir / "chapter_002_附录B_砌筑工程"
            chapter_b_dir.mkdir(parents=True, exist_ok=True)
            chapter_b_payload = {
                "meta": {"chapter_title": "附录B 砌筑工程", "chapter_index": 2},
                "mappings": [
                    {
                        "source_component_name": "砼墙",
                        "source_aliases": ["砼墙"],
                        "selected_standard_name": "措施项目",
                        "standard_aliases": ["措施项目"],
                        "candidate_standard_names": ["措施项目"],
                        "match_type": "semantic_match",
                        "match_status": "matched",
                        "confidence": 0.0,
                        "review_status": "pending",
                        "evidence_paths": ["chapter_B.json"],
                        "evidence_texts": ["附录B 砌筑工程"],
                        "reasoning": "弱语义匹配。",
                        "manual_notes": "",
                    }
                ],
            }
            (chapter_b_dir / "chapter_result.json").write_text(
                json.dumps(chapter_b_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            result = synthesize_existing_step2_outputs(output_dir=output_dir, backup_existing=False)

            self.assertEqual(result["result_payload"]["meta"]["auto_resolved_conflict_count"], 1)
            self.assertEqual(
                result["result_payload"]["mappings"][0]["selected_standard_name"],
                "A.3 平整场地及其他",
            )
            self.assertEqual(result["result_payload"]["mappings"][0]["match_status"], "matched")
            self.assertIn("措施项目", result["result_payload"]["mappings"][0]["candidate_standard_names"])

    @patch("pipeline_v2.step2_engine.api.run_openai_startup_check")
    @patch("pipeline_v2.step2_v2.call_openai_plaintext_model")
    def test_execute_should_process_chapters_serially_and_merge_results_by_chapter(
        self, mock_call_openai_plaintext_model, mock_run_openai_startup_check
    ) -> None:
        mock_run_openai_startup_check.return_value = {"status": "passed"}
        mock_call_openai_plaintext_model.side_effect = [
            json.dumps(
                {
                    "meta": {
                        "task_name": "component_standard_name_matching",
                        "chapter_title": "附录A 土石方工程",
                    },
                    "mappings": [
                        {"source_component_name": "构件1", "selected_standard_name": "标准1"},
                        {"source_component_name": "构件2", "selected_standard_name": "标准2"},
                        {"source_component_name": "构件3", "selected_standard_name": "标准3"},
                        {"source_component_name": "构件4", "selected_standard_name": "标准4"},
                        {"source_component_name": "构件5", "selected_standard_name": "标准5"},
                    ],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "meta": {
                        "task_name": "component_standard_name_matching",
                        "chapter_title": "附录A 土石方工程",
                    },
                    "mappings": [
                        {"source_component_name": "构件6", "selected_standard_name": "标准6"},
                    ],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "meta": {
                        "task_name": "component_standard_name_matching",
                        "chapter_title": "附录B 砌筑工程",
                    },
                    "mappings": [
                        {"source_component_name": "构件1", "selected_standard_name": "标准1"},
                        {"source_component_name": "构件2", "selected_standard_name": "标准2"},
                        {"source_component_name": "构件3", "selected_standard_name": "标准3"},
                        {"source_component_name": "构件4", "selected_standard_name": "标准4"},
                        {"source_component_name": "构件5", "selected_standard_name": "标准5"},
                    ],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "meta": {
                        "task_name": "component_standard_name_matching",
                        "chapter_title": "附录B 砌筑工程",
                    },
                    "mappings": [
                        {"source_component_name": "构件6", "selected_standard_name": "标准6"},
                    ],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "meta": {
                        "task_name": "component_standard_name_matching",
                        "chapter_title": "附录C 桩基工程",
                    },
                    "mappings": [
                        {"source_component_name": "构件1", "selected_standard_name": "标准1"},
                        {"source_component_name": "构件2", "selected_standard_name": "标准2"},
                        {"source_component_name": "构件3", "selected_standard_name": "标准3"},
                        {"source_component_name": "构件4", "selected_standard_name": "标准4"},
                        {"source_component_name": "构件5", "selected_standard_name": "标准5"},
                    ],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "meta": {
                        "task_name": "component_standard_name_matching",
                        "chapter_title": "附录C 桩基工程",
                    },
                    "mappings": [
                        {"source_component_name": "构件6", "selected_standard_name": "标准6"},
                    ],
                },
                ensure_ascii=False,
            ),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            step1_dir = self._write_step1_fixture_with_many_chapters(root)
            components_path = self._write_components_fixture_with_many_items(root, total=6)
            output_dir = root / "data" / "output" / "step2_v2"

            result = execute(components_path=components_path, step1_source_path=step1_dir, output_dir=output_dir)

            self.assertEqual(mock_call_openai_plaintext_model.call_count, 6)
            first_prompt = mock_call_openai_plaintext_model.call_args_list[0].kwargs["prompt_text"]
            self.assertEqual(first_prompt.count("构件名:"), 5)
            self.assertIn("附录A 土石方工程", first_prompt)
            self.assertNotIn("附录B 砌筑工程", first_prompt)
            self.assertNotIn("附录C 桩基工程", first_prompt)

            self.assertEqual(result["run_summary"]["status"], "completed")
            self.assertEqual(result["result_payload"]["meta"]["merged_chapter_count"], 3)
            self.assertEqual(result["result_payload"]["meta"]["merge_strategy"], "chapter_serial_merge")
            self.assertEqual(len(result["result_payload"]["mappings"]), 6)
            self.assertEqual(result["result_payload"]["mappings"][-1]["selected_standard_name"], "标准6")
            self.assertTrue((output_dir / "run_summary.json").exists())
            self.assertTrue((output_dir / "result.json").exists())

    @patch("pipeline_v2.step2_engine.api.run_openai_startup_check")
    @patch("pipeline_v2.step2_v2.call_openai_plaintext_model")
    def test_execute_writes_model_output_and_result(
        self, mock_call_openai_plaintext_model, mock_run_openai_startup_check
    ) -> None:
        mock_run_openai_startup_check.return_value = {"status": "passed"}
        mock_call_openai_plaintext_model.return_value = json.dumps(
            {
                "meta": {"task_name": "component_standard_name_matching"},
                "mappings": [{"source_component_name": "砼墙", "selected_standard_name": "钢筋混凝土墙"}],
            },
            ensure_ascii=False,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            step1_dir = self._write_step1_fixture(root)
            components_path = self._write_components_fixture(root)
            output_dir = root / "data" / "output" / "step2_v2"

            result = execute(components_path=components_path, step1_source_path=step1_dir, output_dir=output_dir)

            self.assertEqual(result["run_summary"]["status"], "completed")
            self.assertTrue((output_dir / "result.json").exists())
            self.assertTrue((output_dir / "run_summary.json").exists())
            self.assertTrue(any(output_dir.rglob("*_model_output.txt")))

    @patch("pipeline_v2.step2_engine.api.run_openai_startup_check")
    @patch("pipeline_v2.step2_v2.call_openai_plaintext_model")
    def test_execute_passes_provider_mode_to_startup_and_model_calls(
        self, mock_call_openai_plaintext_model, mock_run_openai_startup_check
    ) -> None:
        mock_run_openai_startup_check.return_value = {"status": "passed"}
        mock_call_openai_plaintext_model.return_value = json.dumps(
            {
                "meta": {"task_name": "component_standard_name_matching"},
                "mappings": [{"source_component_name": "砼墙", "selected_standard_name": "钢筋混凝土墙"}],
            },
            ensure_ascii=False,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            step1_dir = self._write_step1_fixture(root)
            components_path = self._write_components_fixture(root)
            output_dir = root / "data" / "output" / "step2_v2"

            execute(
                components_path=components_path,
                step1_source_path=step1_dir,
                output_dir=output_dir,
                provider_mode="codex",
            )

            self.assertEqual(mock_run_openai_startup_check.call_args.kwargs["provider_mode"], "codex")
            self.assertEqual(mock_call_openai_plaintext_model.call_args.kwargs["provider_mode"], "codex")

    @patch("pipeline_v2.step2_engine.api.run_openai_startup_check")
    @patch("pipeline_v2.step2_v2.call_openai_plaintext_model")
    def test_execute_codex_clears_inherited_openai_env_for_model_calls(
        self, mock_call_openai_plaintext_model, mock_run_openai_startup_check
    ) -> None:
        observed_env: dict[str, str | None] = {}

        def fake_startup_check(**kwargs):
            observed_env["startup_api_key"] = os.getenv("OPENAI_API_KEY")
            observed_env["startup_base_url"] = os.getenv("OPENAI_BASE_URL")
            return {"status": "passed"}

        def fake_model_call(**kwargs):
            observed_env["model_api_key"] = os.getenv("OPENAI_API_KEY")
            observed_env["model_base_url"] = os.getenv("OPENAI_BASE_URL")
            return json.dumps(
                {
                    "meta": {"task_name": "component_standard_name_matching"},
                    "mappings": [{"source_component_name": "砼墙", "selected_standard_name": "钢筋混凝土墙"}],
                },
                ensure_ascii=False,
            )

        mock_run_openai_startup_check.side_effect = fake_startup_check
        mock_call_openai_plaintext_model.side_effect = fake_model_call

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "existing-openai-key",
                "OPENAI_BASE_URL": "https://api.openai.com/v1",
            },
            clear=False,
        ):
            root = Path(temp_dir)
            step1_dir = self._write_step1_fixture(root)
            components_path = self._write_components_fixture(root)
            output_dir = root / "data" / "output" / "step2_v2"

            execute(
                components_path=components_path,
                step1_source_path=step1_dir,
                output_dir=output_dir,
                provider_mode="codex",
            )

            self.assertIsNone(observed_env["startup_api_key"])
            self.assertIsNone(observed_env["startup_base_url"])
            self.assertIsNone(observed_env["model_api_key"])
            self.assertIsNone(observed_env["model_base_url"])
            self.assertEqual(os.environ["OPENAI_API_KEY"], "existing-openai-key")
            self.assertEqual(os.environ["OPENAI_BASE_URL"], "https://api.openai.com/v1")

    @patch("pipeline_v2.step2_engine.api.run_openai_startup_check")
    @patch("pipeline_v2.step2_v2.call_openai_plaintext_model")
    def test_execute_revalidates_gemini_lite_batch_with_gpt_when_deviation_is_large(
        self, mock_call_openai_plaintext_model, mock_run_openai_startup_check
    ) -> None:
        mock_run_openai_startup_check.return_value = {"status": "passed"}
        mock_call_openai_plaintext_model.side_effect = [
            json.dumps(
                {
                    "meta": {"task_name": "component_standard_name_matching"},
                    "mappings": [
                        {"source_component_name": "构件1", "selected_standard_name": "标准1"},
                        {"source_component_name": "构件2", "selected_standard_name": ""},
                        {"source_component_name": "构件3", "selected_standard_name": ""},
                        {"source_component_name": "构件4", "selected_standard_name": ""},
                        {"source_component_name": "构件5", "selected_standard_name": ""},
                    ],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "meta": {"task_name": "component_standard_name_matching"},
                    "mappings": [
                        {"source_component_name": "构件1", "selected_standard_name": "标准1"},
                        {"source_component_name": "构件2", "selected_standard_name": "标准2"},
                        {"source_component_name": "构件3", "selected_standard_name": "标准3"},
                        {"source_component_name": "构件4", "selected_standard_name": "标准4"},
                        {"source_component_name": "构件5", "selected_standard_name": "标准5"},
                    ],
                },
                ensure_ascii=False,
            ),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            step1_dir = self._write_step1_fixture_with_many_chapters(root)
            components_path = self._write_components_fixture_with_many_items(root, total=5)
            output_dir = root / "data" / "output" / "step2_v2"

            execute(
                components_path=components_path,
                step1_source_path=step1_dir,
                output_dir=output_dir,
                model="gemini-2.5-flash-lite",
                chapter_limit=1,
            )

            self.assertEqual(mock_call_openai_plaintext_model.call_count, 2)
            self.assertEqual(mock_call_openai_plaintext_model.call_args_list[0].kwargs["model"], "gemini-2.5-flash-lite")
            self.assertEqual(mock_call_openai_plaintext_model.call_args_list[1].kwargs["model"], "gpt-5.4")

            batch_result_path = output_dir / "chapter_001_附录A_土石方工程" / "batch_001_result.json"
            batch_payload = json.loads(batch_result_path.read_text(encoding="utf-8"))
            self.assertTrue(batch_payload["meta"]["validation_triggered"])
            self.assertEqual(batch_payload["meta"]["validation_fallback_model"], "gpt-5.4")
            self.assertFalse(batch_payload["meta"]["validation_failed"])
            self.assertEqual(batch_payload["meta"]["validation_primary_summary"]["unmatched_count"], 4)
            self.assertEqual(batch_payload["meta"]["validation_final_summary"]["matched_count"], 5)
            self.assertTrue((output_dir / "chapter_001_附录A_土石方工程" / "batch_001_validation_model_output.txt").exists())

    @patch("pipeline_v2.step2_engine.api.run_openai_startup_check")
    @patch("pipeline_v2.step2_v2.call_openai_plaintext_model")
    def test_execute_skips_gpt_revalidation_when_gemini_lite_quality_is_acceptable(
        self, mock_call_openai_plaintext_model, mock_run_openai_startup_check
    ) -> None:
        mock_run_openai_startup_check.return_value = {"status": "passed"}
        mock_call_openai_plaintext_model.return_value = json.dumps(
            {
                "meta": {"task_name": "component_standard_name_matching"},
                "mappings": [
                    {"source_component_name": "构件1", "selected_standard_name": "标准1"},
                    {"source_component_name": "构件2", "selected_standard_name": "标准2"},
                    {"source_component_name": "构件3", "selected_standard_name": "标准3"},
                    {"source_component_name": "构件4", "selected_standard_name": "标准4"},
                    {"source_component_name": "构件5", "selected_standard_name": "标准5"},
                ],
            },
            ensure_ascii=False,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            step1_dir = self._write_step1_fixture_with_many_chapters(root)
            components_path = self._write_components_fixture_with_many_items(root, total=5)
            output_dir = root / "data" / "output" / "step2_v2"

            execute(
                components_path=components_path,
                step1_source_path=step1_dir,
                output_dir=output_dir,
                model="gemini-2.5-flash-lite",
                chapter_limit=1,
            )

            self.assertEqual(mock_call_openai_plaintext_model.call_count, 1)
            batch_result_path = output_dir / "chapter_001_附录A_土石方工程" / "batch_001_result.json"
            batch_payload = json.loads(batch_result_path.read_text(encoding="utf-8"))
            self.assertFalse(batch_payload["meta"]["validation_triggered"])
            self.assertEqual(batch_payload["meta"]["validation_final_summary"]["matched_count"], 5)
            self.assertFalse((output_dir / "chapter_001_附录A_土石方工程" / "batch_001_validation_model_output.txt").exists())

    @patch("pipeline_v2.step2_engine.api.run_openai_startup_check")
    @patch("pipeline_v2.step2_v2.call_openai_plaintext_model")
    def test_execute_uses_absolute_chapter_and_batch_indexes_when_resuming_from_slices(
        self, mock_call_openai_plaintext_model, mock_run_openai_startup_check
    ) -> None:
        mock_run_openai_startup_check.return_value = {"status": "passed"}
        mock_call_openai_plaintext_model.return_value = json.dumps(
            {
                "meta": {"task_name": "component_standard_name_matching"},
                "mappings": [{"source_component_name": "构件6", "selected_standard_name": "标准6"}],
            },
            ensure_ascii=False,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            step1_dir = self._write_step1_fixture_with_many_chapters(root)
            components_path = self._write_components_fixture_with_many_items(root, total=6)
            output_dir = root / "data" / "output" / "step2_v2"

            execute(
                components_path=components_path,
                step1_source_path=step1_dir,
                output_dir=output_dir,
                start_chapter_index=2,
                chapter_limit=1,
                start_component_batch_index=2,
                component_batch_limit=1,
            )

            target_result = output_dir / "chapter_002_附录B_砌筑工程" / "batch_002_result.json"
            self.assertTrue(target_result.exists())
            payload = json.loads(target_result.read_text(encoding="utf-8"))
            self.assertEqual(payload["meta"]["chapter_index"], 2)
            self.assertEqual(payload["meta"]["component_batch_index"], 2)
            self.assertFalse((output_dir / "chapter_001_附录B_砌筑工程").exists())


if __name__ == "__main__":
    unittest.main()
