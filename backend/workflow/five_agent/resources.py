"""Resource loader for the five/seven-agent contract files.

- agent-interface.json: upstream snapshot extracted from the team handoff
  (five-agent.v0.2, unchanged, kept for provenance).
- agent-interface-seven.json: runtime contract seven-agent.v0.1 — adds
  pr_analyst.analyze_request and splits operations_officer into
  operations_officer.prepare_brief + editorial_reviewer.assess_content.
- domain_schemas.json: DTO subset extracted from the handoff contracts.
- extension_schemas.json: DTOs added on top (RequestAnalysis).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

RESOURCES_DIR = Path(__file__).resolve().parent / "resources"


@lru_cache(maxsize=1)
def load_contract() -> dict:
    return json.loads((RESOURCES_DIR / "agent-interface-seven.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_domain_schemas() -> dict:
    domain = json.loads((RESOURCES_DIR / "domain_schemas.json").read_text(encoding="utf-8"))
    extension = json.loads((RESOURCES_DIR / "extension_schemas.json").read_text(encoding="utf-8"))
    merged = dict(domain)
    merged.update(extension)
    return merged
