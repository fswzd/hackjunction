"""Recovery, idempotency, cancel/late results and budget enforcement.

Acceptance anchors: 双击幂等、断点恢复零重复调用、取消迟到不覆盖版本、
INTERRUPTED 不自动重发、usage unknown 不填零、预算硬闸门、live 不回退 Mock。
Evidence class: mock flow + repository/gateway invariants (dev mode).
"""
import pytest

from backend.workflow.five_agent import adapters as A
from backend.workflow.five_agent.driver import OrchestrationDriver
from backend.workflow.five_agent.gateway import (
    AgentUnavailable, BudgetExceeded, BudgetGate, CancelledError, GatewayError,
    InterruptedUnknown,
)
from backend.workflow.five_agent.repository import ConflictError, DomainError, Repository


def make_driver(scripts=None, mode="mock", audience_exits=None, audience_timeout_at=None):
    repo = Repository(":memory:")
    router = A.AdapterRouter(repo, mode=mode, scripts=scripts or {},
                             audience_exits=audience_exits,
                             audience_timeout_at=audience_timeout_at)
    return repo, OrchestrationDriver(repo, router=router, mode=mode)


def new_task(driver, task_id="task1", **payload):
    base = {"goal": "写一篇新手拍照入门图文", "user_input": "写一篇新手拍照入门图文",
            "input_mode": "idea", "purpose": "content",
            "flags": {"traffic_enabled": False, "goal_clear": True}}
    base.update(payload)
    driver.create_task(task_id, base)
    driver.add_material(task_id, "mat1", "拍照入门：先学会构图三分法，再练光线。")
    return task_id


def confirm_and_accept(driver, snap):
    gate = snap["pending_gates"][0]
    brief_ref = snap["state"]["brief_ref"]
    snap = driver.decide(snap["run_id"], gate["id"], approved=True,
                         payload={"brief_version": brief_ref["brief_version"],
                                  "brief_hash": brief_ref["brief_hash"]})
    if snap["pending_gates"]:
        snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True, payload={})
    return snap


def test_double_click_gate_decision_is_idempotent():
    repo, driver = make_driver()
    new_task(driver)
    snap = driver.start_content_run("task1")
    gate = snap["pending_gates"][0]
    brief_ref = snap["state"]["brief_ref"]
    payload = {"brief_version": brief_ref["brief_version"], "brief_hash": brief_ref["brief_hash"]}
    snap1 = driver.decide(snap["run_id"], gate["id"], approved=True, payload=payload,
                          idempotency_key="double-click-1")
    calls_after_first = len(snap1["calls"])
    snap2 = driver.decide(snap["run_id"], gate["id"], approved=True, payload=payload,
                          idempotency_key="double-click-1")
    assert snap2["status"] == snap1["status"]
    assert len(snap2["calls"]) == calls_after_first, "重复提交同幂等键不重复调用"
    with pytest.raises(ConflictError):
        driver.decide(snap["run_id"], gate["id"], approved=True, payload=payload,
                      idempotency_key="different-key-should-conflict")


def test_restart_replays_committed_receipts_zero_new_calls():
    repo, driver = make_driver()
    new_task(driver)
    snap = driver.start_content_run("task1")
    snap = confirm_and_accept(driver, snap)
    assert snap["status"] == "READY"
    calls_before = len(repo.list_calls(snap["run_id"]))
    usage_before = repo.get_usage(snap["run_id"])

    # simulate a restart after the review step committed: fresh graph/checkpointer,
    # re-enter at the persisted resume_step; gateway replays the receipt
    driver2 = OrchestrationDriver(repo, router=driver.router, mode="mock")
    snap2 = driver2.reinvoke(snap["run_id"], {
        "resume_step": "review",
        "brief_ref": snap["state"]["brief_ref"],
        "version_ref": snap["state"]["version_ref"],
        "rule_ref": snap["state"]["rule_ref"],
        "review_ref": snap["state"]["review_ref"],
        "repair_count": 0,
    })
    assert snap2["status"] in ("READY", "EXPORTED", "WAITING")
    assert len(repo.list_calls(snap["run_id"])) == calls_before, "回执重放零新增调用"
    assert repo.get_usage(snap["run_id"]) == usage_before, "预算不因重放变化"


