"""Human-gate commands and version reads documented by the task contract.

The Flask API is the web boundary for the same transactional commands used by
the storage layer: Brief confirmation, Brief editing, content acceptance and
cancellation all run through CAS checks inside one SQLite transaction. Writes
also persist an idempotent response so a retry after a dropped connection
returns the committed body instead of executing the command twice.
"""
import json
from uuid import uuid4

from flask import Blueprint, current_app

from backend.api import existing_response, fingerprint, json_body, request_id, save_response, success
from backend.api.task_reads import summary
from backend.domain.errors import DomainError
from backend.domain.hashing import canonical_bytes, sha256_json
from backend.domain.schemas import (
    AcceptVersion,
    BriefRead,
    ConfirmBrief,
    ContentCandidate,
    CreateTask,
    EditBrief,
    EditorialReview,
    Expected,
    FeedbackCreate,
    FeedbackRead,
    QuestionsRead,
    ReturnForRevision,
    RuleReport,
    Resume,
    UpdateInput,
    VersionRead,
)
from backend.security.session import require_write
from backend.storage.db import connect, immediate, utc_now
from backend.storage.queue import Queue
from backend.storage.repository import (
    ConfirmBrief as ConfirmBriefCommand,
    accept_version_tx,
    cancel_task_tx,
    confirm_brief_tx,
    edit_brief_tx,
    _event,
)

blueprint = Blueprint("task_actions", __name__)
_SCOPE = "local_operator"


def _task(db, task_id):
    row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if row is None:
        raise DomainError("NOT_FOUND", "Task not found", "Reload tasks")
    return row


def _response_body(data) -> dict:
    return {"data": data, "request_id": request_id()}


def _write(operation_status: int, mutate, response_status: int = 200):
    """Run one idempotent write and return the committed TaskSummary."""
    session, key = require_write()
    raw = json_body()
    digest = fingerprint(raw)
    with connect(current_app.config["DB_PATH"]) as db:
        with immediate(db):
            previous = existing_response(db, _SCOPE, key, digest)
            if previous:
                return previous
            data = mutate(db, raw, session)
            body = _response_body(data)
            save_response(db, _SCOPE, key, digest, body, operation_status)
    return success(data, response_status)


@blueprint.get("/api/v1/tasks/<task_id>/brief")
def read_brief(task_id):
    with connect(current_app.config["DB_PATH"]) as db:
        task = _task(db, task_id)
        version = task["current_brief_version"]
        if version is None:
            row = db.execute("SELECT version,body_json,brief_hash,confirmed_at FROM briefs WHERE task_id=? ORDER BY version DESC LIMIT 1", (task_id,)).fetchone()
        else:
            row = db.execute("SELECT version,body_json,brief_hash,confirmed_at FROM briefs WHERE task_id=? AND version=?", (task_id, version)).fetchone()
        if row is None:
            raise DomainError("NOT_FOUND", "Brief not available", "Wait for Brief planning to finish")
        value = BriefRead(task_id=task_id, brief_version=row["version"], brief_hash=row["brief_hash"],
                          confirmed=row["confirmed_at"] is not None,
                          brief=json.loads(row["body_json"]))
    return success(value.model_dump(mode="json"))


def _version_read(db, row) -> dict:
    rule_row = db.execute("SELECT body_json FROM rule_reports WHERE version_id=? ORDER BY rule_version LIMIT 1", (row["id"],)).fetchone()
    review_row = db.execute("SELECT body_json FROM editorial_reviews WHERE version_id=?", (row["id"],)).fetchone()
    rule_report = RuleReport.model_validate(json.loads(rule_row["body_json"])) if rule_row else None
    editorial_review = EditorialReview.model_validate(json.loads(review_row["body_json"])) if review_row else None
    validation = "pending"
    if editorial_review is not None and editorial_review.overall == "needs_input":
        validation = "needs_input"
    elif rule_report is not None:
        validation = "passed" if rule_report.passed else "invalid"
    value = VersionRead(
        version_id=row["id"], task_id=row["task_id"], ordinal=row["ordinal"],
        parent_version_id=row["parent_id"], brief_hash=row["brief_hash"],
        content_hash=row["content_hash"],
        content=ContentCandidate.model_validate(json.loads(row["content_json"])),
        rule_report=rule_report, editorial_review=editorial_review,
        validation=validation,
    )
    return value.model_dump(mode="json")


