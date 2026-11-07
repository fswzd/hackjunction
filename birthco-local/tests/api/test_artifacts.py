"""Artifacts listing/download wired to the accepted version (FO-1)."""
import hashlib
import json

from backend.app import create_app
from backend.domain.hashing import content_hash, sha256_json
from backend.storage.db import connect, immediate, migrate
from backend.storage.repository import accept_version_tx

BASE = "http://127.0.0.1:5000"
BRIEF = {
    "input_mode": "idea",
    "objective": "写一篇教程",
    "audience": "初学者",
    "platform": "generic",
    "format": "text",
    "core_promise": "用十分钟讲清楚",
    "requirements": [{"id": "r1", "text": "准确"}],
    "material_ids": [],
    "open_questions": [],
    "route": ["draft", "review"],
    "length_rule": {"minimum": None, "maximum": 20000},
    "edit_scope": None,
}
CONTENT = {
    "titles": ["标题一", "标题二", "标题三"],
    "cover_copy": "封面",
    "segments": [{"segment_id": "s1", "kind": "body", "text": "正文内容", "source_refs": []}],
}


def setup(tmp_path):
    migrate(tmp_path)
    client = create_app({"data_dir": tmp_path}).test_client()
    token = client.get("/api/v1/session", base_url=BASE).get_json()["data"]["csrf_token"]
    headers = {"X-CSRF-Token": token, "Idempotency-Key": "0123456789abcdef", "Origin": BASE}
    return client, headers


def payload(account_id):
    return {"account_id": account_id, "input_mode": "idea", "objective": "写一篇教程", "audience": "初学者",
            "platform": "generic", "format": "text", "style": "清楚",
            "requirements": [{"id": "r1", "text": "准确"}], "materials": [], "preview_requested": False,
            "length_rule": {"minimum": None, "maximum": None}}


def seed_task(tmp_path, client, headers, state="READY", version_id="v_test"):
    account_id = client.post("/api/v1/accounts", json={"name": "个人账号"}, headers=headers,
                             base_url=BASE).get_json()["data"]["account_id"]
    response = client.post("/api/v1/tasks", json=payload(account_id), headers=headers, base_url=BASE)
    task_id = response.get_json()["data"]["task_id"]
    brief_hash = sha256_json(BRIEF)
    hash_value = content_hash(CONTENT)
    with connect(tmp_path / "db.sqlite") as db:
        with immediate(db):
            run_id = db.execute("SELECT current_run_id FROM tasks WHERE id=?", (task_id,)).fetchone()[0]
            db.execute("INSERT INTO briefs(task_id,version,body_json,brief_hash,rule_json,created_at) VALUES(?,1,?,?,'{}','2026-11-07T00:00:00Z')",
                       (task_id, json.dumps(BRIEF), brief_hash))
            db.execute("INSERT INTO content_versions(id,task_id,run_id,ordinal,parent_id,brief_version,brief_hash,content_json,content_hash,created_at) VALUES(?,?,?,1,NULL,1,?,?,?,'2026-11-07T00:00:00Z')",
                       (version_id, task_id, run_id, brief_hash, json.dumps(CONTENT), hash_value))
            db.execute("UPDATE tasks SET state=?,current_brief_version=1,head_version_id=?,ready_version_id=?,row_version=row_version+1 WHERE id=?",
                       (state, version_id, version_id, task_id))
    return task_id, run_id, hash_value


def register_artifact(tmp_path, task_id, run_id, version_id, body: bytes, artifact_id="file1"):
    file_hash = hashlib.sha256(body).hexdigest()
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir(exist_ok=True)
    (artifact_dir / f"{artifact_id}.md").write_bytes(body)
    with connect(tmp_path / "db.sqlite") as db:
        with immediate(db):
            db.execute("INSERT INTO export_batches(id,task_id,version_id,run_id,status,formats_json) VALUES('batch1',?,?,?, 'committed','[\"md\"]')",
                       (task_id, version_id, run_id))
            db.execute("INSERT INTO artifacts(id,batch_id,task_id,version_id,format,relative_path,file_hash,byte_size,status) VALUES(?,'batch1',?,?, 'md',?,?,?,'available')",
                       (artifact_id, task_id, version_id, f"artifacts/{artifact_id}.md", file_hash, len(body)))
    return file_hash


