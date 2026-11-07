"""Deterministic content checks. No model, database or network access."""
from backend.domain.hashing import content_hash
from backend.domain.schemas import Brief, ContentCandidate, LengthRule, RuleReport, RuleResult


def validate_content(version_id: str, content: ContentCandidate, brief: Brief) -> RuleReport:
    return validate_content_rules(version_id, content, brief.length_rule)


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
