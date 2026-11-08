"""Deterministic content checks. No model, database or network access."""
import re

from backend.domain.hashing import content_hash
from backend.domain.length import conflicting_mentions, spec_from_requirements
from backend.domain.schemas import Brief, ContentCandidate, LengthRule, RuleReport, RuleResult

# Accept "[第 0–10 秒]", "【开场 0-5s】" and plain "5~25 秒" markers.
_RANGE = re.compile(
    r"(\d+)\s*[–—\-~～至]\s*(\d+)\s*(秒钟|秒|分钟|s(?![A-Za-z]))", re.I
)
# Only explicit *total* claims are checked in the body; per-segment offsets
# are legitimate and are handled by the range check instead.
_TOTAL = re.compile(
    r"(?:全程|总时长|总长|全片|整支|整篇|本片|时长|用时|共)\s*(?:约|大约|为|是)?\s*"
    r"(\d+)\s*(秒钟|秒|分钟|字|字符)", re.I
)


def timeline_issues(content: ContentCandidate, spec) -> list[str]:
    """Validate every time range in the delivered script against the target."""
    text = "\n".join(segment.text for segment in content.segments)
    ranges: list[tuple[int, int]] = []
    for match in _RANGE.finditer(text):
        start, end = int(match.group(1)), int(match.group(2))
        if match.group(3).lower().startswith("分"):
            start, end = start * 60, end * 60
        ranges.append((start, end))
    issues: list[str] = []
    if ranges and spec.target_seconds is None:
        issues.append("文章 / 字数类目标不应出现秒数时间轴")
    elif ranges:
        last = max(end for _, end in ranges)
        if last != spec.target_seconds:
            issues.append(f"时间轴末段落在 {last} 秒，应正好落在 {spec.target_seconds} 秒")
        if any(start >= end or end > spec.target_seconds for start, end in ranges):
            issues.append("时间轴区间超出所选时长或顺序有误")
    for match in _TOTAL.finditer(text):
        number = int(match.group(1))
        unit = match.group(2)
        if "字" in unit:
            if spec.target_characters is not None and number != spec.target_characters:
                issues.append(f"正文声称 {number} 字，与「{spec.describe()}」不符")
        else:
            claimed = number * 60 if unit.startswith("分") else number
            if spec.target_seconds is not None and claimed != spec.target_seconds:
                issues.append(f"正文声称总时长 {match.group(0)}，与「{spec.describe()}」不符")
    return list(dict.fromkeys(issues))


def validate_content(version_id: str, content: ContentCandidate, brief: Brief) -> RuleReport:
    report = validate_content_rules(version_id, content, brief.length_rule)
    spec = spec_from_requirements(r.text for r in brief.requirements)
    if spec is None:
        return report
    # Titles and cover copy are where a "60 秒看懂" claim would contradict a
    # 30-second selection. Body text is deliberately excluded here because
    # timeline markers describe offsets, not the total duration; those are
    # checked separately by RULE_TIMELINE below.
    headline = "\n".join([*content.titles, content.cover_copy or ""])
    conflicts = list(dict.fromkeys(conflicting_mentions(headline, spec)))
    duration_reason = (f"标题/封面时长与目标「{spec.describe()}」一致" if not conflicts
                       else f"标题/封面出现不符的时长或字数：{'、'.join(conflicts[:4])}；应为「{spec.describe()}」")
    timeline = timeline_issues(content, spec)
    timeline_reason = (f"正文时间轴与目标「{spec.describe()}」一致" if not timeline
                       else "；".join(timeline[:4]))
    checks = [
        *report.checks,
        RuleResult(rule_id="RULE_TARGET_DURATION", passed=not conflicts,
                   reason=duration_reason[:1000], segment_id="titles"),
        RuleResult(rule_id="RULE_TIMELINE", passed=not timeline,
                   reason=timeline_reason[:1000], segment_id="body"),
    ]
    return report.model_copy(update={"checks": checks,
                                     "passed": all(item.passed for item in checks)})


def validate_content_rules(version_id: str, content: ContentCandidate, length_rule: LengthRule) -> RuleReport:
    checks = []
    def check(rule_id, passed, reason, segment_id=None):
        checks.append(RuleResult(rule_id=rule_id, passed=passed, reason=reason, segment_id=segment_id))
    check("RULE_TITLES",len(content.titles)==3 and len({t.strip() for t in content.titles})==3 and all(t.strip() and len(t)<=1000 for t in content.titles),"需要三条不同且不超过1000字符的非空标题","titles")
    check("RULE_COVER",bool(content.cover_copy and content.cover_copy.strip()),"需要非空封面文案","cover")
    ids=[s.segment_id for s in content.segments]
    check("RULE_IDS",len(ids)==len(set(ids)) and not set(ids)&{"titles","cover"},"正文段落编号必须唯一且不占用标题封面编号")
    check("RULE_BODY",any(s.kind=="body" and s.text.strip() for s in content.segments),"需要至少一段非空正文")
    count=sum(1 for s in content.segments for c in s.text if not c.isspace())
    check("RULE_LENGTH",count<=20000 and (length_rule.minimum is None or count>=length_rule.minimum) and (length_rule.maximum is None or count<=length_rule.maximum),"正文非空白字符数必须满足确认的长度范围")
    check("RULE_SEGMENTS",bool(content.segments) and all(s.text.strip() for s in content.segments),"内容段落不得为空")
    return RuleReport(version_id=version_id,content_hash=content_hash(content),rule_version="content-rules-v1",passed=all(c.passed for c in checks),body_characters=count,checks=checks)
