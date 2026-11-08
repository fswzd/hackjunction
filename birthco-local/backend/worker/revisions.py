"""Revision runs: user-requested scoped edits on top of a ready version (BW-2).

`create_revision_run_tx` builds the revision run plus its lineage (synthesized
analysis bound to a placeholder preview, per the revision_requests FK chain) and
enqueues it.  `execute_revision` is the worker-side consumer: content_creator
.revise inside the authorized issue scope -> validate_scoped_revision -> child
content_versions row -> rule re-check -> export -> READY with the new
ready_version_id.

Scope discipline: only segments named in issue_locations (rule failures, review
issues, explicit notes) may change; everything else is preserved byte-for-byte.
Consumed feedback rows are recorded in revision_requests.selection_json so a
later request does not silently re-consume them.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from backend.domain.errors import DomainError
from backend.domain.hashing import canonical_bytes, sha256_json
from backend.storage.db import connect, immediate, utc_now
from backend.storage.queue import Queue
from backend.storage.repository import _event
from backend.worker.transitions import apply_transition_tx

RULE_VERSION = "content-rules-v1"


# ------------------------------------------------------------- request synthesis


def _failed_rule_locations(db, version_id: str) -> dict[str, str]:
    row = db.execute("SELECT body_json FROM rule_reports WHERE version_id=? AND rule_version=?",
                     (version_id, RULE_VERSION)).fetchone()
    if row is None:
        return {}
    body = json.loads(row["body_json"])
    locations = {}
    for check in body.get("checks") or []:
        if check.get("passed"):
            continue
        if check.get("segment_id"):
            locations[check["rule_id"]] = check["segment_id"]
    return locations


def _review_locations(db, version_id: str) -> dict[str, str]:
    row = db.execute("SELECT body_json FROM editorial_reviews WHERE version_id=?", (version_id,)).fetchone()
    if row is None:
        return {}
    body = json.loads(row["body_json"])
    locations = {}
    for issue in body.get("issues") or []:
        if issue.get("location"):
            locations[issue["id"]] = issue["location"]
    return locations


def _first_segment(base_payload: dict) -> str:
    segments = base_payload.get("segments") or []
    return segments[0]["segment_id"] if segments else "s_1"


def build_issue_repair_request(db_path, task_id: str, base_version_id: str,
                               base_payload: dict) -> dict:
    """Content-loop repair request: rule failures + review issues (node_repair parity)."""
    with connect(db_path) as db:
        locations = _failed_rule_locations(db, base_version_id)
        locations.update(_review_locations(db, base_version_id))
        rule_details = {}
        row = db.execute("SELECT body_json FROM rule_reports WHERE version_id=? AND rule_version=?",
                         (base_version_id, RULE_VERSION)).fetchone()
        if row:
            for check in json.loads(row["body_json"]).get("checks") or []:
                if not check.get("passed"):
                    rule_details[check["rule_id"]] = check.get("reason") or "规则未通过"
        review_row = db.execute("SELECT body_json FROM editorial_reviews WHERE version_id=?",
                                (base_version_id,)).fetchone()
    details = dict(rule_details)
    if review_row:
        for issue in json.loads(review_row["body_json"]).get("issues") or []:
            details[issue["id"]] = issue.get("requested_change") or issue.get("reason") or "按审稿意见修改"
    issue_ids = list(locations) or ["iss_generic_1"]
    if not locations:
        locations["iss_generic_1"] = _first_segment(base_payload)
    return {
        "kind": "issue_repair",
        "expected_head_version_id": base_version_id,
        "base_version_id": base_version_id,
        "base_content_hash": sha256_json(base_payload),
        "issue_ids": issue_ids,
        "issue_locations": locations,
        "issue_details": details,
        "instructions": "只修复列出的问题，未提及的片段保持原样",
        "allow_title_change": any(loc == "titles" for loc in locations.values()),
        "allow_cover_change": any(loc == "cover" for loc in locations.values()),
    }


def unconsumed_feedback(db, task_id: str, base_version_id: str) -> list[dict]:
    consumed: set[str] = set()
    for row in db.execute("SELECT selection_json FROM revision_requests WHERE task_id=?", (task_id,)):
        try:
            consumed.update(json.loads(row["selection_json"]).get("consumed_feedback_ids") or [])
        except ValueError:
            continue
    rows = db.execute("SELECT * FROM feedback WHERE task_id=? AND version_id=? "
                      "AND kind IN ('edit_request','reject') ORDER BY created_at",
                      (task_id, base_version_id)).fetchall()
    return [dict(row) for row in rows if row["id"] not in consumed]


def synthesize_revision_request(db, task_id: str, base_version_id: str, base_payload: dict,
                                *, notes: list[dict] | None = None,
                                feedback_rows: list[dict] | None = None,
                                instructions: str | None = None,
                                allow_title_change: bool | None = None,
                                allow_cover_change: bool | None = None) -> dict:
    """Merge rule/review issue locations, user notes and consumed feedback into one request."""
    locations = _failed_rule_locations(db, base_version_id)
    locations.update(_review_locations(db, base_version_id))
    details: dict[str, str] = {}
    for index, note in enumerate(notes or []):
        text = str(note.get("text") or "").strip()
        segment = note.get("segment_id") or _first_segment(base_payload)
        note_id = f"note_{index + 1}"
        locations[note_id] = segment
        details[note_id] = text or "按用户备注修改该段"
    for row in feedback_rows or []:
        body = json.loads(row["body_json"])
        locations.setdefault(row["id"], _first_segment(base_payload))
        details[row["id"]] = str(body.get("text") or "按用户反馈修改")
    if not locations:
        locations["iss_generic_1"] = _first_segment(base_payload)
        details["iss_generic_1"] = instructions or "按用户要求修改"
    return {
        "kind": "issue_repair",
        "expected_head_version_id": base_version_id,
        "base_version_id": base_version_id,
        "base_content_hash": sha256_json(base_payload),
        "issue_ids": list(locations),
        "issue_locations": locations,
        "issue_details": details,
        "instructions": (instructions or "只修复列出的问题，未提及的片段保持原样")[:1000],
        "allow_title_change": bool(allow_title_change) if allow_title_change is not None
        else any(loc == "titles" for loc in locations.values()),
        "allow_cover_change": bool(allow_cover_change) if allow_cover_change is not None
        else any(loc == "cover" for loc in locations.values()),
        "consumed_feedback_ids": [row["id"] for row in feedback_rows or []],
        "notes": notes or [],
    }


# ------------------------------------------------------------- run creation


def create_revision_run_tx(db, task_id: str, request: dict, *, mode: str) -> dict:
    """Insert the revision run + analysis lineage and enqueue it (one transaction)."""
    now = utc_now()
    base_version_id = request["base_version_id"]
    run_id = "r_" + uuid4().hex
    seq = db.execute("UPDATE queue_sequence SET next_seq=next_seq+1 WHERE id=1 RETURNING next_seq").fetchone()[0]
    base = db.execute("SELECT brief_version,brief_hash FROM content_versions WHERE id=? AND task_id=?",
                      (base_version_id, task_id)).fetchone()
    if base is None:
        raise DomainError("NOT_FOUND", "Content version not found", "Reload task versions")
    db.execute("INSERT INTO runs(id,task_id,kind,state,mode,phase,brief_version,brief_hash,"
               "base_version_id,limits_json,created_at,updated_at,queue_seq) "
               "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (run_id, task_id, "revision", "QUEUED", mode, "repair", base["brief_version"],
                base["brief_hash"], base_version_id,
                '{"max_model_calls":7,"max_total_tokens":917504}', now, now, seq))
    analysis_body = {
        "kind": "issue_repair_analysis",
        "findings": [{"id": issue_id, "segment_id": location,
                      "interpretation": request.get("issue_details", {}).get(issue_id, "需要修改"),
                      "suggested_edit": request.get("instructions", "")}
                     for issue_id, location in (request.get("issue_locations") or {}).items()],
        "source": "user_feedback_and_rule_reports",
        "note": "由退回修改请求合成的分析记录，未运行观众模拟",
    }
    scenario_body = {"medium": "text", "segmenter_version": "paragraph-v1", "personas": [],
                     "max_segments": 2, "requested_seed": None,
                     "note": "修订运行的占位场景（未执行试映）"}
    scenario_hash = sha256_json(scenario_body)
    scenario_id = "scn_" + scenario_hash[:24]
    if db.execute("SELECT 1 FROM preview_scenarios WHERE id=?", (scenario_id,)).fetchone() is None:
        db.execute("INSERT INTO preview_scenarios(id,scenario_hash,body_json) VALUES(?,?,?)",
                   (scenario_id, scenario_hash, canonical_bytes(scenario_body).decode("utf-8")))
    preview_id = "prv_" + hashlib.sha256(f"{run_id}|preview".encode()).hexdigest()[:24]
    db.execute("INSERT INTO preview_runs(id,task_id,version_id,run_id,content_hash,scenario_id,"
               "conditions_hash,conditions_json,state,row_version,analysis_status) "
               "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               (preview_id, task_id, base_version_id, run_id, request["base_content_hash"],
                scenario_id, sha256_json({"synthetic": run_id}), "{}", "INCOMPLETE", 0, "succeeded"))
    db.execute("INSERT INTO checkpoints(task_id,run_id,step,attempt,status,input_hash,output_hash,created_at) "
               "VALUES(?,?,?,?,'committed',?,?,?)",
               (task_id, run_id, "analysis_seed", 1, sha256_json({"seed": run_id}),
                sha256_json(analysis_body), now))
    call_id = "c_" + uuid4().hex
    db.execute("INSERT INTO model_calls(id,task_id,run_id,step,attempt,role,mode,model_id,prompt_hash,"
               "input_hash,status,reserved_tokens,lease_epoch,started_at) "
               "VALUES(?,?,?,?,?,?,?,?,?,?,'received',0,0,?)",
               (call_id, task_id, run_id, "analysis_seed", 1, "analyst", mode,
                "synthetic-feedback-analysis-v1", sha256_json({"analysis": "issue_repair"}),
                sha256_json({"seed": run_id}), now))
    analysis_id = "an_" + hashlib.sha256(f"{run_id}|analysis".encode()).hexdigest()[:24]
    db.execute("INSERT INTO analyses(id,preview_id,call_id,body_json) VALUES(?,?,?,?)",
               (analysis_id, preview_id, call_id, canonical_bytes(analysis_body).decode("utf-8")))
    request_id = "rvr_" + hashlib.sha256(f"{run_id}|request".encode()).hexdigest()[:24]
    selection = {key: value for key, value in request.items()}
    db.execute("INSERT INTO revision_requests(id,task_id,base_version_id,analysis_id,run_id,"
               "selection_json,output_version_id) VALUES(?,?,?,?,?,?,NULL)",
               (request_id, task_id, base_version_id, analysis_id, run_id,
                canonical_bytes(selection).decode("utf-8")))
    _event(db, task_id, run_id, "revision_requested", "repair", "READY",
           "退回修改已受理", now)
    return {"revision_id": request_id, "task_id": task_id, "base_version_id": base_version_id,
            "run_id": run_id, "state": "QUEUED", "output_version_id": None}


# ------------------------------------------------------------- worker consumer


def execute_revision(worker, lease) -> str:
    """One revision run: scoped revise -> child version -> rule re-check -> export -> READY."""
    run = worker._run_row(lease.run_id)
    with connect(worker.db_path) as db:
        row = db.execute("SELECT * FROM revision_requests WHERE run_id=?", (lease.run_id,)).fetchone()
    if row is None:
        raise DomainError("SCOPE_DENIED", "Revision run binding missing", "Reload revision")
    request = json.loads(row["selection_json"])
    base_id = run["base_version_id"]
    base_row = worker._version_row(base_id)
    base_payload = json.loads(base_row["content_json"])
    brief_ref = {"task_id": lease.task_id, "brief_version": run["brief_version"],
                 "brief_hash": run["brief_hash"]}
    base_ref = {"id": base_id, "sha256": base_row["content_hash"]}
    worker._artifact_store[row["id"]] = request
    request_ref = {"id": row["id"], "sha256": sha256_json(request)}
    step = f"revise:{base_id}"
    from backend.worker.bridges import ensure_orchestration_path
    ensure_orchestration_path()
    from backend.workflow.five_agent import projection

    def build():
        return projection.build_revise_input(brief_ref, base_ref, request_ref)

    def persist(db, attempt, data):
        worker._persist_version(db, lease, worker._version_id_for(lease.run_id, step, attempt),
                                data, parent_id=base_id, run=run)

    def check(data):
        from backend.agents.director import validate_scoped_revision
        from backend.domain.schemas import ContentCandidate, Revision
        base = ContentCandidate.model_validate(base_payload)
        revision = Revision.model_validate(data)
        locations = {("issue", key): value
                     for key, value in (request.get("issue_locations") or {}).items()}
        validate_scoped_revision(base, revision, locations,
                                 bool(request.get("allow_title_change")),
                                 bool(request.get("allow_cover_change")))

    status, raw = worker._model_step(
        lease, step=step, agent_id="content_creator", action="revise", role="director",
        build_input=build, prompt_schema_version=_prompt_version(),
        persist=persist,
        ref_of=lambda attempt, st, data: worker._version_id_for(lease.run_id, step, attempt),
        check=check)
    if status == "replayed":
        child_id = raw["output_ref"]
    elif status == "ok":
        child_id = raw.get("_step_ref") or worker._version_id_for(lease.run_id, step, 1)
    else:
        issues = raw.get("issues") or []
        reason = (issues[0].get("reason") if issues else "修订被确定性拒绝")
        from backend.worker.executor import _Stop
        raise _Stop("SCHEMA_INVALID", f"revise 失败: {reason}", "调整请求后重试")
    return _finish_revision(worker, lease, child_id, request)


def _finish_revision(worker, lease, child_id: str, request: dict) -> str:
    """Rule re-check (复检) then export and hand back to the READY gate."""
    from backend.worker.executor import _artifact_files, _Stop
    child_row = worker._version_row(child_id)
    payload = json.loads(child_row["content_json"])
    brief = worker._latest_brief(lease.task_id) or {}
    report = worker._rule_report(child_id, payload, brief.get("length_rule") or {})
    report_body = canonical_bytes(report.model_dump(mode="json")).decode("utf-8")
    if not report.passed:
        with connect(worker.db_path) as db:
            with immediate(db):
                worker._persist_rule_report(db, lease.task_id, child_id, False, report_body)
                apply_transition_tx(db, lease.task_id, lease.run_id,
                                    from_state="READY", to_state="READY",
                                    action="revision_saved", step="repair",
                                    summary="修订稿已保存", pending=None)
                db.execute("UPDATE runs SET error_json=? WHERE id=?",
                           (json.dumps({"code": "SCHEMA_INVALID", "retryable": False,
                                        "cause_hint": "修订稿未通过规则复检",
                                        "next_action": "查看规则报告后重新退回修改",
                                        "field_errors": [], "current_row_version": None},
                                       ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")), lease.run_id))
                Queue.release_tx(db, lease, "FAILED", utc_now())
        return "failed"
    files = _artifact_files(worker.data_dir, lease.task_id, child_id, payload)
    with connect(worker.db_path) as db:
        with immediate(db):
            worker._persist_rule_report(db, lease.task_id, child_id, True, report_body)
            apply_transition_tx(db, lease.task_id, lease.run_id,
                                from_state="READY", to_state="READY",
                                action="revision_saved", step="repair",
                                summary="修订稿已保存", pending=None)
            db.execute("UPDATE tasks SET head_version_id=?,ready_version_id=? WHERE id=?",
                       (child_id, child_id, lease.task_id))
            worker._persist_exports(db, lease, child_id, files)
            apply_transition_tx(db, lease.task_id, lease.run_id,
                                from_state="READY", to_state="READY",
                                action="revision_exported", step="export",
                                summary="修订稿已导出",
                                pending={"action": "accept_content"})
            Queue.release_tx(db, lease, "SUCCEEDED", utc_now())
    return "done"


def _prompt_version() -> str:
    from backend.worker.bridges import ensure_orchestration_path
    ensure_orchestration_path()
    from backend.workflow.five_agent.registry import PROMPT_SCHEMA_VERSION
    return PROMPT_SCHEMA_VERSION