def test_cancel_mid_call_discards_late_result_and_keeps_versions():
    def cancel_mid_call(call, r):
        # user cancels while the model call is in flight; the result arrives late
        r.repo.bump_epoch(call.context.run_id)
        r.repo.set_run_status(call.context.run_id, "CANCELLED",
                              error={"code": "CANCELLED", "cause_hint": "user cancel"})
        return A.gen_candidate(call, r)

    scripts = {("content_creator", "draft"): [cancel_mid_call]}
    repo, driver = make_driver(scripts=scripts)
    new_task(driver)
    snap = driver.start_content_run("task1")
    gate = snap["pending_gates"][0]
    brief_ref = snap["state"]["brief_ref"]
    with pytest.raises(CancelledError):
        driver.decide(snap["run_id"], gate["id"], approved=True,
                      payload={"brief_version": brief_ref["brief_version"],
                               "brief_hash": brief_ref["brief_hash"]})
    run = repo.get_run(snap["run_id"])
    assert run["status"] == "CANCELLED"
    draft_calls = [c for c in repo.list_calls(snap["run_id"]) if c["action"] == "draft"]
    assert draft_calls and draft_calls[-1]["status"] == "discarded", "迟到结果只记 discarded"
    assert repo.list_versions("task1") == [], "迟到结果不创建版本"


def test_sent_unknown_is_interrupted_not_auto_resent():
    scripts = {
        ("content_creator", "draft"): [
            A.tech_error(sent=True),                       # sent, result unknown
            lambda call, r: A.gen_candidate(call, r),      # only after explicit resend
        ],
    }
    repo, driver = make_driver(scripts=scripts)
    new_task(driver)
    snap = driver.start_content_run("task1")
    gate = snap["pending_gates"][0]
    brief_ref = snap["state"]["brief_ref"]
    with pytest.raises(InterruptedUnknown):
        driver.decide(snap["run_id"], gate["id"], approved=True,
                      payload={"brief_version": brief_ref["brief_version"],
                               "brief_hash": brief_ref["brief_hash"]})
    run = repo.get_run(snap["run_id"])
    assert run["status"] == "INTERRUPTED"
    draft_calls = [c for c in repo.list_calls(snap["run_id"]) if c["action"] == "draft"]
    assert len(draft_calls) == 1, "不自动重发"
    usage = repo.get_usage(snap["run_id"])
    assert usage["unknown_usage_calls"] >= 1
    assert draft_calls[0]["usage_tokens"] is None, "usage unknown 保留，不填零"

    # resend requires explicit cost-risk confirmation
    with pytest.raises(DomainError):
        driver.confirm_interrupted_resend(snap["run_id"], cost_risk_confirmed=False)
    snap = driver.confirm_interrupted_resend(snap["run_id"], cost_risk_confirmed=True)
    assert snap["status"] in ("WAITING", "READY", "EXPORTED")
    draft_calls = [c for c in repo.list_calls(snap["run_id"]) if c["action"] == "draft"]
    assert len(draft_calls) == 2, "确认费用风险后才产生新 attempt"
    assert repo.get_version(snap["state"]["version_ref"]["id"]) is not None


def test_protocol_garbage_rejected_then_technical_retry():
    scripts = {
        ("content_creator", "draft"): [
            A.protocol_garbage(),                          # invalid envelope/usage
            lambda call, r: A.gen_candidate(call, r),
        ],
    }
    repo, driver = make_driver(scripts=scripts)
    new_task(driver)
    snap = driver.start_content_run("task1")
    snap = confirm_and_accept(driver, snap)
    assert snap["status"] == "READY"
    assert snap["usage"]["tech_retries"] == 1, "协议失败走共享技术重试池"
    garbage = [c for c in snap["calls"] if c["status"] == "failed_protocol"]
    assert len(garbage) == 1, "协议失败零领域提交，只留失败记录"


