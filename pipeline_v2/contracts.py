from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


class StepStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"
    MISSING = "missing"


@dataclass
class AuditIssue:
    code: str
    severity: Severity
    summary: str
    recommendation: str
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["severity"] = self.severity.value
        return payload


@dataclass
class StepSnapshot:
    name: str
    status: StepStatus
    source_path: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


@dataclass
class WorkUnit:
    identifier: str
    title: str
    owner: str
    goal: str
    inputs: List[str]
    outputs: List[str]
    depends_on: List[str]
    file_scope: List[str]
    acceptance: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ManualReviewContract:
    stage: str
    review_root: str
    required_fields: List[str]
    feedback_targets: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CutoverGate:
    name: str
    metrics: List[str]
    manual_checks: List[str]
    pass_rule: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectAudit:
    project_root: str
    generated_at: str
    duplicate_paths: List[str] = field(default_factory=list)
    steps: List[StepSnapshot] = field(default_factory=list)
    issues: List[AuditIssue] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_root": self.project_root,
            "generated_at": self.generated_at,
            "duplicate_paths": list(self.duplicate_paths),
            "steps": [step.to_dict() for step in self.steps],
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass
class RedesignPlan:
    title: str
    summary: str
    legacy_boundary: List[str]
    new_workspace_root: str
    workflow: List[str]
    work_units: List[WorkUnit]
    review_contracts: List[ManualReviewContract]
    cutover_gates: List[CutoverGate]
    open_questions: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "legacy_boundary": list(self.legacy_boundary),
            "new_workspace_root": self.new_workspace_root,
            "workflow": list(self.workflow),
            "work_units": [unit.to_dict() for unit in self.work_units],
            "review_contracts": [contract.to_dict() for contract in self.review_contracts],
            "cutover_gates": [gate.to_dict() for gate in self.cutover_gates],
            "open_questions": list(self.open_questions),
        }


# ─────────────────── Step5: Feature Audit ───────────────────


class AuditStatus(str, Enum):
    PENDING = "pending"
    TO_FILL = "to-fill"
    NO_NEED = "no-need"
    TO_CONFIRM = "to-confirm"
    MATCH_FAIL_WIKI = "match-fail-wiki"


class MatchType(str, Enum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    INTERMITTENT = "intermittent"


@dataclass
class FeatureAuditItem:
    """Aggregated feature item for Step5 audit (source_component|label key)."""
    item_key: str
    source_component: str
    label: str
    match_type: MatchType
    occurrence_count: int
    matched_count: int = 0
    unmatched_count: int = 0
    attribute_name: str = ""
    attribute_code: str = ""
    value_samples: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["match_type"] = self.match_type.value
        return payload


@dataclass
class WikiKnowledgePatch:
    """Export format for wiki_patch_import.py compatibility."""
    component_type: str
    attribute_name: str
    attribute_code: str
    value_pattern: str
    source: str = "step5-audit"
    action: str = "add"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
