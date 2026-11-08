"""Atomic task intake and stable 202 idempotency response."""
from uuid import uuid4

from flask import Blueprint, current_app

from backend.api import existing_response, fingerprint, json_body, request_id, save_response, success
from backend.api.task_reads import summary
from backend.domain.errors import DomainError
from backend.domain.hashing import canonical_bytes, sha256_json
from backend.domain.schemas import CreateTask, CreateWorkspaceTask
from backend.integrations import storage as integration_storage
from backend.security.session import require_write
from backend.storage.db import connect, immediate, utc_now
from backend.storage.repository import _event

blueprint = Blueprint("task_create", __name__)


def _history_material(db, account_id: str, external_id: str) -> dict:
    account = db.execute(
        "SELECT platform, handle FROM external_accounts WHERE id=? AND account_id=?",
        (external_id, account_id),
    ).fetchone()
    if account is None:
        raise DomainError("NOT_FOUND", "没有找到此工作区的接入账号。", "请重新选择历史账号。")
    works = db.execute(
        "SELECT title,published_at,plays,likes,comments,shares,favorites FROM imported_videos "
        "WHERE external_account_id=? ORDER BY published_at DESC,created_at DESC,id LIMIT 8",
        (external_id,),
    ).fetchall()
    if not works:
        raise DomainError("INPUT_MISSING", "此账号还没有可用的历史作品。", "先同步实绩，或清空历史账号选项。")
    platform = {"douyin": "抖音", "xiaohongshu": "小红书"}[account["platform"]]
    labels = {"plays": "播放/阅读", "likes": "点赞", "comments": "评论", "shares": "分享", "favorites": "收藏"}
    lines = [f"{platform}账号的近期历史作品（仅作创作参考，指标以最近一次本地导入为准）。"]
    for index, row in enumerate(works, 1):
        title = " ".join(row["title"].split()) or "未命名作品"
        stats = "，".join(f"{label} {row[key]}" for key, label in labels.items() if row[key] is not None)
        date = row["published_at"] or "发布时间未记录"
        lines.append(f"{index}. {title}（{date}）" + (f"：{stats}" if stats else ""))
    return {
        "kind": "user_supplied_experience", "label": f"{platform}历史实绩 · {account['handle']}",
        "text": "\n".join(lines), "source_url": None, "authorized": True,
    }


@blueprint.post("/api/v1/tasks")
def create_task():
    _, key = require_write()
    raw = json_body()
    intake = CreateWorkspaceTask.model_validate(raw)
    db_path = current_app.config["DB_PATH"]
    if intake.history_account_id:
        integration_storage.ensure_integration_tables(db_path)
    mode = current_app.config["MODEL_MODE"]
    digest = fingerprint(raw, mode)
    scope = "local_operator"
    now = utc_now()
    task_id, run_id = "t_" + uuid4().hex, "r_" + uuid4().hex
    with connect(db_path) as db:
        with immediate(db):
            previous = existing_response(db, scope, key, digest)
            if previous:
                return previous
            if db.execute("SELECT 1 FROM accounts WHERE id=?", (intake.account_id,)).fetchone() is None:
                raise DomainError("NOT_FOUND", "Account not found", "Select an existing account")
            value = intake.model_dump(exclude={"history_account_id"})
            if intake.history_account_id:
                value["materials"].append(_history_material(db, intake.account_id, intake.history_account_id))
            payload = CreateTask.model_validate(value)
            if sum(len(material.text) for material in payload.materials) > 80000:
                raise DomainError("OUTPUT_TOO_LARGE", "Materials exceed 80,000 characters", "Shorten the materials")
            seq = db.execute("UPDATE queue_sequence SET next_seq=next_seq+1 WHERE id=1 RETURNING next_seq").fetchone()[0]
            db.execute("INSERT INTO tasks(id,account_id,input_json,state,mode,current_run_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (task_id, payload.account_id, canonical_bytes(payload).decode("utf-8"), "DRAFT", mode, run_id, now, now))
            db.execute("INSERT INTO runs(id,task_id,kind,state,mode,phase,limits_json,created_at,updated_at,queue_seq) VALUES(?,?,?,?,?,?,?,?,?,?)", (run_id, task_id, "content", "QUEUED", mode, "planning", '{"max_model_calls":7,"max_total_tokens":917504}', now, now, seq))
            for material in payload.materials:
                material_id = "m_" + uuid4().hex
                db.execute("INSERT INTO materials(id,account_id,task_id,kind,label,text,source_url,content_hash,authorized_at) VALUES(?,?,?,?,?,?,?,?,?)", (material_id, payload.account_id, task_id, material.kind, material.label, material.text, material.source_url, sha256_json(material.text), now))
            _event(db, task_id, run_id, "task_created", "planning", "DRAFT", "Task accepted", now)
            data = summary(db, db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
            body = {"data": data, "request_id": request_id()}
            save_response(db, scope, key, digest, body, 202)
    return success(data, 202)
