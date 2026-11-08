"""Regression: the requested length/duration must reach the delivered script.

Covers the two user-reported defects:
  * "写一篇 800 字的文章" produced ~120 characters;
  * a title saying "60 秒看懂" survived a 30-second selection.
"""
import pytest

from backend.agents.director import _mock_article
from backend.domain.length import (conflicting_mentions, normalize_mentions,
                                   spec_from_label, spec_from_requirements)
from backend.domain.schemas import Brief, CreateTask, LengthRule, Requirement
from backend.validators.content import validate_content

RESERVED = [f"s_len_{index}" for index in range(3)]


def make_brief(text: str, *, minimum: int | None = None,
               maximum: int | None = 20000, objective: str = "城市漫步指南") -> Brief:
    return Brief(
        input_mode="idea", objective=objective, audience="年轻上班族",
        platform="generic", format="text", core_promise=objective,
        requirements=[Requirement(id="r1", text=text)], material_ids=[],
        open_questions=[], route=["draft", "review", "export"],
        length_rule=LengthRule(minimum=minimum, maximum=maximum),
        edit_scope=None,
    )


def create_payload(text: str) -> dict:
    return {
        "account_id": "a1", "input_mode": "idea", "objective": "写一篇教程",
        "audience": "初学者", "platform": "generic", "format": "text",
        "style": "清楚", "requirements": [{"id": "r1", "text": text}],
        "materials": [], "preview_requested": False,
        "length_rule": {"minimum": None, "maximum": 20000},
    }


def test_presets_resolve_to_a_real_character_budget():
    seconds = spec_from_label("30 秒")
    assert seconds.target_seconds == 30 and seconds.minimum > 100
    article = spec_from_label("800 字")
    assert article.target_characters == 800
    assert article.minimum >= 680 and article.maximum <= 960
    minutes = spec_from_label("3 分钟")
    assert minutes.target_seconds == 180


def test_create_task_recovers_target_from_requirement_text():
    """Backend fallback for clients that only send the text marker."""
    task = CreateTask.model_validate(create_payload("目标时长 / 篇幅：800 字；写一篇城市漫步文章"))
    assert task.length_rule.minimum is not None and task.length_rule.minimum >= 680
    assert task.length_rule.maximum <= 20000


def test_explicit_length_rule_is_not_overwritten():
    task = CreateTask.model_validate({
        **create_payload("目标时长 / 篇幅：800 字"),
        "length_rule": {"minimum": 300, "maximum": 400},
    })
    assert (task.length_rule.minimum, task.length_rule.maximum) == (300, 400)


def test_custom_maximum_is_preserved_when_only_marker_is_sent():
    task = CreateTask.model_validate({
        **create_payload("目标时长 / 篇幅：800 字"),
        "length_rule": {"minimum": None, "maximum": 700},
    })
    assert task.length_rule.minimum == 680
    assert task.length_rule.maximum == 700


def test_legacy_noop_ceiling_is_replaced_by_the_resolved_budget():
    task = CreateTask.model_validate(create_payload("目标时长 / 篇幅：800 字"))
    assert task.length_rule.maximum == 960


def test_mock_script_actually_reaches_800_characters():
    brief = make_brief("目标时长 / 篇幅：800 字；写一篇城市漫步文章",
                       minimum=680, maximum=960)
    spec = spec_from_requirements(r.text for r in brief.requirements)
    candidate = _mock_article(brief, [], spec, 680, 960, RESERVED)
    report = validate_content("v_len_1", candidate, brief)
    assert report.body_characters >= 680, report.body_characters
    assert report.body_characters <= 960, report.body_characters
    assert report.passed, [(c.rule_id, c.reason) for c in report.checks if not c.passed]


def test_mock_short_script_stays_within_30_second_budget():
    brief = make_brief("目标时长 / 篇幅：30 秒", minimum=114, maximum=168)
    spec = spec_from_requirements(r.text for r in brief.requirements)
    candidate = _mock_article(brief, [], spec, 114, 168, RESERVED)
    report = validate_content("v_len_2", candidate, brief)
    assert report.body_characters >= 114
    assert report.passed


def test_title_duration_is_rewritten_to_the_selected_target():
    brief = make_brief("目标时长 / 篇幅：30 秒",
                       minimum=114, maximum=168,
                       objective="5 款 AI 效率工具，大学生 60 秒看懂")
    spec = spec_from_requirements(r.text for r in brief.requirements)
    candidate = _mock_article(brief, [], spec, 114, 168, RESERVED)
    headline = " ".join([*candidate.titles, candidate.cover_copy or ""])
    assert "60 秒" not in headline
    assert "30 秒" in headline
    report = validate_content("v_len_3", candidate, brief)
    assert report.passed, [(c.rule_id, c.reason) for c in report.checks if not c.passed]


