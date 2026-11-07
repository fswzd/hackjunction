"""商单需求分析员真实入口桥接:输入映射/契约包封/失败映射。

Evidence class: [真实 Adapter 联调]——桥接真实入口(含本体校验)经 AgentCall 契约进出;
模型为 mock([真实模型] 属后续阶段)。mock 本体只回显显式 intake 字段,而桥接仅映射
request_text→objective,故 mock 下必缺五个必填字段(brand/product/audience/platform/style)
→ needs_input;ok 包封映射由 stub 本体测试锁定(不修改业务代码)。
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

from backend.adapters.bridge_common import orchestration_ref_digest  # noqa: E402
from backend.adapters.pr_bridge import PRAnalystTeamAdapter  # noqa: E402


def _rows():
    return [{"id": "m1", "text": "产品资料：品牌X新品，主打便携。", "kind": "text",
             "label": "产品资料", "source_url": None}]


def _call(request_text="品牌X新品推广；要求：文案必须出现品牌名"):
    return SimpleNamespace(request_id="req_1", agent_id="pr_analyst",
                           action="analyze_request", contract_version="seven-agent.v0.1",
                           context=SimpleNamespace(task_id="t1", account_id="account"),
                           input={"request_text": request_text,
                                  "material_refs": [{"id": "m1",
                                                     "sha256": orchestration_ref_digest("产品资料：品牌X新品，主打便携。")}]})


def _adapter():
    return PRAnalystTeamAdapter(resolve_material=lambda ref: _rows()[0], mode="mock")


def test_mock_entry_maps_to_contract_envelope():
    """mock 本体语义:仅 objective 有显式值 → 缺五个必填字段 → needs_input(契约包封)。"""
    out = _adapter().invoke(_call())
    assert out["status"] in ("ok", "needs_input"), out
    assert out["agent_id"] == "pr_analyst" and out["action"] == "analyze_request"
    assert out["request_id"] == "req_1"
    assert out["usage"]["status"] in ("known", "unknown")
    if out["status"] == "ok":
        data = out["data"]
        assert set(data) == {"summary", "requirements", "open_questions",
                             "unprovided_business_fields", "ready_for_operator", "source_refs"}
    else:
        assert out["data"] is None
    assert all("id" in q and "question" in q and "reason" in q for q in out["questions"])


def test_incomplete_intake_becomes_needs_input():
    out = _adapter().invoke(_call(request_text="品牌X新品推广"))
    # mock 提取只回显显式 intake 字段(桥接仅映射 objective),
    # brand/product/audience/platform/style 缺失 → needs_input(业务 PRAnalystAgent 语义)
    assert out["status"] == "needs_input" and out["questions"]


def test_fingerprint_mismatch_is_deterministic_error():
    bad = _call()
    bad.input["material_refs"][0]["sha256"] = "0" * 64
    out = _adapter().invoke(bad)
    assert out["status"] == "error" and out["data"] is None
    assert out["usage"] == {"status": "unknown", "total_tokens": None}


def _stub_agent(task_draft=None):
    """stub 本体:返回 ok Envelope[PRExtraction],不走业务模型(仅锁定桥接 ok 映射)。"""
    from backend.adapters.model.protocol import ModelUsage
    from backend.agents.pr_analyst import (
        ExtractedField, PRExtraction, PRRequirement, PRAnalysisResult, SourceQuote)
    from backend.domain.schemas import Envelope

    class StubOK:
        def run(self, snapshot):
            fields = [
                ExtractedField(
                    field=key,
                    value=snapshot.intake.objective if key == "objective" else None,
                    evidence=SourceQuote(source_id="intake_" + key, quote=snapshot.intake.objective)
                    if key == "objective" else None)
                for key in ("brand", "product", "objective", "audience", "platform",
                            "style", "budget", "deadline", "approver")]
            data = PRExtraction(
                fields=fields,
                requirements=[PRRequirement(id=r.id, text=r.text, category="other",
                                            evidence=SourceQuote(source_id="req_stub", quote=r.text))
                              for r in snapshot.requirements],
                conflicts=[], additional_questions=[])
            envelope = Envelope[PRExtraction](
                schema_version="creator-agent.v1", status="ok", summary="需求整理完成",
                data=data, evidence_refs=[], questions=[], issues=[])
            return PRAnalysisResult("mock", snapshot.account_id, "stub", None,
                                    envelope, task_draft, ModelUsage(total=100), ())
    return StubOK()


def test_ok_envelope_data_mapping_with_stubbed_agent():
    """ok 分支的 RequestAnalysis 契约包封(六键、引用、usage 均确定性)。"""
    adapter = _adapter()
    adapter.agent = _stub_agent()
    out = adapter.invoke(_call())
    assert out["status"] == "ok", out
    data = out["data"]
    assert set(data) == {"summary", "requirements", "open_questions",
                         "unprovided_business_fields", "ready_for_operator", "source_refs"}
    assert data["summary"] == "需求整理完成"
    assert data["requirements"] == [{"id": "req_extract", "text": "从任务中整理交付要求"}]
    assert data["open_questions"] == []
    assert data["unprovided_business_fields"] == ["budget", "deadline", "approver"]
    assert data["ready_for_operator"] is False
    assert data["source_refs"] == ["m1"]
    assert out["questions"] == []
    assert out["usage"] == {"status": "known", "total_tokens": 100}


def test_ready_for_operator_reflects_task_draft():
    from backend.domain.schemas import CreateTask, LengthRule, Requirement
    task = CreateTask(account_id="account", input_mode="idea", objective="品牌X新品推广",
                      audience="读者", platform="generic", style="简洁",
                      requirements=[Requirement(id="req_extract", text="从任务中整理交付要求")],
                      materials=[], length_rule=LengthRule(minimum=None, maximum=20000))
    adapter = _adapter()
    adapter.agent = _stub_agent(task_draft=task)
    out = adapter.invoke(_call())
    assert out["status"] == "ok", out
    assert out["data"]["ready_for_operator"] is True