@blueprint.get("/api/v1/tasks/<task_id>/versions")
def list_versions(task_id):
    with connect(current_app.config["DB_PATH"]) as db:
        _task(db, task_id)
        rows = db.execute("SELECT * FROM content_versions WHERE task_id=? ORDER BY ordinal LIMIT 100", (task_id,)).fetchall()
        values = [_version_read(db, row) for row in rows]
    return success(values)


@blueprint.get("/api/v1/tasks/<task_id>/versions/<version_id>")
def read_version(task_id, version_id):
    with connect(current_app.config["DB_PATH"]) as db:
        _task(db, task_id)
        row = db.execute("SELECT * FROM content_versions WHERE id=? AND task_id=?", (version_id, task_id)).fetchone()
        if row is None:
            raise DomainError("NOT_FOUND", "Content version not found", "Reload task versions")
        value = _version_read(db, row)
    return success(value)


@blueprint.post("/api/v1/tasks/<task_id>/confirm")
def confirm_brief(task_id):
    def mutate(db, raw, session):
        payload = ConfirmBrief.model_validate(raw)
        task = _task(db, task_id)
        command = ConfirmBriefCommand(task_id=task_id, run_id=task["current_run_id"],
                                      expected_brief_version=payload.expected_brief_version,
                                      brief_hash=payload.brief_hash)
        confirm_brief_tx(db, command, payload.expected_row_version)
        return summary(db, _task(db, task_id))

    return _write(202, mutate, 202)


@blueprint.put("/api/v1/tasks/<task_id>/brief")
def edit_brief(task_id):
    def mutate(db, raw, session):
        payload = EditBrief.model_validate(raw)
        brief_body = payload.brief.model_dump(mode="json")
        edit_brief_tx(db, task_id, brief_body, payload.expected_row_version,
                      payload.expected_brief_version, sha256_json(brief_body))
        return summary(db, _task(db, task_id))

    return _write(200, mutate, 200)


@blueprint.post("/api/v1/tasks/<task_id>/accept")
def accept_version(task_id):
    def mutate(db, raw, session):
        payload = AcceptVersion.model_validate(raw)
        accept_version_tx(db, task_id, payload.version_id, payload.content_hash,
                          payload.expected_row_version, session["id"])
        return summary(db, _task(db, task_id))

    return _write(200, mutate, 200)


@blueprint.post("/api/v1/tasks/<task_id>/cancel")
def cancel_task(task_id):
    def mutate(db, raw, session):
        payload = Expected.model_validate(raw)
        cancel_task_tx(db, task_id, payload.expected_row_version)
        return summary(db, _task(db, task_id))

    return _write(200, mutate, 200)


