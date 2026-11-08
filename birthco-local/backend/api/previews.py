"""Preview preflight, create, read, events, cancel and resume."""
import json
import os
from uuid import uuid4

from flask import Blueprint, current_app, request

from backend.api import existing_response, fingerprint, json_body, request_id, save_response, success
from backend.domain.errors import DomainError
from backend.domain.hashing import canonical_bytes, conditions_hash, scenario_hash, sha256_json
from backend.domain.schemas import (
    AnalysisRead,
    AudienceEventPage,
    Expected,
    PreflightRead,
    PreviewCreate,
    PreviewRead,
    PreviewSpec,
    Resume,
    SessionSummary,
    StoredAudienceEvent,
    Usage,
)
from backend.security.session import require_write
from backend.storage.db import connect, immediate, utc_now
from backend.storage.repository import _event, cancel_run_tx
from backend.storage.queue import Queue

blueprint = Blueprint("previews", __name__)

_PROMPT_VERSION = "audience-system-v1"
_SCHEMA_VERSION = "creator-agent.v1"
_ESTIMATOR_VERSION = "estimator-v1"
_TEMPERATURE = 0.2
_TOP_P = 1.0
_PROMPT_HASH = sha256_json({"system_base": "audience-v1", "reaction_mix": True, "emotion_modifiers": True})
_SEGMENTER_HASH = sha256_json({"segmenter": "paragraph-v1"})


def _budget(persona_count: int, max_segments: int) -> dict:
    return {"max_calls": persona_count * max_segments, "max_active_seconds": 1200}


def _compute_hashes(spec: PreviewSpec, mode: str):
    s_hash = scenario_hash(spec.scenario)
    budget = _budget(len(spec.scenario.personas), spec.scenario.max_segments)
    c_hash = conditions_hash(
        scenario=spec.scenario, model_id="mock-audience-v1" if mode == "mock" else os.environ.get("MIMO_MODEL_ID", "mimo-v2.6-pro"),
        temperature=_TEMPERATURE, top_p=_TOP_P,
        prompt_version=_PROMPT_VERSION, prompt_hash=_PROMPT_HASH,
        schema_version=_SCHEMA_VERSION,
        segmenter_version=spec.scenario.segmenter_version, segmenter_hash=_SEGMENTER_HASH,
        budget=budget,
        requested_seed=spec.scenario.requested_seed, seed_supported=True,
        estimator_version=_ESTIMATOR_VERSION, mode=mode,
    )
    return s_hash, c_hash, budget


def _estimate(scenario) -> tuple[int, int]:
    calls = len(scenario.personas) * scenario.max_segments
    return calls, calls * 500


