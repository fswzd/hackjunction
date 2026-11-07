"""Optional branches (B): traffic capture, preview + scoped revision.

Acceptance anchors: 跳过可选分支、逐段退出、观众隔离、finding 归属、
未选建议零改稿、局部 scope 与旧版本保留、模板展示零模型。
Evidence class: mock flow (dev mode).
"""
import pytest

from backend.workflow.five_agent import adapters as A
from backend.workflow.five_agent.driver import OrchestrationDriver
from backend.workflow.five_agent.projection import IsolationError, assert_audience_isolation
from backend.workflow.five_agent.repository import ConflictError, Repository


def make_driver(scripts=None, audience_exits=None, audience_timeout_at=None):
    repo = Repository(":memory:")
    router = A.AdapterRouter(repo, mode="mock", scripts=scripts or {},
                             audience_exits=audience_exits,
                             audience_timeout_at=audience_timeout_at)
    return repo, OrchestrationDriver(repo, router=router)


def new_task(driver, task_id="task1", **payload):
    base = {"goal": "写一篇新手拍照入门图文", "user_input": "写一篇新手拍照入门图文",
            "input_mode": "idea", "purpose": "content",
            "flags": {"traffic_enabled": False, "goal_clear": True}}
    base.update(payload)
    driver.create_task(task_id, base)
    driver.add_material(task_id, "mat1", "拍照入门：先学会构图三分法，再练光线。")
    return task_id


def run_content_to_accept(driver, task_id="task1"):
    snap = driver.start_content_run(task_id)
    gate = snap["pending_gates"][0]
    brief_ref = snap["state"]["brief_ref"]
    snap = driver.decide(snap["run_id"], gate["id"], approved=True,
                         payload={"brief_version": brief_ref["brief_version"],
                                  "brief_hash": brief_ref["brief_hash"]})
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True, payload={})
    assert snap["status"] == "READY"
    return snap


PERSONAS = [
    {"id": "p_exit_first", "goal": "随便看看", "knowledge": "零基础", "preferences": []},
    {"id": "p_full", "goal": "学会拍照", "knowledge": "新手", "preferences": ["图文"]},
    {"id": "p_timeout_mid", "goal": "快速了解", "knowledge": "新手", "preferences": []},
]
SCENARIO = {"medium": "text", "segmenter_version": "paragraph-v1",
            "personas": PERSONAS, "max_segments": 8, "requested_seed": None}


def start_preview(driver, repo, snap):
    version_id = snap["state"]["version_ref"]["id"]
    psnap = driver.start_preview_run("task1", version_id)
    assert psnap["status"] == "WAITING" and psnap["pending_gates"][0]["kind"] == "preview_conditions"
    return psnap


# ------------------------------------------------------------------- traffic


def test_clear_goal_skips_traffic_branch():
    repo, driver = make_driver()
    new_task(driver, flags={"traffic_enabled": True, "goal_clear": True})
    snap = run_content_to_accept(driver)
    scout_calls = [c for c in snap["calls"] if c["agent_id"] == "traffic_scout"]
    assert scout_calls == [], "已有明确目标可跳过流量捕捉"
    skipped = [e for e in repo.list_events("task1") if e["kind"] == "traffic_skipped"]
    assert skipped, "跳过有记录"


def test_traffic_branch_with_user_selection_feeds_brief():
    repo, driver = make_driver()
    new_task(driver, flags={"traffic_enabled": True, "goal_clear": False})
    snap = driver.start_content_run("task1")
    assert snap["pending_gates"][0]["kind"] == "select_opportunity"
    oppset_id = snap["state"]["artifact_batch_ref"]["id"]
    opps = repo.get_artifact(oppset_id)["payload"]["opportunities"]
    gate = snap["pending_gates"][0]
    snap = driver.decide(snap["run_id"], gate["id"], approved=True,
                         payload={"selected_opportunity_ref": {"id": opps[0]["id"],
                                                               "sha256": "a" * 64}})
    assert snap["pending_gates"][0]["kind"] == "confirm_brief"
    brief_art = repo.latest_brief("task1")
    assert opps[0]["angle"] in brief_art["payload"]["objective"], "所选机会进入 Brief"
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True,
                         payload={"brief_version": brief_art["brief_version"],
                                  "brief_hash": brief_art["brief_hash"]})
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True, payload={})
    assert snap["status"] == "READY"
    assert snap["usage"]["normal_calls"] == 3, "内容预算不含流量调用"
    scout_runs = [c for c in repo.list_calls(snap["run_id"]) if c["agent_id"] == "traffic_scout"]
    assert scout_runs == [], "流量调用记账在 scout 子 run"


