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
    schema_version: Literal["1"] = "1"
    response_expected: Literal["yes", "no", "unknown"]
    action_required: Literal["yes", "no", "unknown"]
    work_performed: Literal["yes", "no", "unknown"]
    waiting_for_others: Literal["yes", "no", "unknown"]
    review_required: bool
    evidence: list[Evidence]
    actions: list[Action] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


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
