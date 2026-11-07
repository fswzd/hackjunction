"""Application DTOs and role contracts ported from the included v1.1 design.

Pure cross-field checks run here. Ownership checks require repository context
and use the explicit functions in errors.py.
"""
from datetime import datetime, timezone
from typing import Generic, Literal, TypeVar, Annotated
from pydantic import BaseModel, BeforeValidator, AfterValidator, ConfigDict, Field, StringConstraints, model_validator


def require_true(value):
    if type(value) is not bool or value is not True:
        raise ValueError("explicit boolean true is required")
    return value


Confirmed = Annotated[Literal[True], BeforeValidator(require_true)]

Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")]
Hash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Text = Annotated[str, StringConstraints(min_length=1, max_length=20000)]
Short = Annotated[str, StringConstraints(min_length=1, max_length=1000)]
def valid_utc_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be a valid UTC date") from exc
    if parsed.tzinfo != timezone.utc:
        raise ValueError("timestamp must be UTC")
    return value


Timestamp = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"), AfterValidator(valid_utc_timestamp)]
TaskState = Literal["DRAFT", "PLANNING", "WAITING_CONFIRMATION", "QUEUED", "GENERATING", "VALIDATING", "REVISING", "EXPORTING", "READY", "ACCEPTED", "WAITING_INPUT", "NEEDS_REVIEW", "FAILED", "INTERRUPTED", "CANCELLED"]
RunState = Literal["QUEUED", "RUNNING", "WAITING", "SUCCEEDED", "FAILED", "INTERRUPTED", "CANCELLED"]
PreviewState = Literal["QUEUED", "RUNNING", "COMPLETED", "CANCELLED", "FAILED", "INTERRUPTED", "INCOMPLETE"]
ErrorCode = Literal["SCHEMA_INVALID", "VERSION_CONFLICT", "SCOPE_DENIED", "INPUT_MISSING", "MODEL_TIMEOUT", "MODEL_UNAVAILABLE", "MODEL_REJECTED", "BUDGET_EXCEEDED", "ARTIFACT_MISSING", "INTERRUPTED", "OUTPUT_TOO_LARGE", "NOT_FOUND", "IDEMPOTENCY_CONFLICT", "INVALID_TRANSITION", "CONDITIONS_MISMATCH", "STORAGE_UNAVAILABLE", "SESSION_REQUIRED", "ORIGIN_DENIED"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Question(Model):
    id: Id
    question: Short
    reason: Short


class Issue(Model):
    id: Id
    severity: Literal["blocking", "advisory"]
    location: Short
    reason: Short
    requested_change: Short


class Requirement(Model):
    id: Id
    text: Short


class LengthRule(Model):
    minimum: int | None = Field(default=None, ge=0, le=20000)
    maximum: int | None = Field(default=None, ge=1, le=20000)


class EditScope(Model):
    target_segment_ids: list[Id] = Field(max_length=32)
    preserve_segment_ids: list[Id] = Field(max_length=32)
    allow_title_change: bool
    allow_cover_change: bool

    @model_validator(mode="after")
    def disjoint_segments(self):
        targets, preserved = self.target_segment_ids, self.preserve_segment_ids
        if len(targets) != len(set(targets)) or len(preserved) != len(set(preserved)):
            raise ValueError("edit scope segment IDs must be unique")
        if set(targets) & set(preserved):
            raise ValueError("target and preserve segments must not overlap")
        return self


class Brief(Model):
    input_mode: Literal["idea", "existing_draft"]
    objective: Short
    audience: Short
    platform: Short
    format: Literal["text"]
    core_promise: Short
    requirements: list[Requirement] = Field(min_length=1, max_length=30)
    material_ids: list[Id] = Field(max_length=20)
    open_questions: list[Question] = Field(max_length=20)
    route: list[Literal["research", "draft", "review", "preview", "revise", "export"]] = Field(max_length=6)
    length_rule: LengthRule
    edit_scope: EditScope | None

    @model_validator(mode="after")
    def coherent_brief(self):
        if len({r.id for r in self.requirements}) != len(self.requirements):
            raise ValueError("requirement IDs must be unique")
        if len({q.id for q in self.open_questions}) != len(self.open_questions):
            raise ValueError("question IDs must be unique")
        if len(set(self.route)) != len(self.route):
            raise ValueError("route steps must be unique")
        if self.input_mode == "idea" and self.edit_scope is not None:
            raise ValueError("idea mode cannot have edit_scope")
        if self.input_mode == "existing_draft" and self.edit_scope is None:
            raise ValueError("existing_draft requires edit_scope")
        if self.length_rule.minimum is not None and self.length_rule.maximum is not None and self.length_rule.minimum > self.length_rule.maximum:
            raise ValueError("length minimum exceeds maximum")
        return self


class Segment(Model):
    segment_id: Id
    kind: Literal["hook", "body", "closing"]
    text: str = Field(max_length=20000)
    source_refs: list[Id] = Field(max_length=20)


class ContentCandidate(Model):
    # Recoverable completeness failures go to deterministic business rules.
    titles: list[str] = Field(max_length=10)
    cover_copy: str | None = Field(default=None, max_length=1000)
    segments: list[Segment] = Field(max_length=32)


class ContentDelivery(Model):
    titles: list[Short] = Field(min_length=3, max_length=3)
    cover_copy: Short
    segments: list[Segment] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def complete_content(self):
        if any(not title.strip() for title in self.titles) or not self.cover_copy.strip():
            raise ValueError("titles and cover must contain text")
        if not any(segment.kind == "body" and segment.text.strip() for segment in self.segments):
            raise ValueError("at least one nonempty body segment is required")
        ids = [segment.segment_id for segment in self.segments]
        if len(ids) != len(set(ids)) or set(ids) & {"titles", "cover"}:
            raise ValueError("body segment IDs must be unique and not reserved")
        return self


class RequirementCheck(Model):
    requirement_id: Id
    result: Literal["met", "unmet", "unknown"]
    evidence_refs: list[Id] = Field(max_length=32)


class ClaimCheck(Model):
    claim: Short
    location: Id
    source_ref: Id | None
    assessment: Literal["supported", "unsupported", "uncertain", "personal_experience"]


class EditorialReview(Model):
    issues: list[Issue] = Field(max_length=30)
    requirement_checks: list[RequirementCheck] = Field(max_length=30)
    claim_checks: list[ClaimCheck] = Field(max_length=50)
    overall: Literal["pass", "revise", "needs_input"]


class Opportunity(Model):
    id: Id
    angle: Short
    audience_problem: Short
    account_fit: Short
    source_refs: list[Id] = Field(max_length=20)
    evidence_date: Timestamp | None
    hypothesis: Short


class OpportunitySet(Model):
    opportunities: list[Opportunity] = Field(max_length=3)


class Persona(Model):
    id: Id
    goal: Short
    knowledge: Short
    preferences: list[Short] = Field(max_length=10)


class VisibleSegment(Model):
    segment_id: Id
    kind: Literal["cover", "hook", "body", "closing"]
    text: Text


class AudienceEvent(Model):
    segment_id: Id
    action: Literal["continue", "exit"]
    understanding: str = Field(max_length=1000)
    question: str | None = Field(max_length=1000)
    reaction: str = Field(max_length=1000)
    interactions: list[Literal["like", "comment", "save"]] = Field(max_length=3)
    comment_text: str | None = Field(max_length=1000)


class AudienceInput(Model):
    persona: Persona
    current_segment: VisibleSegment
    visible_history: list[VisibleSegment] = Field(max_length=7)
    own_previous_reactions: list[AudienceEvent] = Field(max_length=7)


class Finding(Model):
    id: Id
    segment_id: Id
    observation_refs: list[Id] = Field(min_length=1, max_length=50)
    interpretation: Short
    alternative_explanation: Short
    suggested_edit: Short


class ComparisonConclusion(Model):
    conditions_match: bool
    reason: Short
    summary: Short


class Analysis(Model):
    findings: list[Finding] = Field(max_length=10)
    comparison: ComparisonConclusion
    next_experiment: Short


class Change(Model):
    finding_id: Id | None
    issue_id: Id | None
    old_segment_id: Id
    new_segment_id: Id
    change: Literal["replace", "delete", "insert_after", "move", "metadata_update"]
    reason: Short

    @model_validator(mode="after")
    def coherent_change(self):
        if (self.finding_id is None) == (self.issue_id is None):
            raise ValueError("exactly one finding_id or issue_id is required")
        old, new = self.old_segment_id, self.new_segment_id
        if self.change == "metadata_update":
            if old != new or old not in {"titles", "cover"}:
                raise ValueError("metadata_update requires matching reserved IDs")
        elif old in {"titles", "cover"} or new in {"titles", "cover"}:
            raise ValueError("body change cannot use metadata IDs")
        elif self.change in {"replace", "insert_after"} and old == new:
            raise ValueError("replace and insert_after require a new segment ID")
        elif self.change in {"delete", "move"} and old != new:
            raise ValueError("delete and move must retain the segment ID")
        return self


class Revision(ContentCandidate):
    change_log: list[Change] = Field(min_length=1, max_length=32)


T = TypeVar("T")


class Envelope(Model, Generic[T]):
    schema_version: Literal["creator-agent.v1"]
    status: Literal["ok", "needs_input", "error"]
    summary: Short
    data: T | None
    evidence_refs: list[Id] = Field(max_length=64)
    questions: list[Question] = Field(max_length=20)
    issues: list[Issue] = Field(max_length=30)

    @model_validator(mode="after")
    def coherent_status(self):
        if self.status == "ok" and (self.data is None or self.questions or self.issues):
            raise ValueError("ok requires data and no questions or issues")
        if self.status == "needs_input" and not self.questions:
            raise ValueError("needs_input requires a question")
        if self.status == "error" and not self.issues:
            raise ValueError("error requires an issue")
        return self


class ErrorDetail(Model):
    code: ErrorCode
    retryable: bool
    cause_hint: Short
    next_action: Short
    field_errors: list[Short] = Field(max_length=30)
    current_row_version: int | None = Field(ge=0)


class ApiSuccess(Model, Generic[T]):
    data: T
    request_id: Id


class ApiFailure(Model):
    error: ErrorDetail
    request_id: Id


class MaterialInput(Model):
    kind: Literal["user_supplied_experience", "source_text", "existing_draft"]
    label: Short
    text: Text
    source_url: str | None = Field(default=None, max_length=2000)
    authorized: Confirmed


class CreateTask(Model):
    account_id: Id
    input_mode: Literal["idea", "existing_draft"]
    objective: Short
    audience: Short
    platform: Short = "generic"
    format: Literal["text"] = "text"
    style: Short
    requirements: list[Requirement] = Field(min_length=1, max_length=30)
    materials: list[MaterialInput] = Field(max_length=20)
    preview_requested: bool = False
    length_rule: LengthRule

    @model_validator(mode="after")
    def coherent_input(self):
        if len({r.id for r in self.requirements}) != len(self.requirements):
            raise ValueError("requirement IDs must be unique")
        drafts = sum(material.kind == "existing_draft" for material in self.materials)
        # A missing draft is a valid task intake and becomes WAITING_INPUT.
        # More than one draft is ambiguous and cannot be planned safely.
        if self.input_mode == "existing_draft" and drafts > 1:
            raise ValueError("existing_draft accepts at most one draft material")
        if self.input_mode == "idea" and drafts:
            raise ValueError("idea mode cannot include existing_draft material")
        return self


class Expected(Model):
    expected_row_version: int = Field(ge=0)


class ConfirmBrief(Expected):
    expected_brief_version: int = Field(ge=1)
    brief_hash: Hash


class UpdateInput(Expected):
    answers: dict[Id, Short]
    materials: list[MaterialInput] = Field(max_length=20)


class EditBrief(Expected):
    expected_brief_version: int = Field(ge=1)
    brief: Brief


class Resume(Expected):
    strategy: Literal["continue_checkpoint", "reissue_unknown"]
    acknowledged_unknown_charge: bool


class AcceptVersion(Expected):
    version_id: Id
    content_hash: Hash


class ExportVersion(Expected):
    version_id: Id
    content_hash: Hash
    formats: list[Literal["md", "txt"]] = Field(min_length=1, max_length=2)


class FeedbackCreate(Model):
    version_id: Id
    kind: Literal["accept", "reject", "edit_request", "real_platform_feedback"]
    text: Short
    platform: Short | None
    window_start: Timestamp | None
    window_end: Timestamp | None
    metrics: dict[str, float | int | None]
    source_ref: Short | None

    @model_validator(mode="after")
    def ordered_window(self):
        if self.window_start and self.window_end and datetime.fromisoformat(self.window_start.replace("Z", "+00:00")) > datetime.fromisoformat(self.window_end.replace("Z", "+00:00")):
            raise ValueError("feedback window start exceeds end")
        return self


class OrderCreate(Model):
    task_id: Id
    origin: Literal["trial", "simulation", "real"]
    amount_minor: int = Field(ge=0)
    currency: Literal["CNY"]


class ReceiptCreate(Expected):
    amount_minor: int = Field(gt=0)
    currency: Literal["CNY"]
    evidence_ref: Short
    confirm_received: Confirmed


class OperatorUnlock(Model):
    token: Short


class AccountCreate(Model):
    name: Short


class MemoryCreate(Model):
    kind: Literal["user_preference", "observed_feedback", "simulation_hypothesis"]
    statement: Short
    source_ref: Id
    observed_at: Timestamp
    applicability: Short
    supersedes_id: Id | None


class MemoryDecision(Expected):
    action: Literal["correct", "withdraw"]
    statement: Short | None
    confirm: Confirmed


class Scenario(Model):
    medium: Literal["text"]
    segmenter_version: Literal["paragraph-v1"]
    personas: list[Persona] = Field(min_length=1, max_length=6)
    max_segments: int = Field(ge=2, le=8)
    requested_seed: int | None


class PreviewSpec(Model):
    version_id: Id
    content_hash: Hash
    scenario: Scenario


class PreviewCreate(PreviewSpec):
    expected_conditions_hash: Hash
    expected_scenario_hash: Hash


class VersionTarget(Model):
    version_id: Id
    content_hash: Hash


class ExperimentSpec(Model):
    left: VersionTarget
    right: VersionTarget
    scenario: Scenario


class ExperimentCreate(ExperimentSpec):
    expected_conditions_hash: Hash
    expected_scenario_hash: Hash


class RevisionRequest(Model):
    expected_head_version_id: Id
    base_version_id: Id
    base_content_hash: Hash
    analysis_id: Id
    finding_ids: list[Id] = Field(min_length=1, max_length=10)
    instructions: Short | None
    allow_title_change: bool
    allow_cover_change: bool


class RestoreHead(Expected):
    expected_head_version_id: Id
    target_version_id: Id
    target_content_hash: Hash
    confirm: Confirmed


class ActionContext(Model):
    operator_id: Id
    account_id: Id
    task_id: Id
    run_id: Id | None
    lease_epoch: int | None = Field(ge=0)
    confirmed_brief_hash: Hash | None
    allowed_refs: list[Id]
    allowed_actions: list[Literal["read_material", "read_version", "save_version", "validate_content", "run_preview", "export_artifact", "record_feedback"]]


class ReadMaterialArgs(Model):
    ids: list[Id] = Field(min_length=1, max_length=20)


class ReadVersionArgs(Model):
    id: Id


class SaveVersionArgs(Model):
    content: ContentCandidate | Revision
    parent_id: Id | None


class ValidateContentArgs(Model):
    version: Id


class RunPreviewArgs(Model):
    version: Id
    scenario: Scenario
    expected_conditions_hash: Hash
    expected_scenario_hash: Hash


class ExportArtifactArgs(Model):
    version: Id


class RecordFeedbackArgs(Model):
    version: Id
    feedback: FeedbackCreate


class ToolError(Model):
    code: ErrorCode
    retryable: bool
    cause_hint: Short
    next_action: Short
    stop_condition: Short


class ToolResult(Model, Generic[T]):
    status: Literal["success", "warning", "error"]
    summary: Short
    next_actions: list[Short]
    artifacts: list["EntityRef"]
    data: T | None
    error: ToolError | None


class CompareCreate(Model):
    left_preview_id: Id
    right_preview_id: Id
    allow_descriptive_mismatch: bool


class ScoutRequest(Model):
    task_id: Id
    material_ids: list[Id] = Field(min_length=1, max_length=20)


class EntityRef(Model):
    id: Id
    kind: Short


class Usage(Model):
    calls_reserved: int = Field(ge=0)
    calls_completed: int = Field(ge=0)
    input_tokens: int | None = Field(ge=0)
    output_tokens: int | None = Field(ge=0)
    total_tokens: int | None = Field(ge=0)
    unknown_calls: int = Field(ge=0)
    cost_status: Literal["known", "partial", "unknown", "unpriced"]
    amount_minor: int | None = Field(ge=0)
    currency: Literal["CNY"] | None


class TaskSummary(Model):
    task_id: Id
    account_id: Id
    state: TaskState
    row_version: int = Field(ge=0)
    current_run_id: Id
    brief_version: int | None
    head_version_id: Id | None
    ready_version_id: Id | None
    accepted_version_id: Id | None
    pending_action: Short | None
    queue_position: int | None = Field(ge=1)
    mode: Literal["mock", "live"]
    usage: Usage
    error: ErrorDetail | None


class BriefRead(Model):
    task_id: Id
    brief_version: int = Field(ge=1)
    brief_hash: Hash
    confirmed: bool
    brief: Brief


class RuleResult(Model):
    rule_id: Id
    passed: bool
    reason: Short
    segment_id: Id | None


class RuleReport(Model):
    version_id: Id
    content_hash: Hash
    rule_version: Literal["content-rules-v1"]
    passed: bool
    body_characters: int = Field(ge=0)
    checks: list[RuleResult]


class VersionRead(Model):
    version_id: Id
    task_id: Id
    ordinal: int = Field(ge=1)
    parent_version_id: Id | None
    brief_hash: Hash
    content_hash: Hash
    content: ContentCandidate
    rule_report: RuleReport | None
    editorial_review: EditorialReview | None
    validation: Literal["pending", "invalid", "passed", "needs_input"]


class TaskEvent(Model):
    event_id: Id
    seq: int = Field(ge=1)
    run_id: Id
    type: Short
    step: Short
    state: TaskState
    summary: Short
    created_at: Timestamp


class EventPage(Model):
    items: list[TaskEvent]
    next_after_seq: int = Field(ge=0)
    has_more: bool


class ArtifactRead(Model):
    artifact_id: Id
    version_id: Id
    content_hash: Hash
    file_hash: Hash
    format: Literal["md", "txt"]
    byte_size: int = Field(ge=1)
    status: Literal["available", "missing", "corrupt"]
    download_url: Short | None


class AccountRead(Model):
    account_id: Id
    name: Short
    row_version: int = Field(ge=0)


class MaterialRead(Model):
    material_id: Id
    account_id: Id
    task_id: Id
    kind: Literal["user_supplied_experience", "source_text", "existing_draft"]
    label: Short
    text: Text
    source_url: str | None
    content_hash: Hash


class FeedbackRead(FeedbackCreate):
    feedback_id: Id
    account_id: Id
    task_id: Id
    created_at: Timestamp
    evidence_kind: Literal["user_statement", "real_feedback_unverified"]


class OrderRead(Model):
    order_id: Id
    task_id: Id
    origin: Literal["trial", "simulation", "real"]
    amount_minor: int = Field(ge=0)
    currency: Literal["CNY"]
    payment_state: Literal["not_applicable", "unpaid", "confirmed"]
    row_version: int = Field(ge=0)
    receipt_id: Id | None


class ReceiptRead(Model):
    receipt_id: Id
    order_id: Id
    amount_minor: int = Field(gt=0)
    currency: Literal["CNY"]
    evidence_ref: Short
    confirmed_by_session: Id
    confirmed_at: Timestamp


class MemoryRead(MemoryCreate):
    memory_id: Id
    account_id: Id
    status: Literal["active", "superseded", "withdrawn"]
    row_version: int = Field(ge=0)


class ScoutRead(Model):
    scout_id: Id
    task_id: Id
    state: RunState
    opportunities: OpportunitySet | None
    evidence_kind: Literal["provided_materials_only"]


class SessionRead(Model):
    session_id: Id
    csrf_token: Short
    capabilities: list[Literal["creator", "operator"]]


class SegmentMetric(Model):
    segment_id: Id
    exposures: int = Field(ge=0)
    exits: int = Field(ge=0)
    exit_rate: float | None = Field(ge=0, le=1)


class Metrics(Model):
    selected_sessions: int = Field(ge=0)
    started: int = Field(ge=0)
    completed: int = Field(ge=0)
    exited: int = Field(ge=0)
    incomplete: int = Field(ge=0)
    no_event_sessions: int = Field(ge=0)
    coverage_ratio: float | None = Field(ge=0, le=1)
    completion_ratio: float | None = Field(ge=0, le=1)
    interaction_sessions: dict[Literal["like", "comment", "save"], int]
    interaction_ratios: dict[Literal["like", "comment", "save"], float | None]
    segments: list[SegmentMetric]


class StoredAudienceEvent(Model):
    event_id: Id
    preview_id: Id
    session_id: Id
    version_id: Id
    seq: int = Field(ge=0)
    created_at: Timestamp
    event: AudienceEvent


class AudienceEventPage(Model):
    items: list[StoredAudienceEvent]
    next_after_seq: int = Field(ge=0)
    has_more: bool


class SessionSummary(Model):
    session_id: Id
    persona_id: Id
    cursor: int = Field(ge=0)
    outcome: Literal["pending", "active", "completed", "exited", "incomplete"]
    stop_reason: Short | None


class PreviewRead(Model):
    preview_id: Id
    task_id: Id
    version_id: Id
    content_hash: Hash
    scenario_hash: Hash
    conditions_hash: Hash
    state: PreviewState
    row_version: int = Field(ge=0)
    sessions: list[SessionSummary]
    started_at: Timestamp | None
    finished_at: Timestamp | None
    metrics: Metrics | None
    analysis_id: Id | None
    analysis_status: Literal["pending", "succeeded", "failed", "skipped"]
    usage: Usage
    error: ErrorDetail | None


class PreflightRead(Model):
    eligible: bool
    segment_count: int = Field(ge=0)
    persona_count: int = Field(ge=0)
    estimated_total_tokens: int = Field(ge=0)
    estimated_calls: int = Field(ge=0)
    scenario_hash: Hash
    conditions_hash: Hash
    reasons: list[Short]
    alternatives: list[Scenario]


class ExperimentPreflightRead(Model):
    eligible: bool
    left: PreflightRead
    right: PreflightRead
    total_estimated_calls: int = Field(ge=0)
    total_estimated_tokens: int = Field(ge=0)


class ExperimentRead(Model):
    experiment_id: Id
    task_id: Id
    left_preview_id: Id
    right_preview_id: Id
    planned_execution_order: list[Id] = Field(min_length=2, max_length=2)
    actual_execution_order: list[Id] = Field(max_length=2)
    conditions_hash: Hash
    scenario_hash: Hash
    created_at: Timestamp


class AnalysisRead(Model):
    analysis_id: Id
    preview_id: Id
    version_id: Id
    analysis: Analysis


class RevisionRead(Model):
    revision_id: Id
    task_id: Id
    base_version_id: Id
    run_id: Id
    state: RunState
    row_version: int = Field(ge=0)
    output_version_id: Id | None
    pending_action: Short | None
    error: ErrorDetail | None


class ComparisonRead(Model):
    comparison_id: Id
    left_preview_id: Id
    right_preview_id: Id
    conditions_match: bool
    differences: list[Short]
    aligned_segments: list["AlignedSegment"]
    left_metrics: Metrics
    right_metrics: Metrics
    left_sessions: list[SessionSummary]
    right_sessions: list[SessionSummary]
    left_usage: Usage
    right_usage: Usage
    left_state: PreviewState
    right_state: PreviewState
    planned_execution_order: list[Id] | None
    actual_execution_order: list[Id]
    order_note: Short
    evidence_kind: Literal["simulation"]


class AlignedSegment(Model):
    left_segment_id: Id | None
    right_segment_id: Id | None
    relation: Literal["unchanged", "replaced", "moved", "left_only", "right_only"]


ROLE_MODELS = {
    "operator": Envelope[Brief], "scout": Envelope[OpportunitySet],
    "director": Envelope[ContentCandidate], "editorial-reviewer": Envelope[EditorialReview],
    "audience": Envelope[AudienceEvent], "analyst": Envelope[Analysis],
    "revision": Envelope[Revision],
}

TOOL_MODELS = {
    "read_material": ToolResult[list[MaterialRead]],
    "read_version": ToolResult[VersionRead],
    "save_version": ToolResult[VersionRead],
    "validate_content": ToolResult[RuleReport],
    "run_preview": ToolResult[PreviewRead],
    "export_artifact": ToolResult[list[ArtifactRead]],
    "record_feedback": ToolResult[FeedbackRead],
}
