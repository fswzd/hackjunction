"""Task, material and event reads with account/task scoped SQL."""
import json

from flask import Blueprint, current_app, request
from werkzeug.exceptions import BadRequest

from backend.api import success
from backend.domain.errors import DomainError
from backend.domain.schemas import ErrorDetail, EventPage, MaterialRead, TaskEvent, TaskSummary, Usage
from backend.storage.db import connect

blueprint = Blueprint("task_reads", __name__)


def _int_query(name: str, default: int, maximum: int) -> int:
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise BadRequest("Invalid cursor or limit") from exc
    if value < (0 if name == "after_seq" else 1) or value > maximum:
        raise BadRequest("Cursor or limit out of range")
    return value


def summary(db, row):
    run_id = row["current_run_id"]
    run = db.execute("SELECT queue_seq,calls_reserved,error_json FROM runs WHERE id=? AND task_id=?", (run_id, row["id"])).fetchone()
    if run is None:
        raise DomainError("STORAGE_UNAVAILABLE", "Current run missing", "Reconcile local storage")
    counts = db.execute("SELECT count(*) AS completed,sum(CASE WHEN u.usage_status='known' THEN u.input_tokens END) AS input_tokens,sum(CASE WHEN u.usage_status='known' THEN u.output_tokens END) AS output_tokens,sum(CASE WHEN u.usage_status='known' THEN u.total_tokens END) AS total_tokens,sum(CASE WHEN u.usage_status='unknown' THEN 1 ELSE 0 END) AS unknown_calls FROM model_calls c JOIN usage_ledger u ON u.call_id=c.id WHERE c.run_id=? AND c.status NOT IN ('reserved','sent')", (run_id,)).fetchone()
    unknown = counts["unknown_calls"] or 0
    unresolved = db.execute("SELECT count(*) FROM model_calls WHERE run_id=? AND status='unknown'", (run_id,)).fetchone()[0]
    usage = Usage(calls_reserved=run["calls_reserved"], calls_completed=counts["completed"]-unresolved, input_tokens=counts["input_tokens"], output_tokens=counts["output_tokens"], total_tokens=counts["total_tokens"], unknown_calls=unknown, cost_status="partial" if unknown and counts["total_tokens"] is not None else "unknown" if unknown else "unpriced", amount_minor=None, currency=None)
    seq = run["queue_seq"]
    position = db.execute("SELECT count(*) FROM runs WHERE state='QUEUED' AND queue_seq<=?", (seq,)).fetchone()[0] if seq is not None else None
    pending = json.loads(row["pending_json"]) if row["pending_json"] else None
    run_error = ErrorDetail.model_validate(json.loads(run["error_json"])) if run["error_json"] else None
    value = TaskSummary(task_id=row["id"], account_id=row["account_id"], state=row["state"], row_version=row["row_version"], current_run_id=run_id, brief_version=row["current_brief_version"], head_version_id=row["head_version_id"], ready_version_id=row["ready_version_id"], accepted_version_id=row["accepted_version_id"], pending_action=pending.get("action") if isinstance(pending, dict) else None, queue_position=position, mode=row["mode"], usage=usage, error=run_error)
    return value.model_dump(mode="json")


def _task(db, task_id):
    row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if row is None:
        raise DomainError("NOT_FOUND", "Task not found", "Reload tasks")
    return row


@blueprint.get("/api/v1/tasks")
def list_tasks():
    account_id = request.args.get("account_id")
    if not account_id:
        raise DomainError("SCHEMA_INVALID", "account_id required", "Select an account")
    limit = _int_query("limit", 100, 100)
    with connect(current_app.config["DB_PATH"]) as db:
        if db.execute("SELECT 1 FROM accounts WHERE id=?", (account_id,)).fetchone() is None:
            raise DomainError("NOT_FOUND", "Account not found", "Select an existing account")
        rows = db.execute("SELECT * FROM tasks WHERE account_id=? ORDER BY created_at DESC,id DESC LIMIT ?", (account_id, limit)).fetchall()
        values = [summary(db, row) for row in rows]
    return success(values)


@blueprint.get("/api/v1/tasks/<task_id>")
def read_task(task_id):
    with connect(current_app.config["DB_PATH"]) as db:
        value = summary(db, _task(db, task_id))
    return success(value)


@blueprint.get("/api/v1/tasks/<task_id>/materials")
def read_materials(task_id):
    with connect(current_app.config["DB_PATH"]) as db:
        _task(db, task_id)
        rows = db.execute("SELECT * FROM materials WHERE task_id=? ORDER BY id LIMIT 100", (task_id,)).fetchall()
        values = [MaterialRead(material_id=row["id"], account_id=row["account_id"], task_id=row["task_id"], kind=row["kind"], label=row["label"], text=row["text"], source_url=row["source_url"], content_hash=row["content_hash"]).model_dump(mode="json") for row in rows]
    return success(values)


@blueprint.get("/api/v1/tasks/<task_id>/events")
def read_events(task_id):
    after, limit = _int_query("after_seq", 0, 2147483647), _int_query("limit", 100, 100)
    with connect(current_app.config["DB_PATH"]) as db:
        _task(db, task_id)
        rows = db.execute("SELECT * FROM task_events WHERE task_id=? AND seq>? ORDER BY seq LIMIT ?", (task_id, after, limit + 1)).fetchall()
        items = [TaskEvent(event_id=row["id"], seq=row["seq"], run_id=row["run_id"], type=row["type"], step=row["step"], state=row["state"], summary=row["summary"], created_at=row["created_at"]) for row in rows[:limit]]
        page = EventPage(items=items, next_after_seq=items[-1].seq if items else after, has_more=len(rows) > limit)
    return success(page.model_dump(mode="json"))