def _preview_read(db, preview_id: str) -> dict:
    row = db.execute("SELECT pr.*, ps.scenario_hash FROM preview_runs pr JOIN preview_scenarios ps ON ps.id=pr.scenario_id WHERE pr.id=?", (preview_id,)).fetchone()
    if row is None:
        raise DomainError("NOT_FOUND", "Preview not found", "Reload previews")
    sessions = db.execute("SELECT id,persona_id,cursor,outcome,stop_reason FROM audience_sessions WHERE preview_id=? ORDER BY persona_id", (preview_id,)).fetchall()
    summaries = [SessionSummary(session_id=s["id"], persona_id=s["persona_id"], cursor=s["cursor"], outcome=s["outcome"], stop_reason=s["stop_reason"]).model_dump(mode="json") for s in sessions]
    counts = db.execute("SELECT count(*) AS completed,sum(CASE WHEN u.usage_status='known' THEN u.input_tokens END) AS input_tokens,sum(CASE WHEN u.usage_status='known' THEN u.output_tokens END) AS output_tokens,sum(CASE WHEN u.usage_status='known' THEN u.total_tokens END) AS total_tokens,sum(CASE WHEN u.usage_status='unknown' THEN 1 ELSE 0 END) AS unknown_calls FROM model_calls c JOIN usage_ledger u ON u.call_id=c.id WHERE c.run_id=? AND c.status NOT IN ('reserved','sent')", (row["run_id"],)).fetchone()
    unknown = counts["unknown_calls"] or 0
    # 与 task_reads.summary 同口径：calls_reserved 取 runs 行；unknown（未决）不计入 completed
    run_row = db.execute("SELECT calls_reserved,started_at,finished_at,error_json FROM runs WHERE id=?", (row["run_id"],)).fetchone()
    unresolved = db.execute("SELECT count(*) FROM model_calls WHERE run_id=? AND status='unknown'", (row["run_id"],)).fetchone()[0]
    usage = Usage(calls_reserved=run_row["calls_reserved"] if run_row else 0, calls_completed=(counts["completed"] or 0) - unresolved, input_tokens=counts["input_tokens"], output_tokens=counts["output_tokens"], total_tokens=counts["total_tokens"], unknown_calls=unknown, cost_status="partial" if unknown and counts["total_tokens"] is not None else "unknown" if unknown else "unpriced", amount_minor=None, currency=None)
    metrics = json.loads(row["metrics_json"]) if row["metrics_json"] else None
    error = json.loads(run_row["error_json"]) if run_row["error_json"] else None
    analysis = db.execute("SELECT id FROM analyses WHERE preview_id=? ORDER BY rowid DESC LIMIT 1", (preview_id,)).fetchone()
    return PreviewRead(
        preview_id=row["id"], task_id=row["task_id"], version_id=row["version_id"],
        content_hash=row["content_hash"], scenario_hash=row["scenario_hash"], conditions_hash=row["conditions_hash"],
        state=row["state"], row_version=row["row_version"], sessions=summaries,
        started_at=run_row["started_at"], finished_at=run_row["finished_at"],
        metrics=metrics, analysis_id=analysis["id"] if analysis else None, analysis_status=row["analysis_status"],
        usage=usage, error=error,
        can_resume=row["state"] in {"INTERRUPTED", "INCOMPLETE"} and not Queue.has_unresolved_calls_tx(db, row["run_id"]),
    ).model_dump(mode="json")


@blueprint.post("/api/v1/previews/preflight")
def preview_preflight():
    _, key = require_write()
    raw = json_body()
    payload = PreviewSpec.model_validate(raw)
    mode = current_app.config["MODEL_MODE"]
    s_hash, c_hash, _ = _compute_hashes(payload, mode)
    calls, tokens = _estimate(payload.scenario)
    from backend.domain.schemas import Hash as HashType
    segment_count = payload.scenario.max_segments
    eligible = True
    reasons: list[str] = []
    if segment_count > 8:
        eligible = False
        reasons.append("max_segments exceeds 8")
    result = PreflightRead(
        eligible=eligible, segment_count=segment_count,
        persona_count=len(payload.scenario.personas),
        estimated_total_tokens=tokens, estimated_calls=calls,
        scenario_hash=s_hash, conditions_hash=c_hash,
        reasons=reasons, alternatives=[],
    )
    return success(result.model_dump(mode="json"), 200)


@blueprint.post("/api/v1/previews")
def create_preview():
    _, key = require_write()
    raw = json_body()
    payload = PreviewCreate.model_validate(raw)
    mode = current_app.config["MODEL_MODE"]
    digest = fingerprint(raw, mode)
    scope = "local_operator"
    now = utc_now()
    s_hash, c_hash, _ = _compute_hashes(payload, mode)
    if payload.expected_scenario_hash != s_hash:
        raise DomainError("CONDITIONS_MISMATCH", "Scenario hash mismatch", "Re-run preflight")
    if payload.expected_conditions_hash != c_hash:
        raise DomainError("CONDITIONS_MISMATCH", "Conditions hash mismatch", "Re-run preflight")
    with connect(current_app.config["DB_PATH"]) as db:
        with immediate(db):
            previous = existing_response(db, scope, key, digest)
            if previous:
                return previous
            version = db.execute("SELECT task_id,content_hash,content_json FROM content_versions WHERE id=?", (payload.version_id,)).fetchone()
            if version is None:
                raise DomainError("NOT_FOUND", "Content version not found", "Select an existing version")
            if version["content_hash"] != payload.content_hash:
                raise DomainError("CONDITIONS_MISMATCH", "Content hash mismatch", "Refresh the version")
            preview_id = enqueue_preview(db, version["task_id"], payload, mode, now)
            data = _preview_read(db, preview_id)
            body = {"data": data, "request_id": request_id()}
            save_response(db, scope, key, digest, body, 202)
    return success(data, 202)


