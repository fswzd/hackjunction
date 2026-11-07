"""Repro cases for the architecture-audit defect fixes (F-01..F-05).

Each test names the audit finding it locks down.  Evidence class: mock flow.
"""
import pytest

from backend.workflow.five_agent import adapters as A
from backend.workflow.five_agent import nodes as N
from backend.workflow.five_agent.contracts import default_validators
from backend.workflow.five_agent.driver import OrchestrationDriver
from backend.workflow.five_agent.gateway import AgentGateway, BudgetExceeded
from backend.workflow.five_agent.registry import PROMPT_SCHEMA_VERSION, step_key_scout
from backend.workflow.five_agent.repository import Repository

from test_branches import make_driver, new_task


def _in(goal="A", sha="a"):
    return {"goal": goal, "material_refs": [{"id": "m1", "sha256": sha * 64}]}


# ------------------------------------------------------- F-01 stale receipt replay


def test_f01_gateway_replay_requires_identical_input():
    """同 step_key 不同输入不得重放；逐字节相同输入的重放仍然零调用。"""
    repo = Repository(":memory:")
    router = A.AdapterRouter(repo, mode="mock")
    gw = AgentGateway(repo, router, validators=default_validators())
    repo.create_task("t1", "acc1", {"goal": "x"})
    repo.create_run("r1", "t1", "content")

    out1 = gw.invoke("r1", "scout:fp", "capture_opportunities", _in("A", "a"),
                     "acc1", "t1", PROMPT_SCHEMA_VERSION)
    assert out1.replayed is False
    out2 = gw.invoke("r1", "scout:fp", "capture_opportunities", _in("B", "a"),
                     "acc1", "t1", PROMPT_SCHEMA_VERSION)
    assert out2.replayed is False, "不同输入命中同一 step_key 必须重新调用"
    assert len(repo.list_calls("r1")) == 2
    out3 = gw.invoke("r1", "scout:fp", "capture_opportunities", _in("A", "a"),
                     "acc1", "t1", PROMPT_SCHEMA_VERSION)
    assert out3.replayed is True, "相同输入的幂等重放必须零新调用"
    assert len(repo.list_calls("r1")) == 2


def test_f01_scout_step_key_fingerprint_covers_material_content():
    """素材 id 相同、正文 hash 不同 → step_key 必须不同。"""
    refs1 = [{"id": "m1", "sha256": "a" * 64}]
    refs2 = [{"id": "m1", "sha256": "b" * 64}]
    k1 = step_key_scout(N._fp({"goal": "g", "materials": N._materials_fp(refs1)})[:16])
    k2 = step_key_scout(N._fp({"goal": "g", "materials": N._materials_fp(refs2)})[:16])
    assert k1 != k2, "内容 hash 必须进入指纹"
    assert refs1[0]["id"] in str(N._materials_fp(refs1))


def test_f01_material_change_does_not_replay_stale_capture():
    """端到端：素材正文变更后恢复执行，不得重放陈旧机会卡。"""
    repo, driver = make_driver()
    new_task(driver, flags={"traffic_enabled": True, "goal_clear": False})
    snap = driver.start_content_run("task1")
    run_id = snap["run_id"]
    scout_run = f"{run_id}_scout"
    assert len(repo.list_calls(scout_run)) == 1

    repo._exec("UPDATE materials SET text=? WHERE id='mat1'",
               ("全新素材正文：讲光线与白平衡。",))
    driver.reinvoke(run_id, {"resume_step": "traffic"})
    calls = repo.list_calls(scout_run)
    assert len(calls) == 2, "素材内容变更后必须重新捕捉，不得重放旧收据"

    driver.reinvoke(run_id, {"resume_step": "traffic"})
    assert len(repo.list_calls(scout_run)) == 2, "输入未再变时重放零新调用"


# ------------------------------------------------------ F-02 sub-run terminal state


def _scout_script_result(kind):
    def behaviour(call, r):
        if kind == "error":
            return {"kind": "error", "usage": A.Usage.known(20).to_dict(),
                    "issues": [{"id": "iss_1", "severity": "blocking", "location": "capture",
                                "reason": "mock failure", "requested_change": "修复后重试"}]}
        return {"kind": "needs_input", "usage": A.Usage.known(20).to_dict(),
                "questions": [{"id": "q1", "question": "缺少来源正文", "reason": "不能虚构来源"}]}
    return behaviour


def test_f02_sub_run_terminal_ok():
    repo, driver = make_driver()
    new_task(driver, flags={"traffic_enabled": True, "goal_clear": False})
    snap = driver.start_content_run("task1")
    sub = repo.get_run(f"{snap['run_id']}_scout")
    assert sub["status"] == "READY", "ok 出口必须终结 scout 子 run"


def test_f02_sub_run_terminal_on_error():
    scripts = {("traffic_scout", "capture_opportunities"): [_scout_script_result("error")]}
    repo, driver = make_driver(scripts=scripts)
    new_task(driver, flags={"traffic_enabled": True, "goal_clear": False})
    snap = driver.start_content_run("task1")
    sub = repo.get_run(f"{snap['run_id']}_scout")
    assert sub["status"] == "NEEDS_REVIEW", "error 出口必须终结 scout 子 run"
    assert snap["pending_gates"][0]["kind"] == "confirm_brief", "非发现模式失败分流继续 brief"


