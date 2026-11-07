"""流量捕捉者真实入口桥接:缺省 account/brief 派生 + 机会输出映射。"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BC_BACKEND = ROOT / "birthco-local" / "backend"

import backend  # noqa: E402
if str(BC_BACKEND) not in backend.__path__:
    backend.__path__.append(str(BC_BACKEND))

from backend.adapters.bridge_common import orchestration_ref_digest  # noqa: E402
from backend.adapters.scout_bridge import ScoutTeamAdapter  # noqa: E402


def _call():
    return SimpleNamespace(request_id="req_1", agent_id="traffic_scout",
                           action="capture_opportunities", contract_version="seven-agent.v0.1",
                           context=SimpleNamespace(task_id="t1", account_id="account"),
                           input={"goal": "写一篇新手拍照入门图文",
                                  "material_refs": [{"id": "m1",
                                                     "sha256": orchestration_ref_digest(
                                                         "拍照入门：先学会构图三分法，再练光线。")}]})


def _adapter():
    return ScoutTeamAdapter(resolve_material=lambda ref: {
        "id": "m1", "text": "拍照入门：先学会构图三分法，再练光线。",
        "kind": "text", "label": "构图", "source_url": None}, mode="mock")


def test_opportunities_map_to_opportunity_set():
    out = _adapter().invoke(_call())
    assert out["status"] == "ok", out
    data = out["data"]
    assert "opportunities" in data and data["opportunities"]
    for opp in data["opportunities"]:
        assert set(opp) == {"id", "angle", "audience_problem", "account_fit",
                            "source_refs", "evidence_date", "hypothesis"}
        assert opp["evidence_date"] is None
        assert opp["source_refs"] and set(opp["source_refs"]) <= {"m1"}


def test_no_materials_is_needs_input():
    call = _call()
    call.input["material_refs"] = []
    out = _adapter().invoke(call)
    assert out["status"] == "needs_input" and out["questions"]


def test_bad_fingerprint_is_error():
    call = _call()
    call.input["material_refs"][0]["sha256"] = "0" * 64
    out = _adapter().invoke(call)
    assert out["status"] == "error"


def test_material_id_passthrough_no_remap():
    out = _adapter().invoke(_call())
    for opp in out["data"]["opportunities"]:
        assert all(ref == "m1" for ref in opp["source_refs"])
