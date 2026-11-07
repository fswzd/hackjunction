"""TeamEntry 异常语义映射 + build_reals 惰性导入/逐任务 resolve。"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BC_BACKEND = ROOT / "birthco-local" / "backend"

import backend  # noqa: E402
if str(BC_BACKEND) not in backend.__path__:
    backend.__path__.append(str(BC_BACKEND))

from backend.adapters.bridge_common import BridgePreSendFailure, BridgeUnknownOutcome  # noqa: E402
from backend.domain.errors import DomainError  # noqa: E402
from backend.workflow.five_agent import adapters as A  # noqa: E402
from backend.workflow.five_agent.team_entries import TeamEntry  # noqa: E402


def _call():
    return SimpleNamespace(request_id="req_1", agent_id="operations_officer",
                           action="prepare_brief", contract_version="seven-agent.v0.1",
                           input={"user_input": "x"}, context=SimpleNamespace(task_id="task1"))


class _Boom:
    def __init__(self, exc):
        self.exc = exc

    def invoke(self, call):
        raise self.exc


def test_unknown_outcome_maps_to_unknown_result():
    entry = TeamEntry(lambda task_id: _Boom(BridgeUnknownOutcome("sent")))
    with pytest.raises(A.UnknownResult):
        entry.invoke(_call())


def test_presend_maps_to_presend_failure():
    entry = TeamEntry(lambda task_id: _Boom(BridgePreSendFailure("bad input")))
    with pytest.raises(A.PreSendFailure):
        entry.invoke(_call())


def test_interrupted_domain_error_maps_to_unknown_result():
    entry = TeamEntry(lambda task_id: _Boom(
        DomainError("INTERRUPTED", "remote outcome unknown", "explicit resend")))
    with pytest.raises(A.UnknownResult):
        entry.invoke(_call())


def test_other_domain_error_maps_to_error_result():
    entry = TeamEntry(lambda task_id: _Boom(
        DomainError("SCHEMA_INVALID", "bad output", "inspect schema")))
    out = entry.invoke(_call())
    assert out["status"] == "error" and out["data"] is None
    assert out["issues"][0]["reason"] == "bad output"
    assert out["usage"] == {"status": "unknown", "total_tokens": None}


def test_value_error_maps_to_presend_failure():
    entry = TeamEntry(lambda task_id: _Boom(ValueError("live requires an adapter")))
    with pytest.raises(A.PreSendFailure):
        entry.invoke(_call())


def test_bridge_factory_cached_per_task():
    calls = []
    def factory(task_id):
        calls.append(task_id)
        return _Boom(BridgeUnknownOutcome("x"))
    entry = TeamEntry(factory)
    for _ in range(2):
        with pytest.raises(A.UnknownResult):
            entry.invoke(_call())
    assert calls == ["task1"]  # same task reuses cached bridge


# ------------------------------------------------------------------ build_reals 全链


def test_build_reals_runs_full_content_chain():
    from backend.workflow.five_agent.driver import OrchestrationDriver
    from backend.workflow.five_agent.repository import Repository
    from backend.workflow.five_agent.team_entries import build_reals

    repo = Repository(":memory:")
    reals = build_reals(repo, mode="mock")
    router = A.AdapterRouter(repo, mode="live", reals=reals)
    driver = OrchestrationDriver(repo, router=router)
    driver.create_task("t1", {"goal": "写一篇新手拍照入门图文", "user_input": "写一篇新手拍照入门图文",
                              "input_mode": "idea", "purpose": "content",
                              "flags": {"traffic_enabled": False, "goal_clear": True}})
    driver.add_material("t1", "m1", "拍照入门：先学会构图三分法，再练光线。")
    snap = driver.start_content_run("t1")
    assert snap["pending_gates"][0]["kind"] == "confirm_brief"
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True,
                         payload={"brief_version": snap["state"]["brief_ref"]["brief_version"],
                                  "brief_hash": snap["state"]["brief_ref"]["brief_hash"]})
    # 全七角色真实桥接(mock 模型)走完主链:运营官+主创+审稿三跳均 received;
    # 业务 mock 审稿在规则通过后返回 needs_input(语义待核实)→ WAITING_INPUT。
    assert snap["status"] == "WAITING_INPUT", snap
    assert repo.get_usage(snap["run_id"])["normal_calls"] >= 3


def test_build_reals_runs_preview_with_real_audience_and_analyst():
    from backend.workflow.five_agent.driver import OrchestrationDriver
    from backend.workflow.five_agent.repository import Repository
    from backend.workflow.five_agent.team_entries import build_reals

    repo = Repository(":memory:")
    reals = build_reals(repo, mode="mock")
    # content 角色走编排 mock(保证 READY 快路径);仅试映两角色走真实桥接。
    router = A.AdapterRouter(repo, mode="mock", reals=reals,
                             agent_modes={"simulated_audience": "live",
                                          "data_analyst": "live"})
    driver = OrchestrationDriver(repo, router=router)
    driver.create_task("t1", {"goal": "写一篇新手拍照入门图文", "user_input": "写一篇新手拍照入门图文",
                              "input_mode": "idea", "purpose": "content",
                              "flags": {"traffic_enabled": False, "goal_clear": True}})
    driver.add_material("t1", "m1", "拍照入门：先学会构图三分法，再练光线。")
    snap = driver.start_content_run("t1")
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True,
                         payload={"brief_version": snap["state"]["brief_ref"]["brief_version"],
                                  "brief_hash": snap["state"]["brief_ref"]["brief_hash"]})
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True, payload={})
    assert snap["status"] == "READY", snap
    version_id = snap["state"]["version_ref"]["id"]
    snap = driver.start_preview_run("t1", version_id)
    personas = [{"id": "p_ask", "goal": "想学会拍照", "knowledge": "摄影新手", "preferences": ["喜欢具体步骤"]},
                {"id": "p_exit_first", "goal": "想拍好照片", "knowledge": "有相机但不会用", "preferences": []}]
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True,
                         payload={"scenario": {"medium": "text", "segmenter_version": "paragraph-v1",
                                               "personas": personas, "max_segments": 8,
                                               "requested_seed": None}})
    # 试映跑完(真实观众桥接 + 真实分析师桥接,mock 模型)→ 分析产物存在
    preview_id = snap["state"]["preview_ref"]["id"]
    analysis_id = f"analysis_{preview_id}"
    art = repo.get_artifact(analysis_id)
    if art["kind"] == "analysis":
        for finding in art["payload"]["findings"]:
            assert finding["observation_refs"]
    else:
        assert art["kind"] == "analysis_missing"  # 软降级路径也合法
