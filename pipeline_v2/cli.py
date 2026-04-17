from __future__ import annotations

import argparse
import json
from pathlib import Path

from .audit import audit_project, build_redesign_plan, render_markdown_report
from .global_knowledge_base import build_global_knowledge_base, query_global_knowledge_base
from .import_legacy import import_legacy_outputs
from .knowledge_base import build_knowledge_base, query_knowledge_base
from .model_runtime import (
    DEFAULT_OPENAI_MODEL,
    DEFAULT_REASONING_EFFORT,
    load_step_model_config,
    normalize_model_name,
    resolve_provider_env,
    resolve_validation_provider_env,
)
from .review_queue import build_step3_review_queue, write_review_ledger
from .step1_chapter_ocr.api import process_pdf as step1_process_pdf
from .step2_review_html import apply_step2_review_package, build_step2_review_html
from .step2_review_tool_bundle import build_step2_review_tool_bundle
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
from .step5_feature_audit import main as step5_audit_main


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
    parser.add_argument("--models-config", help="Path to runtime_models.ini for step model/provider selection.")
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
    step2_parser.add_argument("--model", default=DEFAULT_OPENAI_MODEL, help="Model name.")
    step2_parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT, help="Reasoning effort.")
    step2_parser.add_argument("--component-batch-size", type=int, default=5, help="Max component types processed for one chapter batch.")
    step2_parser.add_argument("--start-chapter-index", type=int, default=1, help="1-based chapter index to start from.")
    step2_parser.add_argument("--chapter-limit", type=int, help="Optional number of chapters to process.")
    step2_parser.add_argument("--start-component-batch-index", type=int, default=1, help="1-based component batch index to start from.")
    step2_parser.add_argument("--component-batch-limit", type=int, help="Optional number of component batches to process.")
    step2_parser.add_argument("--write", help="Optional output file path for command response JSON.")

    step2_execute_parser = subparsers.add_parser("step2-execute", help="Run Step2 V2 chapter by chapter with plain-text OpenAI requests.")
    step2_execute_parser.add_argument("--project-root", dest="project_root", help="Path to the project root.")
    step2_execute_parser.add_argument("--components", required=True, help="Path to components.json/components.jsonl.")
    step2_execute_parser.add_argument("--step1-source", required=True, help="Path to Step1 output dir or chapter_index.json.")
    step2_execute_parser.add_argument("--output", required=True, help="Directory to write execute artifacts.")
    step2_execute_parser.add_argument("--model", default=DEFAULT_OPENAI_MODEL, help="Model name.")
    step2_execute_parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT, help="Reasoning effort.")
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
        default=DEFAULT_OPENAI_MODEL,
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

    step2_review_html_parser = subparsers.add_parser("step2-build-review-html", help="Build a self-contained HTML page for Step2 manual review.")
    step2_review_html_parser.add_argument("--project-root", dest="project_root", help="Path to the project root.")
    step2_review_html_parser.add_argument("--step2-output", required=True, help="Path to the Step2 output directory.")
    step2_review_html_parser.add_argument("--output-html", help="Optional HTML output path.")
    step2_review_html_parser.add_argument("--write", help="Optional output file path for command response JSON.")

    step2_apply_review_parser = subparsers.add_parser("step2-apply-review", help="Apply an exported Step2 manual review package and write final reviewed outputs.")
    step2_apply_review_parser.add_argument("--project-root", dest="project_root", help="Path to the project root.")
    step2_apply_review_parser.add_argument("--step2-output", required=True, help="Path to the source Step2 output directory.")
    step2_apply_review_parser.add_argument("--review-json", required=True, help="Path to the exported review package JSON.")
    step2_apply_review_parser.add_argument("--output", help="Optional output directory for final reviewed artifacts.")
    step2_apply_review_parser.add_argument("--write", help="Optional output file path for command response JSON.")

    step2_review_tool_parser = subparsers.add_parser("step2-build-review-tool-bundle", help="Build a standalone Windows-friendly Step2 HTML review tool bundle.")
    step2_review_tool_parser.add_argument("--project-root", dest="project_root", help="Path to the project root.")
    step2_review_tool_parser.add_argument("--output-dir", required=True, help="Directory to place the standalone review tool bundle.")
    step2_review_tool_parser.add_argument("--step2-output", help="Optional Step2 output directory. When provided, key JSON inputs will be copied into the bundle.")
    step2_review_tool_parser.add_argument("--write", help="Optional output file path for command response JSON.")

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

    knowledge_build_parser = subparsers.add_parser("knowledge-build", help="Build a Step1/2/3 vector knowledge base plus wiki pages for Step4.")
    knowledge_build_parser.add_argument("--project-root", dest="project_root", help="Path to the project root.")
    knowledge_build_parser.add_argument("--step1-source", help="Path to Step1 output dir or table_regions.json.")
    knowledge_build_parser.add_argument("--step2-source", help="Path to Step2 output dir or result.json/component_matching_result.json.")
    knowledge_build_parser.add_argument("--step3-result", help="Path to Step3 result dir or project_component_feature_calc_matching_result.json.")
    knowledge_build_parser.add_argument("--output-dir", required=True, help="Directory to write knowledge.db and wiki pages.")
    knowledge_build_parser.add_argument("--write", help="Optional output file path.")

    knowledge_query_parser = subparsers.add_parser("knowledge-query", help="Query the Step4 knowledge base and return ranked snippets.")
    knowledge_query_parser.add_argument("--project-root", dest="project_root", help="Path to the project root.")
    knowledge_query_parser.add_argument("--knowledge-base", required=True, help="Path to knowledge.db or its parent directory.")
    knowledge_query_parser.add_argument("--query", required=True, help="Query text.")
    knowledge_query_parser.add_argument("--component-type", help="Optional component type filter.")
    knowledge_query_parser.add_argument("--top-k", type=int, default=4, help="Max entry hits.")
    knowledge_query_parser.add_argument("--max-context-chars", type=int, default=3200, help="Soft char budget for retrieved snippets.")
    knowledge_query_parser.add_argument("--write", help="Optional output file path.")

    global_kb_build_parser = subparsers.add_parser("global-kb-build", help="Build a global reusable knowledge base from arbitrary files, folders, or a manifest.")
    global_kb_build_parser.add_argument("--project-root", dest="project_root", help="Path to the project root.")
    global_kb_build_parser.add_argument("--source", action="append", help="A file or directory to ingest. Repeatable.")
    global_kb_build_parser.add_argument("--manifest", help="Optional JSON manifest describing collections, tags, and source rules.")
    global_kb_build_parser.add_argument("--output-dir", required=True, help="Directory to write global_knowledge.db and wiki pages.")
    global_kb_build_parser.add_argument("--default-collection", default="general", help="Fallback collection for --source inputs.")
    global_kb_build_parser.add_argument("--chunk-chars", type=int, default=1400, help="Target chars per stored chunk.")
    global_kb_build_parser.add_argument("--chunk-overlap", type=int, default=180, help="Overlap chars between chunks.")
    global_kb_build_parser.add_argument("--write", help="Optional output file path.")

    global_kb_query_parser = subparsers.add_parser("global-kb-query", help="Query the global reusable knowledge base.")
    global_kb_query_parser.add_argument("--project-root", dest="project_root", help="Path to the project root.")
    global_kb_query_parser.add_argument("--knowledge-base", required=True, help="Path to global_knowledge.db or its parent directory.")
    global_kb_query_parser.add_argument("--query", required=True, help="Query text.")
    global_kb_query_parser.add_argument("--collection", action="append", help="Optional collection filter. Repeatable.")
    global_kb_query_parser.add_argument("--tag", action="append", help="Optional tag filter. Repeatable.")
    global_kb_query_parser.add_argument("--top-k", type=int, default=4, help="Max document hits.")
    global_kb_query_parser.add_argument("--max-context-chars", type=int, default=3200, help="Soft char budget for retrieved snippets.")
    global_kb_query_parser.add_argument("--write", help="Optional output file path.")

    step4_parser = subparsers.add_parser("step4-direct-match", help="Directly match bill items to a specified component type.")
    step4_parser.add_argument("--project-root", dest="project_root", help="Path to the project root.")
    step4_parser.add_argument("--items-file", help="Path to a JSON file containing one item or an items array.")
    step4_parser.add_argument("--item-json", help="Inline JSON object or array for bill items.")
    step4_parser.add_argument("--step3-result", help="Optional Step3 result JSON; when provided, Step4 will group rows by resolved component type.")
    step4_parser.add_argument("--component-type", help="Specified component type.")
    step4_parser.add_argument("--components", help="Path to components.json/components.jsonl.")
    step4_parser.add_argument("--synonym-library", help="Optional synonym_library.json path.")
    step4_parser.add_argument("--knowledge-base", help="Optional knowledge.db path or its parent directory, used to retrieve Step1/2/3 context for Step4 prompts.")
    step4_parser.add_argument("--config", help="Optional Step4 runtime config path.")
    step4_parser.add_argument("--output", help="Optional output directory for local/model pipeline artifacts.")
    step4_parser.add_argument("--model", help="Optional model alias used by Step4 model refine.")
    step4_parser.add_argument("--reasoning-effort", help="Optional reasoning effort used by Step4 model refine.")
    step4_parser.add_argument("--openai-api-key", help="Optional OpenAI API key override for Step4 model refine.")
    step4_parser.add_argument("--openai-base-url", help="Optional OpenAI base URL override for Step4 model refine.")
    step4_parser.add_argument("--max-items-per-batch", type=int, help="Max Step4 items per prompt batch.")
    step4_parser.add_argument("--knowledge-top-k", type=int, help="Max knowledge entry hits per Step4 row.")
    step4_parser.add_argument("--knowledge-max-chars", type=int, help="Soft char budget for retrieved Step4 knowledge snippets.")
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

    # ── Step5: Feature Audit Tool ────────────────────────────────
    step5_parser = subparsers.add_parser("step5-audit", help="Generate interactive HTML feature audit tool from Step3 results.")
    step5_parser.add_argument("--step3-result", help="Path to Step3 matching result JSON.")
    step5_parser.add_argument("--components", help="Path to components.json.")
    step5_parser.add_argument("--component-source-table", help="Path to component_source_table.json.")
    step5_parser.add_argument("--output", help="Output HTML file path.")

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

    if args.command == "step2-execute":
        step_model_cfg = load_step_model_config("step2", args.models_config)
        provider_env = resolve_provider_env(step_model_cfg)
        validation_provider_env = resolve_validation_provider_env(step_model_cfg)
        result = step2_execute(
            components_path=args.components,
            step1_source_path=args.step1_source,
            output_dir=args.output,
            model=normalize_model_name(step_model_cfg.get("model") or args.model, DEFAULT_OPENAI_MODEL) or DEFAULT_OPENAI_MODEL,
            reasoning_effort=step_model_cfg.get("reasoning_effort") or args.reasoning_effort,
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
            validation_fallback_model=normalize_model_name(
                step_model_cfg.get("validation_fallback_model") or args.validation_fallback_model,
                DEFAULT_OPENAI_MODEL,
            ),
            validation_min_deviation_score=args.validation_min_deviation_score,
            openai_api_key=provider_env.get("openai_api_key"),
            openai_base_url=provider_env.get("openai_base_url"),
            validation_openai_api_key=validation_provider_env.get("openai_api_key"),
            validation_openai_base_url=validation_provider_env.get("openai_base_url"),
            provider_mode=provider_env.get("provider_mode"),
            validation_provider_mode=validation_provider_env.get("provider_mode"),
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

    if args.command == "step2-build-review-html":
        result = build_step2_review_html(
            step2_output_dir=args.step2_output,
            output_html_path=args.output_html,
        )
        _write_output(args.write, json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "step2-apply-review":
        result = apply_step2_review_package(
            step2_output_dir=args.step2_output,
            review_json_path=args.review_json,
            output_dir=args.output,
        )
        _write_output(args.write, json.dumps(result["run_summary"], ensure_ascii=False, indent=2))
        return

    if args.command == "step2-build-review-tool-bundle":
        result = build_step2_review_tool_bundle(args.output_dir, step2_output_dir=args.step2_output)
        _write_output(args.write, json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "step3-execute":
        step_model_cfg = load_step_model_config("step3", args.models_config)
        runtime_options = step3_resolve_runtime_options(args)
        provider_env = resolve_provider_env(step_model_cfg)
        if step_model_cfg.get("model"):
            runtime_options["model"] = normalize_model_name(step_model_cfg["model"], DEFAULT_OPENAI_MODEL)
        else:
            runtime_options["model"] = normalize_model_name(runtime_options.get("model"), DEFAULT_OPENAI_MODEL)
        if step_model_cfg.get("reasoning_effort"):
            runtime_options["reasoning_effort"] = step_model_cfg["reasoning_effort"]
        if provider_env.get("openai_api_key"):
            runtime_options["openai_api_key"] = provider_env["openai_api_key"]
        if provider_env.get("openai_base_url"):
            runtime_options["openai_base_url"] = provider_env["openai_base_url"]
        if provider_env.get("provider_mode"):
            runtime_options["provider_mode"] = provider_env["provider_mode"]
            runtime_options["use_codex_subscription"] = provider_env.get("use_codex_subscription")
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
                provider_mode=runtime_options["provider_mode"],
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

    if args.command == "knowledge-build":
        result = build_knowledge_base(
            step1_source=args.step1_source,
            step2_source=args.step2_source,
            step3_source=args.step3_result,
            output_dir=args.output_dir,
        )
        _write_output(args.write, json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "knowledge-query":
        result = query_knowledge_base(
            knowledge_base_path=args.knowledge_base,
            query_text=args.query,
            component_type=args.component_type,
            top_k=args.top_k,
            max_context_chars=args.max_context_chars,
        )
        _write_output(args.write, json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "global-kb-build":
        result = build_global_knowledge_base(
            output_dir=args.output_dir,
            source_paths=args.source,
            manifest_path=args.manifest,
            default_collection=args.default_collection,
            chunk_chars=args.chunk_chars,
            chunk_overlap=args.chunk_overlap,
        )
        _write_output(args.write, json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "global-kb-query":
        result = query_global_knowledge_base(
            knowledge_base_path=args.knowledge_base,
            query_text=args.query,
            collections=args.collection,
            tags=args.tag,
            top_k=args.top_k,
            max_context_chars=args.max_context_chars,
        )
        _write_output(args.write, json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "step4-direct-match":
        items = _load_items_from_args(args.items_file, args.item_json) if not args.step3_result else []
        pipeline_mode = any(
            [
                args.step3_result,
                args.models_config,
                args.config,
                args.output,
                args.model,
                args.reasoning_effort,
                args.openai_api_key,
                args.openai_base_url,
                args.knowledge_base,
                args.max_items_per_batch is not None,
                args.knowledge_top_k is not None,
                args.knowledge_max_chars is not None,
                args.prepare_only is not None,
                args.local_only is not None,
            ]
        )
        if pipeline_mode:
            step_model_cfg = load_step_model_config("step4", args.models_config)
            runtime_options = step4_resolve_runtime_options(args)
            provider_env = resolve_provider_env(step_model_cfg)
            if step_model_cfg.get("model"):
                runtime_options["model"] = normalize_model_name(step_model_cfg["model"], DEFAULT_OPENAI_MODEL)
            else:
                runtime_options["model"] = normalize_model_name(runtime_options.get("model"), DEFAULT_OPENAI_MODEL)
            if step_model_cfg.get("reasoning_effort"):
                runtime_options["reasoning_effort"] = step_model_cfg["reasoning_effort"]
            if provider_env.get("openai_api_key"):
                runtime_options["openai_api_key"] = provider_env["openai_api_key"]
            if provider_env.get("openai_base_url"):
                runtime_options["openai_base_url"] = provider_env["openai_base_url"]
            if provider_env.get("provider_mode"):
                runtime_options["provider_mode"] = provider_env["provider_mode"]
                runtime_options["use_codex_subscription"] = provider_env.get("use_codex_subscription")
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
                        knowledge_base_path=runtime_options["knowledge_base_path"],
                        output_dir=runtime_options["output_dir"],
                        model=runtime_options["model"],
                        reasoning_effort=runtime_options["reasoning_effort"],
                        provider_mode=runtime_options["provider_mode"],
                        max_items_per_batch=runtime_options["max_items_per_batch"],
                        knowledge_top_k=runtime_options["knowledge_top_k"],
                        knowledge_max_chars=runtime_options["knowledge_max_chars"],
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
                        knowledge_base_path=runtime_options["knowledge_base_path"],
                        output_dir=runtime_options["output_dir"],
                        model=runtime_options["model"],
                        reasoning_effort=runtime_options["reasoning_effort"],
                        provider_mode=runtime_options["provider_mode"],
                        max_items_per_batch=runtime_options["max_items_per_batch"],
                        knowledge_top_k=runtime_options["knowledge_top_k"],
                        knowledge_max_chars=runtime_options["knowledge_max_chars"],
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

    if args.command == "step5-audit":
        import sys
        # Build sys.argv for step5's own argparse
        step5_args = []
        if args.step3_result:
            step5_args += ["--step3-result", args.step3_result]
        if args.components:
            step5_args += ["--components", args.components]
        if args.component_source_table:
            step5_args += ["--component-source-table", args.component_source_table]
        if args.output:
            step5_args += ["--output", args.output]
        old_argv = sys.argv
        sys.argv = ["step5-audit"] + step5_args
        try:
            step5_audit_main()
        finally:
            sys.argv = old_argv
        return

    plan = build_redesign_plan(audit)
    if args.format == "json":
        payload = json.dumps({"audit": audit.to_dict(), "plan": plan.to_dict()}, ensure_ascii=False, indent=2)
    else:
        payload = render_markdown_report(audit, plan)
    _write_output(args.write, payload)


if __name__ == "__main__":
    main()
