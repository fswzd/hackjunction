"""排查线 16 条确认缺陷修复批次（2026-11-07）的关键回归用例。

每条对应一个已修复缺陷的最小复现断言，防止回退：
- #6  「401」子串误判登录过期（会级联触发账号回滚删除）
- #13 未知账号手动导入应报错于写入之前（而非外键 502）
- #14 情绪关键词重复导致分档翻倍偏移
- #16 风险结论 event_id 必须能回指真实事件
"""
import pytest

from backend.domain.schemas import AudienceEvent
from backend.integrations import intake
from backend.integrations import storage as integ_storage
from backend.integrations.types import ManualImport
from backend.simulation.audience_feedback import _NEGATIVE_KEYWORDS
from backend.simulation.audience_risk import assess_risk
from backend.storage.db import migrate


def test_auth_error_uses_word_boundary_not_substring():
    assert not intake._is_auth_error("作品14015不存在")
    assert not intake._is_auth_error("错误码 40152")
    assert intake._is_auth_error("HTTP 401 unauthorized")
    assert intake._is_auth_error("状态码 401")
    assert intake._is_auth_error("登录已过期，请重新扫码")


def test_negative_keywords_have_no_duplicates():
    assert len(set(_NEGATIVE_KEYWORDS)) == len(_NEGATIVE_KEYWORDS)


def test_assess_risk_maps_real_event_ids():
    events = [AudienceEvent(segment_id="seg1", action="continue", understanding="ok",
                            question=None, reaction="垃圾内容", interactions=[],
                            comment_text=None)]
    legacy = assess_risk(events)
    assert legacy[0]["event_id"] == "seg1"  # 缺省兼容旧行为
    mapped = assess_risk(events, event_ids=["ev_9"])
    assert mapped[0]["event_id"] == "ev_9"
    with pytest.raises(ValueError):
        assess_risk(events, event_ids=[])


def test_import_manual_unknown_account_fails_before_write(tmp_path):
    migrate(tmp_path)
    db = tmp_path / "db.sqlite"
    integ_storage.ensure_integration_tables(db)
    payload = ManualImport.model_validate({"videos": [{"platform_video_id": "v1"}]})
    with pytest.raises(KeyError):
        intake.import_manual(db, "nope", payload)
