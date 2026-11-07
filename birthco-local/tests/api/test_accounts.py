from backend.app import create_app
from backend.storage.db import migrate

BASE = "http://127.0.0.1:5000"


def setup(tmp_path):
    migrate(tmp_path)
    client = create_app({"data_dir": tmp_path}).test_client()
    token = client.get("/api/v1/session", base_url=BASE).get_json()["data"]["csrf_token"]
    headers = {
        "X-CSRF-Token": token,
        "Idempotency-Key": "0123456789abcdef",
        "Origin": BASE,
    }
    return client, headers


def test_creator_stage_round_trip_and_cas(tmp_path):
    client, headers = setup(tmp_path)
    created = client.post(
        "/api/v1/accounts",
        json={"name": "个人账号", "creator_stage": "operating"},
        headers=headers,
        base_url=BASE,
    )
    assert created.status_code == 201
    account = created.get_json()["data"]
    assert account["creator_stage"] == "operating"
    assert account["row_version"] == 0
    account_id = account["account_id"]

    headers["Idempotency-Key"] = "1123456789abcdef"
    updated = client.put(
        f"/api/v1/accounts/{account_id}",
        json={
            "name": "新名字",
            "creator_stage": "established",
            "expected_row_version": 0,
        },
        headers=headers,
        base_url=BASE,
    )
    assert updated.status_code == 200
    data = updated.get_json()["data"]
    assert data["name"] == "新名字"
    assert data["creator_stage"] == "established"
    assert data["row_version"] == 1

    headers["Idempotency-Key"] = "2123456789abcdef"
    stale = client.put(
        f"/api/v1/accounts/{account_id}",
        json={
            "name": "过期修改",
            "creator_stage": "starting",
            "expected_row_version": 0,
        },
        headers=headers,
        base_url=BASE,
    )
    assert stale.status_code == 409
    assert stale.get_json()["error"]["code"] == "VERSION_CONFLICT"
    assert stale.get_json()["error"]["current_row_version"] == 1

    listed = client.get("/api/v1/accounts", base_url=BASE).get_json()["data"]
    assert listed == [
        {
            "account_id": account_id,
            "name": "新名字",
            "creator_stage": "established",
            "row_version": 1,
        }
    ]


def test_account_stage_defaults_for_existing_clients(tmp_path):
    client, headers = setup(tmp_path)
    created = client.post(
        "/api/v1/accounts",
        json={"name": "旧客户端"},
        headers=headers,
        base_url=BASE,
    )
    assert created.status_code == 201
    assert created.get_json()["data"]["creator_stage"] == "starting"
