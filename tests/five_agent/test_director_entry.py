"""内容主创真实入口桥接:draft 主链 + revise 范围保护。"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BC_BACKEND = ROOT / "birthco-local" / "backend"

import backend  # noqa: E402
if str(BC_BACKEND) not in backend.__path__:
    backend.__path__.append(str(BC_BACKEND))

from backend.adapters.bridge_common import orchestration_ref_digest  # noqa: E402
from backend.adapters.director_bridge import DirectorTeamAdapter  # noqa: E402
from backend.workflow.five_agent.repository import Repository, object_hash  # noqa: E402

BRIEF_PAYLOAD = {
    "input_mode": "idea", "objective": "写一篇新手拍照入门图文",
    "audience": "对目标话题感兴趣的新手读者", "platform": "图文平台", "format": "text",
    "core_promise": "让读者理解并能动手实践", "requirements": [{"id": "r1", "text": "口语化"}],
    "material_ids": ["m1"], "open_questions": [], "route": ["draft", "review", "export"],
    "length_rule": {"minimum": 300, "maximum": 20000}, "edit_scope": None,
}


def _make():
    repo = Repository(":memory:")
    repo.create_task("t1", "account", {"goal": "x"})
    repo.add_material("t1", "m1", "拍照入门：先学会构图三分法，再练光线。")
    repo.save_brief("t1", BRIEF_PAYLOAD, [])
    brief = repo.latest_brief("t1")
    resolve_brief = lambda ref: repo.get_brief(ref["task_id"], ref["brief_version"])
    adapter = DirectorTeamAdapter(
        resolve_material=lambda ref: repo.list_materials("t1")[0],
        resolve_brief=resolve_brief,
        resolve_version=lambda ref: repo.get_version(ref["id"]),
        resolve_artifact=lambda ref: repo.get_artifact(ref["id"])["payload"],
        mode="mock")
    return repo, adapter, brief


def _call_draft(brief):
    return SimpleNamespace(request_id="req_1", agent_id="content_creator", action="draft",
                           contract_version="seven-agent.v0.1",
                           context=SimpleNamespace(task_id="t1", account_id="account"),
                           input={"brief_ref": {"task_id": "t1", "brief_version": brief["brief_version"],
                                                "brief_hash": brief["brief_hash"]},
                                  "material_refs": [{"id": "m1",
                                                     "sha256": orchestration_ref_digest(
                                                         "拍照入门：先学会构图三分法，再练光线。")}]})


def test_draft_ok_maps_to_content_candidate():
    repo, adapter, brief = _make()
    out = adapter.invoke(_call_draft(brief))
    assert out["status"] == "ok", out
    data = out["data"]
    assert {"titles", "segments"} <= set(data)
    assert len(data["titles"]) == 3 and data["segments"]
    for seg in data["segments"]:
        assert seg["segment_id"].startswith("res_")
        assert seg["source_refs"] and set(seg["source_refs"]) <= {"m1"}


def test_draft_brief_hash_mismatch_is_error():
    repo, adapter, brief = _make()
    call = _call_draft(brief)
    call.input["brief_ref"]["brief_hash"] = "0" * 64
    out = adapter.invoke(call)
    assert out["status"] == "error"


def test_revise_only_changes_authorized_segments():
    repo, adapter, brief = _make()
    base = repo.save_version("ver_abc", "t1", "run1", None, {
        "titles": ["t1", "t2", "t3"], "cover_copy": "封面",
        "segments": [{"segment_id": "s1", "kind": "hook", "text": "第一段", "source_refs": ["m1"]},
                     {"segment_id": "s2", "kind": "body", "text": "第二段", "source_refs": ["m1"]}]})
    request = {"kind": "issue_repair", "expected_head_version_id": "ver_abc",
               "base_version_id": "ver_abc", "base_content_hash": base["content_hash"],
               "issue_ids": ["i1"], "issue_locations": {"i1": "s2"},
               "instructions": "只改 s2", "allow_title_change": False, "allow_cover_change": False}
    repo.save_artifact("revreq_1", "t1", "run1", "revision_request", request)
    call = SimpleNamespace(request_id="req_2", agent_id="content_creator", action="revise",
                           contract_version="seven-agent.v0.1",
                           context=SimpleNamespace(task_id="t1", account_id="account"),
                           input={"brief_ref": {"task_id": "t1", "brief_version": brief["brief_version"],
                                                "brief_hash": brief["brief_hash"]},
                                  "base_version_ref": {"id": "ver_abc", "sha256": base["content_hash"]},
                                  "revision_request_ref": {"id": "revreq_1",
                                                           "sha256": object_hash(request)}})
    out = adapter.invoke(call)
    assert out["status"] == "ok", out
    data = out["data"]
    assert "change_log" in data and data["change_log"]
    unchanged = [s for s in data["segments"] if s["segment_id"] == "s1"]
    assert unchanged and unchanged[0]["text"] == "第一段"  # 未授权段逐字保留
    changed = [s for s in data["segments"] if s["segment_id"] != "s1" and s["kind"] == "body"]
    assert changed and changed[0]["text"] != "第二段"


from backend.workflow.five_agent import adapters as A
from backend.workflow.five_agent.driver import OrchestrationDriver
from backend.workflow.five_agent.team_entries import TeamEntry


def _operator_entry(repo):
    from backend.adapters.orch_bridge import OperatorTeamAdapter
    def factory(task_id):
        def resolve(ref):
            for m in repo.list_materials(task_id):
                if m["id"] == ref["id"]:
                    return m
            raise KeyError(ref["id"])
        return OperatorTeamAdapter(resolve_material=resolve, mode="mock")
    return TeamEntry(factory)


def test_content_chain_runs_with_real_director_entry():
    repo = Repository(":memory:")
    driver = OrchestrationDriver(repo, router=A.AdapterRouter(
        repo, mode="mock",
        agent_modes={"content_creator": "live", "operations_officer": "live"},
        reals={
            "operations_officer": _operator_entry(repo),
            "content_creator": TeamEntry(
                lambda task_id: DirectorTeamAdapter(
                    resolve_material=lambda ref: repo.list_materials(task_id)[0],
                    resolve_brief=lambda ref: repo.get_brief(ref["task_id"], ref["brief_version"]),
                    resolve_version=lambda ref: repo.get_version(ref["id"]),
                    resolve_artifact=lambda ref: repo.get_artifact(ref["id"])["payload"],
                    mode="mock"))}))
    driver.create_task("t1", {"goal": "写一篇新手拍照入门图文", "user_input": "写一篇新手拍照入门图文",
                              "input_mode": "idea", "purpose": "content",
                              "flags": {"traffic_enabled": False, "goal_clear": True}})
    driver.add_material("t1", "m1", "拍照入门：先学会构图三分法，再练光线。")
    snap = driver.start_content_run("t1")
    assert snap["pending_gates"][0]["kind"] == "confirm_brief"
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True,
                         payload={"brief_version": snap["state"]["brief_ref"]["brief_version"],
                                  "brief_hash": snap["state"]["brief_ref"]["brief_hash"]})
    # 运营官/主创两跳均经真实桥接收妥(非编排层 mock 替身)。
    calls = {(c["action"], c["status"]) for c in snap["calls"]}
    assert ("prepare_brief", "received") in calls and ("draft", "received") in calls
    # 主链经真实桥接收妥后到达交付闸门:规则+编排 mock 审稿通过 → export →
    # wait_accept(用户接受闸门),版本 ready。草稿由真实主创入口产出并按预留
    # res_ 段落号落库。
    assert snap["status"] == "WAITING"
    assert snap["pending_gates"][0]["kind"] == "accept_delivery"
    assert ("assess_content", "received") in calls
    version = repo.get_version(snap["state"]["version_ref"]["id"])
    assert version["status"] == "ready"
    assert version["payload"]["segments"] and all(
        s["segment_id"].startswith("res_") for s in version["payload"]["segments"])
