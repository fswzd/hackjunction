import json

from backend.app import create_app
from backend.domain.schemas import TaskSummary
from backend.storage.db import connect, migrate
from backend.storage.queue import Queue

BASE = "http://127.0.0.1:5000"


def setup(tmp_path):
    migrate(tmp_path)
    client = create_app({"data_dir": tmp_path}).test_client()
    token = client.get("/api/v1/session", base_url=BASE).get_json()["data"]["csrf_token"]
    headers = {"X-CSRF-Token": token, "Idempotency-Key": "0123456789abcdef", "Origin": BASE}
    return client, headers


def payload(account_id, *, mode="idea"):
    return {"account_id": account_id, "input_mode": mode, "objective": "写一篇教程", "audience": "初学者", "platform": "generic", "format": "text", "style": "清楚", "requirements": [{"id": "r1", "text": "准确"}], "materials": [], "preview_requested": False, "length_rule": {"minimum": None, "maximum": None}}


def account(client, headers):
    return client.post("/api/v1/accounts", json={"name": "个人账号"}, headers=headers, base_url=BASE).get_json()["data"]["account_id"]


def test_task_create_stable_idempotency_and_read_dtos(tmp_path):
    client, headers = setup(tmp_path)
    account_id = account(client, headers)
    headers["Idempotency-Key"] = "1123456789abcdef"
    body = payload(account_id, mode="existing_draft")
    first = client.post("/api/v1/tasks", json=body, headers=headers, base_url=BASE)
    assert first.status_code == 202
    dto = TaskSummary.model_validate(first.get_json()["data"])
    assert dto.state == "DRAFT" and dto.queue_position == 1 and dto.mode == "mock"
    assert dto.usage.total_tokens is None
    task_id = dto.task_id
    Queue(tmp_path / "db.sqlite").claim("worker")
    replay = client.post("/api/v1/tasks", json=body, headers=headers, base_url=BASE)
    assert replay.status_code == 202 and replay.get_json() == first.get_json()
    changed = {**body, "objective": "另一篇教程"}
    conflict = client.post("/api/v1/tasks", json=changed, headers=headers, base_url=BASE)
    assert conflict.status_code == 409 and conflict.get_json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    with connect(tmp_path / "db.sqlite") as db:
        assert db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
    listed = client.get("/api/v1/tasks", query_string={"account_id": account_id}, base_url=BASE).get_json()["data"]
    assert len(listed) == 1 and listed[0]["task_id"] == task_id
    assert client.get(f"/api/v1/tasks/{task_id}", base_url=BASE).get_json()["data"]["state"] == "PLANNING"
    assert client.get(f"/api/v1/tasks/{task_id}/materials", base_url=BASE).get_json()["data"] == []
    events = client.get(f"/api/v1/tasks/{task_id}/events", query_string={"after_seq": 0, "limit": 1}, base_url=BASE).get_json()["data"]
    assert events["items"][0]["seq"] == 1 and events["has_more"] is True
    assert client.get(f"/api/v1/tasks/{task_id}/events", query_string={"after_seq": events["next_after_seq"]}, base_url=BASE).get_json()["data"]["items"][0]["seq"] == 2


def test_schema_limits_and_missing_resources_have_no_write(tmp_path):
    client, headers = setup(tmp_path)
    account_id = account(client, headers)
    headers["Idempotency-Key"] = "1123456789abcdef"
    wrong = {**payload(account_id), "unexpected": True}
    assert client.post("/api/v1/tasks", json=wrong, headers=headers, base_url=BASE).status_code == 422
    assert client.post("/api/v1/tasks", data="{bad", content_type="application/json", headers=headers, base_url=BASE).status_code == 400
    huge = "x" * (1048576 + 1)
    assert client.post("/api/v1/tasks", data=huge, content_type="application/json", headers=headers, base_url=BASE).status_code == 413
    assert client.get("/api/v1/tasks/unknown", base_url=BASE).status_code == 404
    assert client.get("/api/v1/tasks", query_string={"account_id": account_id, "limit": 101}, base_url=BASE).status_code == 400
    with connect(tmp_path / "db.sqlite") as db:
        assert db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


def test_account_partition_filters_task_list(tmp_path):
    client, headers = setup(tmp_path)
    first = account(client, headers)
    headers["Idempotency-Key"] = "2123456789abcdef"
    second = account(client, headers)
    headers["Idempotency-Key"] = "3123456789abcdef"
    created = client.post("/api/v1/tasks", json=payload(first), headers=headers, base_url=BASE)
    assert created.status_code == 202
    assert client.get("/api/v1/tasks", query_string={"account_id": second}, base_url=BASE).get_json()["data"] == []
    assert len(client.get("/api/v1/tasks", query_string={"account_id": first}, base_url=BASE).get_json()["data"]) == 1


def test_account_create_idempotency_and_material_scope(tmp_path):
    client, headers = setup(tmp_path)
    first = client.post("/api/v1/accounts", json={"name": "账号"}, headers=headers, base_url=BASE)
    repeat = client.post("/api/v1/accounts", json={"name": "账号"}, headers=headers, base_url=BASE)
    assert repeat.status_code == 201 and repeat.get_json() == first.get_json()
    assert client.post("/api/v1/accounts", json={"name": "另一个"}, headers=headers, base_url=BASE).status_code == 409
    aid = first.get_json()["data"]["account_id"]
    headers["Idempotency-Key"] = "1123456789abcdef"
    body = payload(aid)
    body["materials"] = [{"kind": "source_text", "label": "来源", "text": "原始素材", "source_url": None, "authorized": True}]
    created = client.post("/api/v1/tasks", json=body, headers=headers, base_url=BASE)
    assert created.status_code == 202
    task_id = created.get_json()["data"]["task_id"]
    material = client.get(f"/api/v1/tasks/{task_id}/materials", base_url=BASE).get_json()["data"][0]
    assert material["task_id"] == task_id and material["account_id"] == aid and material["text"] == "原始素材"
    assert client.get("/api/v1/tasks/unknown/materials", base_url=BASE).status_code == 404


def test_material_total_limit_rejects_before_writes(tmp_path):
    client, headers = setup(tmp_path)
    aid = account(client, headers)
    headers["Idempotency-Key"] = "1123456789abcdef"
    body = payload(aid)
    body["materials"] = [{"kind": "source_text", "label": "m", "text": "x" * 20000, "source_url": None, "authorized": True} for _ in range(5)]
    response = client.post("/api/v1/tasks", json=body, headers=headers, base_url=BASE)
    assert response.status_code == 413
    with connect(tmp_path / "db.sqlite") as db:
        assert db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
