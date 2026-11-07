"""Emotion contagion, stance aggregation, and 4-dimension feedback report."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.domain.schemas import AudienceEvent

_NEGATIVE_KEYWORDS = [
    "垃圾", "无聊", "难看", "没用", "废话", "太长", "看不懂", "失望", "恶心",
    "骗人", "假的", "不行", "差评", "无聊", "浪费", "糟糕", "恶心", "受不了",
    "没意思", "太水", "凑数", "抄的", "标题党", "退了", "不看了",
]

_SUPPORT_WORDS = ["有用", "学到了", "不错", "喜欢", "收藏", "赞", "好", "清晰", "实用", "感谢"]
_OPPOSE_WORDS = ["反对", "不对", "假的", "骗人", "垃圾", "太差", "烂", "无聊", "没用"]


def compute_emotion_score(visible_text: str) -> float:
    if not visible_text.strip():
        return 0.1
    chars = [c for c in visible_text if not c.isspace()]
    if not chars:
        return 0.1
    neg_count = sum(visible_text.count(kw) for kw in _NEGATIVE_KEYWORDS)
    neg_ratio = min(1.0, neg_count * 0.15)
    if neg_ratio > 0.5:
        return -0.8
    if neg_ratio > 0.3:
        return -0.5
    if neg_ratio > 0.1:
        return -0.2
    return 0.1


@dataclass
class StanceResult:
    segment_id: str
    support_count: int = 0
    neutral_count: int = 0
    oppose_count: int = 0
    representative: dict[str, str] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.support_count + self.neutral_count + self.oppose_count

    @property
    def support_ratio(self) -> float:
        return self.support_count / self.total if self.total else 0.0

    @property
    def neutral_ratio(self) -> float:
        return self.neutral_count / self.total if self.total else 0.0

    @property
    def oppose_ratio(self) -> float:
        return self.oppose_count / self.total if self.total else 0.0


def _classify_stance(text: str) -> str:
    support = sum(1 for w in _SUPPORT_WORDS if w in text)
    oppose = sum(1 for w in _OPPOSE_WORDS if w in text)
    if oppose > support:
        return "oppose"
    if support > oppose:
        return "support"
    return "neutral"


def aggregate_stance(events: list[AudienceEvent], segment_id: str | None = None) -> StanceResult:
    result = StanceResult(segment_id=segment_id or "full")
    filtered = [e for e in events if segment_id is None or e.segment_id == segment_id]
    for e in filtered:
        text = e.reaction + (" " + e.comment_text if e.comment_text else "")
        stance = _classify_stance(text)
        if stance == "support":
            result.support_count += 1
        elif stance == "oppose":
            result.oppose_count += 1
        else:
            result.neutral_count += 1
        if stance not in result.representative:
            result.representative[stance] = e.comment_text or e.reaction[:100]
    return result


@dataclass
class FeedbackReport:
    emotion_score: float
    stance: StanceResult
    segment_stances: list[StanceResult]
    interaction_counts: dict[str, int]
    exit_count: int
    completed_count: int
    total_viewers: int
    coverage_ratio: float
    completion_ratio: float

    def to_dict(self) -> dict:
        return {
            "emotion": {
                "score": self.emotion_score,
                "verdict": "negative" if self.emotion_score < -0.3 else "positive" if self.emotion_score > 0 else "neutral",
            },
            "stance": {
                "support_ratio": round(self.stance.support_ratio, 3),
                "neutral_ratio": round(self.stance.neutral_ratio, 3),
                "oppose_ratio": round(self.stance.oppose_ratio, 3),
                "representative": self.stance.representative,
            },
            "interactions": self.interaction_counts,
            "influence": {
                "exit_count": self.exit_count,
                "completed_count": self.completed_count,
                "total_viewers": self.total_viewers,
                "coverage_ratio": round(self.coverage_ratio, 3),
                "completion_ratio": round(self.completion_ratio, 3),
            },
            "segment_stances": [
                {
                    "segment_id": s.segment_id,
                    "support": s.support_count,
                    "neutral": s.neutral_count,
                    "oppose": s.oppose_count,
                }
                for s in self.segment_stances
            ],
            "is_simulation": True,
            "predicts_real_traffic": False,
        }


def build_feedback_report(
    events: list[AudienceEvent],
    sessions: list[dict],
    all_segment_ids: list[str],
    visible_texts: dict[str, str],
) -> FeedbackReport:
    full_stance = aggregate_stance(events)
    seg_stances = [aggregate_stance(events, sid) for sid in all_segment_ids if any(e.segment_id == sid for e in events)]

    emotion_parts = [compute_emotion_score(visible_texts.get(sid, "")) for sid in all_segment_ids]
    avg_emotion = sum(emotion_parts) / len(emotion_parts) if emotion_parts else 0.1

    interaction_counts = {"like": 0, "comment": 0, "save": 0}
    for e in events:
        for i in e.interactions:
            interaction_counts[i] = interaction_counts.get(i, 0) + 1

    exited = sum(1 for s in sessions if s.get("outcome") == "exited")
    completed = sum(1 for s in sessions if s.get("outcome") == "completed")
    total = len(sessions)

    return FeedbackReport(
        emotion_score=avg_emotion,
        stance=full_stance,
        segment_stances=seg_stances,
        interaction_counts=interaction_counts,
        exit_count=exited,
        completed_count=completed,
        total_viewers=total,
        coverage_ratio=len(events) / (total * len(all_segment_ids)) if total and all_segment_ids else 0.0,
        completion_ratio=completed / total if total else 0.0,
    )
