"""Real component entries through the workflow, using an offline transport."""
from contextlib import contextmanager
from dataclasses import replace
import json

import pytest

from backend.adapters.model.mock import MockAdapter
from backend.adapters.model.protocol import ModelUsage
from backend.domain import schemas
from backend.memory.material_retrieval import rank_materials
from backend.workflow.five_agent import adapters
from backend.workflow.five_agent.adapters import AdapterRouter
from backend.workflow.five_agent.driver import OrchestrationDriver
from backend.workflow.five_agent.live_adapters import ProductionAdapter
from backend.workflow.five_agent.program import compute_metrics
from backend.workflow.five_agent.repository import DomainError, Repository
from backend.workflow.five_agent.resources import load_domain_schemas

from test_main_chain import confirm_gate, make_driver, new_task


class FixtureTransport:
    def __init__(self):
        self.requests = []

    @contextmanager
    def provider(self, role):
        yield self, "offline-fixture"

    def complete(self, request):
        data = json.loads(request.messages[1].content)
        self.requests.append((request.role, data))
        if request.role == "operator":
            task = data["task"]
            refs = [m["material_id"] for m in data["materials"]]
            result = {"input_mode": task["input_mode"], "objective": task["objective"],
                      "audience": task["audience"], "platform": task["platform"], "format": "text",
                      "core_promise": "构图练习", "requirements": task["requirements"],
                      "material_ids": refs, "open_questions": [], "route": ["draft", "review", "export"],
                      "length_rule": task["length_rule"], "edit_scope": data["edit_scope"]}
        elif request.role == "scout":
            refs = [m["material_id"] for m in data["materials"]][:1]
            result = {"opportunities": [{"id": "topic", "angle": "通勤路上的构图练习",
                "audience_problem": "不知道如何练习", "account_fit": "对应入门任务",
                "source_refs": refs, "evidence_date": None, "hypothesis": "例子可能更易懂"}]}
        elif request.role == "director":
            refs = [m["material_id"] for m in data["materials"]][:1]
            new_id = data["reserved_segment_ids"][0]
            if data["base_content"] is None:
                result = {"titles": ["构图练习", "用一张照片开始", "通勤时的取景"],
                          "cover_copy": "练习框出主体",
                          "segments": [{"segment_id": new_id, "kind": "body", "text": "先选择一个主体。", "source_refs": refs}]}
            else:
                issue = data["edit_requests"][0]
                base = data["base_content"]
                result = {**base, "segments": [
                    {**s, "segment_id": new_id, "text": s["text"] + "例：以路灯为主体。"}
                    if s["segment_id"] == issue["location"] else s for s in base["segments"]],
                    "change_log": [{"finding_id": None, "issue_id": issue["id"], "old_segment_id": issue["location"],
                                    "new_segment_id": new_id, "change": "replace", "reason": "补充示例"}]}
        elif request.role == "editorial-reviewer":
            refs = [data["content"]["segments"][0]["segment_id"]]
            result = {"overall": "pass", "issues": [], "claim_checks": [],
                      "requirement_checks": [{"requirement_id": r["id"], "result": "met", "evidence_refs": refs}
                                             for r in data["brief"]["requirements"]]}
        elif request.role == "analyst":
            event = data["left"]["sessions"][0]["events"][-1]
            refs = [event["event_id"]]
            condition = data["comparison_context"]
            result = {"findings": [{"id": "f1", "segment_id": event["event"]["segment_id"],
                        "observation_refs": refs, "interpretation": "本次模拟中读者见到这段。",
                        "alternative_explanation": "读者设定可能影响反应。", "suggested_edit": "增加例子。"}],
                      "comparison": {"conditions_match": condition["conditions_match"],
                                     "reason": condition["reason"], "summary": "只描述本次模拟。"},
                      "next_experiment": "下一轮对照记录。"}
        else:
            raise AssertionError(f"unexpected model role {request.role}")
        envelope = {"schema_version": "creator-agent.v1", "status": "ok", "summary": "离线接口夹具",
                    "data": result, "evidence_refs": refs, "questions": [], "issues": []}
        fixture = MockAdapter({request.call_id: json.dumps(envelope, ensure_ascii=False)})
        response = fixture.complete(replace(request, mode="mock"))
        return replace(response, mode="live", usage=ModelUsage(input=30, output=30, total=60))


