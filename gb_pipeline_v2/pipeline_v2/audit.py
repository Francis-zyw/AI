from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .contracts import (
    AuditIssue,
    CutoverGate,
    ManualReviewContract,
    ProjectAudit,
    RedesignPlan,
    Severity,
    StepSnapshot,
    StepStatus,
    WorkUnit,
)


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_run_summary(step_root: Path) -> Optional[Path]:
    if not step_root.exists():
        return None
    candidates = sorted(step_root.glob("*/run_summary.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _latest_catalog_summary(step_root: Path) -> Optional[Path]:
    if not step_root.exists():
        return None
    candidates = sorted(step_root.glob("*/catalog_summary.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _append_step2_issues(summary: Dict[str, Any], issues: List[AuditIssue]) -> None:
    status = str(summary.get("status", "")).strip()
    error = str(summary.get("error", "")).strip()
    if status == "failed":
        recommendation = "在 v2 中改为结构化文本片段输入，不再使用旧版 `input_file/file_data` 组包方式。"
        evidence = [f"status={status}"]
        if error:
            evidence.append(error)
        issues.append(
            AuditIssue(
                code="STEP2_REQUEST_FORMAT",
                severity=Severity.BLOCKER,
                summary="Step 2 在首批请求即失败，正式同义词库未产出。",
                recommendation=recommendation,
                evidence=evidence,
            )
        )


def _append_step3_issues(summary: Dict[str, Any], issues: List[AuditIssue]) -> None:
    status = str(summary.get("status", "")).strip()
    matched_rows = _as_int(summary.get("matched_rows"))
    candidate_only_rows = _as_int(summary.get("candidate_only_rows"))
    unmatched_rows = _as_int(summary.get("unmatched_rows"))
    synonym_library_path = str(summary.get("synonym_library_path", "")).strip()

    if status == "completed_local_only":
        issues.append(
            AuditIssue(
                code="STEP3_LOCAL_ONLY",
                severity=Severity.BLOCKER,
                summary="Step 3 只跑了本地规则，没有完成模型校正闭环。",
                recommendation="v2 需要把本地规则、模型批处理、人工复核拆成显式阶段，并为每批保留可恢复状态。",
                evidence=[
                    f"matched_rows={matched_rows}",
                    f"candidate_only_rows={candidate_only_rows}",
                    f"unmatched_rows={unmatched_rows}",
                ],
            )
        )

    if not synonym_library_path:
        issues.append(
            AuditIssue(
                code="STEP3_NO_SYNONYM_INPUT",
                severity=Severity.WARNING,
                summary="Step 3 当前运行未接入 Step 2 的正式 synonym_library.json。",
                recommendation="v2 需要把 Step 2 结果产物登记进工作区清单，禁止以空词库直接进入 Step 3 正式阶段。",
                evidence=["synonym_library_path is empty"],
            )
        )

    if candidate_only_rows or unmatched_rows:
        issues.append(
            AuditIssue(
                code="STEP3_REVIEW_BACKLOG",
                severity=Severity.WARNING,
                summary="Step 3 结果中仍有大量待复核和未匹配数据。",
                recommendation="v2 应生成 review queue，把 `candidate_only`/`unmatched` 变成可追踪的人机协作队列。",
                evidence=[
                    f"candidate_only_rows={candidate_only_rows}",
                    f"unmatched_rows={unmatched_rows}",
                ],
            )
        )


def _append_step3_config_issues(project_root: Path, issues: List[AuditIssue]) -> None:
    config_path = project_root / "pipeline_v2" / "step3_engine" / "runtime_config.ini"
    if not config_path.exists():
        return
    content = config_path.read_text(encoding="utf-8")
    lowered = content.lower()
    if "local_only = true" in lowered or "local_only=true" in lowered:
        issues.append(
            AuditIssue(
                code="STEP3_DEFAULT_LOCAL_ONLY",
                severity=Severity.WARNING,
                summary="Step 3 默认配置即为 `local_only=true`，双击运行时天然会跳过模型校正阶段。",
                recommendation="v2 需要把 `local_only` 改成显式运行模式，而不是默认正式流程；默认值应指向可恢复的标准模式。",
                evidence=[str(config_path)],
            )
        )


def _append_input_layout_issues(project_root: Path, issues: List[AuditIssue]) -> None:
    input_root = project_root / "data" / "input"
    if not input_root.exists():
        return
    has_pdf = any(input_root.glob("*.pdf"))
    has_component_json = any((input_root / name).exists() for name in ("components.json", "components.jsonl"))
    has_component_excels = (input_root / "component_type_attribute_excels").exists()
    if has_pdf and has_component_json and has_component_excels:
        issues.append(
            AuditIssue(
                code="DATA_INPUT_MIXED_ROLES",
                severity=Severity.WARNING,
                summary="`data/input/` 同时承载原始 PDF、构件主数据和 Excel 源文件，输入语义已经混杂。",
                recommendation="v2 建议拆成 `data/source/`、`data/reference/`、`data/workspaces_v2/`、`data/manual_reviews/`、`data/published/` 五层。",
                evidence=[str(input_root)],
            )
        )


def _append_duplicate_path_issues(project_root: Path, duplicate_paths: List[str], issues: List[AuditIssue]) -> None:
    existing = [path for path in duplicate_paths if Path(path).exists()]
    if len(existing) > 1:
        issues.append(
            AuditIssue(
                code="DUPLICATE_COMPONENT_LIBRARY",
                severity=Severity.WARNING,
                summary="构件类型库存在多个副本，主线与历史副本容易继续混写。",
                recommendation="冻结旧副本为只读参考，所有新开发统一进入 `pipeline_v2/` 和 `tools/tool_component_type_library/`。",
                evidence=existing,
            )
        )


def audit_project(project_root: str | Path) -> ProjectAudit:
    root = Path(project_root).resolve()
    output_root = root / "data" / "output"
    issues: List[AuditIssue] = []
    steps: List[StepSnapshot] = []

    step1_summary_path = _latest_catalog_summary(output_root / "step1")
    if step1_summary_path:
        step1_summary = _read_json(step1_summary_path)
        steps.append(
            StepSnapshot(
                name="step1",
                status=StepStatus.COMPLETED,
                source_path=str(step1_summary_path),
                details={
                    "total_pdf_pages": _as_int(step1_summary.get("total_pdf_pages")),
                    "total_regions": _as_int(step1_summary.get("region_counts", {}).get("total")),
                    "regions_with_tables": _as_int(step1_summary.get("table_counts", {}).get("regions_with_tables")),
                    "table_rows": _as_int(step1_summary.get("table_counts", {}).get("rows")),
                },
            )
        )
    else:
        steps.append(StepSnapshot(name="step1", status=StepStatus.MISSING, source_path="", details={}))
        issues.append(
            AuditIssue(
                code="STEP1_OUTPUT_MISSING",
                severity=Severity.BLOCKER,
                summary="未找到 Step 1 输出，无法继续后续阶段。",
                recommendation="先在 v2 工作区重新建立 Step 1 结构化输出，再允许进入 Step 2/Step 3。",
                evidence=[str(output_root / "step1")],
            )
        )

    step2_summary_path = _latest_run_summary(output_root / "step2")
    if step2_summary_path:
        step2_summary = _read_json(step2_summary_path)
        step2_status = StepStatus.FAILED if str(step2_summary.get("status")) == "failed" else StepStatus.PARTIAL
        steps.append(
            StepSnapshot(
                name="step2",
                status=step2_status,
                source_path=str(step2_summary_path),
                details={
                    "status": step2_summary.get("status"),
                    "model": step2_summary.get("model", ""),
                    "total_batches": _as_int(step2_summary.get("total_batches")),
                    "failed_batch": _as_int(step2_summary.get("failed_batch")),
                    "error": str(step2_summary.get("error", "")).strip(),
                },
            )
        )
        _append_step2_issues(step2_summary, issues)
    else:
        steps.append(StepSnapshot(name="step2", status=StepStatus.MISSING, source_path="", details={}))

    step3_summary_path = _latest_run_summary(output_root / "step3")
    if step3_summary_path:
        step3_summary = _read_json(step3_summary_path)
        raw_status = str(step3_summary.get("status", "")).strip()
        step3_status = StepStatus.PARTIAL if raw_status == "completed_local_only" else StepStatus.COMPLETED
        steps.append(
            StepSnapshot(
                name="step3",
                status=step3_status,
                source_path=str(step3_summary_path),
                details={
                    "status": raw_status,
                    "total_source_rows": _as_int(step3_summary.get("total_source_rows")),
                    "generated_rows": _as_int(step3_summary.get("generated_rows")),
                    "matched_rows": _as_int(step3_summary.get("matched_rows")),
                    "candidate_only_rows": _as_int(step3_summary.get("candidate_only_rows")),
                    "unmatched_rows": _as_int(step3_summary.get("unmatched_rows")),
                },
            )
        )
        _append_step3_issues(step3_summary, issues)
    else:
        steps.append(StepSnapshot(name="step3", status=StepStatus.MISSING, source_path="", details={}))

    duplicate_paths = [
        str(root / "tools" / "tool_component_type_library"),
        str(root / "分析工具" / "构件类型-属性"),
        str(root.parent / "构件类型-属性"),
    ]
    _append_step3_config_issues(root, issues)
    _append_input_layout_issues(root, issues)
    _append_duplicate_path_issues(root, duplicate_paths, issues)

    return ProjectAudit(
        project_root=str(root),
        generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        duplicate_paths=duplicate_paths,
        steps=steps,
        issues=issues,
    )


def build_redesign_plan(audit: ProjectAudit) -> RedesignPlan:
    root = Path(audit.project_root)
    new_workspace_root = str(root / "data" / "workspaces_v2")
    workflow = [
        "1. 在 `data/workspaces_v2/<run_id>/` 下建立独立运行工作区，冻结旧版 `data/output/step1|2|3` 为只读参考。",
        "2. Step 1 只负责 `PDF -> chapter_packages + table_regions + layout evidence`，不直接耦合 Step 2 的附录过滤策略。",
        "3. Step 2 负责 `构件库 -> 标准章节 -> 同义词/证据集`，每批请求仅使用结构化文本输入并写回 manifest、prompt、response、result。",
        "4. Step 3 负责 `清单行 -> 候选构件 -> 特征表达式 -> 计算项目`，把本地规则、模型校正、人工复核拆成三个显式状态。",
        "5. 旧 Step1 输出、旧 Step2 人工修订结果、旧 Step3 候选结果先导入 V2 工作区，再决定是否复用或重跑。",
        "6. 所有 `candidate_only/unmatched/conflict` 进入 review queue，确认结果回写 `data/manual_reviews/` 并反哺 Step 2/Step 3。",
        "7. 只有通过 golden baseline、人工抽检和 cutover gate 后，V2 才能替换旧主线。",
    ]
    work_units = [
        WorkUnit(
            identifier="WU-01",
            title="冻结旧主线并建立 v2 隔离区",
            owner="总agent",
            goal="把新增开发明确收口到隔离目录，不再继续直接修改旧的 step1/step2/step3。",
            inputs=["现有项目目录", "legacy 输出样本", "重复工具目录"],
            outputs=["pipeline_v2/ 新骨架", "docs/plans/ 重构方案", "data/workspaces_v2/ 运行根目录"],
            depends_on=[],
            file_scope=["pipeline_v2/*", "docs/plans/*", "data/workspaces_v2/.gitkeep"],
            acceptance=[
                "旧主线不被改写也能继续保留参考价值。",
                "新开发入口明确且可追踪。",
            ],
        ),
        WorkUnit(
            identifier="WU-02",
            title="重写 Step 1 契约层",
            owner="Step1 agent",
            goal="把章节结构识别、文本提取、表格提取拆成独立契约。",
            inputs=["PDF", "TOC/Heading/OCR layout"],
            outputs=["chapter_index.json", "chapter_packages", "table_regions.json", "layout evidence"],
            depends_on=["WU-01"],
            file_scope=["pipeline_v2/step1_*", "tests/unit/*step1*"],
            acceptance=[
                "无 TOC 的 PDF 也能切换到 heading/layout 策略。",
                "文本层与 OCR 统一输出 page layout/token 契约。",
            ],
        ),
        WorkUnit(
            identifier="WU-03",
            title="重写 Step 2 请求与结果编排",
            owner="Step2 agent",
            goal="替换旧版请求组包格式，保证批处理、重试和恢复可控。",
            inputs=["components.json", "chapter_packages", "历史修订结果"],
            outputs=["synonym_library.json", "component_matching_result.json", "request manifests"],
            depends_on=["WU-01", "WU-02"],
            file_scope=["pipeline_v2/step2_*", "tests/unit/*step2*"],
            acceptance=[
                "单批失败可以续跑，不重算全部 57 个批次。",
                "请求不再依赖旧版 `input_file/file_data` 结构。",
            ],
        ),
        WorkUnit(
            identifier="WU-04",
            title="重写 Step 3 为三段式匹配流程",
            owner="Step3 agent",
            goal="把本地规则、模型校正、人工复核拆成显式状态机。",
            inputs=["table_regions.json", "synonym_library.json", "components.json"],
            outputs=["candidate matrix", "review queue", "final export"],
            depends_on=["WU-01", "WU-03"],
            file_scope=["pipeline_v2/step3_*", "tests/unit/*step3*"],
            acceptance=[
                "支持 `local_only`、`model_refine`、`reviewed` 三种状态切换。",
                "`candidate_only/unmatched` 可以被单独追踪与复跑。",
            ],
        ),
        WorkUnit(
            identifier="WU-05",
            title="迁移 legacy 产物与人工修订",
            owner="迁移agent",
            goal="把现有可用产物导入 V2，而不是简单丢弃。",
            inputs=["旧 Step1 输出目录", "旧 Step2 人工修订 JSON", "旧 Step3 候选结果"],
            outputs=["import manifest", "checksums", "workspace imports"],
            depends_on=["WU-01"],
            file_scope=["pipeline_v2/import_*", "data/workspaces_v2/*", "data/manual_reviews/*"],
            acceptance=[
                "能把旧 Step1 `chapter_regions/table_regions` 挂进 V2 工作区。",
                "能把人工修订 JSON 落进 `data/manual_reviews/step2/` 并记录来源。",
            ],
        ),
        WorkUnit(
            identifier="WU-06",
            title="定义人工复核契约与回写链路",
            owner="Review agent",
            goal="把人工确认结果变成可持久化、可追溯、可反哺的标准记录。",
            inputs=["review queue", "tool_component_match_review 导出 JSON", "业务确认结果"],
            outputs=["manual review contract", "review ledger", "feedback patches"],
            depends_on=["WU-03", "WU-04", "WU-05"],
            file_scope=["pipeline_v2/contracts.py", "data/manual_reviews/*", "tools/tool_component_match_review/*"],
            acceptance=[
                "每条人工复核记录至少包含 `record_id/review_status/manual_notes/reviewed_at/source_stage`。",
                "Step2/Step3 都能消费人工确认结果，而不是停留在独立工具里。",
            ],
        ),
        WorkUnit(
            identifier="WU-07",
            title="建立验证门与 cutover 标准",
            owner="验证agent",
            goal="定义 V2 何时可以从 shadow 模式切换为默认主线。",
            inputs=["baseline 标准文档", "V1 结果基线", "V2 运行结果", "人工抽检结论"],
            outputs=["golden baseline", "cutover report", "go/no-go decision"],
            depends_on=["WU-02", "WU-03", "WU-04", "WU-05", "WU-06"],
            file_scope=["pipeline_v2/contracts.py", "pipeline_v2/audit.py", "tests/unit/*"],
            acceptance=[
                "明确 baseline 文档、对比指标、人工抽检比例和放量条件。",
                "只有通过 cutover gate 的结果才能替换旧主线。",
            ],
        ),
        WorkUnit(
            identifier="WU-08",
            title="建立端到端审计与验收",
            owner="总agent",
            goal="让每次运行都有可比较的统计、问题清单和产物索引。",
            inputs=["WU-02/03/04 产物"],
            outputs=["audit report", "run manifest", "review backlog report"],
            depends_on=["WU-02", "WU-03", "WU-04", "WU-05", "WU-06", "WU-07"],
            file_scope=["pipeline_v2/audit.py", "pipeline_v2/cli.py", "tests/unit/test_pipeline_v2_audit.py"],
            acceptance=[
                "能自动指出 Step2 失败、Step3 只跑本地规则、重复工具目录等现状问题。",
                "能输出下一步 work units、迁移状态和 cutover 风险清单。",
            ],
        ),
    ]
    review_contracts = [
        ManualReviewContract(
            stage="step2",
            review_root=str(root / "data" / "manual_reviews" / "step2"),
            required_fields=["record_id", "source_component_name", "selected_standard_name", "review_status", "manual_notes", "reviewed_at"],
            feedback_targets=["synonym_library.json", "component_matching_result.json"],
        ),
        ManualReviewContract(
            stage="step3",
            review_root=str(root / "data" / "manual_reviews" / "step3"),
            required_fields=["record_id", "row_id", "quantity_component", "calculation_item_code", "review_status", "manual_notes", "reviewed_at"],
            feedback_targets=["review queue", "final export"],
        ),
    ]
    cutover_gates = [
        CutoverGate(
            name="GATE-01 Shadow Run",
            metrics=[
                "Step1 baseline 文档必须产出完整 `chapter_index.json` 与 `table_regions.json`。",
                "Step2 必须加载全量附录章节，而不是默认首章。",
                "Step2/Step3 不得出现 schema 级请求错误或 `completed_local_only` 正式模式。",
            ],
            manual_checks=[
                "抽查 baseline 文档 10 个章节路径是否正确。",
                "确认 review queue 已为全部 `candidate_only/unmatched/conflict` 建立记录。",
            ],
            pass_rule="全部自动指标通过且人工抽查无阻断问题，V2 才可进入并行 shadow run。",
        ),
        CutoverGate(
            name="GATE-02 Default Cutover",
            metrics=[
                "baseline 文档上 `matched_rows` 不低于 v1 基线 198。",
                "`candidate_only + unmatched` 总量相对 v1 基线至少下降 20%，或全部进入可追踪 review queue。",
                "manual review ledger 必须可回放到 Step2/Step3 产物。",
            ],
            manual_checks=[
                "人工抽检不少于 50 行或总量 10%，取较大值。",
                "抽检准确率达到 90% 以上，且无系统性错配。",
            ],
            pass_rule="通过自动指标 + 抽检准确率门槛后，V2 才可替换旧主线为默认入口。",
        ),
    ]
    open_questions = [
        "Step 1 是否要在 v2 中保留“只导出附录”这个业务过滤，还是改为在 Step 2 侧做附录选择？",
        "Step 2 的人工修订结果是否要回写成长期 synonym memory，还是按标准文档隔离存储？",
        "Step 3 的最终业务交付格式是继续保持 JSON/Markdown，还是补一个可导入业务系统的规范化表结构？",
    ]
    legacy_boundary = [
        "legacy/",
        "分析工具/构件类型-属性/",
        "../构件类型-属性/",
    ]
    return RedesignPlan(
        title="国标解析主流程 V2 重构方案",
        summary="以隔离旧代码、重建运行工作区、显式化批处理状态为核心，把 Step 1/2/3 重做成可审计、可恢复、可人工复核的流水线。",
        legacy_boundary=legacy_boundary,
        new_workspace_root=new_workspace_root,
        workflow=workflow,
        work_units=work_units,
        review_contracts=review_contracts,
        cutover_gates=cutover_gates,
        open_questions=open_questions,
    )


def render_markdown_report(audit: ProjectAudit, plan: RedesignPlan) -> str:
    lines: List[str] = []
    lines.append("# 国标解析项目 V2 审计与重构建议")
    lines.append("")
    lines.append("## 审计摘要")
    lines.append("")
    lines.append(f"- 项目根目录：`{audit.project_root}`")
    lines.append(f"- 生成时间：`{audit.generated_at}`")
    lines.append("")
    lines.append("### 当前阶段状态")
    lines.append("")
    for step in audit.steps:
        details = ", ".join(f"{key}={value}" for key, value in step.details.items() if value not in ("", None, 0))
        suffix = f" ({details})" if details else ""
        lines.append(f"- `{step.name}`: `{step.status.value}`{suffix}")
    lines.append("")
    lines.append("### 主要问题")
    lines.append("")
    if audit.issues:
        for issue in audit.issues:
            lines.append(f"- [{issue.severity.value}] `{issue.code}`: {issue.summary}")
            lines.append(f"  - 建议：{issue.recommendation}")
            if issue.evidence:
                lines.append(f"  - 证据：{' | '.join(issue.evidence)}")
    else:
        lines.append("- 当前未发现阻断问题。")
    lines.append("")
    lines.append("## V2 流程")
    lines.append("")
    for item in plan.workflow:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Work Units")
    lines.append("")
    for unit in plan.work_units:
        lines.append(f"### {unit.identifier} {unit.title}")
        lines.append(f"- Owner: {unit.owner}")
        lines.append(f"- Goal: {unit.goal}")
        lines.append(f"- Inputs: {', '.join(unit.inputs)}")
        lines.append(f"- Outputs: {', '.join(unit.outputs)}")
        lines.append(f"- Depends on: {', '.join(unit.depends_on) if unit.depends_on else '无'}")
        lines.append(f"- File scope: {', '.join(unit.file_scope)}")
        lines.append("- Acceptance:")
        for item in unit.acceptance:
            lines.append(f"  - {item}")
        lines.append("")
    lines.append("## Legacy Boundary")
    lines.append("")
    for item in plan.legacy_boundary:
        lines.append(f"- `{item}`")
    lines.append("")
    lines.append("## Review Contracts")
    lines.append("")
    for contract in plan.review_contracts:
        lines.append(f"### {contract.stage}")
        lines.append(f"- Review root: {contract.review_root}")
        lines.append(f"- Required fields: {', '.join(contract.required_fields)}")
        lines.append(f"- Feedback targets: {', '.join(contract.feedback_targets)}")
        lines.append("")
    lines.append("## Cutover Gates")
    lines.append("")
    for gate in plan.cutover_gates:
        lines.append(f"### {gate.name}")
        lines.append("- Metrics:")
        for item in gate.metrics:
            lines.append(f"  - {item}")
        lines.append("- Manual checks:")
        for item in gate.manual_checks:
            lines.append(f"  - {item}")
        lines.append(f"- Pass rule: {gate.pass_rule}")
        lines.append("")
    lines.append("## Open Questions")
    lines.append("")
    for item in plan.open_questions:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)
