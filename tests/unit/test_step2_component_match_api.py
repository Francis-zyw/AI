from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import URLError

from pipeline_v2.step2_engine.api import (
    OPENAI_RETRY_LOG_NAME,
    OPENAI_STARTUP_CHECK_NAME,
    build_chapter_request_payload,
    build_consolidation_prompt_text,
    build_initial_component_batches,
    build_synonym_library,
    build_prompt_text,
    call_openai_model,
    pack_selected_regions_into_windows,
    run_component_match_preprocess,
    run_openai_startup_check,
)


class FakeConnectionError(Exception):
    pass


class FakeTimeoutError(Exception):
    pass


class FakeResponsesAPI:
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    def create(self, **_: object) -> object:
        self.calls.append(dict(_))
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeModelsAPI:
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[str] = []

    def retrieve(self, model: str) -> object:
        self.calls.append(model)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, *, response_outcomes: list[object] | None = None, model_outcomes: list[object] | None = None) -> None:
        self.responses = FakeResponsesAPI(response_outcomes or [])
        self.models = FakeModelsAPI(model_outcomes or [])


class Step2ComponentMatchApiTests(unittest.TestCase):
    def test_build_synonym_library_ignores_sentinel_selected_standard_names(self) -> None:
        payload = build_synonym_library(
            mappings=[
                {"source_component_name": "构件1", "selected_standard_name": "None", "match_status": "matched"},
                {"source_component_name": "构件2", "selected_standard_name": "null", "match_status": "matched"},
                {"source_component_name": "构件3", "selected_standard_name": "无", "match_status": "matched"},
                {"source_component_name": "构件4", "selected_standard_name": "未匹配", "match_status": "matched"},
            ],
            result_meta={"standard_document": "sample-standard", "review_stage": "pre_parse"},
        )

        self.assertEqual(payload["synonym_library"], [])
        self.assertEqual(payload["meta"]["matched_canonical_count"], 0)
        self.assertEqual(payload["unmatched_components"], ["构件1", "构件2", "构件3", "构件4"])

    def test_build_chapter_request_payload_splits_instruction_and_two_files(self) -> None:
        payload = build_chapter_request_payload(
            component_payload=[{"source_component_name": "基础梁", "attribute_summaries": []}],
            region_payload=[{"title": "附录E", "path_text": "附录E > 梁", "level": 1, "table_count": 0, "table_row_count": 0}],
            alias_payload=[],
            history_payload=[],
            batch_index=1,
            total_batches=2,
            region_window_index=1,
            region_window_count=1,
        )

        self.assertIn("components.txt", payload["preview_text"])
        self.assertIn("chapter.txt", payload["preview_text"])
        self.assertIn("构件组摘要", payload["components_text"])
        self.assertIn("当前章节窗口摘要", payload["chapter_text"])
        input_items = payload["input_items"]
        self.assertEqual(len(input_items), 1)
        content_items = input_items[0]["content"]
        self.assertEqual(content_items[0]["type"], "input_text")
        self.assertTrue(str(content_items[0]["text"]).startswith("【components.txt】"))
        self.assertEqual(content_items[1]["type"], "input_text")
        self.assertTrue(str(content_items[1]["text"]).startswith("【chapter.txt】"))

    def test_build_prompt_text_uses_compact_structured_sections(self) -> None:
        prompt_text = build_prompt_text(
            component_payload=[
                {
                    "source_component_name": "基础梁",
                    "attribute_summaries": [
                        {"name": "构件类别", "code": "GJLB", "values": ["基础联系梁", "梁"]},
                        {"name": "楼层名称", "code": "LAYMC", "values": []},
                    ],
                }
            ],
            region_payload=[
                {
                    "title": "附录E",
                    "path_text": "附录E > 混凝土工程",
                    "level": 1,
                    "table_count": 1,
                    "table_row_count": 2,
                    "non_table_text_excerpt": "适用于梁。",
                    "tables": [
                        {
                            "title": "现浇混凝土梁",
                            "headers": ["项目名称", "特征"],
                            "rows": [["梁", "基础梁"]],
                            "raw_text_excerpt": "梁表摘录",
                        }
                    ],
                }
            ],
            alias_payload={
                "synonym_library": [
                    {"canonical_name": "基础联系梁", "aliases": ["基础梁"], "source_component_names": ["基础梁"]},
                    {"canonical_name": "墙", "aliases": ["墙体"], "source_component_names": ["墙"]},
                ]
            },
            history_payload=[
                {
                    "source_component_name": "基础梁",
                    "selected_standard_name": "基础联系梁",
                    "match_status": "matched",
                    "review_status": "confirmed",
                    "reasoning": "历史人工确认。",
                }
            ],
            batch_index=1,
            total_batches=3,
            region_window_index=1,
            region_window_count=1,
        )

        self.assertIn("构件名: 基础梁", prompt_text)
        self.assertIn("关键属性:", prompt_text)
        self.assertIn("章节路径: 附录E > 混凝土工程", prompt_text)
        self.assertIn("标准名: 基础联系梁", prompt_text)
        self.assertIn("历史项: source=基础梁", prompt_text)
        self.assertNotIn("\"source_component_name\": \"基础梁\"", prompt_text)

    def test_build_prompt_text_accepts_raw_components_json_shape(self) -> None:
        prompt_text = build_prompt_text(
            component_payload=[
                {
                    "component_type": "主肋梁",
                    "properties": {
                        "attributes": [
                            {"name": "构件类别", "code": "GJLB", "values": ["楼层主肋梁", "屋面主肋梁"]},
                            {"name": "砼标号", "code": "TBH", "values": ["C30", "C35"]},
                        ]
                    },
                }
            ],
            region_payload=[
                {
                    "title": "附录E",
                    "path_text": "附录E > 混凝土工程",
                    "level": 1,
                    "table_count": 0,
                    "table_row_count": 0,
                }
            ],
            alias_payload=[],
            history_payload=[],
            batch_index=1,
            total_batches=1,
            region_window_index=1,
            region_window_count=1,
        )

        self.assertIn("构件名: 主肋梁", prompt_text)
        self.assertIn("构件类别[GJLB]: 楼层主肋梁 | 屋面主肋梁", prompt_text)
        self.assertIn("砼标号[TBH]: C30 | C35", prompt_text)

    def test_build_initial_component_batches_groups_and_splits_by_payload_chars(self) -> None:
        components = [
            {"source_component_name": "基础梁", "attribute_summaries": [{"name": "类别", "code": "A", "values": ["基础梁", "梁"]}]},
            {"source_component_name": "主肋梁", "attribute_summaries": [{"name": "类别", "code": "A", "values": ["主梁", "梁"]}]},
            {"source_component_name": "内墙面", "attribute_summaries": [{"name": "类别", "code": "A", "values": ["墙面", "抹灰"]}]},
        ]

        batches = build_initial_component_batches(
            preprocessed_components=components,
            max_components_per_batch=10,
            max_component_payload_chars=120,
        )

        self.assertGreaterEqual(len(batches), 2)
        self.assertEqual([item["source_component_name"] for item in batches[0]], ["基础梁"])
        self.assertEqual([item["source_component_name"] for item in batches[1]], ["主肋梁"])

    def test_pack_selected_regions_into_windows_keeps_top_level_groups_separate(self) -> None:
        selected_regions = [
            {"title": "附录A", "path_text": "附录A", "level": 1, "table_count": 0, "table_row_count": 0},
            {"title": "附录B", "path_text": "附录B", "level": 1, "table_count": 0, "table_row_count": 0},
        ]
        all_regions = [
            {"title": "附录A", "path_text": "附录A", "level": 1, "table_count": 0, "table_row_count": 0},
            {"title": "A.1", "path_text": "附录A > A.1 梁", "level": 2, "table_count": 0, "table_row_count": 0},
            {"title": "附录B", "path_text": "附录B", "level": 1, "table_count": 0, "table_row_count": 0},
            {"title": "B.1", "path_text": "附录B > B.1 墙", "level": 2, "table_count": 0, "table_row_count": 0},
        ]

        windows, debug_payload = pack_selected_regions_into_windows(
            component_payload=[{"source_component_name": "梁", "attribute_summaries": []}],
            selected_regions=selected_regions,
            all_regions=all_regions,
            alias_payload=[],
            history_payload=[],
            max_prompt_chars=10000,
            max_regions_per_window=10,
        )

        assert windows is not None
        self.assertEqual(len(windows), 2)
        self.assertEqual([item["path_text"] for item in windows[0]], ["附录A", "附录A > A.1 梁"])
        self.assertEqual([item["path_text"] for item in windows[1]], ["附录B", "附录B > B.1 墙"])
        self.assertEqual(debug_payload["selected_group_keys"], ["附录A", "附录B"])

    def test_build_consolidation_prompt_text_summarizes_window_results(self) -> None:
        prompt_text = build_consolidation_prompt_text(
            component_payload=[{"source_component_name": "基础梁", "attribute_summaries": []}],
            window_payloads=[
                {
                    "batch_index": 1,
                    "region_window_index": 1,
                    "region_window_count": 2,
                    "selected_region_paths": ["附录E > 梁"],
                    "result": {
                        "mappings": [
                            {
                                "source_component_name": "基础梁",
                                "selected_standard_name": "基础联系梁",
                                "candidate_standard_names": ["基础梁", "基础联系梁"],
                                "match_status": "matched",
                                "match_type": "alias_bridge",
                                "confidence": 0.91,
                                "review_status": "pending",
                                "evidence_paths": ["附录E > 梁"],
                                "evidence_texts": ["基础梁归入基础联系梁"],
                                "reasoning": "章节内直接给出。",
                            }
                        ]
                    },
                }
            ],
            component_group_id=1,
            total_component_groups=3,
        )

        self.assertIn("整合批次信息:", prompt_text)
        self.assertIn("窗口 1/2", prompt_text)
        self.assertIn("source=基础梁", prompt_text)
        self.assertIn("selected=基础联系梁", prompt_text)

    def test_run_openai_startup_check_writes_status_and_retry_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            fake_client = FakeClient(
                model_outcomes=[
                    FakeConnectionError("temporary reset"),
                    SimpleNamespace(id="gpt-5.4"),
                ]
            )

            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
                with patch("pipeline_v2.step2_engine.api.load_openai_sdk", return_value=(FakeConnectionError, FakeTimeoutError, object)):
                    with patch("pipeline_v2.step2_engine.api.build_openai_client", return_value=fake_client):
                        with patch("pipeline_v2.step2_engine.api.time.sleep"):
                            result = run_openai_startup_check(
                                model="gpt-5.4",
                                request_timeout_seconds=30.0,
                                connection_retries=2,
                                output_path=output_dir,
                            )

            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["attempts_used"], 2)
            self.assertTrue((output_dir / OPENAI_STARTUP_CHECK_NAME).exists())

            log_lines = (output_dir / OPENAI_RETRY_LOG_NAME).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(log_lines), 2)
            first_event = json.loads(log_lines[0])
            second_event = json.loads(log_lines[1])
            self.assertEqual(first_event["phase"], "startup_check")
            self.assertEqual(first_event["event"], "retrying")
            self.assertEqual(second_event["event"], "succeeded")

    def test_run_openai_startup_check_normalizes_provider_prefixed_model_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            fake_client = FakeClient(model_outcomes=[SimpleNamespace(id="gpt-5.4")])

            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
                with patch("pipeline_v2.step2_engine.api.load_openai_sdk", return_value=(FakeConnectionError, FakeTimeoutError, object)):
                    with patch("pipeline_v2.step2_engine.api.build_openai_client", return_value=fake_client):
                        result = run_openai_startup_check(
                            model="openai-codex/gpt-5.4",
                            request_timeout_seconds=30.0,
                            connection_retries=1,
                            output_path=output_dir,
                        )

            self.assertEqual(result["status"], "passed")
            self.assertEqual(fake_client.models.calls[-1], "gpt-5.4")

    def test_run_openai_startup_check_supports_codex_provider_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            fake_completed = SimpleNamespace(returncode=0, stdout="Logged in using ChatGPT\n", stderr="")

            with patch("pipeline_v2.step2_engine.api.subprocess.run", return_value=fake_completed) as mocked_run:
                result = run_openai_startup_check(
                    model="gpt-5.4",
                    request_timeout_seconds=30.0,
                    connection_retries=1,
                    output_path=output_dir,
                    provider_mode="codex",
                )

            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["provider"], "codex-cli")
            self.assertIn("Logged in using ChatGPT", result["auth_status"])
            self.assertEqual(mocked_run.call_args.args[0], ["codex", "login", "status"])

    def test_call_openai_model_logs_retry_then_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / OPENAI_RETRY_LOG_NAME
            fake_client = FakeClient(
                response_outcomes=[
                    FakeConnectionError("peer reset"),
                    SimpleNamespace(output_text="ok"),
                ]
            )

            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
                with patch("pipeline_v2.step2_engine.api.load_openai_sdk", return_value=(FakeConnectionError, FakeTimeoutError, object)):
                    with patch("pipeline_v2.step2_engine.api.build_openai_client", return_value=fake_client):
                        with patch("pipeline_v2.step2_engine.api.time.sleep"):
                            text = call_openai_model(
                                model="gpt-5.4",
                                reasoning_effort="medium",
                                max_output_tokens=32,
                                request_timeout_seconds=30.0,
                                connection_retries=2,
                                prompt_text="hello",
                                instructions_text="follow json",
                                input_items=[{"role": "user", "content": [{"type": "input_file", "filename": "components.txt", "file_data": "a"}]}],
                                retry_log_path=log_path,
                                log_context={"batch_index": 1},
                            )

            self.assertEqual(text, "ok")
            log_lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(log_lines), 2)
            retry_event = json.loads(log_lines[0])
            success_event = json.loads(log_lines[1])
            self.assertEqual(retry_event["event"], "retrying")
            self.assertEqual(retry_event["batch_index"], 1)
            self.assertEqual(success_event["event"], "succeeded")
            self.assertEqual(fake_client.responses.calls[-1]["instructions"], "follow json")
            self.assertIsInstance(fake_client.responses.calls[-1]["input"], list)

    def test_call_openai_model_supports_codex_provider_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / OPENAI_RETRY_LOG_NAME
            observed: dict[str, object] = {}

            def fake_run(cmd: list[str], **kwargs: object) -> object:
                output_index = cmd.index("--output-last-message") + 1
                Path(cmd[output_index]).write_text('{"ok": true}', encoding="utf-8")
                observed["cmd"] = cmd
                observed["input"] = kwargs.get("input")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("pipeline_v2.step2_engine.api.subprocess.run", side_effect=fake_run):
                text = call_openai_model(
                    model="gpt-5.4",
                    reasoning_effort="medium",
                    max_output_tokens=32,
                    request_timeout_seconds=30.0,
                    connection_retries=2,
                    provider_mode="codex",
                    prompt_text="hello",
                    instructions_text="follow json",
                    input_items=[{"filename": "components.txt", "text": "墙"}],
                    retry_log_path=log_path,
                    log_context={"batch_index": 7},
                )

            self.assertEqual(text, '{"ok": true}')
            self.assertIn("codex", observed["cmd"])
            self.assertIn("--ephemeral", observed["cmd"])
            self.assertIn("--sandbox", observed["cmd"])
            self.assertIn("read-only", observed["cmd"])
            self.assertIn("--model", observed["cmd"])
            self.assertIn('model_reasoning_effort="medium"', observed["cmd"])
            self.assertIn("follow json", str(observed["input"]))
            self.assertIn('"filename": "components.txt"', str(observed["input"]))

            log_lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(log_lines), 1)
            success_event = json.loads(log_lines[0])
            self.assertEqual(success_event["event"], "succeeded")
            self.assertEqual(success_event["base_url"], "codex-cli")
            self.assertEqual(success_event["batch_index"], 7)

    def test_call_openai_model_uses_gemini_rest_when_api_key_present(self) -> None:
        class FakeGeminiResponse:
            def __enter__(self) -> "FakeGeminiResponse":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {
                                            "text": '{"ok": true}',
                                        }
                                    ]
                                }
                            }
                        ]
                    },
                    ensure_ascii=False,
                ).encode("utf-8")

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-gemini-key"}, clear=False):
            with patch("pipeline_v2.step2_engine.api.urllib.request.urlopen", return_value=FakeGeminiResponse()) as mocked_urlopen:
                text = call_openai_model(
                    model="gemini-2.5-flash",
                    reasoning_effort="medium",
                    max_output_tokens=32,
                    request_timeout_seconds=30.0,
                    connection_retries=2,
                    prompt_text="hello",
                )

        self.assertEqual(text, '{"ok": true}')
        request = mocked_urlopen.call_args.args[0]
        self.assertIn("gemini-2.5-flash:generateContent", request.full_url)

    def test_call_openai_model_falls_back_to_gemini_cli_when_rest_fails(self) -> None:
        fake_completed = SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-gemini-key"}, clear=False):
            with patch("pipeline_v2.step2_engine.api.urllib.request.urlopen", side_effect=URLError("offline")):
                with patch("subprocess.run", return_value=fake_completed) as mocked_subprocess:
                    text = call_openai_model(
                        model="gemini-2.5-flash-lite",
                        reasoning_effort="medium",
                        max_output_tokens=32,
                        request_timeout_seconds=30.0,
                        connection_retries=2,
                        prompt_text="hello",
                    )

        self.assertEqual(text, '{"ok": true}')
        self.assertIn("gemini-2.5-flash-lite", mocked_subprocess.call_args.args[0])

    def test_call_openai_model_retries_gemini_route(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / OPENAI_RETRY_LOG_NAME
            with patch("pipeline_v2.step2_engine.api.run_gemini_cli_prompt", side_effect=[RuntimeError("temporary"), '{"ok": true}']):
                with patch("pipeline_v2.step2_engine.api.time.sleep"):
                    text = call_openai_model(
                        model="gemini-2.5-flash",
                        reasoning_effort="medium",
                        max_output_tokens=32,
                        request_timeout_seconds=30.0,
                        connection_retries=2,
                        prompt_text="hello",
                        retry_log_path=log_path,
                        log_context={"batch_index": 3},
                    )

            self.assertEqual(text, '{"ok": true}')
            log_lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(log_lines), 2)
            retry_event = json.loads(log_lines[0])
            success_event = json.loads(log_lines[1])
            self.assertEqual(retry_event["event"], "retrying")
            self.assertEqual(retry_event["batch_index"], 3)
            self.assertEqual(success_event["event"], "succeeded")

    def test_run_component_match_preprocess_records_startup_check_in_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            components_path = base / "components.json"
            step1_path = base / "001_附录A.json"
            output_dir = base / "output"

            components_path.write_text(
                json.dumps(
                    [
                        {
                            "component_type": "墙",
                            "properties": {"attributes": []},
                        }
                    ],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            step1_path.write_text(
                json.dumps(
                    {
                        "chapter": {"title": "附录A"},
                        "regions": [
                            {
                                "title": "附录A",
                                "path_text": "附录A",
                                "level": 1,
                                "table_count": 0,
                                "table_row_count": 0,
                                "non_table_text": "墙",
                                "tables": [],
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            batch_plan = {
                "component_group_id": 1,
                "components": [{"source_component_name": "墙", "attribute_summaries": []}],
                "regions": [
                    {
                        "title": "附录A",
                        "path_text": "附录A",
                        "level": 1,
                        "table_count": 0,
                        "table_row_count": 0,
                        "non_table_text_excerpt": "墙",
                    }
                ],
                "region_window_index": 1,
                "region_window_count": 1,
                "prompt_chars": 5,
                "component_chars": 2,
                "region_chars": 2,
                "template_overhead_chars": 1,
                "debug": {},
            }

            with patch(
                "pipeline_v2.step2_engine.api.load_step1_regions_source",
                return_value={
                    "regions": json.loads(step1_path.read_text(encoding="utf-8"))["regions"],
                    "source_path": str(step1_path),
                    "source_type": "chapter_package",
                    "chapters": ["附录A"],
                },
            ):
                with patch("pipeline_v2.step2_engine.api.plan_component_batches", return_value=[batch_plan]):
                    with patch("pipeline_v2.step2_engine.api.build_prompt_text", return_value="prompt"):
                        with patch(
                            "pipeline_v2.step2_engine.api.run_openai_startup_check",
                            return_value={"status": "passed", "attempts_used": 1},
                        ):
                            with patch(
                                "pipeline_v2.step2_engine.api.call_openai_model",
                                return_value=json.dumps(
                                    {
                                        "meta": {"standard_document": "示例标准"},
                                        "mappings": [
                                            {
                                                "source_component_name": "墙",
                                                "selected_standard_name": "砼墙",
                                                "match_status": "matched",
                                                "review_status": "confirmed",
                                            }
                                        ],
                                    },
                                    ensure_ascii=False,
                                ),
                            ):
                                summary = run_component_match_preprocess(
                                    components_path=components_path,
                                    step1_source_path=step1_path,
                                    output_dir=output_dir,
                                    connection_retries=2,
                                )

            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["startup_connectivity_check"]["status"], "passed")
            self.assertEqual(
                summary["startup_connectivity_check"]["check_path"],
                str(output_dir / OPENAI_STARTUP_CHECK_NAME),
            )
            self.assertEqual(summary["retry_log_path"], str(output_dir / OPENAI_RETRY_LOG_NAME))


if __name__ == "__main__":
    unittest.main()
