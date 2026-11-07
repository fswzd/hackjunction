"""数据分析师真实入口桥接:编排预览痕迹重建 + finding 引用真实事件。"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BC_BACKEND = ROOT / "birthco-local" / "backend"

import backend  # noqa: E402
if str(BC_BACKEND) not in backend.__path__:
    backend.__path__.append(str(BC_BACKEND))

from backend.adapters.analyst_bridge import (  # noqa: E402
    AnalystTeamAdapter, _rebuild_trace)
from backend.domain.hashing import content_hash as business_content_hash  # noqa: E402
from backend.simulation.analysis_data import AnalystInput  # noqa: E402
from backend.workflow.five_agent import adapters as A  # noqa: E402
from backend.workflow.five_agent.driver import OrchestrationDriver  # noqa: E402
from backend.workflow.five_agent.repository import Repository  # noqa: E402
from backend.workflow.five_agent.team_entries import TeamEntry  # noqa: E402


def _run_preview():
    """全 mock 编排跑通 content 主链 + preview,拿到预览痕迹。"""
    repo = Repository(":memory:")
    router = A.AdapterRouter(repo, mode="mock")
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
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True, payload={})
    assert snap["status"] == "READY", snap
    version_id = snap["state"]["version_ref"]["id"]
    snap = driver.start_preview_run("t1", version_id)
    assert snap["pending_gates"][0]["kind"] == "preview_conditions"
    # p_ask 在 ordinal 1 提问、p_exit_first 在封面退出(mock 预置),保证业务 mock
    # 分析师能产出引用真实事件的 finding(空 finding 会让断言空转失去意义)。
    personas = [{"id": "p_ask", "goal": "想学会拍照", "knowledge": "摄影新手",
                 "preferences": ["喜欢具体步骤"]},
                {"id": "p_exit_first", "goal": "随便看看", "knowledge": "零基础",
                 "preferences": []}]
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True,
                         payload={"scenario": {"medium": "text", "segmenter_version": "paragraph-v1",
                                               "personas": personas, "max_segments": 8,
                                               "requested_seed": None}})
    # 预览跑完 project/audience/metrics/analysis/show,停在 select_findings 用户门
    assert snap["status"] == "WAITING", snap
    assert snap["pending_gates"][0]["kind"] == "select_findings"
    return repo, snap


def test_analysis_findings_reference_orchestration_events():
    repo, snap = _run_preview()
    preview_id = snap["state"]["preview_ref"]["id"]
    run_id = snap["run_id"]
    event_ids = {e["id"] for e in repo.preview_events(preview_id)}
    assert event_ids, "preview 必须产生观众事件"
    bridge = AnalystTeamAdapter(repo=repo, mode="mock")
    entry = TeamEntry(lambda task_id: bridge)
    call = SimpleNamespace(request_id="req_1", agent_id="data_analyst",
                           action="diagnose_preview", contract_version="seven-agent.v0.1",
                           context=SimpleNamespace(task_id="t1", account_id="account",
                                                   run_id=run_id),
                           input={"preview_ref": {"id": preview_id, "sha256": "0" * 64},
                                  "version_ref": {"id": snap["state"]["version_ref"]["id"],
                                                  "sha256": "0" * 64},
                                  "metrics_ref": {"id": f"metrics_{preview_id}", "sha256": "0" * 64}})
    out = entry.invoke(call)
    assert out["status"] == "ok", out
    data = out["data"]
    assert set(data) == {"findings", "comparison", "next_experiment"}
    assert data["findings"], "业务 mock 分析师应产出引用真实事件的 finding"
    body_ids = {s["segment_id"] for s in repo.get_version(
        snap["state"]["version_ref"]["id"])["payload"]["segments"]}
    for finding in data["findings"]:
        assert finding["observation_refs"], "finding 必须引用真实事件"
        assert set(finding["observation_refs"]) <= event_ids
        assert finding["segment_id"] in {"cover_v1"} | body_ids


def test_no_events_is_needs_input():
    repo = Repository(":memory:")
    repo.create_task("t1", "account", {"goal": "x"})
    version = repo.save_version("ver_abc", "t1", "run1", None, {
        "titles": ["t1", "t2", "t3"], "cover_copy": "封面",
        "segments": [{"segment_id": "s1", "kind": "body", "text": "正文", "source_refs": []}]})
    repo.create_run("run_p", "t1", "preview")
    repo.save_artifact("preview_1", "t1", "run_p", "preview", {
        "version_id": "ver_abc", "content_hash": version["content_hash"],
        "scenario": {"medium": "text", "segmenter_version": "paragraph-v1",
                     "personas": [{"id": "p1", "goal": "想学会拍照", "knowledge": "摄影新手",
                                   "preferences": []}],
                     "max_segments": 8, "requested_seed": None},
        "segmenter_version": "paragraph-v1"})
    repo.save_artifact("metrics_preview_1", "t1", "run_p", "metrics", {"started": 0})
    # 编排侧存在会话但没有任何观众事件/调用:业务分析师应要求补充而非凭空归因
    repo.create_session("sess_x", "preview_1", "p1")
    bridge = AnalystTeamAdapter(repo=repo, mode="mock")
    call = SimpleNamespace(request_id="req_1", agent_id="data_analyst",
                           action="diagnose_preview", contract_version="seven-agent.v0.1",
                           context=SimpleNamespace(task_id="t1", account_id="account", run_id="run_p"),
                           input={"preview_ref": {"id": "preview_1", "sha256": "0" * 64},
                                  "version_ref": {"id": "ver_abc", "sha256": version["content_hash"]},
                                  "metrics_ref": {"id": "metrics_preview_1", "sha256": "0" * 64}})
    out = bridge.invoke(call)
    assert out["status"] == "needs_input" and out["questions"], out


def _trace_repo(personas, payload=None):
    """手搭编排痕迹:任务/版本/预览 artifact/会话,调用行由各测试自行构造。"""
    repo = Repository(":memory:")
    repo.create_task("t1", "account", {"goal": "x"})
    version = repo.save_version("ver_abc", "t1", "run1", None, payload if payload is not None else {
        "titles": ["t1", "t2", "t3"], "cover_copy": "封面",
        "segments": [{"segment_id": "s1", "kind": "body", "text": "正文", "source_refs": []}]})
    repo.create_run("run_p", "t1", "preview")
    repo.save_artifact("preview_1", "t1", "run_p", "preview", {
        "version_id": "ver_abc", "content_hash": version["content_hash"],
        "scenario": {"medium": "text", "segmenter_version": "paragraph-v1",
                     "personas": personas, "max_segments": 8, "requested_seed": None},
        "segmenter_version": "paragraph-v1"})
    return repo, version


def _analyst_call():
    return SimpleNamespace(request_id="req_1", agent_id="data_analyst",
                           action="diagnose_preview", contract_version="seven-agent.v0.1",
                           context=SimpleNamespace(task_id="t1", account_id="account", run_id="run_p"),
                           input={"preview_ref": {"id": "preview_1", "sha256": "0" * 64},
                                  "version_ref": {"id": "ver_abc", "sha256": "0" * 64},
                                  "metrics_ref": {"id": "metrics_preview_1", "sha256": "0" * 64}})


def test_interrupted_call_rebuilds_unknown_report():
    """中断调用(最后一笔)重建为 INTERRUPTED 报告,不因 ErrorDetail 字段缺失崩溃。"""
    repo, version = _trace_repo([{"id": "p1", "goal": "想学会拍照", "knowledge": "摄影新手",
                                  "preferences": []}])
    repo.create_session("sess_x", "preview_1", "p1")
    repo.reserve_call("call_int_1", "run_p", "audience:sess_x:0:" + "a" * 16, 1,
                      "simulated_audience", "read_segment", "req_a1", "a" * 64)
    repo.interrupt_call("call_int_1", "run_p", 1, usage=None)

    source, report = _rebuild_trace(repo, "preview_1", "run_p", "mock")
    assert report.status == "INTERRUPTED"
    assert len(report.calls) == 1
    assert report.calls[0].status == "unknown"
    assert report.calls[0].error is not None
    assert report.calls[0].error.code == "INTERRUPTED"
    assert report.calls[0].error.current_row_version is None
    assert report.sessions[0].stop_reason == "unknown_remote_outcome"

    bridge = AnalystTeamAdapter(repo=repo, mode="mock")
    out = bridge.invoke(_analyst_call())
    assert out["status"] == "needs_input", out
    assert out["questions"]
    assert "validation error" not in str(out).lower()


def test_interrupted_then_later_events_degrades_without_pydantic_leak():
    """中断调用之后仍有后续会话事件:业务校验拒单,桥接给出确定性 error 且不泄漏 pydantic 原文。"""
    repo, version = _trace_repo([{"id": "p1", "goal": "想学会拍照", "knowledge": "摄影新手",
                                  "preferences": []},
                                 {"id": "p2", "goal": "随便看看", "knowledge": "零基础",
                                  "preferences": []}])
    repo.create_session("sess_1", "preview_1", "p1")
    repo.create_session("sess_2", "preview_1", "p2")
    repo.reserve_call("call_int_1", "run_p", "audience:sess_1:0:" + "a" * 16, 1,
                      "simulated_audience", "read_segment", "req_a1", "a" * 64)
    repo.interrupt_call("call_int_1", "run_p", 1, usage=None)
    event = {"segment_id": "cover_v1", "action": "continue",
             "understanding": "mock 理解", "question": None, "reaction": "mock 反应",
             "interactions": [], "comment_text": None}
    step_key = "audience:sess_2:0:" + "b" * 16
    repo.reserve_call("call_ok_2", "run_p", step_key, 1,
                      "simulated_audience", "read_segment", "req_a2", "b" * 64)
    repo.complete_call("call_ok_2", step_key, "run_p", 1, "read_segment", "b" * 64,
                       {"contract_version": "seven-agent.v0.1", "request_id": "req_a2",
                        "agent_id": "simulated_audience", "action": "read_segment",
                        "status": "ok", "data": event, "questions": [], "issues": [],
                        "usage": {"status": "known", "total_tokens": 123}},
                       {"status": "known", "total_tokens": 123}, "out_2")
    repo.save_event_and_advance("sess_2", 0, "cover_v1", event, None)

    out = AnalystTeamAdapter(repo=repo, mode="mock").invoke(_analyst_call())
    assert out["status"] == "error", out
    assert out["data"] is None and out["issues"]
    for issue_ in out["issues"]:
        reason = issue_["reason"].lower()
        assert "validation error" not in reason
        assert "field required" not in reason
    assert out["issues"][0]["reason"] == "trace not reconstructible: session continues after a global stop"
    assert out["usage"] == {"status": "unknown", "total_tokens": None}


REVISION_PAYLOAD = {
    "titles": ["t1", "t2", "t3"], "cover_copy": "封面",
    "segments": [{"segment_id": "s1", "kind": "body", "text": "正文", "source_refs": []}],
    "change_log": [{"finding_id": None, "issue_id": "i1",
                    "old_segment_id": "s1", "new_segment_id": "s2",
                    "change": "replace", "reason": "按审稿意见修改该段"}],
}


def test_revision_version_rebuilds_trace_with_business_hash():
    """修订版(4-key Revision 载荷)痕迹:业务快照改用业务三键内容哈希,
    编排四键 object_hash 不进入 AudienceSimulationInput/SimulationReport。"""
    repo, version = _trace_repo([{"id": "p1", "goal": "想学会拍照", "knowledge": "摄影新手",
                                  "preferences": []}], payload=REVISION_PAYLOAD)
    repo.create_session("sess_x", "preview_1", "p1")

    source, report = _rebuild_trace(repo, "preview_1", "run_p", "mock")
    expected = business_content_hash(source.content)
    assert source.content_hash == expected
    assert report.content_hash == expected
    assert source.content_hash != version["content_hash"], "编排四键哈希不得进入业务快照"
    AnalystInput(analysis_requested=True, source=source, simulation=report,
                 comparison_source=None, comparison_simulation=None,
                 allow_descriptive_comparison=False)  # 不抛异常即自洽校验通过

    out = AnalystTeamAdapter(repo=repo, mode="mock").invoke(_analyst_call())
    assert out["status"] in ("ok", "needs_input"), out


def test_interrupted_first_session_propagates_global_stop_to_empty_second():
    """会话 1 中断(unknown_remote_outcome)后,会话 2 零事件零调用:
    继承同一 stop_reason,报告通过业务自洽校验,分析不丢失。"""
    repo, version = _trace_repo([{"id": "p1", "goal": "想学会拍照", "knowledge": "摄影新手",
                                  "preferences": []},
                                 {"id": "p2", "goal": "随便看看", "knowledge": "零基础",
                                  "preferences": []}])
    repo.create_session("sess_1", "preview_1", "p1")
    repo.create_session("sess_2", "preview_1", "p2")
    repo.reserve_call("call_int_1", "run_p", "audience:sess_1:0:" + "a" * 16, 1,
                      "simulated_audience", "read_segment", "req_a1", "a" * 64)
    repo.interrupt_call("call_int_1", "run_p", 1, usage=None)

    source, report = _rebuild_trace(repo, "preview_1", "run_p", "mock")
    assert [s.session_id for s in report.sessions] == ["sess_1", "sess_2"]
    assert [s.stop_reason for s in report.sessions] == [
        "unknown_remote_outcome", "unknown_remote_outcome"]
    assert report.sessions[1].outcome == "incomplete"
    assert report.sessions[1].cursor == 0 and not report.sessions[1].events
    assert report.status == "INTERRUPTED"
    AnalystInput(analysis_requested=True, source=source, simulation=report,
                 comparison_source=None, comparison_simulation=None,
                 allow_descriptive_comparison=False)  # 不抛异常即自洽校验通过

    out = AnalystTeamAdapter(repo=repo, mode="mock").invoke(_analyst_call())
    assert out["status"] in ("ok", "needs_input"), out