def test_five_real_entries_and_blind_retest(monkeypatch):
    repo = Repository()
    transport = FixtureTransport()
    entry = ProductionAdapter(repo, provider=transport.provider)
    roles = ["operations_officer", "content_creator", "editorial_reviewer", "traffic_scout", "data_analyst"]
    router = AdapterRouter(repo, reals=dict.fromkeys(roles, entry), agent_modes=dict.fromkeys(roles, "live"))
    driver = OrchestrationDriver(repo, router=router)
    new_task(driver, flags={"traffic_enabled": True, "goal_clear": False})
    snap = driver.start_content_run("task1")
    assert [role for role, _ in transport.requests] == ["scout"]
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"],
                         payload={"selected_opportunity_ref": {"id": "topic"}})
    assert "通勤路上的构图练习" in repo.latest_brief("task1")["payload"]["objective"]
    snap = confirm_gate(snap, driver)
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], payload={})
    assert snap["status"] == "READY"
    original = snap["state"]["version_ref"]["id"]
    persona = {"id": "p_full", "goal": "学构图", "knowledge": "新手", "preferences": []}
    preview = driver.start_preview_run("task1", original)
    preview = driver.decide(preview["run_id"], preview["pending_gates"][0]["id"],
                            payload={"scenario": {"personas": [persona]}})
    preview_id = preview["state"]["preview_ref"]["id"]
    assert [role for role, _ in transport.requests] == ["scout", "operator", "director", "editorial-reviewer", "analyst"]
    assert driver.preview_history(preview_id)[0]["payload"]["stage"] == "hypotheses"
    preview = driver.decide(preview["run_id"], preview["pending_gates"][0]["id"], payload={"finding_ids": ["f1"]})
    rev = driver.start_revision_run("task1", preview["state"]["revision_ref"]["id"])
    rev = driver.decide(rev["run_id"], rev["pending_gates"][0]["id"], payload={})
    assert rev["status"] == "READY"
    revised = repo.get_version(rev["state"]["version_ref"]["id"])
    assert revised["payload"]["change_log"][0]["finding_id"] == "f1"
    assert "增加例子。" in transport.requests[-2][1]["edit_requests"][0]["requested_change"]
    original_find = repo.find_artifacts

    def no_history(task_id, kind):
        assert kind != "experiment_entry"
        return original_find(task_id, kind)

    blind = driver.start_preview_run("task1", revised["id"])
    with monkeypatch.context() as patch:
        patch.setattr(repo, "find_artifacts", no_history)
        blind = driver.decide(blind["run_id"], blind["pending_gates"][0]["id"],
                              payload={"scenario": {"personas": [persona], "blind": True, "retest_of": preview_id}})
        with pytest.raises(DomainError, match="blind preview"):
            driver.preview_history(blind["state"]["preview_ref"]["id"])
    prompt = transport.requests[-1][1]
    assert set(prompt["left"]) == {"version_id", "content_hash", "content", "personas", "segments", "sessions"}
    stages = {e["payload"]["stage"] for e in driver.preview_history(preview_id)}
    assert stages == {"hypotheses", "selected", "revision_candidate", "retest"}


def test_fourth_supplement_stops_and_records_each_accepted_round_once():
    def ask(call, resolver):
        return {"kind": "needs_input", "questions": [{"id": "q", "question": "请补充资料", "reason": "本轮缺信息"}]}
    repo, driver = make_driver(scripts={("operations_officer", "prepare_brief"): [ask] * 4})
    new_task(driver)
    snap = driver.start_content_run("task1")
    gate_ids = set()
    for round_no in range(1, 4):
        gate = snap["pending_gates"][0]
        assert json.loads(gate["subject_json"])["round"] == round_no
        gate_ids.add(gate["id"])
        snap = driver.decide(snap["run_id"], gate["id"], payload={"answers": [f"补充 {round_no}"]})
    assert len(gate_ids) == 3 and snap["status"] == "NEEDS_REVIEW"
    assert snap["usage"]["normal_calls"] == 4
    assert len(repo.list_events("task1", "input_supplied")) == 3
    assert repo.get_task("task1")["payload"]["answers"] == ["补充 1", "补充 2", "补充 3"]


