"""Typed domain failures; API adapters map these to the shared error envelope."""
from dataclasses import dataclass

from .schemas import AudienceEvent, Brief, ContentCandidate, ErrorCode, ErrorDetail


@dataclass
class DomainError(Exception):
    code: ErrorCode
    cause_hint: str
    next_action: str
    retryable: bool = False
    current_row_version: int | None = None
    field_errors: tuple[str, ...] = ()

    def detail(self) -> ErrorDetail:
        return ErrorDetail(
            code=self.code,
            retryable=self.retryable,
            cause_hint=self.cause_hint,
            next_action=self.next_action,
            field_errors=list(self.field_errors),
            current_row_version=self.current_row_version,
        )


def require_owned_refs(refs: set[str], allowed_refs: set[str]) -> None:
    """Repository calls this after loading account/task ownership in one transaction."""
    if not refs <= allowed_refs:
        raise DomainError("SCOPE_DENIED", "Reference outside current task scope", "Reload the task and choose its own materials")


def validate_brief_scope(brief: Brief, *, material_kinds: dict[str, str], existing_segment_ids: set[str], p0_only: bool = True) -> None:
    """Call after repository ownership lookup; no database access occurs here."""
    require_owned_refs(set(brief.material_ids), set(material_kinds))
    if brief.input_mode == "existing_draft":
        drafts = [ref for ref in brief.material_ids if material_kinds[ref] == "existing_draft"]
        if len(drafts) != 1:
            raise DomainError("INPUT_MISSING", "Exactly one existing draft is required", "Select one authorized draft")
        scope = brief.edit_scope
        assert scope is not None
        require_owned_refs(set(scope.target_segment_ids + scope.preserve_segment_ids), existing_segment_ids)
    if p0_only and set(brief.route) - {"draft", "review", "export"}:
        raise DomainError("SCOPE_DENIED", "Route contains a disabled step", "Choose a P0 content route")


def validate_candidate_scope(candidate: ContentCandidate, *, allowed_material_ids: set[str]) -> None:
    for segment in candidate.segments:
        require_owned_refs(set(segment.source_refs), allowed_material_ids)


def validate_audience_scope(event: AudienceEvent, *, current_segment_id: str, visible_segment_ids: set[str]) -> None:
    if event.segment_id != current_segment_id or event.segment_id not in visible_segment_ids:
        raise DomainError("SCOPE_DENIED", "Audience event refers to an unseen segment", "Use only the current visible segment")
