"""Comment de-homogenization: similarity guard + high-temperature rewrite."""
from __future__ import annotations

import re
from collections import defaultdict

from backend.domain.schemas import AudienceEvent

_CLICHE_PATTERNS = [
    r"写得不错", r"学到了", r"涨知识", r"干货满满", r"收藏了", r"点赞",
    r"支持一下", r"加油", r"不错不错", r"很好很好", r"谢谢分享", r"感谢分享",
    r"太棒了", r"真不错", r"很有用", r"受教了", r"mark一下",
]

_SIMILARITY_THRESHOLD = 0.7
_MAX_REWRITES = 3


def _char_ngrams(text: str, n: int = 3) -> set[str]:
    cleaned = re.sub(r"\s+", "", text)
    return {cleaned[i:i+n] for i in range(len(cleaned) - n + 1)} if len(cleaned) >= n else {cleaned}


def _similarity(a: str, b: str) -> float:
    ga, gb = _char_ngrams(a), _char_ngrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def _is_cliche(text: str) -> bool:
    return any(re.search(p, text) for p in _CLICHE_PATTERNS)


def needs_rewrite(comment: str, prior_comments: list[str]) -> bool:
    if not comment or not comment.strip():
        return False
    if _is_cliche(comment):
        return True
    return any(_similarity(comment, prior) > _SIMILARITY_THRESHOLD for prior in prior_comments)


def deduplicate_comments(events: list[AudienceEvent], rewrite_fn=None) -> list[AudienceEvent]:
    """Detect homogenized comments and optionally rewrite. Falls back to original on failure."""
    seen_per_segment: dict[str, list[str]] = defaultdict(list)
    result: list[AudienceEvent] = []
    for e in events:
        if e.comment_text and needs_rewrite(e.comment_text, seen_per_segment[e.segment_id]):
            original = e.comment_text
            rewritten = None
            if rewrite_fn:
                for attempt in range(_MAX_REWRITES):
                    try:
                        candidate = rewrite_fn(original, temperature=0.5 + 0.1 * attempt)
                        if candidate and candidate.strip() and not needs_rewrite(candidate, seen_per_segment[e.segment_id]):
                            rewritten = candidate.strip()
                            break
                    except Exception:
                        break
            if rewritten:
                e = e.model_copy(update={"comment_text": rewritten[:1000]})
            seen_per_segment[e.segment_id].append(e.comment_text)
        elif e.comment_text:
            seen_per_segment[e.segment_id].append(e.comment_text)
        result.append(e)
    return result