def test_metrics_count_early_interaction_once_and_zero_event_incomplete():
    sessions = [{"id": "reader", "status": "completed"}, {"id": "unstarted", "status": "active"}]
    events = [{"id": "event1", "session_id": "reader",
               "payload": {"segment_id": "s1", "action": "continue", "interactions": ["like", "save"]}},
              {"id": "event2", "session_id": "reader",
               "payload": {"segment_id": "s2", "action": "continue", "interactions": ["like"]}},
              {"id": "event3", "session_id": "reader",
               "payload": {"segment_id": "s3", "action": "continue", "interactions": []}}]
    metrics = compute_metrics(sessions, events, ["s1", "s2", "s3"])
    assert metrics["interaction_sessions"] == {"like": 1, "comment": 0, "save": 1}
    assert metrics["incomplete"] == metrics["no_event_sessions"] == 1
    assert metrics["coverage_ratio"] == 0.5


def test_three_supplements_can_finish_inside_total_call_cap():
    def ask(call, resolver):
        return {"kind": "needs_input", "questions": [{"id": "q", "question": "请补充", "reason": "缺资料"}]}
    _, driver = make_driver(scripts={("operations_officer", "prepare_brief"): [ask] * 3})
    new_task(driver)
    snap = driver.start_content_run("task1")
    for round_no in range(3):
        snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], payload={"answers": [str(round_no)]})
    snap = confirm_gate(snap, driver)
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], payload={})
    assert snap["status"] == "READY" and snap["usage"]["calls_reserved"] == 6


def test_bad_scout_evidence_does_not_commit_or_retry():
    class BadEvidence(FixtureTransport):
        def complete(self, request):
            response = super().complete(request)
            raw = json.loads(response.text)
            raw["data"]["opportunities"][0]["source_refs"] = ["unknown_material"]
            return replace(response, text=json.dumps(raw))

    repo = Repository()
    transport = BadEvidence()
    router = AdapterRouter(repo, reals={"traffic_scout": ProductionAdapter(repo, transport.provider)},
                           agent_modes={"traffic_scout": "live"})
    driver = OrchestrationDriver(repo, router=router)
    new_task(driver)
    result = driver.start_scout_run("task1")
    assert result["status"] == "NEEDS_REVIEW"
    assert len(transport.requests) == 1 and repo.find_artifacts("task1", "opportunity_set") == []
    assert result["usage"]["tokens_known"] == 60


def test_preview_at_maximum_size_can_finish():
    def long_draft(call, resolver):
        result = adapters.gen_candidate(call, resolver)
        template = result["data"]["segments"][1]
        result["data"]["segments"][1:1] = [{**template, "segment_id": f"extra_{i}",
                                            "text": f"不同的例子 {i}"} for i in range(4)]
        return result

    repo, driver = make_driver(scripts={("content_creator", "draft"): [long_draft]})
    new_task(driver)
    content = confirm_gate(driver.start_content_run("task1"), driver)
    preview = driver.start_preview_run("task1", content["state"]["version_ref"]["id"])
    personas = [{"id": f"reader{i}", "goal": "学习", "knowledge": "新手", "preferences": []} for i in range(6)]
    result = driver.decide(preview["run_id"], preview["pending_gates"][0]["id"],
                           payload={"scenario": {"personas": personas}})
    preview_id = result["state"]["preview_ref"]["id"]
    assert len(repo.preview_events(preview_id)) == 48
    assert repo.get_artifact(f"metrics_{preview_id}")["payload"]["completed"] == 6
    assert result["usage"]["normal_calls"] == 49


def test_material_retrieval_keeps_provenance_and_expands_three_rounds():
    materials = [{"id": "irrelevant", "text": "weather"},
                 {"id": "three", "text": "light reflection"},
                 {"id": "two", "text": "framing light"},
                 {"id": "one", "text": "portrait framing"}]
    ranked, rounds = rank_materials("portrait", materials)
    assert rounds == [["one"], ["two"], ["three"]]
    assert [row["id"] for row in ranked] == ["one", "two", "three", "irrelevant"]


@pytest.mark.parametrize("name", ["Brief", "OpportunitySet", "ContentCandidate", "Revision", "EditorialReview", "Analysis"])
def test_specialist_output_contracts_match_component_schemas(name):
    assert load_domain_schemas()[name] == getattr(schemas, name).model_json_schema()