@blueprint.post("/api/v1/tasks/<task_id>/revise")
def return_for_revision(task_id):
    def mutate(db, raw, _):
        from backend.worker.content import edit_requests

        payload = ReturnForRevision.model_validate(raw)
        task = _task(db, task_id)
        if task["row_version"] != payload.expected_row_version or task["ready_version_id"] != payload.version_id:
            raise DomainError("VERSION_CONFLICT", "Ready version changed", "Reload the current draft")
        if task["state"] != "READY":
            raise DomainError("INVALID_TRANSITION", "Task is not ready for revision", "Wait for a ready version")
        version = db.execute("SELECT * FROM content_versions WHERE id=? AND task_id=?", (payload.version_id, task_id)).fetchone()
        if version is None or version["content_hash"] != payload.content_hash:
            raise DomainError("CONDITIONS_MISMATCH", "Ready content fingerprint changed", "Reload the current draft")
        if not payload.note.strip():
            raise DomainError("INPUT_MISSING", "Revision note is blank", "Describe the requested change")
        candidate = ContentCandidate.model_validate_json(version["content_json"])
        scope = db.execute("SELECT body_json FROM briefs WHERE task_id=? AND version=?", (task_id, version["brief_version"])).fetchone()
        if json.loads(scope["body_json"]).get("edit_scope"):
            raise DomainError("SCOPE_DENIED", "The original draft has a restricted edit scope", "Start a new task with an explicit scope")
        issues = edit_requests([s.segment_id for s in candidate.segments] + ["titles", "cover"], payload.note)
        if len(issues) > 30:
            raise DomainError("OUTPUT_TOO_LARGE", "This draft exceeds the full-revision scope",
                              "Start an explicitly scoped revision of fewer paragraphs")
        now, run_id = utc_now(), "r_" + uuid4().hex
        feedback = FeedbackCreate(version_id=version["id"], kind="edit_request", text=payload.note,
                                  platform=None, window_start=None, window_end=None, metrics={}, source_ref=None)
        db.execute("INSERT INTO feedback(id,account_id,task_id,version_id,kind,evidence_kind,body_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                   ("fb_" + uuid4().hex, task["account_id"], task_id, version["id"], "edit_request", "user_statement",
                    canonical_bytes(feedback).decode(), now))
        db.execute("INSERT INTO runs(id,task_id,kind,state,mode,phase,brief_version,brief_hash,base_version_id,limits_json,created_at,updated_at) "
                   "VALUES(?,?,'content','WAITING',?,'repair',?,?,?,'{\"max_model_calls\":4,\"max_total_tokens\":60000}',?,?)",
                   (run_id, task_id, task["mode"], version["brief_version"], version["brief_hash"], version["id"], now, now))
        pending = {"issues": [item.model_dump() for item in issues]}
        db.execute("UPDATE tasks SET state='QUEUED',current_run_id=?,ready_version_id=NULL,pending_json=?,row_version=row_version+1,updated_at=? WHERE id=?",
                   (run_id, canonical_bytes(pending).decode(), now, task_id))
        Queue.enqueue_tx(db, run_id, now)
        _event(db, task_id, run_id, "revision_requested", "repair", "QUEUED", "用户已退回修改", now)
        return summary(db, _task(db, task_id))

    return _write(202, mutate, 202)


@blueprint.get("/api/v1/tasks/<task_id>/input")
def read_questions(task_id):
    with connect(current_app.config["DB_PATH"]) as db:
        task = _task(db, task_id)
        pending = json.loads(task["pending_json"] or "{}")
        return success(QuestionsRead(questions=pending.get("questions", [])).model_dump(mode="json"))


@blueprint.post("/api/v1/tasks/<task_id>/input")
def supply_input(task_id):
    def mutate(db, raw, _):
        payload = UpdateInput.model_validate(raw)
        task = _task(db, task_id)
        if task["row_version"] != payload.expected_row_version:
            raise DomainError("VERSION_CONFLICT", "Task version changed", "Reload questions")
        if task["state"] != "WAITING_INPUT" or task["current_brief_version"] is not None:
            raise DomainError("INVALID_TRANSITION", "Task is not awaiting planning input", "Reload the task")
        if not payload.answers and not payload.materials:
            raise DomainError("INPUT_MISSING", "No input was provided", "Add answers or authorized material")
        existing = CreateTask.model_validate_json(task["input_json"])
        value = existing.model_dump(mode="json")
        value["materials"] += [item.model_dump(mode="json") for item in payload.materials]
        updated = CreateTask.model_validate(value)
        if sum(len(material.text) for material in updated.materials) > 80000:
            raise DomainError("OUTPUT_TOO_LARGE", "Materials exceed 80,000 characters", "Shorten the materials")
        now = utc_now()
        for material in payload.materials:
            db.execute("INSERT INTO materials(id,account_id,task_id,kind,label,text,source_url,content_hash,authorized_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       ("m_" + uuid4().hex, task["account_id"], task_id, material.kind, material.label, material.text,
                        material.source_url, sha256_json(material.text), now))
        pending = json.loads(task["pending_json"] or "{}")
        answers = {**pending.get("answers", {}), **payload.answers}
        pending = {"answers": answers, "input_version": task["row_version"] + 1}
        db.execute("UPDATE tasks SET input_json=?,state='QUEUED',pending_json=?,row_version=row_version+1,updated_at=? WHERE id=?",
                   (canonical_bytes(updated).decode(), canonical_bytes(pending).decode(), now, task_id))
        Queue.enqueue_tx(db, task["current_run_id"], now)
        _event(db, task_id, task["current_run_id"], "input_supplied", "planning", "QUEUED", "用户已补充资料", now)
        return summary(db, _task(db, task_id))

    return _write(202, mutate, 202)


