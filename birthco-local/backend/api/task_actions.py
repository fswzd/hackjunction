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
    EditBrief,
    EditorialReview,
    Expected,
    FeedbackCreate,
    FeedbackRead,
    RuleReport,
    VersionRead,
)
from backend.security.session import require_write
from backend.storage.db import connect, immediate, utc_now
from backend.storage.repository import (
    ConfirmBrief as ConfirmBriefCommand,
    accept_version_tx,
    cancel_task_tx,
    confirm_brief_tx,
    edit_brief_tx,
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
