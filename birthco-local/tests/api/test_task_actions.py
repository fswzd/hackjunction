import json

from backend.app import create_app
from backend.domain.hashing import content_hash, sha256_json
from backend.storage.db import connect, immediate, migrate
from backend.storage.queue import Queue

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


def account(client, headers):
    return client.post("/api/v1/accounts", json={"name": "个人账号"}, headers=headers, base_url=BASE).get_json()["data"]["account_id"]


def created_task(client, headers, tmp_path, key):
    headers["Idempotency-Key"] = key
    account_id = account(client, headers)
    response = client.post("/api/v1/tasks", json=payload(account_id), headers=headers, base_url=BASE)
    assert response.status_code == 202
    task_id = response.get_json()["data"]["task_id"]
    with connect(tmp_path / "db.sqlite") as db:
        run_id = db.execute("SELECT current_run_id FROM tasks WHERE id=?", (task_id,)).fetchone()[0]
    return task_id, run_id


def seed_waiting_confirmation(client, headers, tmp_path, task_id, run_id):
    lease = Queue(tmp_path / "db.sqlite").claim("worker")
    assert lease is not None
    Queue(tmp_path / "db.sqlite").release(lease, "WAITING")
    brief_hash = sha256_json(BRIEF)
    with connect(tmp_path / "db.sqlite") as db:
        with immediate(db):
            db.execute("INSERT INTO briefs(task_id,version,body_json,brief_hash,rule_json,created_at) VALUES(?,1,?,?,'{}','2026-11-07T00:00:00Z')",
                       (task_id, json.dumps(BRIEF), brief_hash))
            db.execute("UPDATE tasks SET state='WAITING_CONFIRMATION',current_brief_version=1,row_version=row_version+1 WHERE id=?", (task_id,))
    return brief_hash


def seed_ready_version(tmp_path, task_id, run_id, brief_hash):
    hash_value = content_hash(CONTENT)
    with connect(tmp_path / "db.sqlite") as db:
        with immediate(db):
            db.execute("INSERT INTO briefs(task_id,version,body_json,brief_hash,rule_json,created_at) VALUES(?,1,?,?,'{}','2026-11-07T00:00:00Z')",
                       (task_id, json.dumps(BRIEF), brief_hash))
            db.execute("INSERT INTO content_versions(id,task_id,run_id,ordinal,parent_id,brief_version,brief_hash,content_json,content_hash,created_at) VALUES('v_test',?,?,1,NULL,1,?,?,?,'2026-11-07T00:00:00Z')",
                       (task_id, run_id, brief_hash, json.dumps(CONTENT), hash_value))
            db.execute("UPDATE tasks SET state='READY',current_brief_version=1,head_version_id='v_test',ready_version_id='v_test',row_version=row_version+1 WHERE id=?", (task_id,))
    return hash_value


def test_confirm_brief_is_idempotent_and_cas_checked(tmp_path):
    client, headers = setup(tmp_path)
    task_id, run_id = created_task(client, headers, tmp_path, "1123456789abcdef")
    brief_hash = seed_waiting_confirmation(client, headers, tmp_path, task_id, run_id)
    brief = client.get(f"/api/v1/tasks/{task_id}/brief", base_url=BASE).get_json()["data"]
    assert brief["brief_version"] == 1 and brief["brief_hash"] == brief_hash and brief["confirmed"] is False

    headers["Idempotency-Key"] = "2123456789abcdef"
    body = {"expected_row_version": 2, "expected_brief_version": 1, "brief_hash": brief_hash}
    first = client.post(f"/api/v1/tasks/{task_id}/confirm", json=body, headers=headers, base_url=BASE)
    assert first.status_code == 202
    assert first.get_json()["data"]["state"] == "QUEUED"
    assert first.get_json()["data"]["row_version"] == 3
    replay = client.post(f"/api/v1/tasks/{task_id}/confirm", json=body, headers=headers, base_url=BASE)
    assert replay.status_code == 202 and replay.get_json() == first.get_json()

    headers["Idempotency-Key"] = "3123456789abcdef"
    stale = client.post(f"/api/v1/tasks/{task_id}/confirm", json=body, headers=headers, base_url=BASE)
    assert stale.status_code == 409 and stale.get_json()["error"]["code"] == "VERSION_CONFLICT"


def test_edit_brief_creates_new_version_and_refreshes_gate(tmp_path):
    client, headers = setup(tmp_path)
    task_id, run_id = created_task(client, headers, tmp_path, "1123456789abcdef")
    seed_waiting_confirmation(client, headers, tmp_path, task_id, run_id)
    edited = json.loads(json.dumps(BRIEF))
    edited["requirements"].append({"id": "rev-2", "text": "开场更具体"})
    headers["Idempotency-Key"] = "2123456789abcdef"
    response = client.put(f"/api/v1/tasks/{task_id}/brief", json={
        "expected_row_version": 2, "expected_brief_version": 1, "brief": edited,
    }, headers=headers, base_url=BASE)
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["state"] == "WAITING_CONFIRMATION" and data["brief_version"] == 2 and data["row_version"] == 3
    brief = client.get(f"/api/v1/tasks/{task_id}/brief", base_url=BASE).get_json()["data"]
    assert brief["brief_version"] == 2 and brief["brief"]["requirements"][-1]["text"] == "开场更具体"
    assert brief["confirmed"] is False