def enqueue_preview(db, task_id, spec, mode, now):
    s_hash, c_hash, budget = _compute_hashes(spec, mode)
    preview_id, run_id = "pv_" + uuid4().hex, "r_" + uuid4().hex
    scenario_id = "sc_" + uuid4().hex
    seq = db.execute("UPDATE queue_sequence SET next_seq=next_seq+1 WHERE id=1 RETURNING next_seq").fetchone()[0]
    limits = {**budget, "max_model_calls": budget["max_calls"] + 1, "max_total_tokens": 2228224}
    db.execute("INSERT INTO runs(id,task_id,kind,state,mode,phase,limits_json,created_at,updated_at,queue_seq) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (run_id, task_id, "preview", "QUEUED", mode, "audience", json.dumps(limits), now, now, seq))
    db.execute("INSERT INTO preview_scenarios(id,scenario_hash,body_json) VALUES(?,?,?) ON CONFLICT(scenario_hash) DO NOTHING",
               (scenario_id, s_hash, canonical_bytes(spec.scenario).decode("utf-8")))
    scenario_id = db.execute("SELECT id FROM preview_scenarios WHERE scenario_hash=?", (s_hash,)).fetchone()[0]
    db.execute("INSERT INTO preview_runs(id,task_id,version_id,run_id,content_hash,scenario_id,conditions_hash,conditions_json,state,row_version,analysis_status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               (preview_id, task_id, spec.version_id, run_id, spec.content_hash, scenario_id, c_hash,
                json.dumps({"mode": mode, "budget": budget}), "QUEUED", 0, "pending"))
    for persona in spec.scenario.personas:
        db.execute("INSERT INTO audience_sessions(id,preview_id,persona_id,persona_json,cursor,outcome) VALUES(?,?,?,?,0,'pending')",
                   ("session_" + uuid4().hex, preview_id, persona.id, canonical_bytes(persona).decode("utf-8")))
    _event(db, task_id, run_id, "preview_created", "audience", "QUEUED", "试映已排队", now)
    return preview_id


@blueprint.get("/api/v1/tasks/<task_id>/previews")
def list_previews(task_id):
    with connect(current_app.config["DB_PATH"]) as db:
        ids = db.execute("SELECT id FROM preview_runs WHERE task_id=? ORDER BY rowid DESC LIMIT 100", (task_id,))
        return success([_preview_read(db, row["id"]) for row in ids])


@blueprint.get("/api/v1/previews/<preview_id>/analysis")
def read_analysis(preview_id):
    with connect(current_app.config["DB_PATH"]) as db:
        row = db.execute("SELECT a.id,a.body_json,p.version_id FROM analyses a JOIN preview_runs p ON p.id=a.preview_id WHERE a.preview_id=? ORDER BY a.rowid DESC LIMIT 1", (preview_id,)).fetchone()
        if row is None:
            raise DomainError("NOT_FOUND", "Analysis not available", "Wait for preview analysis")
        value = AnalysisRead(analysis_id=row["id"], preview_id=preview_id, version_id=row["version_id"],
                             analysis=json.loads(row["body_json"]))
    return success(value.model_dump(mode="json"))


@blueprint.get("/api/v1/previews/<preview_id>")
def get_preview(preview_id: str):
    with connect(current_app.config["DB_PATH"]) as db:
        data = _preview_read(db, preview_id)
    return success(data, 200)


