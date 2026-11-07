"""Atomic task intake and stable 202 idempotency response."""
from uuid import uuid4

from flask import Blueprint, current_app

from backend.api import existing_response, fingerprint, json_body, request_id, save_response, success
from backend.api.task_reads import summary
from backend.domain.errors import DomainError
from backend.domain.hashing import canonical_bytes, sha256_json
from backend.domain.schemas import CreateTask
from backend.security.session import require_write
from backend.storage.db import connect, immediate, utc_now
from backend.storage.repository import _event

blueprint = Blueprint("task_create", __name__)


@blueprint.post("/api/v1/tasks")
def create_task():
    _, key = require_write()
    raw = json_body()
    payload = CreateTask.model_validate(raw)
    if sum(len(material.text) for material in payload.materials) > 80000:
        raise DomainError("OUTPUT_TOO_LARGE", "Materials exceed 80,000 characters", "Shorten the materials")
    mode = current_app.config["MODEL_MODE"]
    digest = fingerprint(raw, mode)
    scope = "local_operator"
    now = utc_now()
    task_id, run_id = "t_" + uuid4().hex, "r_" + uuid4().hex
    with connect(current_app.config["DB_PATH"]) as db:
        with immediate(db):
            previous = existing_response(db, scope, key, digest)
            if previous:
                return previous
            if db.execute("SELECT 1 FROM accounts WHERE id=?", (payload.account_id,)).fetchone() is None:
                raise DomainError("NOT_FOUND", "Account not found", "Select an existing account")
            seq = db.execute("UPDATE queue_sequence SET next_seq=next_seq+1 WHERE id=1 RETURNING next_seq").fetchone()[0]
            db.execute("INSERT INTO tasks(id,account_id,input_json,state,mode,current_run_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (task_id, payload.account_id, canonical_bytes(payload).decode("utf-8"), "DRAFT", mode, run_id, now, now))
            db.execute("INSERT INTO runs(id,task_id,kind,state,mode,phase,limits_json,created_at,updated_at,queue_seq) VALUES(?,?,?,?,?,?,?,?,?,?)", (run_id, task_id, "content", "QUEUED", mode, "planning", '{"max_model_calls":7,"max_total_tokens":60000}', now, now, seq))
            for material in payload.materials:
                material_id = "m_" + uuid4().hex
                db.execute("INSERT INTO materials(id,account_id,task_id,kind,label,text,source_url,content_hash,authorized_at) VALUES(?,?,?,?,?,?,?,?,?)", (material_id, payload.account_id, task_id, material.kind, material.label, material.text, material.source_url, sha256_json(material.text), now))
            _event(db, task_id, run_id, "task_created", "planning", "DRAFT", "Task accepted", now)
            data = summary(db, db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
            body = {"data": data, "request_id": request_id()}
            save_response(db, scope, key, digest, body, 202)
    return success(data, 202)
