from backend.app import create_app
from backend.storage.db import connect, migrate

BASE = "http://127.0.0.1:5000"


def make_client(tmp_path):
    migrate(tmp_path)
    return create_app({"data_dir": tmp_path}).test_client()


def test_bootstrap_cookie_csrf_and_session_gate(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/api/v1/accounts", base_url=BASE).status_code == 401
    response = client.get("/api/v1/session", base_url=BASE)
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert "SameSite=Strict" in response.headers["Set-Cookie"]
    data = response.get_json()["data"]
    assert data["capabilities"] == ["creator"]
    assert client.get("/api/v1/accounts", base_url=BASE).status_code == 200
    no_csrf = client.post("/api/v1/accounts", json={"name": "账号"}, headers={"Idempotency-Key": "0123456789abcdef"}, base_url=BASE)
    assert no_csrf.status_code == 401
    wrong_csrf = client.post("/api/v1/accounts", json={"name": "账号"}, headers={"Idempotency-Key": "0123456789abcdef", "X-CSRF-Token": "wrong"}, base_url=BASE)
    assert wrong_csrf.status_code == 401
    good = client.post("/api/v1/accounts", json={"name": "账号"}, headers={"Idempotency-Key": "0123456789abcdef", "X-CSRF-Token": data["csrf_token"]}, base_url=BASE)
    assert good.status_code == 201


def test_cross_origin_and_wrong_host_rejected_before_session_creation(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/api/v1/session", headers={"Origin": "https://attacker.example"}, base_url=BASE).status_code == 403
    assert client.get("/api/v1/session", headers={"Sec-Fetch-Site": "cross-site"}, base_url=BASE).status_code == 403
    assert client.get("/api/v1/session", base_url="http://localhost:5000").status_code == 403
    with connect(tmp_path / "db.sqlite") as db:
        assert db.execute("SELECT count(*) FROM app_sessions").fetchone()[0] == 0


def test_host_config_and_migration_are_startup_gates(tmp_path):
    import pytest
    from backend.domain.errors import DomainError
    with pytest.raises(ValueError):
        create_app({"data_dir": tmp_path, "host": "0.0.0.0"})
    with pytest.raises(DomainError):
        create_app({"data_dir": tmp_path})


def test_global_write_gate_and_csrf_idempotency(tmp_path):
    client = make_client(tmp_path)
    first = client.get("/api/v1/session", base_url=BASE).get_json()["data"]["csrf_token"]
    second = client.get("/api/v1/session", base_url=BASE).get_json()["data"]["csrf_token"]
    # 同会话重复 bootstrap 必须幂等（token 为会话派生值）。旧行为每次轮换，
    # 多份前端会话缓存互踩后写请求报 "CSRF token invalid"。
    assert first == second
    missing_key = client.post("/api/v1/accounts", json={"name": "账号"}, headers={"X-CSRF-Token": second}, base_url=BASE)
    assert missing_key.status_code == 422
    unknown = client.get("/api/v1/not-a-route", base_url=BASE)
    assert unknown.status_code == 404 and unknown.get_json()["error"]["code"] == "NOT_FOUND"
    with connect(tmp_path / "db.sqlite") as db:
        assert db.execute("SELECT count(*) FROM accounts").fetchone()[0] == 0
