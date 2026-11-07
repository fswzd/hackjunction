"""Canonical UTF-8 JSON hashing. No normalization of user text or line endings."""
import hashlib
import json
from typing import Any

from pydantic import BaseModel


def _plain(value: Any) -> Any:
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(_plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def brief_hash(brief: Any, frozen_rules: dict[str, Any]) -> str:
    return sha256_json({"brief": _plain(brief), "frozen_rules": frozen_rules})


def content_hash(content: Any) -> str:
    data = _plain(content)
    return sha256_json({key: data[key] for key in ("titles", "cover_copy", "segments")})


def scenario_hash(scenario: Any) -> str:
    return sha256_json(scenario)


def conditions_hash(*, scenario: Any, model_id: str, temperature: float, top_p: float,
                    prompt_version: str, prompt_hash: str, schema_version: str,
                    segmenter_version: str, segmenter_hash: str, budget: dict[str, Any],
                    requested_seed: int | None, seed_supported: bool,
                    estimator_version: str, mode: str) -> str:
    return sha256_json({
        "scenario_hash": scenario_hash(scenario), "model_id": model_id,
        "temperature": temperature, "top_p": top_p,
        "prompt_version": prompt_version, "prompt_hash": prompt_hash,
        "schema_version": schema_version, "segmenter_version": segmenter_version,
        "segmenter_hash": segmenter_hash, "budget": budget,
        "requested_seed": requested_seed, "seed_supported": seed_supported,
        "estimator_version": estimator_version, "mode": mode,
    })
