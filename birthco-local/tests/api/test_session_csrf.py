"""CSRF 幂等回归：重复 bootstrap 不得使既有 token 失效。

场景：工作台（api.ts）与账号组件（externalAccounts.ts）各自缓存会话 token；
账号侧再次 bootstrap 时，旧实现会轮换 csrf_hash，工作台随后写请求报
"CSRF token invalid"。修复后 token 为会话派生值，重复 bootstrap 恒等。
"""
from backend.app import create_app
from backend.storage.db import migrate

BASE = "http://127.0.0.1:5000"


def setup(tmp_path):
    migrate(tmp_path)
    return create_app({"data_dir": tmp_path}).test_client()


def bootstrap(client):
    return client.get("/api/v1/session", base_url=BASE).get_json()["data"]["csrf_token"]


def test_repeated_bootstrap_returns_same_token(tmp_path):
    client = setup(tmp_path)
    first = bootstrap(client)
    second = bootstrap(client)  # 模拟账号组件并发取 session
    assert first == second


def test_cached_token_survives_rebootstrap_and_can_write(tmp_path):
    client = setup(tmp_path)
    token_workbench = bootstrap(client)  # 工作台缓存
    bootstrap(client)                    # 账号组件再次 bootstrap（旧行为会轮换）
    created = client.post(
        "/api/v1/accounts",
        json={"name": "个人账号", "creator_stage": "starting"},
        headers={"X-CSRF-Token": token_workbench,
                 "Idempotency-Key": "0123456789abcdef", "Origin": BASE},
        base_url=BASE,
    )
    assert created.status_code == 201, created.get_json()