def test_accept_frozen_ready_version_and_record_session(tmp_path):
    client, headers = setup(tmp_path)
    task_id, run_id = created_task(client, headers, tmp_path, "1123456789abcdef")
    hash_value = seed_ready_version(tmp_path, task_id, run_id, sha256_json(BRIEF))
    versions = client.get(f"/api/v1/tasks/{task_id}/versions", base_url=BASE).get_json()["data"]
    assert len(versions) == 1 and versions[0]["version_id"] == "v_test" and versions[0]["content_hash"] == hash_value
    detail = client.get(f"/api/v1/tasks/{task_id}/versions/v_test", base_url=BASE).get_json()["data"]
    assert detail["content"]["segments"][0]["text"] == "正文内容" and detail["validation"] == "pending"

    headers["Idempotency-Key"] = "2123456789abcdef"
    body = {"expected_row_version": 1, "version_id": "v_test", "content_hash": hash_value}
    response = client.post(f"/api/v1/tasks/{task_id}/accept", json=body, headers=headers, base_url=BASE)
    assert response.status_code == 200
    assert response.get_json()["data"]["state"] == "ACCEPTED"
    with connect(tmp_path / "db.sqlite") as db:
        row = db.execute("SELECT task_id,version_id,content_hash,session_id FROM acceptances").fetchone()
        assert row["task_id"] == task_id and row["version_id"] == "v_test" and row["content_hash"] == hash_value
        assert row["session_id"]


def test_accept_rejects_wrong_hash(tmp_path):
    client, headers = setup(tmp_path)
    task_id, run_id = created_task(client, headers, tmp_path, "1123456789abcdef")
    seed_ready_version(tmp_path, task_id, run_id, sha256_json(BRIEF))
    headers["Idempotency-Key"] = "2123456789abcdef"
    response = client.post(f"/api/v1/tasks/{task_id}/accept", json={
        "expected_row_version": 1, "version_id": "v_test", "content_hash": "a" * 64,
    }, headers=headers, base_url=BASE)
    assert response.status_code == 409 and response.get_json()["error"]["code"] == "CONDITIONS_MISMATCH"
    with connect(tmp_path / "db.sqlite") as db:
        assert db.execute("SELECT count(*) FROM acceptances").fetchone()[0] == 0


def test_cancel_task_and_reject_terminal_state(tmp_path):
    client, headers = setup(tmp_path)
    task_id, _ = created_task(client, headers, tmp_path, "1123456789abcdef")
    headers["Idempotency-Key"] = "2123456789abcdef"
    cancelled = client.post(f"/api/v1/tasks/{task_id}/cancel", json={"expected_row_version": 0}, headers=headers, base_url=BASE)
    assert cancelled.status_code == 200 and cancelled.get_json()["data"]["state"] == "CANCELLED"
    headers["Idempotency-Key"] = "3123456789abcdef"
    again = client.post(f"/api/v1/tasks/{task_id}/cancel", json={"expected_row_version": 1}, headers=headers, base_url=BASE)
    assert again.status_code == 409 and again.get_json()["error"]["code"] == "INVALID_TRANSITION"


def test_feedback_records_edit_request(tmp_path):
    client, headers = setup(tmp_path)
    task_id, run_id = created_task(client, headers, tmp_path, "1123456789abcdef")
    seed_ready_version(tmp_path, task_id, run_id, sha256_json(BRIEF))
    headers["Idempotency-Key"] = "2123456789abcdef"
    body = {"version_id": "v_test", "kind": "edit_request", "text": "开场更具体", "platform": None,
            "window_start": None, "window_end": None, "metrics": {}, "source_ref": None}
    created = client.post(f"/api/v1/tasks/{task_id}/feedback", json=body, headers=headers, base_url=BASE)
    assert created.status_code == 201
    data = created.get_json()["data"]
    assert data["kind"] == "edit_request" and data["text"] == "开场更具体" and data["evidence_kind"] == "user_statement"
    listed = client.get(f"/api/v1/tasks/{task_id}/feedback", base_url=BASE).get_json()["data"]
    assert len(listed) == 1 and listed[0]["feedback_id"] == data["feedback_id"]
    missing = client.post(f"/api/v1/tasks/{task_id}/feedback", json={**body, "version_id": "v_missing"}, headers={**headers, "Idempotency-Key": "3123456789abcdef"}, base_url=BASE)
    assert missing.status_code == 404
