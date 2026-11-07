"""小红书现有账号接入 —— 离线测试（与抖音同法：归一化/去重/中位数/降级/API）。"""
from __future__ import annotations

import pytest

from backend.app import create_app
from backend.integrations import intake, storage
from backend.integrations.types import ExternalAccountCreate, ManualImport
from backend.integrations.xiaohongshu.fetch import FetchError, normalize_comments, normalize_note

BASE = "http://127.0.0.1:5000"


def sample_notes():
    return {"source": "manual", "videos": [
        {"platform_video_id": "n1", "title": "图文笔记一", "plays": 5000, "likes": 80,
         "comments": 12, "shares": 3, "favorites": 40,
         "top_comments": [{"text": "收藏了", "likes": 9}]},
        {"platform_video_id": "n2", "title": "视频笔记二", "plays": 1500, "likes": 20},
        {"platform_video_id": "n3", "title": "笔记三", "plays": 3000, "likes": 30},
    ]}


def test_register_xiaohongshu_import_dedup_and_baseline(tmp_path):
    account = intake.register_account(tmp_path, ExternalAccountCreate.model_validate(
        {"account_id": "a_1", "platform": "xiaohongshu", "handle": "xhs_1"}))
    result = intake.import_manual(tmp_path, account["id"],
                                  ManualImport.model_validate(sample_notes()))
    assert result["imported"] == 3
    assert result["baseline_plays"] == 3000, "baseline = 全部导入阅读中位数"
    again = intake.import_manual(tmp_path, account["id"],
                                 ManualImport.model_validate(sample_notes()))
    assert again["imported"] == 0 and again["skipped_duplicates"] == 3


def test_normalize_note_maps_xiaohongshu_fields():
    note = normalize_note({
        "note_id": "64abc", "display_title": "标题", "create_time": 1760000000000,
        "interact_info": {"view_count": 900, "liked_count": 80, "comment_count": 7,
                          "share_count": 6, "collected_count": 50}})
    assert note.platform_video_id == "64abc"
    assert (note.plays, note.likes, note.comments, note.shares, note.favorites) == (900, 80, 7, 6, 50)
    assert note.published_at is not None, "毫秒时间戳应正确归一"
    with pytest.raises(FetchError):
        normalize_note({"display_title": "无 ID"})


def test_normalize_comments_sorted_by_likes():
    comments = normalize_comments({"comments": [
        {"content": "一般", "like_count": 2}, {"content": "热评", "like_count": 120},
    ]}, "n1")
    assert comments[0] == {"text": "热评", "likes": 120}


def test_adapter_import_without_session_falls_back(tmp_path):
    account = intake.register_account(tmp_path, ExternalAccountCreate.model_validate(
        {"account_id": "a_1", "platform": "xiaohongshu", "handle": "xhs_1"}))
    with pytest.raises(Exception) as exc:
        intake.import_via_adapter(tmp_path, account["id"])
    assert "manual" in str(exc.value) or "会话" in str(exc.value)


def test_api_register_import_xiaohongshu(tmp_path):
    from backend.storage.db import migrate
    migrate(tmp_path)
    client = create_app({"data_dir": tmp_path}).test_client()
    token = client.get("/api/v1/session", base_url=BASE).get_json()["data"]["csrf_token"]
    headers = {"X-CSRF-Token": token, "Idempotency-Key": "xhs1234abcd5678ef", "Origin": BASE}
    account_id = client.post("/api/v1/accounts", json={"name": "小红书分区"},
                             headers=headers, base_url=BASE).get_json()["data"]["account_id"]
    created = client.post("/api/v1/accounts/external", headers=headers, base_url=BASE, json={
        "account_id": account_id, "platform": "xiaohongshu", "handle": "xhs_api",
        "display_name": "小红书号", "profile_url": None}).get_json()["data"]
    assert created["platform"] == "xiaohongshu" and created["session_status"] == "none"
    imported = client.post(f"/api/v1/accounts/external/{created['external_account_id']}/import",
                           headers={**headers, "Idempotency-Key": "xhs9012ijkl3456mn"},
                           base_url=BASE, json=sample_notes()).get_json()["data"]
    assert imported["imported"] == 3 and imported["baseline_plays"] == 3000
    videos = client.get(f"/api/v1/accounts/external/{created['external_account_id']}/videos",
                        base_url=BASE).get_json()["data"]
    assert len(videos) == 3 and videos[0]["top_comments"] is not None


def test_extract_notes_handles_shapes():
    from backend.integrations.xiaohongshu.fetch import FetchError, _extract_notes
    assert _extract_notes({"data": {"notes": [{"id": "n1"}]}}) == [{"id": "n1"}]
    assert _extract_notes({"data": [{"id": "n2"}]}) == [{"id": "n2"}]
    assert _extract_notes({"data": '[{"id": "n3"}]'}) == [{"id": "n3"}], "二次编码 JSON 也能解"
    with pytest.raises(FetchError):
        _extract_notes({"success": False, "msg": "登录已过期"}), "失败响应应报出平台 msg"
    with pytest.raises(FetchError):
        _extract_notes({"data": "d0daeb8f6c8316845713a0c06f31d3c9"}), "字符串 data 应可操作报错"
    with pytest.raises(FetchError):
        _extract_notes(["not-a-dict-shape"])


def test_extract_notes_failure_message_mentions_platform_msg():
    from backend.integrations.xiaohongshu.fetch import FetchError, _extract_notes
    with pytest.raises(FetchError) as exc:
        _extract_notes({"code": -1, "success": False, "msg": "登录已过期", "data": "abc"})
    assert "登录已过期" in str(exc.value)