# ------------------------------------------------------------------- preview


def test_declined_preview_conditions_zero_audience_calls():
    repo, driver = make_driver()
    new_task(driver)
    snap = run_content_to_accept(driver)
    psnap = start_preview(driver, repo, snap)
    psnap = driver.reject(psnap["run_id"], psnap["pending_gates"][0]["id"])
    assert psnap["status"] == "CANCELLED"
    assert [c for c in psnap["calls"] if c["agent_id"] == "simulated_audience"] == []


def test_preview_requires_qualified_version():
    repo, driver = make_driver()
    new_task(driver)
    # a candidate version that never passed rules/review must not be previewed
    repo.save_version("ver_cand_only00000000000", "task1", "manual_run", None,
                      {"titles": ["t"], "cover_copy": "c", "segments": [
                          {"segment_id": "s1", "kind": "hook", "text": "x", "source_refs": []}]},
                      status="candidate")
    with pytest.raises(ConflictError):
        driver.start_preview_run("task1", "ver_cand_only00000000000")


def test_preview_segments_exit_incomplete_metrics_and_analysis():
    repo, driver = make_driver()
    new_task(driver)
    snap = run_content_to_accept(driver)
    psnap = start_preview(driver, repo, snap)
    psnap = driver.decide(psnap["run_id"], psnap["pending_gates"][0]["id"], approved=True,
                          payload={"scenario": SCENARIO, "budget_ack": True})
    assert psnap["status"] == "WAITING" and psnap["pending_gates"][0]["kind"] == "select_findings"

    preview_id = psnap["state"]["preview_ref"]["id"]
    sessions = {s["persona_id"]: s for s in repo.sessions_for_preview(preview_id)}
    events = repo.preview_events(preview_id)
    by_session = {}
    for e in events:
        by_session.setdefault(e["session_id"], []).append(e)

    # p_exit_first: one event (exit at cover), session ended, no further reads
    exit_events = by_session[sessions["p_exit_first"]["id"]]
    assert len(exit_events) == 1 and exit_events[0]["payload"]["action"] == "exit"
    assert sessions["p_exit_first"]["status"] == "exited"

    # p_full: reads all segments (cover + 3), completed
    full_events = by_session[sessions["p_full"]["id"]]
    assert len(full_events) == 4 and sessions["p_full"]["status"] == "completed"

    # p_timeout_mid: s1 event preserved, session incomplete — never faked as exit
    timeout_events = by_session[sessions["p_timeout_mid"]["id"]]
    assert len(timeout_events) == 1 and sessions["p_timeout_mid"]["status"] == "incomplete"
    assert all(e["payload"]["action"] != "exit" for e in timeout_events)

    metrics = repo.get_artifact(f"metrics_{preview_id}")["payload"]
    assert metrics["started"] == 3 and metrics["completed"] == 1
    assert metrics["exited"] == 1 and metrics["incomplete"] == 1

    analysis = repo.get_artifact(f"analysis_{preview_id}")
    assert analysis["kind"] == "analysis"
    event_ids = {e["id"] for e in events}
    for finding in analysis["payload"]["findings"]:
        assert set(finding["observation_refs"]) <= event_ids, "finding 必须引用实际观察"

    # audience isolation: every model-visible input has exactly the four fields
    aud = driver.router.mock("simulated_audience")
    assert aud.invocations, "观众调用发生过"
    for inv in aud.invocations:
        assert set(inv["model_visible_input"]) == {"persona", "current_segment",
                                                  "visible_history", "own_previous_reactions"}
        assert inv["context_seen_by_model"] is False

    # template display is zero model: suggestions exist, no extra calls
    before = len(psnap["calls"])
    suggestions = repo.get_artifact(f"suggestions_{preview_id}")["payload"]
    assert suggestions["renderer"] == "template-v1" and suggestions["analysis_available"]
    assert len(psnap["calls"]) == before

    # user selects nothing -> zero scoped revisions
    psnap = driver.decide(psnap["run_id"], psnap["pending_gates"][0]["id"], approved=True,
                          payload={"finding_ids": []})
    assert psnap["status"] == "READY"
    assert [c for c in psnap["calls"] if c["action"] == "revise"] == [], "未选择建议零改稿"


