from pathlib import Path

import pytest

from backend.adapters.personas import _allocate, _map_one, load_personas, sample_personas
from backend.domain.schemas import Persona

DATA_DIR = Path(__file__).resolve().parents[3] / "personas"


class TestLoadPersonas:
    def test_three_types(self):
        pools = load_personas(DATA_DIR)
        assert set(pools.keys()) == {"positive", "neutral", "negative"}

    def test_counts(self):
        pools = load_personas(DATA_DIR)
        assert len(pools["positive"]) == 200
        assert len(pools["neutral"]) == 200
        assert len(pools["negative"]) == 200

    def test_all_valid_personas(self):
        pools = load_personas(DATA_DIR)
        for t, pool in pools.items():
            for p in pool:
                assert isinstance(p, Persona), f"{t} has invalid entry"
                assert p.goal.strip(), f"{t}/{p.id} empty goal"
                assert p.knowledge.strip(), f"{t}/{p.id} empty knowledge"

    def test_all_ids_unique(self):
        pools = load_personas(DATA_DIR)
        all_ids = [p.id for pool in pools.values() for p in pool]
        assert len(all_ids) == len(set(all_ids))


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

    def test_missing_optional_fields(self):
        raw = {
            "id": "minimal_001",
            "type": "neutral",
            "name": "Min",
            "demographics": {"age": "25", "region": "LA"},
            "background": "Minimal persona.",
            "personality_traits": ["Simple"],
        }
        p = _map_one(raw)
        assert p.id == "minimal_001"
        assert "Minimal persona." in p.goal
        assert "Simple" in p.preferences

    def test_long_fields_truncated(self):
        long_text = "x" * 2000
        raw = {
            "id": "trunc_001",
            "type": "positive",
            "name": "T",
            "demographics": {"age": "30", "profession": "W", "region": "R"},
            "background": long_text,
            "personality_traits": [long_text],
            "communication_style": {"tone": long_text},
        }
        p = _map_one(raw)
        assert len(p.goal) <= 1000
        assert len(p.knowledge) <= 1000
        for pref in p.preferences:
            assert len(pref) <= 1000

    def test_preferences_capped_at_10(self):
        raw = {
            "id": "cap_001",
            "type": "positive",
            "name": "C",
            "demographics": {"age": "30", "profession": "W", "region": "R"},
            "background": "bg",
            "personality_traits": [f"trait_{i}" for i in range(15)],
            "communication_style": {"tone": "t", "engagement_level": "e", "argument_approach": "a"},
        }
        p = _map_one(raw)
        assert len(p.preferences) <= 10


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

    def test_oversample_raises(self):
        with pytest.raises(ValueError):
            sample_personas(400, seed=42, data_dir=DATA_DIR)

    def test_n6_type_ratio(self):
        pools = load_personas(DATA_DIR)
        personas = sample_personas(6, seed=42, data_dir=DATA_DIR)
        type_map = {}
        for t, pool in pools.items():
            for p in pool:
                type_map[p.id] = t
        counts = {"positive": 0, "neutral": 0, "negative": 0}
        for p in personas:
            counts[type_map[p.id]] += 1
        assert counts["positive"] >= counts["neutral"] >= counts["negative"]


class TestAudienceIntegration:
    def test_sampled_personas_fit_simulation_input(self):
        from backend.simulation.audience_session import AudienceSimulationInput
        from backend.domain.hashing import content_hash

        content = {
            "titles": ["标题一", "标题二", "标题三"],
            "cover_copy": "封面文案",
            "segments": [
                {"segment_id": "s1", "kind": "body", "text": "第一段正文。", "source_refs": []},
                {"segment_id": "s2", "kind": "closing", "text": "结尾段。", "source_refs": []},
            ],
        }
        personas = sample_personas(3, seed=42, data_dir=DATA_DIR)
        snapshot = AudienceSimulationInput(
            confirmed=True,
            version_id="v_" + "a" * 32,
            content_hash=content_hash(content),
            content=content,
            personas=personas,
            max_segments=8,
            max_calls=9,
            max_active_seconds=1200,
        )
        assert len(snapshot.personas) == 3

    def test_sampled_personas_serialize_cleanly(self):
        personas = sample_personas(4, seed=42, data_dir=DATA_DIR)
        for p in personas:
            d = p.model_dump(mode="json")
            assert set(d.keys()) == {"id", "goal", "knowledge", "preferences"}
            assert isinstance(d["preferences"], list)
