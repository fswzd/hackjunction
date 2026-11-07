"""运营官真实入口（桥接夹具）集成 + prepare_brief 契约语义锁定。

Evidence class: [真实 Adapter 联调]——桥接真实入口（含本体校验）经 AgentAdapter
契约进出；模型为 mock（[真实模型] 属后续阶段）。审计 F-O1/F-O2/F-O5 的回归锚。
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BC_BACKEND = ROOT / "birthco-local" / "backend"

import backend  # noqa: E402  (repo root package)
if str(BC_BACKEND) not in backend.__path__:
    backend.__path__.append(str(BC_BACKEND))

from backend.adapters.orch_bridge import (  # noqa: E402
    BridgePreSendFailure, BridgeUnknownOutcome, OperatorTeamAdapter,
    orchestration_ref_digest,
)
from backend.workflow.five_agent import adapters as A  # noqa: E402
from backend.workflow.five_agent.contracts import ProtocolError, default_validators  # noqa: E402
from backend.workflow.five_agent.driver import OrchestrationDriver  # noqa: E402
from backend.workflow.five_agent.repository import Repository  # noqa: E402


class TeamEntry:
    """AgentAdapter 兼容包装：桥接异常 ↔ 编排层故障语义。"""

    def __init__(self, bridge):
        self.bridge = bridge

    def invoke(self, call):
        try:
            return self.bridge.invoke(call)
        except BridgeUnknownOutcome as exc:
            raise A.UnknownResult(str(exc) or "sent but outcome unknown") from None
        except BridgePreSendFailure as exc:
            raise A.PreSendFailure(str(exc) or "bridge pre-send failure") from None


def make_driver(task_id="task1"):
    repo = Repository(":memory:")

    def resolve(ref):
        for m in repo.list_materials(task_id):
            if m["id"] == ref["id"]:
                return m
        raise KeyError(ref["id"])

    bridge = OperatorTeamAdapter(resolve_material=resolve, mode="mock")
    router = A.AdapterRouter(repo, mode="mock",
                             agent_modes={"operations_officer": "live"},
                             reals={"operations_officer": TeamEntry(bridge)})
    return repo, OrchestrationDriver(repo, router=router)


def confirm_gate(snap, driver, approved=True):
    gate = snap["pending_gates"][0]
    brief_ref = dict(snap["state"]["brief_ref"])
    return driver.decide(snap["run_id"], gate["id"], approved=approved,
                         payload={"brief_version": brief_ref["brief_version"],
                                  "brief_hash": brief_ref["brief_hash"]})


def test_real_entry_runs_main_chain_to_accept():
    repo, driver = make_driver()
    driver.create_task("task1", {"goal": "写一篇新手拍照入门图文",
                                 "user_input": "写一篇新手拍照入门图文",
                                 "input_mode": "idea", "purpose": "content",
                                 "flags": {"traffic_enabled": False, "goal_clear": True}})
    driver.add_material("task1", "mat1", "拍照入门：先学会构图三分法，再练光线。")
    snap = driver.start_content_run("task1")
    assert snap["status"] == "WAITING" and snap["pending_gates"][0]["kind"] == "confirm_brief"
    brief = repo.latest_brief("task1")
    assert brief["payload"]["material_ids"] == ["mat1"], "桥接必须回编排层素材 ID"
    assert brief["payload"]["objective"] == "写一篇新手拍照入门图文", "目标不被改写"
    assert brief["payload"]["route"] == ["draft", "review", "export"]
    snap = confirm_gate(snap, driver)
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True, payload={})
    assert snap["status"] == "READY"
    assert snap["usage"]["normal_calls"] == 3 and snap["usage"]["tech_retries"] == 0


def test_commercial_requirements_keep_original_ids_through_real_entry():
    repo, driver = make_driver()
    driver.create_task("task1", {"goal": "品牌X新品推广",
                                 "user_input": "品牌X新品推广",
                                 "input_mode": "idea", "purpose": "commercial_order",
                                 "client_brief": "品牌X新品推广；要求：文案必须出现品牌名",
                                 "flags": {"traffic_enabled": False, "goal_clear": True}})
    driver.add_material("task1", "mat1", "产品资料：品牌X新品，主打便携。")
    snap = driver.start_content_run("task1")
    assert snap["pending_gates"][0]["kind"] == "confirm_brief"
    pr = repo.find_artifacts("task1", "pr_analysis")[0]
    pr_reqs = {r["id"]: r["text"] for r in pr["payload"]["requirements"]}
    brief = repo.latest_brief("task1")
    got = {r["id"]: r["text"] for r in brief["payload"]["requirements"]}
    assert got == pr_reqs, "客户硬性要求必须带原 requirement_id 进入 Brief（F-O5）"
    assert "文案必须出现品牌名" in brief["payload"]["objective"]


def _bridge_brief_data(requirements=None):
    rows = [{"id": "m1", "text": "素材正文", "kind": "source_text", "label": "s", "source_url": None}]
    payload = {"user_input": "写一篇图文", "input_mode": "idea",
               "material_refs": [{"id": "m1", "sha256": orchestration_ref_digest("素材正文")}],
               "selected_opportunity_ref": None}
    if requirements is not None:
        payload["requirements"] = requirements
    call = SimpleNamespace(request_id="req_1", agent_id="operations_officer",
                           action="prepare_brief", contract_version="seven-agent.v0.1",
                           input=payload, context=SimpleNamespace(account_id="account"))
    result = OperatorTeamAdapter(resolve_material=lambda ref: rows[0], mode="mock").invoke(call)
    assert result["status"] == "ok", result
    return result["data"]


def _raw_result(data, **over):
    raw = {"contract_version": "seven-agent.v0.1", "request_id": "req_1",
           "agent_id": "operations_officer", "action": "prepare_brief",
           "status": "ok", "data": data, "questions": [], "issues": [],
           "usage": {"status": "known", "total_tokens": 100}}
    raw.update(over)
    return raw


def _request(requirements=None):
    payload = {"user_input": "写一篇图文", "input_mode": "idea",
               "material_refs": [{"id": "m1", "sha256": "0" * 64}],
               "selected_opportunity_ref": None}
    if requirements is not None:
        payload["requirements"] = requirements
    return {"contract_version": "seven-agent.v0.1", "request_id": "req_1",
            "agent_id": "operations_officer", "action": "prepare_brief",
            "context": {"account_id": "account", "task_id": "task1", "run_id": "run1",
                        "step_key": "brief:x", "attempt": 1, "input_hash": "0" * 64},
            "input": payload}


def test_semantics_reject_ok_with_open_questions():
    data = _bridge_brief_data()
    data["open_questions"] = [{"id": "q1", "question": "目标平台？", "reason": "影响篇幅"}]
    with pytest.raises(ProtocolError):
        default_validators().validate_result(_raw_result(data), _request())


def test_semantics_reject_requirement_drift_and_invented_refs():
    data = _bridge_brief_data(requirements=[{"id": "r1", "text": "解释预算"}])
    drifted = dict(data, requirements=[{"id": "r1", "text": "被改写"}])
    with pytest.raises(ProtocolError):
        default_validators().validate_result(
            _raw_result(drifted), _request(requirements=[{"id": "r1", "text": "解释预算"}]))
    invented = dict(data, material_ids=["m1", "invented"])
    with pytest.raises(ProtocolError):
        default_validators().validate_result(_raw_result(invented), _request())
    off_route = dict(data, route=["draft", "research"])
    with pytest.raises(ProtocolError):
        default_validators().validate_result(_raw_result(off_route), _request())
