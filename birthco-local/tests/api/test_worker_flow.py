import hashlib
from uuid import uuid4

from backend.app import create_app
from backend.domain.errors import DomainError
from backend.storage.db import connect, migrate
from backend.worker.executor import Work, Worker


BASE = "http://127.0.0.1:5000"


class Workbench:
    def __init__(self, data_dir):
        migrate(data_dir)
        self.worker = Worker(data_dir)
        self.client = create_app({"data_dir": data_dir, "model_mode": "mock"}).test_client()
        self.token = self.read("/session")["csrf_token"]
        self.account = self.write("/accounts", {"name": "验收账号"}, status=201)["account_id"]

    def read(self, route):
        response = self.client.get("/api/v1" + route, base_url=BASE)
        assert response.status_code == 200, response.get_json()
        return response.get_json()["data"]

    def write(self, route, payload, *, status=202, key=None):
        response = self.client.post("/api/v1" + route, json=payload, base_url=BASE, headers={
            "Origin": BASE, "X-CSRF-Token": self.token, "Idempotency-Key": key or uuid4().hex,
        })
        assert response.status_code == status, response.get_json()
        return response.get_json().get("data")

    def create(self, *, source=None, preview=False):
        materials = [{"kind": "source_text", "label": "商单简报", "text": source,
                      "source_url": None, "authorized": True}] if source else []
        task = self.write("/tasks", {"account_id": self.account, "input_mode": "idea",
                                    "objective": "写城市散步指南", "audience": "第一次参加的读者",
                                    "style": "清晰", "requirements": [{"id": "r1", "text": "写清出发点"}],
                                    "materials": materials, "preview_requested": preview,
                                    "length_rule": {"minimum": None, "maximum": 20000}})
        return "/tasks/" + task["task_id"]

    def confirm(self, path):
        task = self.read(path)
        brief = self.read(path + "/brief")
        assert task["state"] == "WAITING_CONFIRMATION" and not brief["confirmed"]
        assert not self.read(path + "/versions")
        payload = {"expected_row_version": task["row_version"], "expected_brief_version": brief["brief_version"],
                   "brief_hash": brief["brief_hash"]}
        key = uuid4().hex
        assert self.write(path + "/confirm", payload, key=key) == self.write(path + "/confirm", payload, key=key)


def test_seven_roles_persist_review_preview_revision_and_asset(tmp_path):
    app = Workbench(tmp_path)
    path = app.create(source="品牌：城市脚步\n产品：周末步行指南", preview=True)
    assert app.worker.once() and not app.worker.once()
    assert "preview" in app.read(path + "/brief")["brief"]["route"]
    app.confirm(path)
    assert app.worker.once()
    ready = app.read(path)
    assert ready["state"] == "READY"
    first = app.read(path + "/versions")[0]
    approval = {"expected_row_version": ready["row_version"], "version_id": first["version_id"],
                "content_hash": first["content_hash"]}
    app.write(path + "/accept", approval, status=409)
    assert app.worker.once()
    previews = app.read(path + "/previews")
    assert previews[0]["state"] == "COMPLETED"
    assert previews[0]["metrics"]["started"] == 2
    preview_path = "/previews/" + previews[0]["preview_id"]
    assert app.read(preview_path + "/events")["items"]
    assert app.read(preview_path + "/analysis")["analysis"]["findings"]
    event_steps = {event["step"] for event in app.read(path + "/events")["items"]}
    assert {"pr_intake", "operator", "scout", "draft", "review", "audience", "analysis"} <= event_steps

    app.write(path + "/revise", {**approval, "note": "开头先写出发前的准备"})
    assert app.worker.once() and app.worker.once()
    first_after, second = app.read(path + "/versions")
    assert first_after == first
    assert second["parent_version_id"] == first["version_id"]
    assert second["content_hash"] != first["content_hash"]
    assert app.read(path + "/feedback")[0]["kind"] == "edit_request"
    ready = app.read(path)
    accepted = app.write(path + "/accept", {"expected_row_version": ready["row_version"],
                          "version_id": second["version_id"], "content_hash": second["content_hash"]}, status=200)
    assert accepted["state"] == "ACCEPTED"
    asset = app.read(path + "/artifacts")[0]
    downloaded = app.client.get(asset["download_url"], base_url=BASE)
    assert downloaded.status_code == 200
    assert hashlib.sha256(downloaded.data).hexdigest() == asset["file_hash"]
    with connect(tmp_path / "db.sqlite") as db:
        calls = db.execute("SELECT role,status FROM model_calls WHERE task_id=?", (accepted["task_id"],)).fetchall()
        assert {row["role"] for row in calls} == {"pr_analyst", "operator", "scout", "director", "reviewer", "audience", "analyst"}
        assert all(row["status"] == "received" for row in calls)


def test_missing_commercial_fields_can_be_supplied_idempotently(tmp_path):
    app = Workbench(tmp_path)
    path = app.create(source="周末散步商单")
    assert app.worker.once()
    waiting = app.read(path)
    assert waiting["state"] == "WAITING_INPUT"
    assert {question["id"] for question in app.read(path + "/input")["questions"]} >= {"missing_brand", "missing_product"}
    key = uuid4().hex
    payload = {"expected_row_version": waiting["row_version"],
               "answers": {"missing_brand": "城市脚步", "missing_product": "周末步行指南"}, "materials": []}
    assert app.write(path + "/input", payload, key=key) == app.write(path + "/input", payload, key=key)
    assert app.worker.once()
    app.confirm(path)
    assert app.worker.once()
    assert app.read(path)["state"] == "READY"


def test_pre_call_failure_can_resume_and_ready_can_cancel(tmp_path, monkeypatch):
    app = Workbench(tmp_path)
    path = app.create()

    def fail_before_call(_work):
        raise DomainError("MODEL_UNAVAILABLE", "Configuration unavailable", "Inspect model configuration")

    with monkeypatch.context() as patch:
        patch.setattr(Work, "execute", fail_before_call)
        assert app.worker.once()
    failure = app.read(path)
    assert failure["state"] == "FAILED" and failure["error"]["code"] == "MODEL_UNAVAILABLE"
    app.write(path + "/resume", {"expected_row_version": failure["row_version"], "strategy": "continue_checkpoint",
                                 "acknowledged_unknown_charge": False})
    assert app.worker.once()
    app.confirm(path)
    assert app.worker.once()
    ready = app.read(path)
    assert app.write(path + "/cancel", {"expected_row_version": ready["row_version"]}, status=200)["state"] == "CANCELLED"
    with connect(tmp_path / "db.sqlite") as db:
        assert {row["role"] for row in db.execute("SELECT role FROM model_calls")} == {"operator", "director", "reviewer"}
