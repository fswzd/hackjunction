"""Regression: seven agent interfaces, health probe and loopback origin policy."""
from backend.app import create_app
from backend.storage.db import migrate

BASE = "http://127.0.0.1:5000"


def make_client(tmp_path):
    migrate(tmp_path)
    return create_app({"data_dir": tmp_path}).test_client()


def test_health_probe_is_public_and_reports_mode(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/api/v1/health", base_url=BASE)
    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == "ok"
    assert response.get_json()["data"]["mode"] == "mock"


def test_agent_registry_exposes_all_seven_without_credentials(tmp_path):
    client = make_client(tmp_path)
    client.get("/api/v1/session", base_url=BASE)
    response = client.get("/api/v1/agents", base_url=BASE)
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["count"] == 7
    assert data["configured_count"] == 7
    assert data["ready"] is True
    assert {row["agent_id"] for row in data["agents"]} == {
        "pr_analyst", "operations_officer", "content_creator",
        "editorial_reviewer", "traffic_scout", "data_analyst",
        "simulated_audience",
    }
    payload = str(data)
    assert "sk-" not in payload and "secret" not in payload.lower().replace("api_key_configured", "")


def test_local_origin_on_another_port_is_accepted(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/api/v1/session", base_url=BASE,
                          headers={"Origin": "http://127.0.0.1:4273"})
    assert response.status_code == 200


def test_foreign_origin_is_still_rejected(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/api/v1/session", base_url=BASE,
                          headers={"Origin": "https://attacker.example"})
    assert response.status_code == 403
