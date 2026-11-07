"""Map persona databases to the audience Persona schema and sample proportionally."""
import json
import random
from pathlib import Path

from backend.domain.schemas import Persona

_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "personas"
_TYPES = ("positive", "neutral", "negative")
_RATIO = (0.6, 0.3, 0.1)


class AudiencePersonaSelector:
    """Multi-round persona selector with dedup pool and exhaustion reset."""

    def __init__(self, data_dir: Path | None = None, pools: dict[str, list[Persona]] | None = None):
        self.pools = pools or load_personas(data_dir)
        self.used_ids: set[str] = set()
        self.round_history: list[dict] = []
        self.effectiveness: dict[str, float] = {}

    def select(self, n: int, *, seed: int | None = None) -> list[Persona]:
        counts = _allocate(n)
        rng = random.Random(seed)
        result: list[Persona] = []
        for type_name, count in zip(_TYPES, counts):
            if count == 0:
                continue
            available = [p for p in self.pools[type_name] if p.id not in self.used_ids]
            if len(available) < count:
                self.used_ids.clear()
                available = list(self.pools[type_name])
            if self.effectiveness:
                weights = [1.0 + self.effectiveness.get(p.id, 0.0) for p in available]
                picked = rng.choices(available, weights=weights, k=count)
                seen: set[str] = set()
                unique_picked = []
                for p in picked:
                    if p.id not in seen:
                        seen.add(p.id)
                        unique_picked.append(p)
                while len(unique_picked) < count:
                    extra = rng.choice(available)
                    if extra.id not in seen:
                        seen.add(extra.id)
                        unique_picked.append(extra)
                picked = unique_picked
            else:
                picked = rng.sample(available, count)
            result.extend(picked)
        rng.shuffle(result)
        self.used_ids.update(p.id for p in result)
        self.round_history.append({"seed": seed, "selected_ids": [p.id for p in result]})
        return result

    def record_feedback(self, persona_id: str, effectiveness: float) -> None:
        self.effectiveness[persona_id] = self.effectiveness.get(persona_id, 0.0) + effectiveness

    def reset(self) -> None:
        self.used_ids.clear()
        self.round_history.clear()


def _profession(raw: dict) -> str:
    if "profession" in raw.get("demographics", {}):
        return raw["demographics"]["profession"]
    return raw.get("profession", "")


def _map_one(raw: dict) -> Persona:
    demo = raw.get("demographics", {})
    bg = raw.get("background", "")
    cs = raw.get("communication_style", {})
    traits = raw.get("personality_traits", [])

    goal_parts = [bg]
    if cs.get("content_preference"):
        goal_parts.append("偏好内容：" + cs["content_preference"])
    goal = " ".join(goal_parts)[:1000]

    demo_bits = [_profession(raw)]
    if demo.get("age"):
        demo_bits.append(f"{demo['age']}岁")
    if demo.get("region"):
        demo_bits.append(demo["region"])
    knowledge = "，".join(b for b in demo_bits if b)[:1000]

    prefs = list(traits)
    if cs.get("tone"):
        prefs.append("语气：" + cs["tone"])
    if cs.get("engagement_level"):
        prefs.append("参与度：" + cs["engagement_level"])
    if cs.get("argument_approach"):
        prefs.append("讨论方式：" + cs["argument_approach"])
    preferences = [p[:1000] for p in prefs if p.strip()][:10]

    return Persona(id=raw["id"], goal=goal, knowledge=knowledge, preferences=preferences)


def load_personas(data_dir: Path | None = None) -> dict[str, list[Persona]]:
    data_dir = data_dir or _DEFAULT_DATA_DIR
    result: dict[str, list[Persona]] = {}
    for t in _TYPES:
        path = data_dir / f"{t}_personas_database.json"
        raw_list = json.loads(path.read_text(encoding="utf-8"))
        result[t] = [_map_one(r) for r in raw_list]
    return result


def _allocate(n: int) -> tuple[int, int, int]:
    if n < 1:
        raise ValueError("n must be >= 1")
    if n == 1:
        return (1, 0, 0)
    if n == 2:
        return (1, 1, 0)
    remaining = n - 3
    raw = [remaining * r for r in _RATIO]
    floors = [int(x) for x in raw]
    deficit = remaining - sum(floors)
    order = sorted(range(3), key=lambda i: -(raw[i] - floors[i]))
    for i in range(deficit):
        floors[order[i]] += 1
    return (1 + floors[0], 1 + floors[1], 1 + floors[2])


def sample_personas(
    n: int,
    *,
    seed: int | None = None,
    data_dir: Path | None = None,
) -> list[Persona]:
    pools = load_personas(data_dir)
    counts = _allocate(n)
    rng = random.Random(seed)
    result: list[Persona] = []
    for type_name, count in zip(_TYPES, counts):
        if count > 0:
            result.extend(rng.sample(pools[type_name], count))
    rng.shuffle(result)
    return result
