"""live 生产路径接通 build_reals 七角色真实桥接（FO-2）。

锁定三件事：
1. driver 默认 router（mode='live'）七角色 adapter_for(...) 均非 RealAdapterStub，
   全部为真实桥接 TeamEntry；
2. 原 stub 三角色（data_analyst / pr_analyst / simulated_audience）经桥接返回
   AgentResult 形状结果（离线 fake 模型只替代传输层，桥接与本体校验走真实代码）；
3. 不变量：剔除某角色 reals 后仍抛 AGENT_UNAVAILABLE、全程无 Mock 回退；
   agent_modes 逐角色灰度保留。
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BC_BACKEND = ROOT / "birthco-local" / "backend"

import backend  # noqa: E402
if str(BC_BACKEND) not in backend.__path__:
    backend.__path__.append(str(BC_BACKEND))

from backend.adapters.model import factory as model_factory  # noqa: E402
from backend.adapters.model.protocol import AdapterResponse, ModelUsage  # noqa: E402
from backend.domain.schemas import (  # noqa: E402
    Analysis, AudienceEvent, ComparisonConclusion, Envelope, Finding)
from backend.workflow.five_agent import adapters as A  # noqa: E402
from backend.workflow.five_agent.driver import OrchestrationDriver  # noqa: E402
from backend.workflow.five_agent.gateway import AgentUnavailable  # noqa: E402
from backend.workflow.five_agent.repository import Repository  # noqa: E402
from backend.workflow.five_agent.live_adapters import ProductionAdapter  # noqa: E402
from backend.workflow.five_agent.team_entries import TeamEntry, build_reals  # noqa: E402

AGENT_RESULT_KEYS = {"contract_version", "request_id", "agent_id", "action",
                     "status", "data", "questions", "issues", "usage"}
ALL_ACTIONS = ("analyze_request", "prepare_brief", "draft", "revise",
               "assess_content", "capture_opportunities", "diagnose_preview",
               "read_segment")


class FakeLiveModel:
    """离线传输夹具：只替代模型 HTTP 层；桥接、本体校验全走真实代码。

    每个角色回放业务 mock 语义（同 run_analyst 等 CLI 的 mock 路径产物），
    不新增任何编排侧捷径。
    """

    def complete(self, request):
        payload = json.loads(request.messages[1].content)
        if request.role == "pr-analyst":
            from backend.agents.pr_analyst import PRAnalysisInput, mock_extraction
            snapshot = PRAnalysisInput.model_validate(payload["intake"])
            text = mock_extraction(snapshot).model_dump_json()
        elif request.role == "audience":
            segment_id = payload["current_segment"]["segment_id"]
            event = AudienceEvent(segment_id=segment_id, action="continue",
                                  understanding="离线夹具：读到了当前片段，大致明白在讲什么。",
                                  question=None, reaction="有点意思",
                                  interactions=["like"], comment_text=None)
            text = Envelope[AudienceEvent](
                schema_version="creator-agent.v1", status="ok", summary="离线夹具观众事件",
                data=event, evidence_refs=[segment_id], questions=[], issues=[]).model_dump_json()
        elif request.role == "analyst":
            events = [r for s in payload["left"]["sessions"] for r in s["events"]]
            refs = [events[-1]["event_id"]] if events else []
            compare = payload["comparison_context"]
            findings = [Finding(
                id="finding_1", segment_id=events[-1]["event"]["segment_id"],
                observation_refs=refs,
                interpretation="离线夹具：该片段在本次模拟中被读到。",
                alternative_explanation="夹具假设：persona 设定可能影响反应。",
                suggested_edit="夹具试验：增加一个具体例子后重测。")] if refs else []
            analysis = Analysis(
                findings=findings,
                comparison=ComparisonConclusion(
                    conditions_match=compare["conditions_match"],
                    reason=compare["reason"], summary="离线夹具：只描述本次模拟。"),
                next_experiment="夹具下一轮对照记录。")
            text = Envelope[Analysis](
                schema_version="creator-agent.v1", status="ok", summary="离线夹具分析",
                data=analysis, evidence_refs=refs, questions=[], issues=[]).model_dump_json()
        else:
            raise AssertionError(f"FakeLiveModel 未覆盖的模型角色: {request.role}")
        raw = text.encode("utf-8")
        return AdapterResponse(
            status="received", text=text, finish_reason="stop",
            provider_request_id=None, usage=ModelUsage(input=30, output=30, total=60),
            error_code=None, retry_after_seconds=None, response_bytes=len(raw),
            response_hash="f" * 64, latency_ms=1, mode="live")


@pytest.fixture()
def fake_live_model(monkeypatch):
    monkeypatch.setattr(model_factory, "create_live_adapter",
                        lambda agent_id=None, **kwargs: FakeLiveModel())
    monkeypatch.setattr(model_factory, "live_model_id",
                        lambda agent_id=None, **kwargs: "fixture-model-v1")
    return FakeLiveModel()


def _call(agent_id, action, payload, task_id="task1", run_id="run_1"):
    return SimpleNamespace(
        request_id="req_1", agent_id=agent_id, action=action,
        contract_version="seven-agent.v0.1", input=payload,
        context=SimpleNamespace(task_id=task_id, run_id=run_id, account_id="acc"))


def test_driver_default_router_live_wires_all_seven_bridges(fake_live_model):
    driver = OrchestrationDriver(Repository(":memory:"), mode="live")
    for action in ALL_ACTIONS:
        adapter = driver.router.adapter_for(action)
        assert not isinstance(adapter, A.RealAdapterStub), f"{action} 仍落 RealAdapterStub"
        # 新版默认 live 路由：五个专家面走 ProductionAdapter，两个补位面走 TeamEntry 桥接，
        # 七角色全部真实接线（TeamEntry 注入路径见灰度用例）
        assert isinstance(adapter, (ProductionAdapter, TeamEntry)), f"{action} 未走真实桥接: {adapter!r}"
        assert not isinstance(adapter, A.MockAgent), "live 不得路由 Mock"


def test_three_former_stub_roles_return_agent_result_shape(fake_live_model):
    repo = Repository(":memory:")
    reals = build_reals(repo, mode="live")

    # pr_analyst：素材解引用 + 本体提取校验（mock_extraction 语义的离线模型回放）
    repo.create_task("pr_task", "acc", {"goal": "g"})
    repo.add_material("pr_task", "mat1", "拍照入门：先学会构图三分法。")
    out = reals["pr_analyst"].invoke(_call(
        "pr_analyst", "analyze_request",
        {"request_text": "写一篇新手拍照入门图文", "material_refs": [{"id": "mat1"}]},
        task_id="pr_task"))
    assert set(out) == AGENT_RESULT_KEYS
    assert out["status"] in ("ok", "needs_input"), out

    # simulated_audience：AudienceInput 全字段校验 + 事件校验走真实本体
    audience_payload = {
        "persona": {"id": "p_full", "goal": "学会拍照", "knowledge": "新手", "preferences": ["图文"]},
        "visible_history": [],
        "current_segment": {"segment_id": "cover_v1", "kind": "cover",
                            "text": "封面：十分钟学会构图"},
        "own_previous_reactions": [],
    }
    out = reals["simulated_audience"].invoke(_call(
        "simulated_audience", "read_segment", audience_payload))
    assert set(out) == AGENT_RESULT_KEYS
    assert out["status"] == "ok", out
    assert out["data"]["segment_id"] == "cover_v1"

    # data_analyst：真实 preview 痕迹重建 + 本体分析校验
    preview_id, run_id = _seed_preview_trace(repo)
    out = reals["data_analyst"].invoke(_call(
        "data_analyst", "diagnose_preview", {"preview_ref": {"id": preview_id}},
        run_id=run_id))
    assert set(out) == AGENT_RESULT_KEYS
    assert out["status"] == "ok", out
    assert out["data"]["findings"], out


def _seed_preview_trace(repo):
    """用编排 mock 快路径在 repo 里跑出真实 preview 痕迹（桥接重建的输入）。"""
    router = A.AdapterRouter(repo, mode="mock")
    driver = OrchestrationDriver(repo, router=router)
    driver.create_task("task1", {"goal": "写一篇新手拍照入门图文",
                                 "user_input": "写一篇新手拍照入门图文",
                                 "input_mode": "idea", "purpose": "content",
                                 "flags": {"traffic_enabled": False, "goal_clear": True}})
    driver.add_material("task1", "mat2", "拍照入门：先学会构图三分法。")
    snap = driver.start_content_run("task1")
    gate = snap["pending_gates"][0]
    brief_ref = snap["state"]["brief_ref"]
    snap = driver.decide(snap["run_id"], gate["id"], approved=True,
                         payload={"brief_version": brief_ref["brief_version"],
                                  "brief_hash": brief_ref["brief_hash"]})
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True, payload={})
    assert snap["status"] == "READY"
    version_id = snap["state"]["version_ref"]["id"]
    psnap = driver.start_preview_run("task1", version_id)
    scenario = {"medium": "text", "segmenter_version": "paragraph-v1", "max_segments": 8,
                "requested_seed": None,
                "personas": [{"id": "p_full", "goal": "学会拍照", "knowledge": "新手",
                              "preferences": ["图文"]}]}
    psnap = driver.decide(psnap["run_id"], psnap["pending_gates"][0]["id"], approved=True,
                          payload={"scenario": scenario, "budget_ack": True})
    assert psnap["pending_gates"][0]["kind"] == "select_findings", psnap
    return psnap["state"]["preview_ref"]["id"], psnap["run_id"]


def test_missing_real_keeps_agent_unavailable_without_mock_fallback(fake_live_model):
    repo = Repository(":memory:")
    reals = build_reals(repo, mode="mock")
    # 新版路由会自动补齐七角色桥接（缺位即回填）；显式注入 Stub 才能表达
    # "该角色未接真实桥接"，随后必须 AgentUnavailable 且绝不回退 Mock
    reals["pr_analyst"] = A.RealAdapterStub("pr_analyst", ("analyze_request",))
    router = A.AdapterRouter(repo, mode="live", reals=reals)
    driver = OrchestrationDriver(repo, router=router, mode="live")
    assert isinstance(driver.router.adapter_for("analyze_request"), A.RealAdapterStub)
    driver.create_task("task1", {"goal": "写一篇新手拍照入门图文",
                                 "user_input": "写一篇新手拍照入门图文",
                                 "input_mode": "idea", "purpose": "content",
                                 "flags": {"traffic_enabled": False, "goal_clear": True}})
    with pytest.raises(AgentUnavailable):
        driver.start_pr_analysis_run("task1")
    for agent_id, mock in driver.router.mocks.items():
        assert mock.invocations == [], f"live 回退了 Mock: {agent_id}"


def test_agent_modes_grayscale_keeps_per_role_rollout(fake_live_model):
    repo = Repository(":memory:")
    reals = build_reals(repo, mode="mock")
    router = A.AdapterRouter(repo, mode="live", reals=reals,
                             agent_modes={"data_analyst": "mock",
                                          "simulated_audience": "mock"})
    assert isinstance(router.adapter_for("diagnose_preview"), A.MockAgent)
    assert isinstance(router.adapter_for("read_segment"), A.MockAgent)
    for action in ("analyze_request", "prepare_brief", "draft", "revise",
                   "assess_content", "capture_opportunities"):
        adapter = router.adapter_for(action)
        assert isinstance(adapter, TeamEntry), f"{action} 灰度下应走 live 桥接"
        assert not isinstance(adapter, A.MockAgent)