def test_selected_findings_scoped_revision_preserves_unselected():
    repo, driver = make_driver()
    new_task(driver)
    snap = run_content_to_accept(driver)
    base_version_id = snap["state"]["version_ref"]["id"]
    base_version = repo.get_version(base_version_id)

    psnap = start_preview(driver, repo, snap)
    psnap = driver.decide(psnap["run_id"], psnap["pending_gates"][0]["id"], approved=True,
                          payload={"scenario": SCENARIO, "budget_ack": True})
    preview_id = psnap["state"]["preview_ref"]["id"]
    analysis = repo.get_artifact(f"analysis_{preview_id}")["payload"]
    assert analysis["findings"], "预置场景应产生 finding"
    body_findings = [f for f in analysis["findings"] if f["segment_id"] != "cover_v1"]
    picked = (body_findings or analysis["findings"])[0]
    psnap = driver.decide(psnap["run_id"], psnap["pending_gates"][0]["id"], approved=True,
                          payload={"finding_ids": [picked["id"]], "allow_title_change": False,
                                   "allow_cover_change": False, "instructions": "只改选中片段"})
    assert psnap["state"]["revision_ref"], "产生修订请求"
    rev = driver.start_revision_run("task1", psnap["state"]["revision_ref"]["id"])
    gate = rev["pending_gates"][0]
    assert gate["kind"] == "accept_delivery"
    rev = driver.decide(rev["run_id"], gate["id"], approved=True, payload={})
    assert rev["status"] == "READY"

    new_version = repo.get_version(rev["state"]["version_ref"]["id"])
    assert new_version["base_version_id"] == base_version_id
    base_segments = {s["segment_id"]: s for s in base_version["payload"]["segments"]}
    new_segments = {s["segment_id"]: s for s in new_version["payload"]["segments"]}
    changed = {c["old_segment_id"] for c in new_version["payload"]["change_log"]}
    target = picked["segment_id"]
    assert target in changed, "选中片段被修订"
    for sid, seg in base_segments.items():
        if sid in changed:
            continue
        assert new_segments.get(sid) == seg, f"未选片段 {sid} 必须原样保留"
    # old version still downloadable/intact; new one accepted
    assert repo.get_version(base_version_id)["status"] in ("ready", "accepted")
    assert new_version["status"] == "accepted"
    assert repo.get_artifact(f"batch_{base_version_id}")["payload"]["files"]
    assert repo.get_artifact(f"batch_{new_version['id']}")["payload"]["files"]


