"""Deterministic program steps: rule checks (content-rules-v1), preview metrics
and scoped-revision validation.  These are code, not model calls (zero budget).

Rule semantics (interaction design §2): a schema-valid candidate missing
cover/titles is a fixable rule failure — save and repair; unparseable/typed
garbage is a technical error handled by the gateway, never a rule failure.

Rules now share the business single source (validate_content_rules /
validate_scoped_revision).  The pre-refactor public surface below is kept for
compatibility with existing importers.
"""
from __future__ import annotations

from pydantic import ValidationError

from backend.agents.director import validate_scoped_revision
from backend.domain.errors import DomainError
from backend.domain.schemas import ContentCandidate, LengthRule, Revision
from backend.simulation.analysis_data import summarize_sessions
from backend.validators.content import validate_content_rules
from .repository import object_hash


class RuleFailure(Exception):
    """Structural failure that is NOT a fixable candidate (e.g. no segments at all).

    Kept as the pre-refactor public type; the shared rule layer reports such
    cases through the RuleReport DTO instead of raising.
    """

    def __init__(self, rule_id: str, reason: str):
        super().__init__(reason)
        self.rule_id = rule_id
        self.reason = reason


def _non_whitespace_len(text: str) -> int:
    """Kept as the pre-refactor helper for existing importers."""
    return sum(1 for ch in text if not ch.isspace())


def run_rules(version_id: str, candidate: dict, length_rule: dict | None = None) -> dict:
    """Use the director and reviewer rules for the same confirmed length range."""
    content = ContentCandidate.model_validate({k: candidate[k] for k in ("titles", "cover_copy", "segments")
                                               if k in candidate})
    report = validate_content_rules(version_id, content, LengthRule.model_validate(length_rule or {}))
    # Workflow versions bind the full persisted payload, including revision lineage.
    return {**report.model_dump(mode="json"), "content_hash": object_hash(candidate)}


def failed_checks(report: dict) -> list[dict]:
    return [c for c in report["checks"] if not c["passed"]]


def normalized_sessions(session_rows: list[dict], event_rows: list[dict]) -> list[dict]:
    events_by_session: dict[str, list[dict]] = {}
    for row in event_rows:
        events_by_session.setdefault(row["session_id"], []).append(
            {"event_id": row["id"], "event": row["payload"]})
    return [{"session_id": row["id"], "persona_id": row.get("persona_id"),
             "outcome": row["status"] if row["status"] in ("completed", "exited") else "incomplete",
             "events": events_by_session.get(row["id"], [])} for row in session_rows]


def project_metrics(metrics: dict) -> dict:
    """Keep the public workflow Metrics DTO while sharing the business math."""
    intentions = metrics["interaction_intentions"]
    return {"selected_sessions": metrics["N"], "started": metrics["S"], "completed": metrics["C"],
            "exited": metrics["exited"], "incomplete": metrics["U"], "no_event_sessions": metrics["Z"],
            "coverage_ratio": metrics["coverage_ratio"]["value"],
            "completion_ratio": metrics["completion_ratio"]["value"],
            "interaction_sessions": {key: value["numerator"] for key, value in intentions.items()},
            "interaction_ratios": {key: value["value"] for key, value in intentions.items()},
            "segments": [{"segment_id": s["segment_id"], "exposures": s["seen_sessions"],
                          "exits": s["exit_sessions"], "exit_rate": s["exit_rate"]["value"]}
                         for s in metrics["segments"]]}


def compute_metrics(session_rows: list[dict], event_rows: list[dict], segment_ids: list[str]) -> dict:
    return project_metrics(summarize_sessions(normalized_sessions(session_rows, event_rows), segment_ids))


def validate_revision(base_payload: dict, revision: dict,
                      allow_title_change: bool, allow_cover_change: bool,
                      finding_segment: dict[str, str],
                      issue_locations: dict[str, str]) -> None:
    """Apply the same change-log checks to workflow drafts and live edits."""
    locations = {("finding", key): ("cover" if value == "cover_v1" else value)
                 for key, value in finding_segment.items()}
    locations.update({("issue", key): value for key, value in issue_locations.items()})
    try:
        base = ContentCandidate.model_validate({k: base_payload[k] for k in ("titles", "cover_copy", "segments")
                                               if k in base_payload})
        validate_scoped_revision(base, Revision.model_validate(revision), locations,
                                 allow_title_change, allow_cover_change)
    except DomainError as exc:
        raise ScopeError([exc.cause_hint]) from None
    except ValidationError:
        raise ScopeError(["revision structure is invalid"]) from None


class ScopeError(Exception):
    code = "SCOPE_DENIED"

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems
