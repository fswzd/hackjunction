"""U-3 prompt 哈希冻结锁定 + U-4 schema 双源漂移检查。"""
import json
from pathlib import Path

from backend.agents.operator import prompt_fingerprint
from backend.domain import schemas

REPO_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = REPO_ROOT / "evidence" / "operator-prompt-hash.json"
DOMAIN_SCHEMAS = REPO_ROOT / "backend" / "workflow" / "five_agent" / "resources" / "domain_schemas.json"


def test_prompt_hash_matches_frozen_declaration():
    """SYSTEM 或输出 schema 变更 → 此测试失败 → 申报件失效须重报（G-06）。"""
    recorded = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    current = prompt_fingerprint()
    assert current["prompt_hash"] == recorded["prompt_hash"], (
        "prompt/schema 已变更：重报 evidence/operator-prompt-hash.json 后再冻结")
    assert current["system_sha256"] == recorded["system_sha256"]
    assert current["schema_sha256"] == recorded["schema_sha256"]


def test_no_placeholder_hashes_in_operator_evidence():
    recorded = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert recorded["prompt_hash"] != "b" * 64 and len(recorded["prompt_hash"]) == 64


def _shape(schema: dict) -> dict:
    return {"properties": sorted(schema.get("properties", {})),
            "required": sorted(schema.get("required", []))}


def test_domain_schemas_do_not_drift_from_pydantic_models():
    """birthco-local pydantic 定义与编排层 domain_schemas.json 快照结构不漂移。"""
    snapshot = json.loads(DOMAIN_SCHEMAS.read_text(encoding="utf-8"))
    brief_snap = snapshot["Brief"]
    defs = brief_snap.get("$defs", {})
    sources = {"Brief": brief_snap, "EditScope": defs["EditScope"],
               "Requirement": defs["Requirement"], "LengthRule": defs["LengthRule"]}
    for name, model in (("Brief", schemas.Brief), ("EditScope", schemas.EditScope),
                        ("Requirement", schemas.Requirement), ("LengthRule", schemas.LengthRule)):
        assert _shape(model.model_json_schema()) == _shape(sources[name]), f"{name} 双源结构漂移"

    def _enum(node):
        if "enum" in node:
            return set(node["enum"])
        for sub in node.get("anyOf", []) or []:
            if "enum" in sub:
                return set(sub["enum"])
        raise AssertionError(f"no enum in route items: {node}")

    pydantic_route = _enum(schemas.Brief.model_json_schema()["properties"]["route"]["items"])
    snap_route = _enum(brief_snap["properties"]["route"]["items"])
    assert pydantic_route == snap_route, "route 枚举漂移"
