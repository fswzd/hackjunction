"""账号登录 / 经验库 API —— 离线测试（登录线程用桩代替扫码，无网络、无浏览器）。"""
from __future__ import annotations

import time

import pytest

from backend.app import create_app
from backend.integrations import intake, storage
from backend.storage.db import migrate

BASE = "http://127.0.0.1:5000"


def _client(tmp_path):
    migrate(tmp_path)
    client = create_app({"data_dir": tmp_path}).test_client()
    token = client.get("/api/v1/session", base_url=BASE).get_json()["data"]["csrf_token"]
    headers = {"X-CSRF-Token": token, "Idempotency-Key": "loginapi1234567890ab",
               "Origin": BASE}
    return client, headers


def _register(client, headers, platform="douyin", handle="dy_login"):
    account_id = client.post("/api/v1/accounts", json={"name": "登录测试分区"},
                             headers=headers, base_url=BASE).get_json()["data"]["account_id"]
    created = client.post("/api/v1/accounts/external", headers=headers, base_url=BASE, json={
        "account_id": account_id, "platform": platform, "handle": handle,
        "display_name": "测试号", "profile_url": None}).get_json()["data"]
    return created["external_account_id"]


def _wait_status(client, external_id, predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = client.get(f"/api/v1/accounts/external/{external_id}/status",
                             base_url=BASE).get_json()["data"]
        if predicate(payload):
            return payload
        time.sleep(0.02)
    raise AssertionError(f"status 未在 {timeout}s 内满足条件：{payload}")


def test_login_thread_stub_success_records_logged_in_and_experience(tmp_path, monkeypatch):
    client, headers = _client(tmp_path)
    external_id = _register(client, headers)

    def stub(db_path, external_account_id, *, count=10):
        storage.set_session_state(db_path, external_account_id, status="logged_in")
        return {"imported": 0, "baseline_plays": None, "imported_count": 0}

    monkeypatch.setattr(intake, "login_and_import", stub)
    started = client.post(f"/api/v1/accounts/external/{external_id}/login",
                          headers={**headers, "Idempotency-Key": "loginstart1234567ab"},
                          base_url=BASE)
    assert started.status_code == 202
    assert started.get_json()["data"]["session_status"] == "logging_in"

    payload = _wait_status(client, external_id, lambda p: p["session_status"] == "logged_in")
    assert payload["login_error"] is None
    exp = client.get(f"/api/v1/accounts/external/{external_id}/experience",
                     base_url=BASE).get_json()["data"]
    assert exp["imported_count"] == 0 and exp["totals"]["plays"] == 0
    assert exp["platform"] == "douyin"


def test_login_thread_failure_surfaces_login_error(tmp_path, monkeypatch):
    from backend.integrations.douyin import session as douyin_session
    client, headers = _client(tmp_path)
    external_id = _register(client, headers)

    def boom(external_account_id, *, headless=False, session_file=None):
        raise RuntimeError("未安装 playwright，请改用 manual 导入")

    monkeypatch.setattr(douyin_session, "login_interactive", boom)
    started = client.post(f"/api/v1/accounts/external/{external_id}/login",
                          headers={**headers, "Idempotency-Key": "loginfail12345678ab"},
                          base_url=BASE)
    assert started.status_code == 202

    payload = _wait_status(client, external_id, lambda p: p["session_status"] != "logging_in")
    assert payload["session_status"] == "none", "登录线程失败后不应卡在 logging_in"
    assert "playwright" in (payload["login_error"] or ""), "登录错误应可操作、可轮询"


@pytest.mark.parametrize("platform", ["douyin", "xiaohongshu"])
def test_restart_reuses_saved_session_and_refreshes_metrics(tmp_path, monkeypatch, platform):
    from backend.integrations.browser_session import save_session
    from backend.integrations.douyin import fetch as douyin_fetch
    from backend.integrations.xiaohongshu import fetch as xiaohongshu_fetch
    from backend.integrations.types import PerfVideo

    monkeypatch.delenv("BIRTHCO_SESSION_DIR", raising=False)
    client, headers = _client(tmp_path)
    external_id = _register(client, headers, platform=platform)
    path = f"/api/v1/accounts/external/{external_id}"
    launches = []
    plays = iter([100, 245])

    class BrowserContext:
        def storage_state(self, *, indexed_db):
            assert indexed_db
            return {"cookies": [], "origins": []}

    def login(external_account_id, *, session_file):
        launches.append(external_account_id)
        assert session_file.parent == tmp_path / "sessions"
        save_session(BrowserContext(), session_file)
        return session_file

    def recent(external_account_id, *, count, session_file):
        assert session_file.is_file()
        return [PerfVideo(platform_video_id="v1", title="测试作品", plays=next(plays))]

    monkeypatch.setattr(intake._platform_session(platform), "login_interactive", login)
    fetch = douyin_fetch if platform == "douyin" else xiaohongshu_fetch
    monkeypatch.setattr(fetch, "fetch_recent_works", recent)

    for number, expected_plays in enumerate((100, 245)):
        # New app instance with the same data directory, as after a restart.
        client, headers = _client(tmp_path)
        started = client.post(path + "/login", headers={
            **headers, "Idempotency-Key": f"restart-login-key-{number}",
        }, base_url=BASE)
        assert started.status_code == 202
        status = _wait_status(client, external_id, lambda p: not p["job_running"])
        assert status["session_status"] == "logged_in"
        assert status["last_synced_at"]
        assert status["last_sync_count"] == 1
        assert status["imported_count"] == 1
        assert status["baseline_plays"] == expected_plays
        works = client.get(path + "/videos", base_url=BASE).get_json()["data"]
        assert works[0]["plays"] == expected_plays
    assert launches == [external_id]


def test_selected_history_is_frozen_into_task(tmp_path):
    client, headers = _client(tmp_path)
    external_id = _register(client, headers)
    path = f"/api/v1/accounts/external/{external_id}"
    imported = client.post(path + "/import", headers=headers, base_url=BASE, json={
        "videos": [{"platform_video_id": "history1", "title": "我的历史作品", "likes": 42}],
    })
    assert imported.status_code == 201
    account = client.get("/api/v1/accounts", base_url=BASE).get_json()["data"][0]
    response = client.post("/api/v1/tasks", headers=headers, base_url=BASE, json={
        "account_id": account["account_id"], "input_mode": "idea", "objective": "创作一篇新稿",
        "audience": "入门读者", "style": "清楚", "requirements": [{"id": "r1", "text": "内容实用"}],
        "materials": [], "length_rule": {"minimum": None, "maximum": None},
        "history_account_id": external_id,
    })
    assert response.status_code == 202
    task_id = response.get_json()["data"]["task_id"]
    materials = client.get(f"/api/v1/tasks/{task_id}/materials", base_url=BASE).get_json()["data"]
    assert len(materials) == 1
    assert materials[0]["kind"] == "user_supplied_experience"
    assert "我的历史作品" in materials[0]["text"] and "点赞 42" in materials[0]["text"]


def test_experience_aggregates_manual_import(tmp_path):
    client, headers = _client(tmp_path)
    external_id = _register(client, headers)
    videos = {"source": "manual", "videos": [
        {"platform_video_id": "v1", "title": "作品一", "plays": 1000, "likes": 10,
         "comments": 2, "shares": 1, "favorites": 5,
         "top_comments": [{"text": "讲得清楚", "likes": 5}]},
        {"platform_video_id": "v2", "title": "作品二", "plays": 3000, "likes": 30,
         "top_comments": [{"text": "热评", "likes": 120}]},
        {"platform_video_id": "v3", "plays": 2000, "likes": 20},
    ]}
    imported = client.post(f"/api/v1/accounts/external/{external_id}/import",
                           headers={**headers, "Idempotency-Key": "importexp12345678ab"},
                           base_url=BASE, json=videos).get_json()["data"]
    assert imported["imported"] == 3 and imported["baseline_plays"] == 2000

    exp = client.get(f"/api/v1/accounts/external/{external_id}/experience",
                     base_url=BASE).get_json()["data"]
    assert exp["imported_count"] == 3 and exp["baseline_plays"] == 2000
    assert exp["totals"] == {"plays": 6000, "likes": 60, "comments": 2,
                             "shares": 1, "favorites": 5}
    assert exp["top_comments"][0]["text"] == "热评", "热评按点赞降序"
    assert len(exp["recent_videos"]) == 3

    status = client.get(f"/api/v1/accounts/external/{external_id}/status",
                        base_url=BASE).get_json()["data"]
    assert status["imported_count"] == 3 and status["baseline_plays"] == 2000


def test_status_and_login_unknown_account_returns_404(tmp_path):
    client, headers = _client(tmp_path)
    for method, path in (("get", "/api/v1/accounts/external/ext_missing/status"),
                         ("post", "/api/v1/accounts/external/ext_missing/login")):
        response = getattr(client, method)(
            path, headers={**headers, "Idempotency-Key": "unknownext12345678ab"},
            base_url=BASE)
        assert response.status_code == 404
        assert response.get_json()["data"]["error"]["code"] == "NOT_FOUND"


def test_delete_external_account_rolls_back_registration(tmp_path):
    client, headers = _client(tmp_path)
    external_id = _register(client, headers)
    videos = {"source": "manual", "videos": [
        {"platform_video_id": "v1", "title": "作品一", "plays": 1000, "likes": 10},
        {"platform_video_id": "v2", "plays": 2000, "likes": 20},
    ]}
    imported = client.post(f"/api/v1/accounts/external/{external_id}/import",
                           headers={**headers, "Idempotency-Key": "delexpimport1234567ab"},
                           base_url=BASE, json=videos).get_json()["data"]
    assert imported["imported"] == 2

    deleted = client.delete(f"/api/v1/accounts/external/{external_id}",
                            headers={**headers, "Idempotency-Key": "deleteext1234567890ab"},
                            base_url=BASE)
    assert deleted.status_code == 200
    assert deleted.get_json()["data"]["removed_videos"] == 2, "经验库数据一并回滚"
    listed = client.get("/api/v1/accounts/external", base_url=BASE).get_json()["data"]
    assert all(row["external_account_id"] != external_id for row in listed), "列表不留痕"
    assert client.get(f"/api/v1/accounts/external/{external_id}/status",
                      base_url=BASE).status_code == 404
    again = client.delete(f"/api/v1/accounts/external/{external_id}",
                          headers={**headers, "Idempotency-Key": "deleteext2234567890ab"},
                          base_url=BASE)
    assert again.status_code == 404, "重复删除返回 404 而非假成功"


def test_import_auth_error_marks_expired_not_logged_in(tmp_path, monkeypatch):
    client, headers = _client(tmp_path)
    external_id = _register(client, headers)

    def boom(db_path, external_account_id, *, count=10):
        raise RuntimeError("接口返回失败：登录已过期")

    monkeypatch.setattr(intake, "import_via_adapter", boom)
    response = client.post(f"/api/v1/accounts/external/{external_id}/import",
                           headers={**headers, "Idempotency-Key": "autherr12345678901ab"},
                           base_url=BASE, json={"source": "adapter", "count": 5})
    assert response.status_code == 502
    status = client.get(f"/api/v1/accounts/external/{external_id}/status",
                        base_url=BASE).get_json()["data"]
    assert status["session_status"] == "expired", "平台不认的会话不得停留在已登录假象上"
    assert "登录已过期" in (status["import_error"] or "")


def test_import_non_auth_error_marks_pending(tmp_path, monkeypatch):
    client, headers = _client(tmp_path)
    external_id = _register(client, headers)

    def boom(db_path, external_account_id, *, count=10):
        raise RuntimeError("抓取失败：平台路由已变化")

    monkeypatch.setattr(intake, "import_via_adapter", boom)
    response = client.post(f"/api/v1/accounts/external/{external_id}/import",
                           headers={**headers, "Idempotency-Key": "routeerr1234567890ab"},
                           base_url=BASE, json={"source": "adapter", "count": 5})
    assert response.status_code == 502
    status = client.get(f"/api/v1/accounts/external/{external_id}/status",
                        base_url=BASE).get_json()["data"]
    assert status["session_status"] == "pending_adapter_setup", "会话有效仅数据通道故障"
