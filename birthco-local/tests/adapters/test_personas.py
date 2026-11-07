from pathlib import Path

import pytest

from backend.adapters.personas import AudiencePersonaSelector, _allocate, _map_one, load_personas, sample_personas
from backend.domain.schemas import Persona

DATA_DIR = Path(__file__).resolve().parents[3] / "personas"


class TestMapOne:
    def test_positive(self):
        raw = {
            "id": "positive_test_001",
            "type": "positive",
            "name": "Test",
            "demographics": {"age": "30", "profession": "Engineer", "region": "NYC"},
            "background": "An engineer who likes clear writing.",
            "personality_traits": ["Pragmatic", "Thoughtful"],
            "communication_style": {"tone": "Friendly", "engagement_level": "high",
                                     "content_preference": "Inspiring posts", "argument_approach": "Logical"},
        }
        p = _map_one(raw)
        assert isinstance(p, Persona)
        assert p.id == "positive_test_001"
        assert "clear writing" in p.goal
        assert "Inspiring posts" in p.goal
        assert "Engineer" in p.knowledge
        assert "30岁" in p.knowledge
        assert "Pragmatic" in p.preferences
        assert any("Friendly" in x for x in p.preferences)

    def test_neutral_profession_top_level(self):
        raw = {
            "id": "neutral_test_001",
            "type": "neutral",
            "name": "Test",
            "profession": "Nurse",
            "demographics": {"age": "50", "region": "VT"},
            "background": "A nurse who watches debates.",
            "personality_traits": ["Cautious"],
            "communication_style": {"tone": "Reflective", "engagement_level": "low"},
        }
        p = _map_one(raw)
        assert "Nurse" in p.knowledge
        assert "50" in p.knowledge
        assert any("Reflective" in x for x in p.preferences)

    def test_negative(self):
        raw = {
            "id": "negative_test_001",
            "type": "negative",
            "name": "Test",
            "demographics": {"age": "40", "profession": "Troll", "region": "Nowhere"},
            "background": "A hostile commenter.",
            "personality_traits": ["Aggressive"],
            "communication_style": {"tone": "Hostile", "engagement_level": "burst",
                                     "content_preference": "Chaos", "argument_approach": "Derail"},
        }
        p = _map_one(raw)
        assert p.id == "negative_test_001"
        assert any("Hostile" in x for x in p.preferences)
        assert "Troll" in p.knowledge


class TestAllocate:
    def test_n1(self):
        assert _allocate(1) == (1, 0, 0)

    def test_n2(self):
        assert _allocate(2) == (1, 1, 0)

    def test_n3(self):
        assert _allocate(3) == (1, 1, 1)

    def test_n4(self):
        assert _allocate(4) == (2, 1, 1)

    def test_n5(self):
        assert _allocate(5) == (2, 2, 1)

    def test_n6(self):
        assert _allocate(6) == (3, 2, 1)

    def test_sums_to_n(self):
        for n in range(1, 20):
            counts = _allocate(n)
            assert sum(counts) == n
            assert all(c >= 0 for c in counts)

    def test_at_least_one_each_when_n3(self):
        for n in range(3, 20):
            counts = _allocate(n)
            assert all(c >= 1 for c in counts), f"n={n} -> {counts}"

    def test_invalid(self):
        with pytest.raises(ValueError):
            _allocate(0)


class TestSample:
    def test_returns_valid_personas(self):
        personas = sample_personas(6, seed=42, data_dir=DATA_DIR)
        assert len(personas) == 6
        for p in personas:
            assert isinstance(p, Persona)
            assert p.goal.strip()
            assert p.knowledge.strip()
            assert len(p.preferences) >= 1

    def test_unique_ids(self):
        personas = sample_personas(6, seed=42, data_dir=DATA_DIR)
        ids = [p.id for p in personas]
        assert len(ids) == len(set(ids))

    def test_seed_reproducible(self):
        a = sample_personas(6, seed=42, data_dir=DATA_DIR)
        b = sample_personas(6, seed=42, data_dir=DATA_DIR)
        assert [p.id for p in a] == [p.id for p in b]

    def test_different_seed_different_result(self):
        a = sample_personas(6, seed=1, data_dir=DATA_DIR)
        b = sample_personas(6, seed=999, data_dir=DATA_DIR)
        assert [p.id for p in a] != [p.id for p in b]

    def test_n3_has_all_types(self):
        pools = load_personas(DATA_DIR)
        personas = sample_personas(3, seed=42, data_dir=DATA_DIR)
        type_map = {}
        for t, pool in pools.items():
            for p in pool:
                type_map[p.id] = t
        types_used = {type_map[p.id] for p in personas}
        assert types_used == {"positive", "neutral", "negative"}

    def test_min_n(self):
        personas = sample_personas(1, seed=42, data_dir=DATA_DIR)
        assert len(personas) == 1


