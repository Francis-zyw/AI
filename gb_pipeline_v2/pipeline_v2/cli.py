from __future__ import annotations

import argparse
import json
from pathlib import Path

from .audit import audit_project, build_redesign_plan, render_markdown_report
from .import_legacy import import_legacy_outputs
from .review_queue import build_step3_review_queue, write_review_ledger
from .step1_chapter_ocr.api import process_pdf as step1_process_pdf
from .step2_engine.api import run_component_match_preprocess as step2_preprocess
from .step3_engine.api import (
    apply_runtime_environment as step3_apply_runtime_environment,
    resolve_runtime_options as step3_resolve_runtime_options,
    restore_runtime_environment as step3_restore_runtime_environment,
    run_filter_condition_pipeline,
)
from .step2_v2 import execute as step2_execute
from .step2_v2 import load_json_or_jsonl, prepare as step2_prepare, synthesize_existing_step2_outputs
from .step3_v2 import match_bill_items_to_component
from .step4_direct_match import (
    apply_runtime_environment as step4_apply_runtime_environment,
    direct_match_bill_items,
    restore_runtime_environment as step4_restore_runtime_environment,
    resolve_runtime_options as step4_resolve_runtime_options,
    run_step4_from_step3_result_pipeline,
    run_step4_pipeline,
)


