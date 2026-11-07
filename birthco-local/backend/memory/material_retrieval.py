"""Rank authorized material within one task using bounded lexical expansion."""
from backend.memory.operator_memory import terms_of


def rank_materials(query: str, materials: list[dict]) -> tuple[list[dict], list[list[str]]]:
    """Return all rows in retrieval order and a three-round trace of matched IDs."""
    pending = list(materials)
    ranked = []
    rounds = []
    terms = terms_of(query)
    for _ in range(3):
        if not pending or not terms:
            break
        scores = {m["id"]: sum(term.casefold() in m["text"].casefold() for term in terms)
                  for m in pending}
        matched = sorted((m for m in pending if scores[m["id"]] > 0),
                         key=lambda m: (-scores[m["id"]], m["id"]))[:3]
        if not matched:
            break
        matched_ids = {m["id"] for m in matched}
        rounds.append([m["id"] for m in matched])
        ranked.extend(matched)
        pending = [m for m in pending if m["id"] not in matched_ids]
        terms = terms_of(" ".join(m["text"][:500] for m in matched))
    return ranked + pending, rounds
