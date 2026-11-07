"""Role input projections and context-isolation assertions.

Each action receives only the projection its role owns (interaction design §5,
workflow-spec role_projection).  The simulated audience projection is exactly
the four AudienceInput fields and is scanned for future-segment / cross-session
leaks before the call is allowed.  No builder ever receives or forwards the
full GraphState, creator chat or model reasoning.
"""
from __future__ import annotations

from .contracts import sha256_hex, canonical_json
from .registry import LIMITS


class IsolationError(Exception):
    code = "SCOPE_DENIED"


def build_prepare_brief_input(user_input: str, input_mode: str, material_refs: list[dict],
                              selected_opportunity_ref: dict | None) -> dict:
    return {"user_input": user_input[:20000], "input_mode": input_mode,
            "material_refs": material_refs, "selected_opportunity_ref": selected_opportunity_ref}


def build_draft_input(brief_ref: dict, material_refs: list[dict]) -> dict:
    return {"brief_ref": brief_ref, "material_refs": material_refs}


def build_revise_input(brief_ref: dict, base_version_ref: dict, revision_request_ref: dict) -> dict:
    return {"brief_ref": brief_ref, "base_version_ref": base_version_ref,
            "revision_request_ref": revision_request_ref}


def build_assess_input(brief_ref: dict, version_ref: dict, rule_report_ref: dict,
                       material_refs: list[dict]) -> dict:
    """Editorial review sees: requirements(brief), materials, current candidate,
    rule report — never creator chat/self-eval (which do not exist in state)."""
    allowed = {"brief_ref", "version_ref", "rule_report_ref", "material_refs"}
    payload = {"brief_ref": brief_ref, "version_ref": version_ref,
               "rule_report_ref": rule_report_ref, "material_refs": material_refs}
    assert set(payload) == allowed
    return payload


def build_capture_input(goal: str, material_refs: list[dict]) -> dict:
    return {"goal": goal[:20000], "material_refs": material_refs}


def build_diagnose_input(preview_ref: dict, version_ref: dict, metrics_ref: dict) -> dict:
    return {"preview_ref": preview_ref, "version_ref": version_ref, "metrics_ref": metrics_ref}


def visible_segments(version_payload: dict) -> list[dict]:
    """Preview projection: cover + body segments, capped at 8 including cover."""
    segments = [{"segment_id": "cover_v1", "kind": "cover",
                 "text": version_payload.get("cover_copy") or "（无封面）"}]
    for seg in version_payload.get("segments", []):
        segments.append({"segment_id": seg["segment_id"], "kind": seg["kind"], "text": seg["text"]})
    return segments[:LIMITS["preview_segments_including_cover"]]


def build_audience_input(persona: dict, segments: list[dict], ordinal: int,
                         own_previous_events: list[dict]) -> dict:
    """Build the AudienceInput projection for one (session, ordinal) step.

    - visible_history: only segments this session already read (prefix, ≤7).
    - own_previous_reactions: only this session's own events (≤7).
    - future segments, other personas' reactions and creator goals never enter.
    """
    if ordinal >= len(segments):
        raise IsolationError(f"ordinal {ordinal} beyond last segment")
    history = segments[:ordinal]
    if len(history) > LIMITS["history_segments"]:
        raise IsolationError("visible_history exceeds history_segments limit")
    payload = {
        "persona": persona,
        "current_segment": segments[ordinal],
        "visible_history": history,
        "own_previous_reactions": own_previous_events[-LIMITS["history_segments"]:],
    }
    assert_audience_isolation(payload, segments, persona_id=persona["id"],
                              other_sessions_reactions=[])
    return payload


def assert_audience_isolation(audience_input: dict, all_segments: list[dict], persona_id: str,
                              other_sessions_reactions: list[dict]) -> None:
    """Reject any leak of future segments / other sessions / forbidden keys."""
    keys = set(audience_input)
    expected = {"persona", "current_segment", "visible_history", "own_previous_reactions"}
    if keys != expected:
        raise IsolationError(f"audience input keys {keys} != {expected}")
    current = audience_input["current_segment"]
    ids = [s["segment_id"] for s in all_segments]
    if current["segment_id"] not in ids:
        raise IsolationError("current segment not part of frozen version")
    cursor = ids.index(current["segment_id"])
    history_ids = [s["segment_id"] for s in audience_input["visible_history"]]
    if history_ids != ids[:cursor]:
        raise IsolationError("visible_history is not the session prefix (future or skipped segments)")
    # no future content anywhere in the serialized projection
    serialized = canonical_json(audience_input).decode("utf-8")
    for future in all_segments[cursor + 1:]:
        if future["text"] and len(future["text"]) >= 12 and future["text"] in serialized:
            raise IsolationError(f"future segment text leaked into audience input: {future['segment_id']}")
    for react in audience_input["own_previous_reactions"]:
        if react.get("segment_id") in ids[cursor + 1:]:
            raise IsolationError("own reaction references a future segment")
    for react in other_sessions_reactions:
        if canonical_json(react).decode("utf-8") in serialized:
            raise IsolationError("another session's reaction leaked into audience input")
    # persona identity must match the session owner
    if audience_input["persona"]["id"] != persona_id:
        raise IsolationError("persona mismatch")


def projection_hash(payload: dict) -> str:
    return sha256_hex(canonical_json(payload))