@blueprint.get("/api/v1/previews/<preview_id>/events")
def preview_events(preview_id: str):
    after_seq = request.args.get("after_seq", "0")
    limit = request.args.get("limit", "100")
    try:
        after_seq = int(after_seq)
        limit = min(max(int(limit), 1), 100)
    except ValueError:
        raise DomainError("SCHEMA_INVALID", "Invalid cursor or limit", "Use integer after_seq and limit")
    if after_seq < 0:
        raise DomainError("SCHEMA_INVALID", "after_seq must be >= 0", "Use a non-negative cursor")
    with connect(current_app.config["DB_PATH"]) as db:
        pv = db.execute("SELECT version_id FROM preview_runs WHERE id=?", (preview_id,)).fetchone()
        if pv is None:
            raise DomainError("NOT_FOUND", "Preview not found", "Reload previews")
        vid = pv["version_id"]
        rows = db.execute("SELECT * FROM audience_events WHERE preview_id=? AND preview_seq>? ORDER BY preview_seq LIMIT ?", (preview_id, after_seq, limit + 1)).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [StoredAudienceEvent(
            event_id=r["id"], preview_id=r["preview_id"], session_id=r["session_id"],
            version_id=vid, seq=r["preview_seq"], created_at=r["created_at"],
            event=json.loads(r["body_json"]),
        ).model_dump(mode="json") for r in rows]
        next_seq = rows[-1]["preview_seq"] if rows else after_seq
    return success(AudienceEventPage(items=items, next_after_seq=next_seq, has_more=has_more).model_dump(mode="json"), 200)


@blueprint.post("/api/v1/previews/<preview_id>/cancel")
def cancel_preview(preview_id: str):
    _, key = require_write()
    raw = json_body()
    payload = Expected.model_validate(raw)
    digest = fingerprint(raw)
    now = utc_now()
    with connect(current_app.config["DB_PATH"]) as db:
        with immediate(db):
            previous = existing_response(db, "local_operator", key, digest)
            if previous:
                return previous
            row = db.execute("SELECT * FROM preview_runs WHERE id=?", (preview_id,)).fetchone()
            if row is None:
                raise DomainError("NOT_FOUND", "Preview not found", "Reload previews")
            if row["row_version"] != payload.expected_row_version:
                raise DomainError("VERSION_CONFLICT", "Row version changed", "Reload the preview")
            if row["state"] in {"COMPLETED", "CANCELLED", "FAILED"}:
                raise DomainError("INVALID_TRANSITION", "Preview already finished", "Read the final state")
            run = db.execute("SELECT id,lease_owner,lease_epoch FROM runs WHERE id=?", (row["run_id"],)).fetchone()
            cancel_run_tx(db, run, now)
            _event(db, row["task_id"], row["run_id"], "preview_cancelled", "audience", "CANCELLED", "Preview cancelled", now)
            data = _preview_read(db, preview_id)
            save_response(db, "local_operator", key, digest, {"data": data, "request_id": request_id()}, 200)
    return success(data, 200)


@blueprint.post("/api/v1/previews/<preview_id>/resume")
def resume_preview(preview_id: str):
    _, key = require_write()
    raw = json_body()
    payload = Resume.model_validate(raw)
    digest = fingerprint(raw)
    now = utc_now()
    with connect(current_app.config["DB_PATH"]) as db:
        with immediate(db):
            previous = existing_response(db, "local_operator", key, digest)
            if previous:
                return previous
            row = db.execute("SELECT * FROM preview_runs WHERE id=?", (preview_id,)).fetchone()
            if row is None:
                raise DomainError("NOT_FOUND", "Preview not found", "Reload previews")
            if row["row_version"] != payload.expected_row_version:
                raise DomainError("VERSION_CONFLICT", "Row version changed", "Reload the preview")
            if row["state"] not in {"INTERRUPTED", "INCOMPLETE"}:
                raise DomainError("INVALID_TRANSITION", "Preview is not resumable", "Only interrupted or incomplete previews can resume")
            Queue.check_resumable_tx(db, row["run_id"], payload.strategy)
            Queue.enqueue_tx(db, row["run_id"], now)
            db.execute("UPDATE preview_runs SET state='QUEUED',analysis_status='pending',row_version=row_version+1 WHERE id=?", (preview_id,))
            db.execute("UPDATE runs SET error_json=NULL,finished_at=NULL WHERE id=?", (row["run_id"],))
            _event(db, row["task_id"], row["run_id"], "preview_resumed", "audience", "QUEUED", "Preview resumed", now)
            data = _preview_read(db, preview_id)
            body = {"data": data, "request_id": request_id()}
            save_response(db, "local_operator", key, digest, body, 202)
    return success(data, 202)