def accept(tmp_path, task_id, version_id, hash_value):
    with connect(tmp_path / "db.sqlite") as db:
        with immediate(db):
            session_id = db.execute("SELECT id FROM app_sessions LIMIT 1").fetchone()[0]
            row_version = db.execute("SELECT row_version FROM tasks WHERE id=?", (task_id,)).fetchone()[0]
            accept_version_tx(db, task_id, version_id, hash_value, row_version, session_id)


def test_artifacts_list_returns_registered_rows_after_accept(tmp_path):
    client, headers = setup(tmp_path)
    task_id, run_id, hash_value = seed_task(tmp_path, client, headers)
    body = "# 标题一\n\n正文内容\n".encode("utf-8")
    file_hash = register_artifact(tmp_path, task_id, run_id, "v_test", body)
    accept(tmp_path, task_id, "v_test", hash_value)

    response = client.get(f"/api/v1/tasks/{task_id}/artifacts", base_url=BASE)
    assert response.status_code == 200
    rows = response.get_json()["data"]
    assert len(rows) == 1
    row = rows[0]
    assert row["artifact_id"] == "file1" and row["version_id"] == "v_test"
    assert row["file_hash"] == file_hash and row["byte_size"] == len(body)
    assert row["relative_path"] == "artifacts/file1.md"
    assert row["download_url"] == "/api/v1/artifacts/file1/download"


def test_download_returns_bytes_matching_file_hash(tmp_path):
    client, headers = setup(tmp_path)
    task_id, run_id, hash_value = seed_task(tmp_path, client, headers)
    body = "# 标题一\n\n正文内容\n".encode("utf-8")
    file_hash = register_artifact(tmp_path, task_id, run_id, "v_test", body)
    accept(tmp_path, task_id, "v_test", hash_value)

    response = client.get("/api/v1/artifacts/file1/download", base_url=BASE)
    assert response.status_code == 200
    assert hashlib.sha256(response.data).hexdigest() == file_hash
    assert response.data == body


def test_unaccepted_task_lists_empty_artifacts(tmp_path):
    client, headers = setup(tmp_path)
    task_id, run_id, _ = seed_task(tmp_path, client, headers)
    response = client.get(f"/api/v1/tasks/{task_id}/artifacts", base_url=BASE)
    assert response.status_code == 200
    assert response.get_json()["data"] == []


def test_unknown_artifact_id_returns_404(tmp_path):
    client, headers = setup(tmp_path)
    response = client.get("/api/v1/artifacts/does-not-exist/download", base_url=BASE)
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "NOT_FOUND"
    missing_task = client.get("/api/v1/tasks/missing-task/artifacts", base_url=BASE)
    assert missing_task.status_code == 404


def test_synthetic_artifact_download_matches_listed_hash(tmp_path):
    """Acceptance without an export batch still yields one downloadable asset."""
    client, headers = setup(tmp_path)
    task_id, run_id, hash_value = seed_task(tmp_path, client, headers)
    accept(tmp_path, task_id, "v_test", hash_value)

    rows = client.get(f"/api/v1/tasks/{task_id}/artifacts", base_url=BASE).get_json()["data"]
    assert len(rows) == 1
    row = rows[0]
    assert row["file_hash"] and row["byte_size"] > 0
    response = client.get(row["download_url"], base_url=BASE)
    assert response.status_code == 200
    assert hashlib.sha256(response.data).hexdigest() == row["file_hash"]
    assert len(response.data) == row["byte_size"]


def test_download_rejects_corrupt_registered_artifact(tmp_path):
    client, headers = setup(tmp_path)
    task_id, run_id, hash_value = seed_task(tmp_path, client, headers)
    body = "# 标题一\n\n正文内容\n".encode("utf-8")
    register_artifact(tmp_path, task_id, run_id, "v_test", body)
    accept(tmp_path, task_id, "v_test", hash_value)
    (tmp_path / "artifacts" / "file1.md").write_bytes(b"tampered")

    response = client.get("/api/v1/artifacts/file1/download", base_url=BASE)
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "ARTIFACT_MISSING"
