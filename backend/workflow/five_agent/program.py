"""Deterministic program steps: rule checks (content-rules-v1), preview metrics
and scoped-revision validation.  These are code, not model calls (zero budget).

Rule semantics (interaction design §2): a schema-valid candidate missing
cover/titles is a fixable rule failure — save and repair; unparseable/typed
garbage is a technical error handled by the gateway, never a rule failure.
"""
from __future__ import annotations

from .registry import LIMITS, RULE_VERSION
from .repository import object_hash


def _non_whitespace_len(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


class RuleFailure(Exception):
    """Structural failure that is NOT a fixable candidate (e.g. no segments at all)."""

    def __init__(self, rule_id: str, reason: str):
        super().__init__(reason)
        self.rule_id = rule_id
        self.reason = reason


def run_rules(version_id: str, candidate: dict) -> dict:
    """content-rules-v1: deterministic checks -> RuleReport DTO."""
    checks: list[dict] = []

    def check(rule_id: str, passed: bool, reason: str, segment_id: str | None = None):
        checks.append({"rule_id": rule_id, "passed": passed, "reason": reason, "segment_id": segment_id})

    titles = candidate.get("titles") or []
    segments = candidate.get("segments") or []
    cover = candidate.get("cover_copy")

    check("titles_present", bool(titles), "标题数量满足" if titles else "缺少标题（可修订）")
    for idx, title in enumerate(titles[:10]):
        check(f"title_length_{idx}", len(title) <= LIMITS["title_characters_each"],
              "标题长度合规" if len(title) <= LIMITS["title_characters_each"] else "标题超长（可修订）")
    check("cover_present", bool(cover), "封面文案存在" if cover else "缺少封面文案（可修订）")
    if cover:
        check("cover_length", len(cover) <= LIMITS["cover_characters"],
              "封面文案长度合规" if len(cover) <= LIMITS["cover_characters"] else "封面文案超长（可修订）")
    check("segments_present", bool(segments), "正文存在" if segments else "缺少正文")
    if not segments:
        raise RuleFailure("segments_present", "candidate has no segments at all")
    check("segments_count", len(segments) <= LIMITS["body_segments"],
          "段落数合规" if len(segments) <= LIMITS["body_segments"] else "段落过多（可修订）")

    body_chars = 0
    kinds = set()
    for seg in segments:
        sid = seg["segment_id"]
        kinds.add(seg["kind"])
        body_chars += _non_whitespace_len(seg["text"])
        check(f"segment_text_nonempty_{sid}", bool(seg["text"].strip()),
              "段落有正文" if seg["text"].strip() else "段落为空（可修订）", sid)
        check(f"segment_text_length_{sid}", len(seg["text"]) <= 20000,
              "段落长度合规" if len(seg["text"]) <= 20000 else "段落超长（可修订）", sid)
    check("body_characters", body_chars <= LIMITS["body_non_whitespace_characters"],
          "正文字数合规" if body_chars <= LIMITS["body_non_whitespace_characters"] else "正文超长（可修订）")
    check("kinds_present", "hook" in kinds and "closing" in kinds,
          "开头与结尾齐备" if ("hook" in kinds and "closing" in kinds) else "缺少开头或结尾段（可修订）")

    passed = all(c["passed"] for c in checks)
    return {
        "version_id": version_id,
        "content_hash": object_hash(candidate),
        "rule_version": RULE_VERSION,
        "passed": passed,
        "body_characters": body_chars,
        "checks": checks,
    }


def failed_checks(report: dict) -> list[dict]:
    return [c for c in report["checks"] if not c["passed"]]


def compute_metrics(session_rows: list[dict], event_rows: list[dict],
                    segment_ids: list[str]) -> dict:
    """Program-computed preview metrics from persisted events (never model stats)."""
    events_by_session: dict[str, list[dict]] = {}
    for evt in event_rows:
        events_by_session.setdefault(evt["session_id"], []).append(evt)

    started = completed = exited = incomplete = no_event = 0
    interaction_sessions = {"like": 0, "comment": 0, "save": 0}
    exposures = {sid: 0 for sid in segment_ids}
    exits = {sid: 0 for sid in segment_ids}

    for sess in session_rows:
        evts = events_by_session.get(sess["id"], [])
        if not evts:
            no_event += 1
            if sess["status"] != "active":
                incomplete += 1
            continue
        started += 1
        last = evts[-1]
        for evt in evts:
            sid = evt["payload"]["segment_id"]
            exposures[sid] = exposures.get(sid, 0) + 1
            if evt["payload"]["action"] == "exit":
                exits[sid] = exits.get(sid, 0) + 1
        for interaction in last["payload"].get("interactions", []):
            if interaction in interaction_sessions:
                interaction_sessions[interaction] += 1
        if sess["status"] == "completed":
            completed += 1
        elif sess["status"] == "exited" or last["payload"]["action"] == "exit":
            exited += 1
        else:
            incomplete += 1

    segments = []
    for sid in segment_ids:
        exp = exposures.get(sid, 0)
        ex = exits.get(sid, 0)
        segments.append({"segment_id": sid, "exposures": exp, "exits": ex,
                         "exit_rate": (ex / exp) if exp else None})

    def ratio(a: int, b: int):
        return (a / b) if b else None

    return {
        "selected_sessions": len(session_rows),
        "started": started,
        "completed": completed,
        "exited": exited,
        "incomplete": incomplete,
        "no_event_sessions": no_event,
        "coverage_ratio": ratio(started, len(session_rows)),
        "completion_ratio": ratio(completed, started),
        "interaction_sessions": interaction_sessions,
        "interaction_ratios": {k: ratio(v, started) for k, v in interaction_sessions.items()},
        "segments": segments,
    }


def validate_revision(base_payload: dict, revision: dict,
                      allow_title_change: bool, allow_cover_change: bool,
                      finding_segment: dict[str, str],
                      issue_locations: dict[str, str]) -> None:
    """Scoped revision invariants (interaction design §3/§9):
    - every text change cites a selected finding (finding->segment) or a selected
      issue (issue->location segment)
    - only those segments may change; all others stay byte-identical
    - titles/cover change only when the frozen request explicitly allows it

    finding_segment: {finding_id: segment_id} for user-selected findings.
    issue_locations: {issue_id: segment_id} for rule/review issues being repaired.
    """
    problems: list[str] = []

    for change in revision.get("change_log", []):
        if change.get("change") == "metadata_update":
            continue  # metadata rides with the allowed title/cover flags, checked below
        fid, iid = change.get("finding_id"), change.get("issue_id")
        if fid is not None:
            if fid not in finding_segment:
                problems.append(f"change cites unselected finding {fid}")
            elif change["old_segment_id"] != finding_segment[fid]:
                problems.append(f"segment {change['old_segment_id']} outside finding {fid} scope")
        elif iid is not None:
            if iid not in issue_locations:
                problems.append(f"change cites unselected issue {iid}")
            elif change["old_segment_id"] != issue_locations[iid]:
                problems.append(f"segment {change['old_segment_id']} outside issue {iid} location")
        else:
            problems.append("change cites neither finding nor issue")

    base_segments = {s["segment_id"]: s for s in base_payload["segments"]}
    rev_segments = {s["segment_id"]: s for s in revision["segments"]}
    changed_ids = {c["old_segment_id"] for c in revision.get("change_log", [])}
    changed_ids |= {c["new_segment_id"] for c in revision.get("change_log", [])}

    for sid, seg in base_segments.items():
        if sid in changed_ids:
            continue
        if sid not in rev_segments:
            problems.append(f"unselected segment {sid} was deleted")
        elif rev_segments[sid] != seg:
            problems.append(f"unselected segment {sid} was modified")
    for sid in rev_segments:
        if sid not in base_segments and sid not in changed_ids:
            problems.append(f"segment {sid} added outside change_log")

    if revision.get("titles") != base_payload.get("titles") and not allow_title_change:
        problems.append("titles changed without allow_title_change")
    if revision.get("cover_copy") != base_payload.get("cover_copy") and not allow_cover_change:
        problems.append("cover_copy changed without allow_cover_change")

    if problems:
        raise ScopeError(problems)


class ScopeError(Exception):
    code = "SCOPE_DENIED"

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems
