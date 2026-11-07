"""Keyword + LLM dual-channel risk verdict for audience feedback."""
from __future__ import annotations

from dataclasses import dataclass

from backend.domain.schemas import AudienceEvent

_RISK_CATEGORIES = {
    "hostility": ["垃圾", "滚", "蠢", "白痴", "恶心", "去死", "废物", "智障"],
    "misinformation": ["假的", "骗人", "造谣", "谣言", "伪造", "捏造"],
    "spam": ["加群", "私信", "优惠", "免费领", "点击链接", "扫码", "广告"],
    "off_topic": ["跑题", "无关", "偏了", "不相关"],
}

_WHITELIST = ["标题党", "假的吧", "不是假的"]


@dataclass
class RiskVerdict:
    flagged: bool
    category: str | None
    severity: str
    confidence: float
    reason: str
    detected_keywords: list[str]

    def to_dict(self) -> dict:
        return {
            "flagged": self.flagged,
            "category": self.category,
            "severity": self.severity,
            "confidence": self.confidence,
            "reason": self.reason,
            "detected_keywords": self.detected_keywords,
        }


def keyword_risk_check(text: str) -> RiskVerdict:
    if not text.strip():
        return RiskVerdict(flagged=False, category=None, severity="none", confidence=0.0,
                           reason="空文本", detected_keywords=[])
    detected: list[str] = []
    category = None
    for cat, words in _RISK_CATEGORIES.items():
        for w in words:
            count = text.count(w)
            if count > 0 and w not in _WHITELIST:
                detected.extend([w] * count)
                if category is None:
                    category = cat
    if not detected:
        return RiskVerdict(flagged=False, category=None, severity="none", confidence=0.9,
                           reason="未检测到风险关键词", detected_keywords=[])
    unique = list(dict.fromkeys(detected))
    severity = "high" if len(detected) >= 3 else "medium" if len(detected) >= 2 else "low"
    confidence = min(0.95, 0.5 + 0.15 * len(detected))
    return RiskVerdict(flagged=True, category=category, severity=severity,
                       confidence=round(confidence, 2),
                       reason=f"检测到 {len(detected)} 个风险关键词",
                       detected_keywords=unique)


def assess_risk(events: list[AudienceEvent], llm_checker=None,
                event_ids: list[str] | None = None) -> list[dict]:
    """event_ids 为并行的真实事件 id 列表；缺省时退回 segment_id（兼容旧调用）。

    旧行为把 segment_id 写进 event_id 字段，风险结论无法回指触发它的事件。
    """
    if event_ids is not None and len(event_ids) != len(events):
        raise ValueError("event_ids must match events length")
    results = []
    for index, e in enumerate(events):
        texts = [e.reaction]
        if e.comment_text:
            texts.append(e.comment_text)
        combined = " ".join(texts)
        verdict = keyword_risk_check(combined)
        if llm_checker is not None and verdict.flagged:
            try:
                llm_verdict = llm_checker(combined, verdict.category)
                if llm_verdict and isinstance(llm_verdict, dict):
                    verdict = RiskVerdict(
                        flagged=llm_verdict.get("flagged", verdict.flagged),
                        category=llm_verdict.get("category", verdict.category),
                        severity=llm_verdict.get("severity", verdict.severity),
                        confidence=llm_verdict.get("confidence", verdict.confidence),
                        reason=llm_verdict.get("reason", verdict.reason),
                        detected_keywords=verdict.detected_keywords,
                    )
            except Exception:
                pass
        results.append({"event_id": e.segment_id if event_ids is None else event_ids[index],
                        "verdict": verdict.to_dict()})
    return results
