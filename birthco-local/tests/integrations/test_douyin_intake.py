"""抖音现有账号接入 —— 离线测试（无网络、无浏览器、无真实凭据）。"""
from __future__ import annotations

import json

import pytest

from backend.app import create_app
from backend.integrations import intake, storage
from backend.integrations.douyin.fetch import FetchError, _extract_works, normalize_comments, normalize_work
from backend.integrations.types import ExternalAccountCreate, ManualImport

BASE = "http://127.0.0.1:5000"


def test_works_list_distinguishes_empty_list_from_platform_error():
    assert _extract_works({"status_code": 0, "aweme_list": []}) == ([], False, None)
    with pytest.raises(FetchError, match="登录已过期"):
        _extract_works({"status_code": 401, "aweme_list": []})
    with pytest.raises(FetchError, match="未识别"):
        _extract_works({"status_code": 0, "data": {}})


def sample_videos():
    return {"source": "manual", "videos": [
        {"platform_video_id": "v1", "title": "教程一", "published_at": "2026-10-01T00:00:00+00:00",
         "plays": 1000, "likes": 10, "comments": 2, "shares": 1,
         "top_comments": [{"text": "讲得清楚", "likes": 5}]},
        {"platform_video_id": "v2", "title": "教程二", "plays": 3000, "likes": 30},
        {"platform_video_id": "v3", "title": "教程三", "plays": 2000, "likes": 20},
    ]}


def test_register_existing_account_is_idempotent_per_platform_handle(tmp_path):
    payload = ExternalAccountCreate.model_validate(
        {"account_id": "a_1", "platform": "douyin", "handle": "dy_123", "display_name": "我的号"})
    row1 = intake.register_account(tmp_path, payload)
    row2 = intake.register_account(tmp_path, payload)
    assert row1["id"] == row2["id"], "同一平台同一账号重复接入返回同一登记"
    assert row1["session_status"] == "none"


def test_manual_import_dedup_and_baseline_median(tmp_path):
    account = intake.register_account(tmp_path, ExternalAccountCreate.model_validate(
        {"account_id": "a_1", "platform": "douyin", "handle": "dy_123"}))
    result = intake.import_manual(tmp_path, account["id"], ManualImport.model_validate(sample_videos()))
    assert result["imported"] == 3
    assert result["baseline_plays"] == 2000, "baseline_plays = 播放中位数"
    again = intake.import_manual(tmp_path, account["id"], ManualImport.model_validate(sample_videos()))
    assert again["imported"] == 0 and again["skipped_duplicates"] == 3
    videos = storage.list_imported_videos(tmp_path, account["id"])
    assert len(videos) == 3
    assert videos[0]["top_comments"] in ([{"text": "讲得清楚", "likes": 5}], [])


def test_top_comments_preserved_and_normalized(tmp_path):
    comments = normalize_comments({"comments": [
        {"text": "低", "digg_count": 1}, {"text": "高", "digg_count": 99}, {"text": "", "digg_count": 5},
    ]}, "v1")
    assert comments[0] == {"text": "高", "likes": 99}
    assert all(c["text"] for c in comments)


def test_normalize_work_maps_creator_center_fields():
    video = normalize_work({"aweme_id": "42", "desc": "标题", "create_time": 1760000000,
                            "statistics": {"play_count": 9, "digg_count": 8, "comment_count": 7,
                                           "share_count": 6, "collect_count": 5}})
    assert video.platform_video_id == "42"
    assert (video.plays, video.likes, video.comments, video.shares, video.favorites) == (9, 8, 7, 6, 5)
    with pytest.raises(FetchError):
        normalize_work({"desc": "无 ID"})


def test_adapter_import_without_session_points_to_manual(tmp_path):
    account = intake.register_account(tmp_path, ExternalAccountCreate.model_validate(
        {"account_id": "a_1", "platform": "douyin", "handle": "dy_123"}))
    with pytest.raises(Exception) as exc:
        intake.import_via_adapter(tmp_path, account["id"])
    assert "manual" in str(exc.value) or "会话" in str(exc.value)


def test_session_state_transitions(tmp_path):
    account = intake.register_account(tmp_path, ExternalAccountCreate.model_validate(
        {"account_id": "a_1", "platform": "douyin", "handle": "dy_123"}))
    intake.mark_pending_adapter(tmp_path, account["id"])
    assert storage.get_external_account(tmp_path, account["id"])["session_status"] == "pending_adapter_setup"
    session_file = tmp_path / "state.json"
    session_file.write_text('{"cookies": []}', encoding="utf-8")
    row = intake.attach_session(tmp_path, account["id"], session_file)
    assert row["session_status"] == "logged_in"
    assert row["session_fingerprint"] and row["session_ref"].endswith("state.json")
    assert "cookies" not in json.dumps(row), "凭据内容不入库"


def test_api_register_import_list(tmp_path):
    migrate_ok = True
    from backend.storage.db import migrate
    migrate(tmp_path)
    client = create_app({"data_dir": tmp_path}).test_client()
    token = client.get("/api/v1/session", base_url=BASE).get_json()["data"]["csrf_token"]
    headers = {"X-CSRF-Token": token, "Idempotency-Key": "abcd1234efgh5678", "Origin": BASE}
    account_id = client.post("/api/v1/accounts", json={"name": "个人账号"}, headers=headers,
                             base_url=BASE).get_json()["data"]["account_id"]
    created = client.post("/api/v1/accounts/external", headers=headers, base_url=BASE, json={
        "account_id": account_id, "platform": "douyin", "handle": "dy_api",
        "display_name": "API号", "profile_url": None}).get_json()["data"]
    assert created["session_status"] == "none"
    imported = client.post(f"/api/v1/accounts/external/{created['external_account_id']}/import",
                           headers={**headers, "Idempotency-Key": "ijkl9012mnop3456"},
                           base_url=BASE, json=sample_videos()).get_json()["data"]
    assert imported["imported"] == 3 and imported["baseline_plays"] == 2000
    videos = client.get(f"/api/v1/accounts/external/{created['external_account_id']}/videos",
                        base_url=BASE).get_json()["data"]
    assert len(videos) == 3
    listed = client.get("/api/v1/accounts/external", base_url=BASE).get_json()["data"]
    assert any(r["handle"] == "dy_api" for r in listed)