class TestPersonaSelector:
    def test_no_repeat_across_rounds(self):
        sel = AudiencePersonaSelector(data_dir=DATA_DIR)
        r1 = sel.select(6, seed=1)
        r2 = sel.select(6, seed=2)
        ids1 = {p.id for p in r1}
        ids2 = {p.id for p in r2}
        assert not ids1 & ids2

    def test_exhaustion_resets(self):
        sel = AudiencePersonaSelector(data_dir=DATA_DIR)
        all_selected = set()
        for i in range(5):
            batch = sel.select(6, seed=i)
            all_selected.update(p.id for p in batch)
        assert len(all_selected) > 6

    def test_seed_reproducible(self):
        sel1 = AudiencePersonaSelector(data_dir=DATA_DIR)
        sel2 = AudiencePersonaSelector(data_dir=DATA_DIR)
        r1 = sel1.select(6, seed=42)
        r2 = sel2.select(6, seed=42)
        assert [p.id for p in r1] == [p.id for p in r2]

    def test_history_recorded(self):
        sel = AudiencePersonaSelector(data_dir=DATA_DIR)
        sel.select(3, seed=1)
        assert len(sel.round_history) == 1
        assert len(sel.round_history[0]["selected_ids"]) == 3

    def test_reset(self):
        sel = AudiencePersonaSelector(data_dir=DATA_DIR)
        sel.select(3, seed=1)
        sel.reset()
        assert sel.used_ids == set()
        assert sel.round_history == []


class TestCrossRoundEvolution:
    def test_record_feedback(self):
        sel = AudiencePersonaSelector(data_dir=DATA_DIR)
        sel.record_feedback("p1", 0.5)
        sel.record_feedback("p1", 0.3)
        assert sel.effectiveness["p1"] == pytest.approx(0.8)

    def test_feedback_influences_selection(self):
        sel = AudiencePersonaSelector(data_dir=DATA_DIR)
        pools = sel.pools
        target_ids = [p.id for p in pools["positive"][:3]]
        for pid in target_ids:
            sel.record_feedback(pid, 10.0)
        results = set()
        for seed in range(50):
            sel.used_ids.clear()
            batch = sel.select(3, seed=seed)
            results.update(p.id for p in batch)
        boosted = set(target_ids) & results
        assert len(boosted) >= 1, f"none of {target_ids} selected across 50 rounds"

    def test_reset_preserves_effectiveness(self):
        sel = AudiencePersonaSelector(data_dir=DATA_DIR)
        sel.record_feedback("p1", 1.0)
        sel.reset()
        assert sel.effectiveness == {"p1": 1.0}


class TestReactionMix:
    def test_reaction_mix_in_prompt(self):
        from backend.agents.audience import build_system_prompt
        p = Persona(id="p1", goal="g", knowledge="k", preferences=[])
        prompt = build_system_prompt(p)
        assert "REACTION MIX" in prompt


class TestPromptBuild:
    def test_persona_injection(self):
        from backend.agents.audience import build_system_prompt
        p = Persona(id="p1", goal="学会拍照", knowledge="新手", preferences=["图文"])
        prompt = build_system_prompt(p)
        assert "学会拍照" in prompt
        assert "新手" in prompt
        assert "图文" in prompt

    def test_emotion_modifier(self):
        from backend.agents.audience import build_system_prompt
        p = Persona(id="p1", goal="g", knowledge="k", preferences=[])
        prompt = build_system_prompt(p, emotion_score=-0.8)
        assert "情绪" in prompt

    def test_no_emotion(self):
        from backend.agents.audience import build_system_prompt
        p = Persona(id="p1", goal="g", knowledge="k", preferences=[])
        prompt = build_system_prompt(p)
        assert "情绪" not in prompt


class TestParseOutput:
    def test_clean_json(self):
        from backend.agents.audience import parse_audience_event_json
        result = parse_audience_event_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_markdown_fence(self):
        from backend.agents.audience import parse_audience_event_json
        result = parse_audience_event_json('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_bare_fence(self):
        from backend.agents.audience import parse_audience_event_json
        result = parse_audience_event_json('```\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_raw_decode_fallback(self):
        from backend.agents.audience import parse_audience_event_json
        result = parse_audience_event_json('prefix {"key": "value"} suffix')
        assert result == {"key": "value"}

    def test_invalid_raises(self):
        from backend.agents.audience import parse_audience_event_json
        with pytest.raises(ValueError):
            parse_audience_event_json("not json at all")
