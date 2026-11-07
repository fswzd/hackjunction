"""模拟观众真实入口桥接:事件映射 + unknown/failed 失败语义。"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BC_BACKEND = ROOT / "birthco-local" / "backend"

import backend  # noqa: E402
if str(BC_BACKEND) not in backend.__path__:
    backend.__path__.append(str(BC_BACKEND))

from backend.adapters.audience_bridge import AudienceTeamAdapter  # noqa: E402
from backend.adapters.bridge_common import BridgeUnknownOutcome  # noqa: E402
from backend.adapters.model.protocol import blank_response  # noqa: E402
from backend.workflow.five_agent.team_entries import TeamEntry  # noqa: E402


def _audience_input():
    return {"persona": {"id": "p1", "goal": "想学会拍照", "knowledge": "摄影新手",
                        "preferences": ["喜欢具体步骤"]},
            "current_segment": {"segment_id": "cover_v1", "kind": "cover",
                                "text": "三步上手，少走弯路"},
            "visible_history": [],
            "own_previous_reactions": []}


def _call(payload=None):
    return SimpleNamespace(request_id="req_1", agent_id="simulated_audience",
                           action="read_segment", contract_version="seven-agent.v0.1",
                           context=SimpleNamespace(task_id="t1", account_id="account"),
                           input=payload or _audience_input())


def test_mock_reaction_maps_to_audience_event():
    out = AudienceTeamAdapter(mode="mock").invoke(_call())
    assert out["status"] == "ok", out
    data = out["data"]
    assert set(data) == {"segment_id", "action", "understanding", "question",
                         "reaction", "interactions", "comment_text"}
    assert data["segment_id"] == "cover_v1"
    assert data["action"] == "continue"  # mock 机械继续
    assert out["usage"]["status"] in ("known", "unknown")


def test_cover_must_be_first_scope_is_error():
    # 业务 react 在模型调用前对 cover-first 规则直接抛 DomainError(SCOPE_DENIED):
    # 桥接不拦截,TeamEntry 转成确定性 error 结果(零模型调用)。
    payload = _audience_input()
    payload["current_segment"]["kind"] = "body"
    entry = TeamEntry(lambda task_id: AudienceTeamAdapter(mode="mock"))
    out = entry.invoke(_call(payload))
    assert out["status"] == "error" and out["issues"]


def test_invalid_input_is_deterministic_error():
    payload = _audience_input()
    payload["persona"]["id"] = ""  # pydantic Id 模式失败
    out = AudienceTeamAdapter(mode="mock").invoke(_call(payload))
    assert out["status"] == "error" and out["data"] is None


class _RaisingAdapter:
    """业务 ModelAdapter 协议的最小替身:complete() 抛异常 → INTERRUPTED/unknown。"""
    def complete(self, request):
        raise RuntimeError("network down")


def test_unknown_outcome_raises_bridge_unknown():
    bridge = AudienceTeamAdapter(mode="live",
                                 model_adapter=_RaisingAdapter(), model_id="mimo-v2.6-pro")
    entry = TeamEntry(lambda task_id: bridge)
    from backend.workflow.five_agent import adapters as A
    with pytest.raises(A.UnknownResult):
        entry.invoke(_call())


class _FailedAdapter:
    """模型返回 failed 状态 → 业务 reaction failed → 桥接确定性 error 结果。"""
    def complete(self, request):
        return blank_response(status="failed", mode="live",
                              error_code="MODEL_UNAVAILABLE")


def test_model_failure_is_deterministic_error():
    bridge = AudienceTeamAdapter(mode="live", model_adapter=_FailedAdapter(),
                                 model_id="mimo-v2.6-pro")
    out = bridge.invoke(_call())
    assert out["status"] == "error" and out["data"] is None and out["issues"]
    assert out["issues"][0]["location"] == "read_segment"
    assert "Viewer model failed" in out["issues"][0]["reason"]