@blueprint.post("/api/v1/tasks/<task_id>/resume")
def resume_task(task_id):
    def mutate(db, raw, _):
        payload = Resume.model_validate(raw)
        task = _task(db, task_id)
        if task["row_version"] != payload.expected_row_version:
            raise DomainError("VERSION_CONFLICT", "Task version changed", "Reload the task")
        if task["state"] not in {"FAILED", "INTERRUPTED"}:
            raise DomainError("INVALID_TRANSITION", "Task is not resumable", "Reload the task")
        now = utc_now()
        run_id = task["current_run_id"]
        Queue.check_resumable_tx(db, run_id, payload.strategy)
        pending = json.loads(task["pending_json"] or "{}")
        pending.pop("action", None)
        db.execute("UPDATE tasks SET state='QUEUED',pending_json=?,row_version=row_version+1,updated_at=? WHERE id=?",
                   (canonical_bytes(pending).decode(), now, task_id))
        Queue.enqueue_tx(db, run_id, now)
        db.execute("UPDATE runs SET error_json=NULL,finished_at=NULL WHERE id=?", (run_id,))
        _event(db, task_id, run_id, "task_resumed", "recovery", "QUEUED", "从已保存的步骤继续", now)
        return summary(db, _task(db, task_id))

    return _write(202, mutate, 202)


def _feedback_read(row) -> dict:
    body = json.loads(row["body_json"])
    return FeedbackRead(
        version_id=row["version_id"], kind=row["kind"], text=body["text"],
        platform=body.get("platform"), window_start=body.get("window_start"),
        window_end=body.get("window_end"), metrics=body.get("metrics", {}),
        source_ref=body.get("source_ref"), feedback_id=row["id"],
        account_id=row["account_id"], task_id=row["task_id"],
        created_at=row["created_at"], evidence_kind=row["evidence_kind"],
    ).model_dump(mode="json")


@blueprint.post("/api/v1/tasks/<task_id>/feedback")
def create_feedback(task_id):
    def mutate(db, raw, session):
        payload = FeedbackCreate.model_validate(raw)
        task = _task(db, task_id)
        if db.execute("SELECT 1 FROM content_versions WHERE id=? AND task_id=?", (payload.version_id, task_id)).fetchone() is None:
            raise DomainError("NOT_FOUND", "Content version not found", "Select an existing version")
        feedback_id = "fb_" + uuid4().hex
        now = utc_now()
        evidence = "real_feedback_unverified" if payload.kind == "real_platform_feedback" else "user_statement"
        db.execute("INSERT INTO feedback(id,account_id,task_id,version_id,kind,evidence_kind,body_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                   (feedback_id, task["account_id"], task_id, payload.version_id, payload.kind,
                    evidence, canonical_bytes(payload).decode("utf-8"), now))
        row = db.execute("SELECT * FROM feedback WHERE id=?", (feedback_id,)).fetchone()
        return _feedback_read(row)

    return _write(201, mutate, 201)


@blueprint.get("/api/v1/tasks/<task_id>/feedback")
def list_feedback(task_id):
    with connect(current_app.config["DB_PATH"]) as db:
        _task(db, task_id)
        rows = db.execute("SELECT * FROM feedback WHERE task_id=? ORDER BY created_at DESC LIMIT 100", (task_id,)).fetchall()
        values = [_feedback_read(row) for row in rows]
    return success(values)