def test_scope_violating_revision_is_rejected():
    def bad_scope(call, r):
        base = r.version(call.input["base_version_ref"])["payload"]
        segs = [dict(s) for s in base["segments"]]
        # modify a segment that is NOT in the selected finding scope
        segs[0]["text"] = "被越权改写的内容"
        request = r.artifact(call.input["revision_request_ref"])["payload"]
        target_fid = request["finding_ids"][0]
        data = {"titles": list(base["titles"]), "cover_copy": base.get("cover_copy"),
                "segments": segs,
                "change_log": [{"finding_id": target_fid, "issue_id": None,
                                "old_segment_id": segs[0]["segment_id"],
                                "new_segment_id": segs[0]["segment_id"],
                                "change": "replace", "reason": "越权改动"}]}
        return {"kind": "ok", "data": data, "usage": A.Usage.known(200).to_dict()}

    scripts = {("content_creator", "revise"): [bad_scope]}
    repo, driver = make_driver(scripts=scripts)
    new_task(driver)
    snap = run_content_to_accept(driver)
    psnap = start_preview(driver, repo, snap)
    psnap = driver.decide(psnap["run_id"], psnap["pending_gates"][0]["id"], approved=True,
                          payload={"scenario": SCENARIO, "budget_ack": True})
    preview_id = psnap["state"]["preview_ref"]["id"]
    analysis = repo.get_artifact(f"analysis_{preview_id}")["payload"]
    picked = analysis["findings"][0]
    psnap = driver.decide(psnap["run_id"], psnap["pending_gates"][0]["id"], approved=True,
                          payload={"finding_ids": [picked["id"]], "allow_title_change": False,
                                   "allow_cover_change": False})
    before_versions = len(repo.list_versions("task1"))
    rev = driver.start_revision_run("task1", psnap["state"]["revision_ref"]["id"])
    assert rev["status"] == "NEEDS_REVIEW", "越权 scope 转人工"
    assert len(repo.list_versions("task1")) == before_versions, "违规新稿不产生版本"
    assert repo.get_version(snap["state"]["version_ref"]["id"])["status"] in ("ready", "accepted"), "旧版本保留"


def test_revision_base_must_be_head():
    repo, driver = make_driver()
    new_task(driver)
    snap = run_content_to_accept(driver)
    psnap = start_preview(driver, repo, snap)
    psnap = driver.decide(psnap["run_id"], psnap["pending_gates"][0]["id"], approved=True,
                          payload={"scenario": SCENARIO, "budget_ack": True})
    preview_id = psnap["state"]["preview_ref"]["id"]
    analysis = repo.get_artifact(f"analysis_{preview_id}")["payload"]
    picked = analysis["findings"][0]
    psnap = driver.decide(psnap["run_id"], psnap["pending_gates"][0]["id"], approved=True,
                          payload={"finding_ids": [picked["id"]], "allow_title_change": False,
                                   "allow_cover_change": False})
    req_id = psnap["state"]["revision_ref"]["id"]
    # force a newer head version so the frozen base is stale
    repo.save_version("ver_manual_override000000000", "task1", "manual_run", None,
                      {"titles": ["t"], "cover_copy": "c", "segments": [
                          {"segment_id": "s1", "kind": "hook", "text": "x", "source_refs": []}]})
    with pytest.raises(ConflictError):
        driver.start_revision_run("task1", req_id)


# ------------------------------------------------------------ isolation unit


def test_audience_projection_rejects_future_and_foreign_leaks():
    segments = [
        {"segment_id": "cover_v1", "kind": "cover", "text": "封面标题文字"},
        {"segment_id": "seg_a", "kind": "hook", "text": "第一段正文内容甲"},
        {"segment_id": "seg_b", "kind": "body", "text": "第二段未来内容乙"},
    ]
    persona = {"id": "p1", "goal": "g", "knowledge": "k", "preferences": []}

    ok_input = {"persona": persona,
                "current_segment": segments[0],
                "visible_history": [],
                "own_previous_reactions": []}
    assert_audience_isolation(ok_input, segments, "p1", [])

    leaked = dict(ok_input)
    leaked["visible_history"] = [segments[1]]  # future segment in history
    with pytest.raises(IsolationError):
        assert_audience_isolation(leaked, segments, "p1", [])

    foreign = {"id": "e1", "segment_id": "seg_a", "action": "continue", "understanding": "x",
               "question": None, "reaction": "y", "interactions": [], "comment_text": None}
    with pytest.raises(IsolationError):
        # a reaction known to belong to another session must not appear in the input
        assert_audience_isolation({**ok_input, "own_previous_reactions": [foreign]}, segments,
                                  "p1", [foreign])

    extra_key = {**ok_input, "creator_goal_score": 0.9}
    with pytest.raises(IsolationError):
        assert_audience_isolation(extra_key, segments, "p1", [])
