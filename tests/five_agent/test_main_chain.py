"""Main content chain (A): intake -> brief -> confirm -> draft -> rules -> review
-> one repair -> export -> accept.

Acceptance anchors: 未确认零主创、一次修订、缺信息暂停、确认绑定版本/hash。
Evidence class: mock flow (dev mode, no live models, no teammate code).
"""
import pytest

from backend.workflow.five_agent import adapters as A
from backend.workflow.five_agent.driver import OrchestrationDriver
from backend.workflow.five_agent.repository import DomainError, Repository
from backend.workflow.five_agent.registry import BUDGETS


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


def confirm_gate(snap, driver, approved=True, brief_over=None):
    gate = snap["pending_gates"][0]
    brief_ref = dict(snap["state"]["brief_ref"])
    brief_ref.update(brief_over or {})
    return driver.decide(snap["run_id"], gate["id"], approved=approved,
                         payload={"brief_version": brief_ref["brief_version"],
                                  "brief_hash": brief_ref["brief_hash"]})


def test_happy_path_three_normal_calls_and_accept():
    repo, driver = make_driver()
    new_task(driver)
    snap = driver.start_content_run("task1")
    assert snap["status"] == "WAITING" and snap["pending_gates"][0]["kind"] == "confirm_brief"
    calls_before_creator = [c for c in snap["calls"] if c["agent_id"] == "content_creator"]
    assert calls_before_creator == [], "未确认零主创"

    snap = confirm_gate(snap, driver)
    assert snap["status"] == "WAITING" and snap["pending_gates"][0]["kind"] == "accept_delivery"
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True, payload={})
    assert snap["status"] == "READY"
    # prepare_brief + draft + assess_content = 3 normal, no repair
    assert snap["usage"]["normal_calls"] == 3
    assert snap["usage"]["tech_retries"] == 0
    assert snap["state"]["repair_count"] == 0
    version = repo.get_version(snap["state"]["version_ref"]["id"])
    assert version["status"] == "accepted"
    assert len(version["payload"]["titles"]) == 3


def test_confirm_bound_to_exact_version_and_hash():
    repo, driver = make_driver()
    new_task(driver)
    snap = driver.start_content_run("task1")
    # wrong hash is not authority: CONDITIONS_MISMATCH, run fails, zero creator calls
    with pytest.raises(DomainError):
        confirm_gate(snap, driver, brief_over={"brief_hash": "f" * 64})
    calls = repo.list_calls(snap["run_id"])
    assert [c for c in calls if c["agent_id"] == "content_creator"] == []


def test_reject_brief_gate_zero_creator_calls():
    repo, driver = make_driver()
    new_task(driver)
    snap = driver.start_content_run("task1")
    snap = confirm_gate(snap, driver, approved=False)
    assert snap["status"] == "CANCELLED"
    assert [c for c in snap["calls"] if c["agent_id"] == "content_creator"] == []


def test_unconfirmed_brief_guard_blocks_creator_entry():
    repo, driver = make_driver()
    new_task(driver)
    snap = driver.start_content_run("task1")
    run_id = snap["run_id"]
    # attempt to skip the gate by re-entering at draft: guard must refuse
    with pytest.raises(DomainError):
        driver.reinvoke(run_id, {"resume_step": "draft",
                                 "brief_ref": snap["state"]["brief_ref"],
                                 "version_ref": None})
    assert [c for c in repo.list_calls(run_id) if c["agent_id"] == "content_creator"] == []


def test_brief_needs_input_pauses_then_replans_without_budget_reset():
    scripts = {
        ("operations_officer", "prepare_brief"): [
            A.needs_input([{"id": "q1", "question": "目标平台是什么？", "reason": "影响篇幅"}]),
        ],
    }
    repo, driver = make_driver(scripts=scripts)
    new_task(driver)
    snap = driver.start_content_run("task1")
    assert snap["status"] == "WAITING" and snap["pending_gates"][0]["kind"] == "supply_input"
    gate = snap["pending_gates"][0]
    snap = driver.decide(snap["run_id"], gate["id"], approved=True,
                         payload={"answers": ["图文平台"], "materials": [{"id": "mat2", "text": "补充：目标是小红书图文"}]})
    # replanned brief reaches confirm; budget accumulated across the replan
    assert snap["status"] == "WAITING" and snap["pending_gates"][0]["kind"] == "confirm_brief"
    brief_calls = [c for c in snap["calls"] if c["action"] == "prepare_brief"]
    assert len(brief_calls) == 2, "补料重规划继续计原预算，产生第二次 prepare_brief"
    assert snap["usage"]["normal_calls"] == 2
    snap = confirm_gate(snap, driver)
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True, payload={})
    assert snap["status"] == "READY"
    assert snap["usage"]["normal_calls"] <= BUDGETS["content"].max_normal_calls