def test_budget_gate_counts_normal_and_retries():
    repo = Repository(":memory:")
    repo.create_task("t1", "acc", {"goal": "g"})
    repo.save_brief("t1", {"input_mode": "idea", "objective": "目标", "audience": "读者",
                           "platform": "图文", "format": "text", "core_promise": "承诺",
                           "requirements": [{"id": "r1", "text": "t"}], "material_ids": [],
                           "open_questions": [], "route": ["draft"], "length_rule": {},
                           "edit_scope": None}, [])
    repo.create_run("r1", "t1", "content")
    gate = BudgetGate(repo)
    router = A.AdapterRouter(repo, mode="mock")
    router.bind_task("t1")
    from backend.workflow.five_agent.gateway import AgentGateway
    gw = AgentGateway(repo, router)

    for i in range(5):
        out = gw.invoke("r1", f"step_{i}", "draft",
                        {"brief_ref": {"task_id": "t1", "brief_version": 1, "brief_hash": "b" * 64},
                         "material_refs": []},
                        account_id="acc", task_id="t1", prompt_schema_version="v")
        assert out.status == "ok"
    with pytest.raises(BudgetExceeded):
        gw.invoke("r1", "step_5", "draft",
                  {"brief_ref": {"task_id": "t1", "brief_version": 1, "brief_hash": "b" * 64},
                   "material_refs": []},
                  account_id="acc", task_id="t1", prompt_schema_version="v")
    usage = repo.get_usage("r1")
    assert usage["normal_calls"] == 5 and usage["calls_reserved"] == 5


def test_preview_unknown_audience_keeps_incomplete_without_fake_exit():
    repo, driver = make_driver(audience_timeout_at={"p_timeout_mid": 1},
                               audience_exits={"p_exit_first": 0, "p_full": None,
                                               "p_timeout_mid": None})
    new_task(driver)
    snap = driver.start_content_run("task1")
    snap = confirm_and_accept(driver, snap)
    psnap = driver.start_preview_run("task1", snap["state"]["version_ref"]["id"])
    scenario = {"medium": "text", "segmenter_version": "paragraph-v1", "max_segments": 8,
                "requested_seed": None,
                "personas": [{"id": "p_timeout_mid", "goal": "g", "knowledge": "k", "preferences": []}]}
    psnap = driver.decide(psnap["run_id"], psnap["pending_gates"][0]["id"], approved=True,
                          payload={"scenario": scenario, "budget_ack": True})
    assert psnap["status"] == "WAITING" and psnap["pending_gates"][0]["kind"] == "select_findings"
    preview_id = psnap["state"]["preview_ref"]["id"]
    sessions = repo.sessions_for_preview(preview_id)
    assert sessions[0]["status"] == "incomplete"
    events = repo.preview_events(preview_id)
    assert len(events) == 1 and events[0]["payload"]["action"] == "continue"
    metrics = repo.get_artifact(f"metrics_{preview_id}")["payload"]
    assert metrics["incomplete"] == 1 and metrics["exited"] == 0
    # the timeout call is usage-unknown but counted
    unknown_calls = [c for c in psnap["calls"] if c["status"] == "interrupted"]
    assert unknown_calls and unknown_calls[0]["usage_tokens"] is None


def test_live_mode_never_falls_back_to_mock():
    repo, driver = make_driver(mode="live")
    new_task(driver)
    with pytest.raises(AgentUnavailable):
        driver.start_content_run("task1")  # prepare_brief hits the real stub -> AGENT_UNAVAILABLE
    assert repo.list_versions("task1") == []
    mock = driver.router.mock("operations_officer")
    assert mock.invocations == [], "正式模式不静默使用 Mock"
