"""Seven-role layout (seven-agent.v0.1): pr_analyst joins, operations_officer
splits into operations_officer (prepare_brief) + editorial_reviewer (assess_content).

Covers: 商单链 pr_analyst→运营官 顺序与交接、需求缺口暂停补料、分析失败转人工、
非商单跳过、独立商单分析 run、审校归属 editorial_reviewer。
Evidence class: mock flow (dev mode).
"""
import pytest

from backend.workflow.five_agent import adapters as A
from backend.workflow.five_agent.driver import OrchestrationDriver
from backend.workflow.five_agent.repository import Repository
from backend.workflow.five_agent.registry import ACTIONS, ROLES


def make_driver(scripts=None):
    repo = Repository(":memory:")
    router = A.AdapterRouter(repo, mode="mock", scripts=scripts or {})
    return repo, OrchestrationDriver(repo, router=router)


def new_commercial_task(driver, task_id="task1", client_brief="品牌X新品推广；要求：文案必须出现品牌名"):
    driver.create_task(task_id, {
        "goal": "品牌X新品推广文案", "user_input": "品牌X新品推广文案",
        "input_mode": "idea", "purpose": "commercial_order",
        "client_brief": client_brief,
        "flags": {"traffic_enabled": False, "goal_clear": True}})
    driver.add_material(task_id, "mat1", "品牌X：主打便携与耐用。")
    return task_id


def test_seven_roles_eight_actions_binding():
    assert len(ROLES) == 7 and len(ACTIONS) == 8
    assert ACTIONS["analyze_request"] == "pr_analyst"
    assert ACTIONS["prepare_brief"] == "operations_officer"
    assert ACTIONS["assess_content"] == "editorial_reviewer"


def test_commercial_chain_runs_pr_analyst_before_operator():
    repo, driver = make_driver()
    new_commercial_task(driver)
    snap = driver.start_content_run("task1")

    # pr calls are booked to the explicit pr_intake sub-run (own budget)
    pr_runs = [r["id"] for r in [repo.get_run(snap["run_id"] + "_pr")]]
    pr_usage = repo.get_usage(pr_runs[0])
    assert pr_usage["normal_calls"] == 1
    assert snap["usage"]["normal_calls"] == 1, "内容预算只含 prepare_brief，不含商单分析"

    pr_art = repo.find_artifacts("task1", "pr_analysis")
    assert pr_art and pr_art[-1]["payload"]["ready_for_operator"]
    assert pr_art[-1]["payload"]["requirements"][0]["text"] == "文案必须出现品牌名"

    assert snap["pending_gates"][0]["kind"] == "confirm_brief"
    brief = repo.latest_brief("task1")
    assert "文案必须出现品牌名" in brief["payload"]["objective"], "客户硬性要求进入 Brief"
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True,
                         payload={"brief_version": brief["brief_version"],
                                  "brief_hash": brief["brief_hash"]})
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True, payload={})
    assert snap["status"] == "READY"
    # content run: brief + draft + assess (by editorial_reviewer) = 3 normal
    assert snap["usage"]["normal_calls"] == 3
    assess_calls = [c for c in snap["calls"] if c["action"] == "assess_content"]
    assert assess_calls and assess_calls[0]["agent_id"] == "editorial_reviewer"


def test_pr_gap_pauses_then_replans_until_ready():
    repo, driver = make_driver()
    new_commercial_task(driver, client_brief="品牌X新品推广")  # no 要求
    snap = driver.start_content_run("task1")
    assert snap["status"] == "WAITING" and snap["pending_gates"][0]["kind"] == "supply_input"
    assert [c for c in snap["calls"] if c["action"] == "prepare_brief"] == [], "需求未就绪不过运营官"

    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True,
                         payload={"answers": ["要求：文案必须出现品牌名"]})
    assert snap["pending_gates"][0]["kind"] == "confirm_brief"
    pr_art = repo.find_artifacts("task1", "pr_analysis")
    assert pr_art and pr_art[-1]["payload"]["ready_for_operator"]
    assert repo.get_usage(snap["run_id"] + "_pr")["normal_calls"] == 2, "补料后重新分析计原预算"


def test_pr_analysis_error_goes_manual():
    scripts = {("pr_analyst", "analyze_request"): [A.error([{
        "id": "iss_pr_1", "severity": "blocking", "location": "client_brief",
        "reason": "无法解析客户简报", "requested_change": "提供结构化要求"}])]}
    repo, driver = make_driver(scripts=scripts)
    new_commercial_task(driver)
    snap = driver.start_content_run("task1")
    assert snap["status"] == "NEEDS_REVIEW", "商单分析不交接，转人工"
    assert [c for c in snap["calls"] if c["action"] == "prepare_brief"] == []


def test_non_commercial_skips_pr_analyst():
    repo, driver = make_driver()
    driver.create_task("task2", {"goal": "写一篇新手拍照入门图文", "user_input": "写一篇新手拍照入门图文",
                                 "input_mode": "idea", "purpose": "content",
                                 "flags": {"traffic_enabled": False, "goal_clear": True}})
    driver.add_material("task2", "mat1", "拍照入门。")
    snap = driver.start_content_run("task2")
    assert snap["pending_gates"][0]["kind"] == "confirm_brief"
    assert driver.router.mock("pr_analyst").invocations == [], "非商单任务零商单分析调用"


def test_standalone_pr_analysis_run():
    repo, driver = make_driver()
    new_commercial_task(driver)
    snap = driver.start_pr_analysis_run("task1")
    assert snap["status"] == "READY"
    assert snap["usage"]["normal_calls"] == 1
    art = repo.find_artifacts("task1", "pr_analysis")
    assert art and art[-1]["payload"]["ready_for_operator"]


def test_pr_needs_input_standalone_stops_without_handoff():
    repo, driver = make_driver()
    new_commercial_task(driver, client_brief="品牌X新品推广")  # no 要求 -> needs_input
    snap = driver.start_pr_analysis_run("task1")
    assert snap["status"] == "WAITING_INPUT"
    assert repo.find_artifacts("task1", "pr_analysis") == [], "needs_input 不生成交接产物"
