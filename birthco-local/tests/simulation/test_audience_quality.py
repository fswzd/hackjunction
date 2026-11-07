"""Tests for comment de-homogenization: cliche detection, similarity, rewrite."""
import pytest

from backend.domain.schemas import AudienceEvent
from backend.simulation.audience_quality import (
    deduplicate_comments,
    needs_rewrite,
)


def make_event(segment_id="s1", comment_text=None):
    return AudienceEvent(
        segment_id=segment_id,
        action="continue",
        understanding="I understand the content",
        question=None,
        reaction="Interesting content",
        interactions=["comment"] if comment_text else [],
        comment_text=comment_text,
    )


class TestNeedsRewrite:
    def test_clean_comment_no_rewrite(self):
        assert not needs_rewrite("从技术架构角度看这个方案的扩展性确实值得深入思考", ["完全不同的内容"])

    def test_empty_comment_no_rewrite(self):
        assert not needs_rewrite("", [])
        assert not needs_rewrite("   ", [])

    def test_cliche_triggers_rewrite(self):
        assert needs_rewrite("写得不错", [])
        assert needs_rewrite("干货满满", [])
        assert needs_rewrite("感谢分享", [])

    def test_similarity_triggers_rewrite(self):
        prior = ["这个内容讲了很多有用的东西"]
        assert needs_rewrite("这个内容讲了很多有用的东西啊", prior)

    def test_different_comments_no_rewrite(self):
        prior = ["第一个观点很好"]
        assert not needs_rewrite("第二个观点完全不同", prior)


class TestDeduplicate:
    def test_no_comments_passthrough(self):
        events = [make_event("s1"), make_event("s1", "独特评论A")]
        result = deduplicate_comments(events)
        assert len(result) == 2
        assert result[0].comment_text is None

    def test_unique_comments_untouched(self):
        events = [
            make_event("s1", "第一段的深度分析"),
            make_event("s1", "第二段的不同看法"),
        ]
        result = deduplicate_comments(events)
        assert result[0].comment_text == "第一段的深度分析"
        assert result[1].comment_text == "第二段的不同看法"

    def test_duplicate_comments_rewritten(self):
        calls = []
        def fake_rewrite(text, temperature=0.5):
            calls.append((text, temperature))
            return f"rewritten_{len(calls)}"
        events = [
            make_event("s1", "duplicate comment here"),
            make_event("s1", "duplicate comment here"),
        ]
        result = deduplicate_comments(events, rewrite_fn=fake_rewrite)
        assert result[0].comment_text == "duplicate comment here"
        assert result[1].comment_text == "rewritten_1"
        assert len(calls) == 1

    def test_rewrite_failure_falls_back(self):
        def bad_rewrite(text, temperature=0.5):
            raise RuntimeError("model unavailable")
        events = [
            make_event("s1", "写得不错"),
            make_event("s1", "写得不错"),
        ]
        result = deduplicate_comments(events, rewrite_fn=bad_rewrite)
        assert result[0].comment_text == "写得不错"
        assert result[1].comment_text == "写得不错"

    def test_per_segment_isolation(self):
        events = [
            make_event("s1", "写得不错"),
            make_event("s2", "写得不错"),
        ]
        result = deduplicate_comments(events)
        assert result[0].comment_text == "写得不错"
        assert result[1].comment_text == "写得不错"

    def test_comment_length_capped(self):
        def long_rewrite(text, temperature=0.5):
            return "长" * 2000
        events = [
            make_event("s1", "写得不错"),
            make_event("s1", "写得不错"),
        ]
        result = deduplicate_comments(events, rewrite_fn=long_rewrite)
        assert len(result[1].comment_text) <= 1000