def _write_output(path: str | None, content: str) -> None:
    if path:
        target = Path(path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return
    print(content)


def _load_items_from_args(items_file: str | None, item_json: str | None) -> list[dict]:
    if items_file:
        payload = json.loads(Path(items_file).expanduser().resolve().read_text(encoding="utf-8"))
    elif item_json:
        payload = json.loads(item_json)
    else:
        raise ValueError("必须提供 --items-file 或 --item-json。")

    if isinstance(payload, dict):
        if isinstance(payload.get("items"), list):
            payload = payload["items"]
        else:
            payload = [payload]
    if not isinstance(payload, list):
        raise ValueError("清单输入必须是对象、数组，或包含 items 数组。")
    return [item for item in payload if isinstance(item, dict)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="国标解析 V2 单入口 CLI。")
    parser.add_argument("--project-root", default=".", help="Path to the project root.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser("audit", help="Audit current v1 outputs and risks.")
    audit_parser.add_argument("--project-root", dest="project_root", help="Path to the project root.")
    audit_parser.add_argument("--format", choices=("json", "markdown"), default="json")
    audit_parser.add_argument("--write", help="Optional output file path.")

    plan_parser = subparsers.add_parser("plan", help="Build the V2 redesign plan from current audit.")
    plan_parser.add_argument("--project-root", dest="project_root", help="Path to the project root.")
    plan_parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    plan_parser.add_argument("--write", help="Optional output file path.")

    step1_parser = subparsers.add_parser("step1-extract", help="Extract chapter packages and table regions from a PDF.")
    step1_parser.add_argument("--project-root", dest="project_root", help="Path to the project root.")
    step1_parser.add_argument("--pdf", required=True, help="Path to the PDF file.")
    step1_parser.add_argument("--output", help="Output directory. Defaults to data/output/step1/<pdf-name>.")
    step1_parser.add_argument("--no-save", action="store_true", help="Return summary without writing output files.")
    step1_parser.add_argument("--use-paddleocr", action="store_true", help="Enable PaddleOCR fallback when available.")
    step1_parser.add_argument("--no-auto-install-paddleocr", action="store_true", help="Disable PaddleOCR auto install.")
    step1_parser.add_argument("--minimum-text-length", type=int, default=1, help="Fallback threshold for provider switching.")
    step1_parser.add_argument("--write", help="Optional output file path.")

    import_legacy_parser = subparsers.add_parser("import-legacy", help="Import legacy Step1/2/3 outputs into a V2 workspace.")
    import_legacy_parser.add_argument("--project-root", dest="project_root", help="Path to the project root.")
    import_legacy_parser.add_argument("--run-id", required=True, help="Workspace run id.")
    import_legacy_parser.add_argument("--step1-dir", help="Legacy Step1 output directory.")
    import_legacy_parser.add_argument("--step2-dir", help="Legacy Step2 output directory.")
    import_legacy_parser.add_argument("--step3-dir", help="Legacy Step3 output directory.")
    import_legacy_parser.add_argument("--write", help="Optional output file path.")

    review_queue_parser = subparsers.add_parser("step3-build-review-queue", help="Build a Step3 review queue ledger from result rows.")
    review_queue_parser.add_argument("--project-root", dest="project_root", help="Path to the project root.")
    review_queue_parser.add_argument("--step3-result", required=True, help="Path to Step3 result JSON.")
    review_queue_parser.add_argument("--output", required=True, help="Review ledger output path.")
    review_queue_parser.add_argument("--source-stage", default="step3", help="Source stage name.")
    review_queue_parser.add_argument("--write", help="Optional output file path.")

    step2_parser = subparsers.add_parser("step2-prepare", help="Prepare Step2 V2 artifacts using chapter-serial component batching.")
    step2_parser.add_argument("--project-root", dest="project_root", help="Path to the project root.")
    step2_parser.add_argument("--components", required=True, help="Path to components.json/components.jsonl.")
    step2_parser.add_argument("--step1-source", required=True, help="Path to Step1 output dir or chapter_index.json.")
    step2_parser.add_argument("--output", required=True, help="Directory to write prepare artifacts.")
    step2_parser.add_argument("--model", default="gpt-5.4", help="Model name.")
    step2_parser.add_argument("--reasoning-effort", default="medium", help="Reasoning effort.")
    step2_parser.add_argument("--component-batch-size", type=int, default=5, help="Max component types processed for one chapter batch.")
    step2_parser.add_argument("--start-chapter-index", type=int, default=1, help="1-based chapter index to start from.")
    step2_parser.add_argument("--chapter-limit", type=int, help="Optional number of chapters to process.")
    step2_parser.add_argument("--start-component-batch-index", type=int, default=1, help="1-based component batch index to start from.")
    step2_parser.add_argument("--component-batch-limit", type=int, help="Optional number of component batches to process.")
    step2_parser.add_argument("--write", help="Optional output file path for command response JSON.")

    step2_legacy_parser = subparsers.add_parser("step2-legacy-preprocess", help="Run the internal Step2 preprocessing engine from the unified CLI.")
    step2_legacy_parser.add_argument("--project-root", dest="project_root", help="Path to the project root.")
    step2_legacy_parser.add_argument("--components", help="Path to components.json or components.jsonl.")
    step2_legacy_parser.add_argument("--step1-source", help="Path to Step1 source: chapter_index.json, chapter JSON, chapter_regions dir, or Step1 output dir.")
    step2_legacy_parser.add_argument("--output", help="Output directory, default: data/output/step2/<standard-name>.")
    step2_legacy_parser.add_argument("--alias-dict", help="Optional prior alias dictionary JSON.")
    step2_legacy_parser.add_argument("--history-review", help="Optional prior human review JSON.")
    step2_legacy_parser.add_argument("--model", default="gpt-5.4", help="OpenAI model alias.")
    step2_legacy_parser.add_argument("--reasoning-effort", default="medium", help="Reasoning effort passed to Responses API.")
    step2_legacy_parser.add_argument("--max-components-per-batch", type=int, default=120, help="Upper bound of components per model batch.")
    step2_legacy_parser.add_argument("--max-attribute-values", type=int, default=6, help="Max dropdown values kept per attribute.")
    step2_legacy_parser.add_argument("--max-region-text-chars", type=int, default=2400, help="Max non-table text chars kept per region.")
    step2_legacy_parser.add_argument("--max-table-text-chars", type=int, default=2400, help="Max raw table chars kept per table.")
    step2_legacy_parser.add_argument("--max-table-rows", type=int, default=60, help="Max rows kept per table.")
    step2_legacy_parser.add_argument("--only-regions-with-tables", action="store_true", help="Only include regions containing tables.")
    step2_legacy_parser.add_argument("--max-component-payload-chars", type=int, default=18000, help="Soft char budget for the component block inside one batch.")
    step2_legacy_parser.add_argument("--max-prompt-chars", type=int, default=120000, help="Soft prompt size ceiling.")
    step2_legacy_parser.add_argument("--target-region-chars", type=int, default=60000, help="Approximate character budget reserved for selected regions per batch.")
    step2_legacy_parser.add_argument("--max-regions-per-batch", type=int, default=18, help="Max selected regions carried into one batch prompt.")
    step2_legacy_parser.add_argument("--max-output-tokens", type=int, default=8000, help="Responses API max_output_tokens.")
    step2_legacy_parser.add_argument("--tpm-budget", type=int, default=320000, help="Estimated tokens-per-minute budget used for local throttling; set 0 to disable.")
    step2_legacy_parser.add_argument("--request-timeout-seconds", type=float, default=120.0, help="HTTP timeout for each OpenAI request.")
    step2_legacy_parser.add_argument("--connection-retries", type=int, default=5, help="Retry count for connection/timeouts before failing.")
    step2_legacy_parser.add_argument("--prepare-only", action="store_true", help="Only preprocess and write prompts, do not call the model.")
    step2_legacy_parser.add_argument("--write", help="Optional output file path.")

    step2_execute_parser = subparsers.add_parser("step2-execute", help="Run Step2 V2 chapter by chapter with plain-text OpenAI requests.")
    step2_execute_parser.add_argument("--project-root", dest="project_root", help="Path to the project root.")
    step2_execute_parser.add_argument("--components", required=True, help="Path to components.json/components.jsonl.")
    step2_execute_parser.add_argument("--step1-source", required=True, help="Path to Step1 output dir or chapter_index.json.")
    step2_execute_parser.add_argument("--output", required=True, help="Directory to write execute artifacts.")
    step2_execute_parser.add_argument("--model", default="gpt-5.4", help="Model name.")
    step2_execute_parser.add_argument("--reasoning-effort", default="medium", help="Reasoning effort.")
    step2_execute_parser.add_argument("--component-batch-size", type=int, default=5, help="Max component types processed for one chapter batch.")
    step2_execute_parser.add_argument("--start-chapter-index", type=int, default=1, help="1-based chapter index to start from.")
    step2_execute_parser.add_argument("--chapter-limit", type=int, help="Optional number of chapters to process.")
    step2_execute_parser.add_argument("--start-component-batch-index", type=int, default=1, help="1-based component batch index to start from.")
    step2_execute_parser.add_argument("--component-batch-limit", type=int, help="Optional number of component batches to process.")
    step2_execute_parser.add_argument("--max-component-payload-chars", type=int, default=18000, help="Soft char budget for one component batch.")
    step2_execute_parser.add_argument("--max-prompt-chars", type=int, default=120000, help="Soft prompt size ceiling per chapter window.")
    step2_execute_parser.add_argument("--target-region-chars", type=int, default=60000, help="Approximate region char budget per chapter window.")
    step2_execute_parser.add_argument("--max-regions-per-batch", type=int, default=18, help="Max selected regions carried into one chapter window.")
    step2_execute_parser.add_argument("--max-region-text-chars", type=int, default=2400, help="Max non-table text chars kept per region.")
    step2_execute_parser.add_argument("--max-table-text-chars", type=int, default=2400, help="Max raw table chars kept per table.")
    step2_execute_parser.add_argument("--max-table-rows", type=int, default=60, help="Max rows kept per table.")
    step2_execute_parser.add_argument("--only-regions-with-tables", action="store_true", help="Only include regions containing tables.")
    step2_execute_parser.add_argument("--tpm-budget", type=int, default=320000, help="Estimated tokens-per-minute budget used for local throttling; set 0 to disable.")
    step2_execute_parser.add_argument("--prepare-only", action="store_true", help="Only write prompts/manifests, do not call the model.")
    step2_execute_parser.add_argument("--no-resume-existing", action="store_true", help="Ignore completed batch results in output dir and rerun them.")
    step2_execute_parser.add_argument("--max-output-tokens", type=int, default=8000, help="Max output tokens.")
    step2_execute_parser.add_argument("--request-timeout-seconds", type=float, default=120.0, help="HTTP timeout seconds.")
    step2_execute_parser.add_argument("--connection-retries", type=int, default=5, help="Connection retries.")
    step2_execute_parser.add_argument(
        "--validation-fallback-model",
        default="gpt-5.4",
        help="When Gemini lite batch quality deviates too much, rerun one validation pass with this model. Set to none to disable.",
    )
    step2_execute_parser.add_argument(
        "--validation-min-deviation-score",
        type=float,
        default=0.6,
        help="Trigger fallback validation when the batch deviation score reaches this threshold.",
    )
    step2_execute_parser.add_argument("--write", help="Optional output file path for command response JSON.")

    step2_synthesize_parser = subparsers.add_parser("step2-synthesize", help="Synthesize Step2 main outputs from existing chapter/batch result files.")
    step2_synthesize_parser.add_argument("--project-root", dest="project_root", help="Path to the project root.")
    step2_synthesize_parser.add_argument("--output", required=True, help="Existing Step2 output directory to repair.")
    step2_synthesize_parser.add_argument("--components", help="Optional components.json/components.jsonl override.")
    step2_synthesize_parser.add_argument("--step1-source", help="Optional Step1 output dir or chapter_index.json override.")
    step2_synthesize_parser.add_argument("--write", help="Optional output file path for command response JSON.")

    step3_execute_parser = subparsers.add_parser("step3-execute", help="Run Step3 formal pipeline from Step1 table regions and Step2 outputs.")
    step3_execute_parser.add_argument("--project-root", dest="project_root", help="Path to the project root.")
    step3_execute_parser.add_argument("--config", help="Path to runtime config. If omitted, pipeline_v2/step3_engine/runtime_config.ini will be used when present.")
    step3_execute_parser.add_argument("--step1-table-regions", help="Path to Step1 table_regions.json.")
    step3_execute_parser.add_argument("--step2-result", help="Optional Step2 result path, used to infer sibling synonym_library.json.")
    step3_execute_parser.add_argument("--components", help="Path to components.json or components.jsonl.")
    step3_execute_parser.add_argument("--synonym-library", help="Optional Step2 synonym_library.json path.")
    step3_execute_parser.add_argument("--output", help="Output directory, default: data/output/step3/<step1-parent>.")
    step3_execute_parser.add_argument("--model", help="OpenAI model alias, default: gpt-5.4.")
    step3_execute_parser.add_argument("--reasoning-effort", help="Reasoning effort passed to Responses API.")
    step3_execute_parser.add_argument("--request-timeout-seconds", type=float, help="HTTP timeout seconds for model requests.")
    step3_execute_parser.add_argument("--connection-retries", type=int, help="Connection retries for startup check and model requests.")
    step3_execute_parser.add_argument("--max-rows-per-batch", type=int, help="Max Step1 rows per prompt batch.")
    step3_execute_parser.add_argument("--max-components-per-item", type=int, help="Max candidate components kept per item.")
    step3_execute_parser.add_argument(
        "--prepare-only",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Only preprocess and write prompts, do not call the model.",
    )
    step3_execute_parser.add_argument(
        "--local-only",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Only use local rules, skip model call.",
    )
    step3_execute_parser.add_argument("--write", help="Optional output file path.")

    step3_parser = subparsers.add_parser("step3-forced-match", help="Match bill items with a specified component type using Step3 V2 adapter.")
    step3_parser.add_argument("--project-root", dest="project_root", help="Path to the project root.")
    step3_parser.add_argument("--items-file", help="Path to a JSON file containing one item or an items array.")
    step3_parser.add_argument("--item-json", help="Inline JSON object or array for bill items.")
    step3_parser.add_argument("--component-type", required=True, help="Specified component type.")
    step3_parser.add_argument("--components", required=True, help="Path to components.json/components.jsonl.")
    step3_parser.add_argument("--synonym-library", help="Optional synonym_library.json path.")
    step3_parser.add_argument("--write", help="Optional output file path.")

    step4_parser = subparsers.add_parser("step4-direct-match", help="Directly match bill items to a specified component type.")
    step4_parser.add_argument("--project-root", dest="project_root", help="Path to the project root.")
    step4_parser.add_argument("--items-file", help="Path to a JSON file containing one item or an items array.")
    step4_parser.add_argument("--item-json", help="Inline JSON object or array for bill items.")
    step4_parser.add_argument("--step3-result", help="Optional Step3 result JSON; when provided, Step4 will group rows by resolved component type.")
    step4_parser.add_argument("--component-type", help="Specified component type.")
    step4_parser.add_argument("--components", help="Path to components.json/components.jsonl.")
    step4_parser.add_argument("--synonym-library", help="Optional synonym_library.json path.")
    step4_parser.add_argument("--config", help="Optional Step4 runtime config path.")
    step4_parser.add_argument("--output", help="Optional output directory for local/model pipeline artifacts.")
    step4_parser.add_argument("--model", help="Optional model alias used by Step4 model refine.")
    step4_parser.add_argument("--reasoning-effort", help="Optional reasoning effort used by Step4 model refine.")
    step4_parser.add_argument("--openai-api-key", help="Optional OpenAI API key override for Step4 model refine.")
    step4_parser.add_argument("--openai-base-url", help="Optional OpenAI base URL override for Step4 model refine.")
    step4_parser.add_argument("--max-items-per-batch", type=int, help="Max Step4 items per prompt batch.")
    step4_parser.add_argument(
        "--prepare-only",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Only write Step4 prompt artifacts, do not call the model.",
    )
    step4_parser.add_argument(
        "--local-only",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Only run local Step4 direct match logic, skip model refine.",
    )
    step4_parser.add_argument("--write", help="Optional output file path.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    project_root = args.project_root or "."
    audit = audit_project(project_root)

    if args.command == "step1-extract":
        result = step1_process_pdf(
            pdf_path=args.pdf,
            output_dir=args.output,
            save_outputs=not args.no_save,
            use_paddleocr=args.use_paddleocr,
            minimum_text_length=args.minimum_text_length,
            auto_install_paddleocr=not args.no_auto_install_paddleocr,
        )
        _write_output(args.write, json.dumps(result.to_dict()["summary"], ensure_ascii=False, indent=2))
        return

    if args.command == "audit":
        if args.format == "json":
            payload = json.dumps(audit.to_dict(), ensure_ascii=False, indent=2)
        else:
            payload = render_markdown_report(audit, build_redesign_plan(audit))
        _write_output(args.write, payload)
        return

    if args.command == "import-legacy":
        result = import_legacy_outputs(
            project_root=project_root,
            run_id=args.run_id,
            step1_dir=args.step1_dir,
            step2_dir=args.step2_dir,
            step3_dir=args.step3_dir,
        )
        _write_output(args.write, json.dumps(result["manifest"], ensure_ascii=False, indent=2))
        return

    if args.command == "step3-build-review-queue":
        payload = json.loads(Path(args.step3_result).expanduser().resolve().read_text(encoding="utf-8"))
        rows = payload.get("rows") if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            raise ValueError("Step3 result JSON 必须包含 rows 数组。")
        queue = build_step3_review_queue(rows, source_stage=args.source_stage)
        ledger = write_review_ledger(args.output, queue, source_stage=args.source_stage)
        _write_output(args.write, json.dumps(ledger, ensure_ascii=False, indent=2))
        return

    if args.command == "step2-prepare":
        result = step2_prepare(
            components_path=args.components,
            step1_source_path=args.step1_source,
            output_dir=args.output,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            component_batch_size=args.component_batch_size,
            start_chapter_index=args.start_chapter_index,
            chapter_limit=args.chapter_limit,
            start_component_batch_index=args.start_component_batch_index,
            component_batch_limit=args.component_batch_limit,
        )
        _write_output(args.write, json.dumps(result["manifest"], ensure_ascii=False, indent=2))
        return

    if args.command == "step2-legacy-preprocess":
        summary = step2_preprocess(
            components_path=args.components,
            step1_source_path=args.step1_source,
            output_dir=args.output,
            alias_dict_path=args.alias_dict,
            history_review_path=args.history_review,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            max_components_per_batch=args.max_components_per_batch,
            max_attribute_values=args.max_attribute_values,
            max_region_text_chars=args.max_region_text_chars,
            max_table_text_chars=args.max_table_text_chars,
            max_table_rows=args.max_table_rows,
            only_regions_with_tables=args.only_regions_with_tables,
            max_component_payload_chars=args.max_component_payload_chars,
            max_prompt_chars=args.max_prompt_chars,
            target_region_chars=args.target_region_chars,
            max_regions_per_batch=args.max_regions_per_batch,
            max_output_tokens=args.max_output_tokens,
            tpm_budget=args.tpm_budget,
            request_timeout_seconds=args.request_timeout_seconds,
            connection_retries=args.connection_retries,
            prepare_only=args.prepare_only,
        )
        _write_output(args.write, json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if args.command == "step2-execute":
        result = step2_execute(
            components_path=args.components,
            step1_source_path=args.step1_source,
            output_dir=args.output,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            component_batch_size=args.component_batch_size,
            start_chapter_index=args.start_chapter_index,
            chapter_limit=args.chapter_limit,
            start_component_batch_index=args.start_component_batch_index,
            component_batch_limit=args.component_batch_limit,
            max_component_payload_chars=args.max_component_payload_chars,
            max_prompt_chars=args.max_prompt_chars,
            target_region_chars=args.target_region_chars,
            max_regions_per_batch=args.max_regions_per_batch,
            max_region_text_chars=args.max_region_text_chars,
            max_table_text_chars=args.max_table_text_chars,
            max_table_rows=args.max_table_rows,
            only_regions_with_tables=args.only_regions_with_tables,
            tpm_budget=args.tpm_budget,
            prepare_only=args.prepare_only,
            resume_existing=not args.no_resume_existing,
            max_output_tokens=args.max_output_tokens,
            request_timeout_seconds=args.request_timeout_seconds,
            connection_retries=args.connection_retries,
            validation_fallback_model=args.validation_fallback_model,
            validation_min_deviation_score=args.validation_min_deviation_score,
        )
        _write_output(args.write, json.dumps(result["run_summary"], ensure_ascii=False, indent=2))
        return

    if args.command == "step2-synthesize":
        result = synthesize_existing_step2_outputs(
            output_dir=args.output,
            components_path=args.components,
            step1_source_path=args.step1_source,
        )
        _write_output(args.write, json.dumps(result["run_summary"], ensure_ascii=False, indent=2))
        return

    if args.command == "step3-execute":
        runtime_options = step3_resolve_runtime_options(args)
        previous_environment = step3_apply_runtime_environment(runtime_options)
        try:
            summary = run_filter_condition_pipeline(
                step1_table_regions_path=runtime_options["step1_table_regions_path"],
                components_path=runtime_options["components_path"],
                synonym_library_path=runtime_options["synonym_library_path"],
                output_dir=runtime_options["output_dir"],
                model=runtime_options["model"],
                reasoning_effort=runtime_options["reasoning_effort"],
                request_timeout_seconds=runtime_options["request_timeout_seconds"],
                connection_retries=runtime_options["connection_retries"],
                max_rows_per_batch=runtime_options["max_rows_per_batch"],
                max_components_per_item=runtime_options["max_components_per_item"],
                prepare_only=runtime_options["prepare_only"],
                local_only=runtime_options["local_only"],
                step2_result_path=runtime_options["step2_result_path"],
            )
        finally:
            step3_restore_runtime_environment(previous_environment)
        if runtime_options.get("config_path"):
            summary["config_path"] = runtime_options["config_path"]
        _write_output(args.write, json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if args.command == "step3-forced-match":
        items = _load_items_from_args(args.items_file, args.item_json)
        result = match_bill_items_to_component(
            bill_items=items,
            component_type=args.component_type,
            components_path=args.components,
            synonym_library_path=args.synonym_library,
        )
        _write_output(args.write, json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "step4-direct-match":
        items = _load_items_from_args(args.items_file, args.item_json) if not args.step3_result else []
        pipeline_mode = any(
            [
                args.step3_result,
                args.config,
                args.output,
                args.model,
                args.reasoning_effort,
                args.openai_api_key,
                args.openai_base_url,
                args.max_items_per_batch is not None,
                args.prepare_only is not None,
                args.local_only is not None,
            ]
        )
        if pipeline_mode:
            runtime_options = step4_resolve_runtime_options(args)
            if not runtime_options["components_path"]:
                raise ValueError("Step4 配置模式需要 components 路径，可通过 --components 或配置文件提供。")
            previous_environment = step4_apply_runtime_environment(runtime_options)
            try:
                if args.step3_result:
                    result = run_step4_from_step3_result_pipeline(
                        step3_result_path=args.step3_result,
                        component_type=runtime_options["component_type"] or None,
                        components_path=runtime_options["components_path"],
                        synonym_library_path=runtime_options["synonym_library_path"],
                        output_dir=runtime_options["output_dir"],
                        model=runtime_options["model"],
                        reasoning_effort=runtime_options["reasoning_effort"],
                        max_items_per_batch=runtime_options["max_items_per_batch"],
                        prepare_only=runtime_options["prepare_only"],
                        local_only=runtime_options["local_only"],
                        config_path=runtime_options["config_path"],
                    )
                else:
                    if not runtime_options["component_type"]:
                        raise ValueError("Step4 配置模式需要 component_type，可通过 --component-type 或配置文件提供。")
                    result = run_step4_pipeline(
                        bill_items=items,
                        component_type=runtime_options["component_type"],
                        components_path=runtime_options["components_path"],
                        synonym_library_path=runtime_options["synonym_library_path"],
                        output_dir=runtime_options["output_dir"],
                        model=runtime_options["model"],
                        reasoning_effort=runtime_options["reasoning_effort"],
                        max_items_per_batch=runtime_options["max_items_per_batch"],
                        prepare_only=runtime_options["prepare_only"],
                        local_only=runtime_options["local_only"],
                        config_path=runtime_options["config_path"],
                    )
            finally:
                step4_restore_runtime_environment(previous_environment)
            payload = dict(result["result_payload"])
            payload["run_summary"] = result["run_summary"]
        else:
            if not args.component_type:
                raise ValueError("Step4 直匹配模式需要 --component-type。")
            if not args.components:
                raise ValueError("Step4 直匹配模式需要 --components。")
            components_payload = load_json_or_jsonl(args.components)
            synonym_payload = load_json_or_jsonl(args.synonym_library) if args.synonym_library else None
            enriched_items = [dict(item, component_type=args.component_type) for item in items]
            rows = direct_match_bill_items(
                bill_items=enriched_items,
                components_payload=components_payload,
                synonym_library_payload=synonym_payload,
            )
            payload = {
                "meta": {
                    "task_name": "step4_direct_match",
                    "specified_component_type": args.component_type,
                    "components_path": str(Path(args.components).expanduser().resolve()),
                    "synonym_library_path": str(Path(args.synonym_library).expanduser().resolve()) if args.synonym_library else "",
                    "total_items": len(enriched_items),
                    "generation_mode": "local_direct",
                },
                "rows": rows,
            }
        _write_output(args.write, json.dumps(payload, ensure_ascii=False, indent=2))
        return

    plan = build_redesign_plan(audit)
    if args.format == "json":
        payload = json.dumps({"audit": audit.to_dict(), "plan": plan.to_dict()}, ensure_ascii=False, indent=2)
    else:
        payload = render_markdown_report(audit, plan)
    _write_output(args.write, payload)


if __name__ == "__main__":
    main()
