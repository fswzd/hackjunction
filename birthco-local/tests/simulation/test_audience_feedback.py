"""Tests for W4: emotion contagion, stance aggregation, feedback report."""
from backend.simulation.audience_feedback import (
    aggregate_stance, build_feedback_report, compute_emotion_score,
)
from backend.domain.schemas import AudienceEvent


def make_event(segment_id="s1", reaction="内容不错", comment_text=None,
               interactions=None, action="continue"):
    return AudienceEvent(segment_id=segment_id, action=action,
                         understanding="理解了", question=None,
                         reaction=reaction, interactions=interactions or [],
                         comment_text=comment_text)


class TestEmotionScore:
    def test_empty_text(self):
        assert compute_emotion_score("") == 0.1

    def test_positive_content(self):
        score = compute_emotion_score("这篇文章写得很好，清晰实用。")
        assert score > 0

    def test_negative_content(self):
        score = compute_emotion_score("垃圾 垃圾 垃圾 垃圾 垃圾 垃圾")
        assert score < -0.5

    def test_neutral_content(self):
        score = compute_emotion_score("今天天气不错。")
        assert score == 0.1

    def test_partial_negative(self):
        score = compute_emotion_score("垃圾 垃圾")
        assert -0.5 <= score <= -0.2


class TestStanceAggregation:
    def test_support(self):
        events = [make_event(reaction="学到了，很实用")]
        result = aggregate_stance(events)
        assert result.support_count == 1
        assert result.support_ratio == 1.0

    def test_oppose(self):
        events = [make_event(reaction="垃圾，完全没用")]
        result = aggregate_stance(events)
        assert result.oppose_count == 1

    def test_neutral(self):
        events = [make_event(reaction="还行吧")]
        result = aggregate_stance(events)
        assert result.neutral_count == 1

    def test_mixed(self):
        events = [
            make_event(reaction="学到了"),
            make_event(reaction="垃圾"),
            make_event(reaction="一般般"),
        ]
        result = aggregate_stance(events)
        assert result.total == 3
        assert result.support_count + result.neutral_count + result.oppose_count == 3

    def test_segment_filter(self):
        events = [make_event(segment_id="s1", reaction="好"), make_event(segment_id="s2", reaction="差")]
        result = aggregate_stance(events, "s1")
        assert result.total == 1

    def test_representative_comment(self):
        events = [make_event(reaction="不错", comment_text="很有帮助")]
        result = aggregate_stance(events)
        assert "support" in result.representative
        assert result.representative["support"] == "很有帮助"

    def test_empty_events(self):
        result = aggregate_stance([])
        assert result.total == 0
        assert result.support_ratio == 0.0


class TestFeedbackReport:
    def test_basic_report(self):
        events = [
            make_event(segment_id="s1", reaction="不错", interactions=["like"]),
            make_event(segment_id="s2", reaction="还行"),
        ]
        sessions = [
            {"outcome": "completed"},
            {"outcome": "exited"},
        ]
        seg_ids = ["s1", "s2"]
        texts = {"s1": "第一段内容", "s2": "第二段内容"}
        report = build_feedback_report(events, sessions, seg_ids, texts)
        d = report.to_dict()
        assert d["is_simulation"] is True
        assert d["predicts_real_traffic"] is False
        assert d["interactions"]["like"] == 1
        assert d["influence"]["exit_count"] == 1
        assert d["influence"]["completed_count"] == 1
        assert d["influence"]["total_viewers"] == 2

    def test_empty(self):
        report = build_feedback_report([], [], [], {})
        d = report.to_dict()
        assert d["influence"]["total_viewers"] == 0
        assert d["influence"]["coverage_ratio"] == 0.0