def test_conflicting_title_is_rejected_by_validator():
    brief = make_brief("目标时长 / 篇幅：30 秒", minimum=114, maximum=168)
    spec = spec_from_requirements(r.text for r in brief.requirements)
    candidate = _mock_article(brief, [], spec, 114, 168, RESERVED)
    bad = candidate.model_copy(update={"titles": ["60 秒看懂 AI 工具", "第二条标题", "第三条标题"]})
    report = validate_content("v_len_4", bad, brief)
    failed = [c.rule_id for c in report.checks if not c.passed]
    assert "RULE_TARGET_DURATION" in failed
    assert not report.passed


def test_normalize_and_conflict_detection_preserve_other_units():
    spec = spec_from_label("30 秒")
    assert conflicting_mentions("60 秒看懂", spec) == ["60 秒"]
    assert normalize_mentions("60 秒看懂", spec) == "30 秒看懂"
    assert normalize_mentions("3 分钟讲完", spec) == "30 秒讲完"
    # A word-count target must not rewrite a seconds claim, and vice versa.
    words = spec_from_label("800 字")
    assert normalize_mentions("60 秒看懂", words) == "60 秒看懂"
    assert conflicting_mentions("60 秒看懂", words) == []


def with_body(candidate, text: str):
    """Replace the first segment text while keeping the other segments intact."""
    segments = list(candidate.segments)
    segments[0] = segments[0].model_copy(update={"text": text})
    return candidate.model_copy(update={"segments": segments})


def test_short_script_timeline_ends_exactly_on_selected_duration():
    brief = make_brief("目标时长 / 篇幅：30 秒", minimum=114, maximum=168)
    spec = spec_from_requirements(r.text for r in brief.requirements)
    candidate = _mock_article(brief, [], spec, 114, 168, RESERVED)
    body = "\n".join(segment.text for segment in candidate.segments)
    assert "–30 秒]" in body
    report = validate_content("v_len_5", candidate, brief)
    assert "RULE_TIMELINE" in [c.rule_id for c in report.checks if c.passed]
    assert report.passed, [(c.rule_id, c.reason) for c in report.checks if not c.passed]


def test_wrong_timeline_end_is_rejected():
    brief = make_brief("目标时长 / 篇幅：30 秒", minimum=114, maximum=168)
    spec = spec_from_requirements(r.text for r in brief.requirements)
    candidate = _mock_article(brief, [], spec, 114, 168, RESERVED)
    bad = with_body(candidate, "[第 0–60 秒] 这一段把时长写错了。")
    report = validate_content("v_len_6", bad, brief)
    assert "RULE_TIMELINE" in [c.rule_id for c in report.checks if not c.passed]
    assert not report.passed


def test_explicit_total_duration_claim_is_rejected():
    brief = make_brief("目标时长 / 篇幅：30 秒", minimum=114, maximum=168)
    spec = spec_from_requirements(r.text for r in brief.requirements)
    candidate = _mock_article(brief, [], spec, 114, 168, RESERVED)
    bad = with_body(candidate, "本片总时长 60 秒，请按顺序阅读。")
    report = validate_content("v_len_7", bad, brief)
    assert "RULE_TIMELINE" in [c.rule_id for c in report.checks if not c.passed]


@pytest.mark.parametrize("label,low,high", [
    ("30 秒", 114, 168), ("60 秒", 229, 324), ("3 分钟", 688, 972),
])
def test_timeline_labels_are_never_split_across_segments(label, low, high):
    brief = make_brief(f"目标时长 / 篇幅：{label}", minimum=low, maximum=high)
    spec = spec_from_requirements(r.text for r in brief.requirements)
    candidate = _mock_article(brief, [], spec, low, high, RESERVED)
    for segment in candidate.segments:
        opened = segment.text.count("[第 ")
        closed = segment.text.count("秒]")
        assert opened == closed, (label, segment.text[:80])
    body = "\n\n".join(segment.text for segment in candidate.segments)
    assert low <= sum(1 for ch in body if not ch.isspace()) <= high
    report = validate_content(f"v_len_timeline_{low}", candidate, brief)
    assert report.passed, [(c.rule_id, c.reason) for c in report.checks if not c.passed]


def test_article_request_has_no_seconds_timeline():
    brief = make_brief("目标时长 / 篇幅：800 字；写一篇城市漫步文章",
                       minimum=680, maximum=960)
    spec = spec_from_requirements(r.text for r in brief.requirements)
    candidate = _mock_article(brief, [], spec, 680, 960, RESERVED)
    body = "\n".join(segment.text for segment in candidate.segments)
    assert "秒]" not in body
    report = validate_content("v_len_8", candidate, brief)
    assert report.passed, [(c.rule_id, c.reason) for c in report.checks if not c.passed]
    bad = with_body(candidate, "【开场 0–5 秒】这是误加的视频时间轴。")
    assert "RULE_TIMELINE" in [c.rule_id for c in validate_content("v_len_9", bad, brief).checks
                               if not c.passed]
