"""Tests for W5: keyword + LLM dual-channel risk verdict."""
from backend.simulation.audience_risk import assess_risk, keyword_risk_check
from backend.domain.schemas import AudienceEvent


def make_event(reaction="好", comment_text=None):
    return AudienceEvent(segment_id="s1", action="continue",
                         understanding="理解", question=None,
                         reaction=reaction, interactions=[],
                         comment_text=comment_text)


class TestKeywordRiskCheck:
    def test_clean_text(self):
        v = keyword_risk_check("文章写得不错，学到了很多。")
        assert v.flagged is False
        assert v.severity == "none"

    def test_empty_text(self):
        v = keyword_risk_check("")
        assert v.flagged is False

    def test_hostility(self):
        v = keyword_risk_check("垃圾 垃圾 垃圾")
        assert v.flagged is True
        assert v.category == "hostility"
        assert v.severity == "high"

    def test_spam(self):
        v = keyword_risk_check("加群领取免费优惠")
        assert v.flagged is True
        assert v.category == "spam"

    def test_whitelist_not_flagged(self):
        v = keyword_risk_check("标题党吧")
        assert v.flagged is False

    def test_severity_scaling(self):
        v1 = keyword_risk_check("垃圾")
        v2 = keyword_risk_check("垃圾 垃圾")
        v3 = keyword_risk_check("垃圾 垃圾 垃圾")
        assert v1.severity == "low"
        assert v2.severity == "medium"
        assert v3.severity == "high"

    def test_verdict_fields(self):
        v = keyword_risk_check("垃圾")
        d = v.to_dict()
        assert "flagged" in d
        assert "category" in d
        assert "severity" in d
        assert "confidence" in d
        assert "reason" in d
        assert "detected_keywords" in d


class TestAssessRisk:
    def test_clean_events(self):
        events = [make_event(reaction="不错"), make_event(reaction="还行")]
        results = assess_risk(events)
        assert len(results) == 2
        assert all(not r["verdict"]["flagged"] for r in results)

    def test_flagged_event(self):
        events = [make_event(reaction="垃圾 垃圾 垃圾")]
        results = assess_risk(events)
        assert results[0]["verdict"]["flagged"] is True

    def test_llm_checker_integration(self):
        def mock_llm(text, category):
            return {"flagged": True, "category": "hostility", "severity": "low",
                    "confidence": 0.6, "reason": "LLM确认"}
        events = [make_event(reaction="垃圾 垃圾")]
        results = assess_risk(events, llm_checker=mock_llm)
        assert results[0]["verdict"]["reason"] == "LLM确认"

    def test_llm_failure_falls_back(self):
        def bad_llm(text, category):
            raise RuntimeError("LLM down")
        events = [make_event(reaction="垃圾 垃圾")]
        results = assess_risk(events, llm_checker=bad_llm)
        assert results[0]["verdict"]["flagged"] is True

    def test_comment_text_included(self):
        events = [make_event(reaction="还行", comment_text="垃圾 垃圾 垃圾")]
        results = assess_risk(events)
        assert results[0]["verdict"]["flagged"] is True