def test_f02_sub_run_terminal_on_needs_input():
    scripts = {("traffic_scout", "capture_opportunities"): [_scout_script_result("needs_input")]}
    repo, driver = make_driver(scripts=scripts)
    new_task(driver, flags={"traffic_enabled": True, "goal_clear": False})
    snap = driver.start_content_run("task1")
    sub = repo.get_run(f"{snap['run_id']}_scout")
    assert sub["status"] == "WAITING_INPUT", "needs_input 出口必须终结 scout 子 run"
    pending = repo.get_artifact(f"pending_questions_{snap['run_id']}_scout")
    assert pending["payload"]["questions"], "缺料问题必须留痕供用户补齐"


def test_f02_standalone_scout_needs_input_waits_not_reviews():
    scripts = {("traffic_scout", "capture_opportunities"): [_scout_script_result("needs_input")]}
    repo, driver = make_driver(scripts=scripts)
    new_task(driver, flags={"traffic_enabled": True, "goal_clear": False})
    snap = driver.start_scout_run("task1")
    assert snap["status"] == "WAITING_INPUT", "独立 scout 缺料是等待补充，不是人工复核"


# ------------------------------------------------------- F-03 per-agent rollout


def test_f03_per_agent_live_rollout():
    repo = Repository(":memory:")
    router = A.AdapterRouter(repo, mode="mock",
                             agent_modes={"traffic_scout": "live"})
    assert isinstance(router.adapter_for("capture_opportunities"), A.RealAdapterStub), \
        "traffic_scout 可单独切 live"
    assert isinstance(router.adapter_for("prepare_brief"), A.MockAgent), \
        "其余角色保持 mock，不受牵连"


def test_f03_agent_modes_rejects_invalid_entries():
    repo = Repository(":memory:")
    with pytest.raises(ValueError):
        A.AdapterRouter(repo, mode="mock", agent_modes={"traffic_scout": "sometimes"})
    with pytest.raises(ValueError):
        A.AdapterRouter(repo, mode="mock", agent_modes={"no_such_agent": "live"})


# ----------------------------------------------- F-04 orphan call accounting


def test_f04_sent_orphans_settled_interrupted_and_counted():
    repo = Repository(":memory:")
    router = A.AdapterRouter(repo, mode="mock")
    gw = AgentGateway(repo, router, validators=default_validators())
    repo.create_task("t1", "acc1", {})
    repo.create_run("r1", "t1", "scout")  # budget: 3 normal calls
    for i in range(3):
        cid = f"call_orphan{i}"
        repo.reserve_call(cid, "r1", f"scout:o{i}", 1, "traffic_scout",
                          "capture_opportunities", f"req_{i}", "h" * 64)
        repo.mark_send_intent(cid)

    with pytest.raises(BudgetExceeded):
        gw.invoke("r1", "scout:x", "capture_opportunities", _in(), "acc1", "t1",
                  PROMPT_SCHEMA_VERSION)

    statuses = [c["status"] for c in repo.list_calls("r1")]
    assert statuses.count("interrupted") == 3, "崩溃遗留的已发送调用必须结算为 interrupted"
    usage = repo.get_usage("r1")
    assert usage["normal_calls"] == 3 and usage["unknown_usage_calls"] == 3, \
        "孤儿 attempt 必须计入预算"


def test_f04_unsent_orphan_settled_as_aborted():
    repo = Repository(":memory:")
    router = A.AdapterRouter(repo, mode="mock")
    gw = AgentGateway(repo, router, validators=default_validators())
    repo.create_task("t1", "acc1", {})
    repo.create_run("r1", "t1", "scout")
    repo.reserve_call("call_unsent", "r1", "scout:u", 1, "traffic_scout",
                      "capture_opportunities", "req_u", "h" * 64)

    gw.invoke("r1", "scout:x", "capture_opportunities", _in(), "acc1", "t1",
              PROMPT_SCHEMA_VERSION)
    rows = {c["id"]: c for c in repo.list_calls("r1")}
    assert rows["call_unsent"]["status"] == "aborted_pre_send", "未发送孤儿不得伪装成已发送"
    assert rows["call_unsent"]["usage_status"] is None


# ------------------------------------------------------- F-05 diagnostics refs


def test_f05_discovery_error_persists_diagnostics():
    scripts = {("traffic_scout", "capture_opportunities"): [_scout_script_result("error")]}
    repo, driver = make_driver(scripts=scripts)
    new_task(driver, flags={"traffic_enabled": True, "goal_clear": False},
             purpose="discover_topics")
    snap = driver.start_content_run("task1")
    assert snap["status"] == "NEEDS_REVIEW"
    diags = repo.find_artifacts("task1", "diagnostics")
    assert diags, "错误诊断必须落库，error_ref 不得是占位符"
    payload = diags[-1]["payload"]
    assert payload["source"] == "traffic" and payload["issue_codes"] == ["iss_1"]


def test_f05_gateway_exception_persists_error_code():
    def boom(call, r):
        raise A.PreSendFailure("mock transport exploded")

    scripts = {("traffic_scout", "capture_opportunities"): [boom, boom, boom]}
    repo, driver = make_driver(scripts=scripts)
    new_task(driver, flags={"traffic_enabled": True, "goal_clear": False},
             purpose="discover_topics")
    snap = driver.start_content_run("task1")
    assert snap["status"] == "NEEDS_REVIEW"
    diags = repo.find_artifacts("task1", "diagnostics")
    assert diags and diags[-1]["payload"]["error_code"], "异常路径必须留下错误码诊断"