def test_rule_failure_triggers_one_repair_then_pass():
    # draft missing cover -> rule fail (skips first review) -> revise fixes -> review pass
    scripts = {
        ("content_creator", "draft"): [lambda call, r: A.gen_candidate(call, r, with_cover=False)],
    }
    repo, driver = make_driver(scripts=scripts)
    new_task(driver)
    snap = driver.start_content_run("task1")
    snap = confirm_gate(snap, driver)
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True, payload={})
    assert snap["status"] == "READY"
    assert snap["state"]["repair_count"] == 1, "自动业务修订最多一次"
    # brief + draft + revise + assess = 4 normal (first review skipped after rule failure)
    assert snap["usage"]["normal_calls"] == 4
    assert snap["usage"]["tech_retries"] == 0
    version = repo.get_version(snap["state"]["version_ref"]["id"])
    assert version["payload"]["cover_copy"], "修订后封面补齐"
    assert version["base_version_id"] is not None, "修订产生新版本"
    base = repo.get_version(version["base_version_id"])
    assert base["payload"]["cover_copy"] is None, "失败的新稿不破坏旧版本"


def test_second_blocking_issue_after_repair_goes_needs_review():
    # draft missing cover -> repair once -> review still revise -> 已修过仍阻断 -> NEEDS_REVIEW
    scripts = {
        ("content_creator", "draft"): [lambda call, r: A.gen_candidate(call, r, with_cover=False)],
        ("editorial_reviewer", "assess_content"): [
            lambda call, r: A.gen_review(call, r, overall="revise"),
            lambda call, r: A.gen_review(call, r, overall="revise"),
        ],
    }
    repo, driver = make_driver(scripts=scripts)
    new_task(driver)
    snap = driver.start_content_run("task1")
    snap = confirm_gate(snap, driver)  # draft -> rules fail -> repair -> review revise -> blocked
    assert snap["status"] == "NEEDS_REVIEW"
    assert snap["state"]["repair_count"] == 1
    revise_calls = [c for c in snap["calls"] if c["action"] == "revise"]
    assert len(revise_calls) == 1, "第二次阻断不再自动修订"
    assert repo.list_versions("task1"), "候选稿保留可查"


def test_review_needs_input_pauses_run_without_export():
    scripts = {
        ("editorial_reviewer", "assess_content"): [
            A.needs_input([{"id": "q2", "question": "材料里没有价格事实，是否保留？", "reason": "缺事实不猜测"}]),
        ],
    }
    repo, driver = make_driver(scripts=scripts)
    new_task(driver)
    snap = driver.start_content_run("task1")
    snap = confirm_gate(snap, driver)  # review returns needs_input -> pause for facts
    assert snap["status"] == "WAITING_INPUT", "缺少事实时暂停"
    batches = repo.find_artifacts("task1", "export_batch")
    assert batches == [], "暂停时不导出"
    version = repo.get_version(snap["state"]["version_ref"]["id"])
    assert version["status"] == "candidate", "未合格不改 ready"


def test_gate_resume_must_be_committed_decision_not_model_text():
    from langgraph.types import Command
    repo, driver = make_driver()
    new_task(driver)
    snap = driver.start_content_run("task1")
    run_id = snap["run_id"]
    graph = driver._compiled("content")
    config = {"configurable": {"thread_id": run_id}}
    for fake in ("true", 1, "已获批准", {"approved": True}):
        with pytest.raises(DomainError):
            graph.invoke(Command(resume=fake), config)
    assert [c for c in repo.list_calls(run_id) if c["agent_id"] == "content_creator"] == []
