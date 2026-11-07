import copy
import math

import pytest

from backend.domain.hashing import canonical_bytes, brief_hash, content_hash, scenario_hash


def test_canonical_hash_is_order_independent_and_preserves_text_bytes():
    left = {"b": "中\n文", "a": 1}
    right = {"a": 1, "b": "中\n文"}
    assert canonical_bytes(left) == canonical_bytes(right) == b'{"a":1,"b":"\xe4\xb8\xad\\n\xe6\x96\x87"}'
    assert canonical_bytes({"b": "中\r\n文", "a": 1}) != canonical_bytes(left)
    with pytest.raises(ValueError):
        canonical_bytes({"value": math.nan})


def test_content_hash_excludes_version_metadata_but_keeps_segment_order():
    content = {"titles": ["甲", "乙", "丙"], "cover_copy": "封面", "segments": [
        {"segment_id": "s1", "kind": "body", "text": "一", "source_refs": ["m1"]},
        {"segment_id": "s2", "kind": "body", "text": "二", "source_refs": []},
    ], "version_id": "v1", "change_log": []}
    other = {**content, "version_id": "v2", "change_log": [{"x": 1}]}
    assert content_hash(content) == content_hash(other)
    reordered = copy.deepcopy(content)
    reordered["segments"].reverse()
    assert content_hash(content) != content_hash(reordered)


def test_brief_rules_and_persona_order_affect_hash():
    assert brief_hash({"objective": "甲"}, {"rule": 1}) != brief_hash({"objective": "甲"}, {"rule": 2})
    scenario = {"personas": [{"id": "a"}, {"id": "b"}], "medium": "text"}
    reordered = {**scenario, "personas": list(reversed(scenario["personas"]))}
    assert scenario_hash(scenario) != scenario_hash(reordered)
