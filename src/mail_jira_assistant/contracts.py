from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Request(Strict):
    source_ref: str
    subject: str
    body: str
    knowledge: list[dict] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    direction: Literal["inbound", "outbound", "unknown"] = "unknown"
    identity: list[str] = Field(default_factory=list)
    context_version: int = 0
    recipients: str = ""
    cc: str = ""
    notes: list[dict] = Field(default_factory=list)
    open_actions: list[dict] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    projects: list[dict] = Field(default_factory=list)
    history_basis: int | None = None


class Evidence(Strict):
    source_ref: str
    segment_ref: str = "body"
    text: str


class Action(Strict):
    kind: Literal["todo", "performed", "waiting"] = "todo"
    description: str = Field(min_length=1, max_length=2000)
    assignee: str = "self"
    due_at: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    related_action_ids: list[int] = Field(default_factory=list)


class Classification(Strict):
    schema_version: Literal["1", "2"] = "2"
    response_expected: Literal["yes", "no", "unknown"]
    action_required: Literal["yes", "no", "unknown"]
    work_performed: Literal["yes", "no", "unknown"]
    waiting_for_others: Literal["yes", "no", "unknown"]
    review_required: bool
    evidence: list[Evidence]
    actions: list[Action] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    project_update_needed: Literal["yes", "no", "unknown"] = "unknown"
    update_kinds: list[str] = Field(default_factory=list)
    project_hints: list[str] = Field(default_factory=list)


class ProjectChange(Strict):
    project_id: int
    section: Literal[
        "overview", "progress", "issues", "decisions", "updates", "next_actions"
    ]
    kind: Literal[
        "todo",
        "decision",
        "progress",
        "schedule",
        "performed",
        "waiting",
        "issue",
        "project_metadata",
    ]
    operation: Literal["add", "update", "delete"] = "add"
    entry_id: int | None = None
    work_item_id: int | None = None
    work_title: str = Field(default="", max_length=300)
    detail: bool = False
    text: str = Field(min_length=1, max_length=5000)
    reason: str = Field(default="", max_length=2000)
    evidence: list[Evidence] = Field(min_length=1)
    action_id: int | None = None
    metadata_field: Literal["purpose", "owner", "state", "started_on"] | None = None


class ProjectUpdate(Strict):
    no_change: bool = False
    changes: list[ProjectChange] = Field(default_factory=list, max_length=50)


def validate_project_update(result, request):
    if result.no_change == bool(result.changes):
        raise ValueError("project_update_result_inconsistent")
    projects = {p["id"]: p for p in request.projects}
    for change in result.changes:
        p = projects.get(change.project_id)
        if not p:
            raise ValueError("project_target_not_linked")
        entries = {e["id"]: e for e in p["entries"]}
        if change.operation != "add" and change.entry_id not in entries:
            raise ValueError("project_entry_missing")
        if change.operation == "delete" and request.limitations:
            raise ValueError("project_delete_requires_complete_evidence")
        if change.operation == "add" and change.entry_id is not None:
            raise ValueError("project_add_has_target")
        if change.entry_id and entries[change.entry_id]["section"] != change.section:
            raise ValueError("project_section_mismatch")
        if change.work_item_id and change.work_item_id not in {
            w["id"] for w in p["work_items"]
        }:
            raise ValueError("project_work_item_mismatch")
        if change.action_id and change.action_id not in {
            a["id"] for a in request.open_actions
        }:
            raise ValueError("project_action_mismatch")
        if change.metadata_field:
            if change.section != "overview" or change.operation != "add":
                raise ValueError("project_metadata_operation_invalid")
            if change.metadata_field == "started_on":
                from datetime import date

                date.fromisoformat(change.text)
        for evidence in change.evidence:
            if (
                evidence.source_ref != request.source_ref
                or evidence.segment_ref != "body"
                or not evidence.text
                or evidence.text not in request.body
            ):
                raise ValueError("project_invalid_evidence")


class KnowledgeEvidence(Strict):
    ref: str
    excerpt: str = Field(min_length=1)
    applicable: bool
    conditions: list[str] = Field(default_factory=list)


class Draft(Strict):
    answer_mode: Literal["technical_answer", "clarification_request", "internal_review"]
    subject: str
    body: str
    knowledge_refs: list[str]
    evidence: list[KnowledgeEvidence] = Field(default_factory=list)
    missing_information: list[str]
    limitations: list[str]


class AiRunner(Protocol):
    def classify(self, request: Request) -> Classification: ...
    def draft(self, request: Request) -> Draft: ...
    def project_update(self, request: Request) -> ProjectUpdate: ...


def validate_evidence(result, request):
    if not result.evidence:
        raise ValueError("missing_evidence")
    for e in result.evidence:
        if (
            e.source_ref != request.source_ref
            or e.segment_ref != "body"
            or not e.text
            or e.text not in request.body
        ):
            raise ValueError("invalid_evidence")
    allowed = {request.source_ref + "#body"}
    action_ids = {a["id"] for a in request.open_actions}
    for action in result.actions:
        if not set(action.related_action_ids) <= action_ids:
            raise ValueError("invalid_related_action")
        if not action.evidence_refs or not set(action.evidence_refs) <= allowed:
            raise ValueError("invalid_action_evidence")


def validate_draft(result, request):
    refs = {k["ref"] for k in request.knowledge}
    if not set(result.knowledge_refs) <= refs:
        raise ValueError("invalid_knowledge_reference")
    if result.answer_mode == "technical_answer" and (
        not result.knowledge_refs
        or request.limitations
        or request.missing_information
        or result.missing_information
    ):
        raise ValueError("insufficient_coverage")
    docs = {k["ref"]: k["text"] for k in request.knowledge}
    for evidence in result.evidence:
        if evidence.ref not in docs or evidence.excerpt not in docs[evidence.ref]:
            raise ValueError("invalid_knowledge_evidence")
    if result.answer_mode == "technical_answer":
        supported = {e.ref for e in result.evidence if e.applicable and e.conditions}
        if not set(result.knowledge_refs) <= supported:
            raise ValueError("unverified_knowledge_applicability")
