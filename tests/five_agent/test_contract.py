"""Boundary contract tests: AgentCall/AgentResult protocol (five-agent.v0.2).

Runtime counterpart of the handoff tool five-agent/tools/verify_interfaces.py —
same fixture semantics, enforced by ContractValidators at the gateway boundary.
Evidence class: offline interface schema fixtures (no agent/model/graph).
"""
import copy

import pytest

from backend.workflow.five_agent.contracts import (
    AgentCall, AgentResult, ContractValidators, ProtocolError, SchemaDriftError,
    StepContext, Usage, frozen_input_hash,
)
from backend.workflow.five_agent.registry import ACTIONS, CONTRACT_VERSION, ROLES


@pytest.fixture(scope="module")
def validators():
    return ContractValidators()


CTX = StepContext("account1", "task1", "run1", "step1", 1, "c" * 64)
REF = {"id": "version1", "sha256": "a" * 64}
BRIEF = {"task_id": "task1", "brief_version": 1, "brief_hash": "b" * 64}

INPUTS = {
    "analyze_request": {"request_text": "品牌X新品推广；要求：文案必须出现品牌名；要求：不夸大功效",
                         "material_refs": [REF]},
    "prepare_brief": {"user_input": "把授权经验写成新手图文", "input_mode": "idea",
                      "material_refs": [REF], "selected_opportunity_ref": None},
    "assess_content": {"brief_ref": BRIEF, "version_ref": REF, "rule_report_ref": REF,
                       "material_refs": [REF]},
    "draft": {"brief_ref": BRIEF, "material_refs": [REF]},
    "revise": {"brief_ref": BRIEF, "base_version_ref": REF, "revision_request_ref": REF},
    "capture_opportunities": {"goal": "寻找新手可操作的角度", "material_refs": [REF]},
    "diagnose_preview": {"preview_ref": REF, "version_ref": REF, "metrics_ref": REF},
    "read_segment": {"persona": {"id": "persona1", "goal": "学会拍照", "knowledge": "新手",
                                 "preferences": []},
                     "current_segment": {"segment_id": "cover_v1", "kind": "cover", "text": "封面"},
                     "visible_history": [], "own_previous_reactions": []},
}


def make_call(action: str) -> AgentCall:
    return AgentCall(request_id="req_" + action, agent_id=ACTIONS[action], action=action,
                     context=CTX, input=copy.deepcopy(INPUTS[action]))


def test_roles_and_actions_cardinality():
    assert set(ROLES) == {"pr_analyst", "content_creator", "operations_officer",
                          "editorial_reviewer", "traffic_scout", "data_analyst",
                          "simulated_audience"}
    assert len(ROLES) == 7
    assert len(ACTIONS) == 8
    assert {a for a in ACTIONS} == {"analyze_request", "draft", "revise", "prepare_brief",
                                    "assess_content", "capture_opportunities",
                                    "diagnose_preview", "read_segment"}
    assert ACTIONS["assess_content"] == "editorial_reviewer"
    assert ACTIONS["analyze_request"] == "pr_analyst"


@pytest.mark.parametrize("action", sorted(ACTIONS))
def test_valid_call_per_action(validators, action):
    validators.validate_call(make_call(action))


def test_wrong_agent_for_action_rejected(validators):
    call = make_call("draft")
    bad = AgentCall(call.request_id, "data_analyst", "draft", call.context, call.input)
    with pytest.raises(SchemaDriftError):
        validators.validate_call(bad)


def test_sixth_legacy_role_rejected(validators):
    call = make_call("assess_content")
    bad = AgentCall(call.request_id, "EditorialReviewer", "assess_content", call.context, call.input)
    with pytest.raises(SchemaDriftError):
        validators.validate_call(bad)


def test_audience_future_field_rejected(validators):
    call = make_call("read_segment")
    bad_input = copy.deepcopy(call.input)
    bad_input["future_segments"] = ["FUTURE_SENTINEL"]
    bad = AgentCall(call.request_id, call.agent_id, call.action, call.context, bad_input)
    with pytest.raises(SchemaDriftError):
        validators.validate_call(bad)


def test_brief_task_reference_mismatch_rejected(validators):
    call = make_call("draft")
    bad_input = copy.deepcopy(call.input)
    bad_input["brief_ref"]["task_id"] = "another_task"
    bad = AgentCall(call.request_id, call.agent_id, call.action, call.context, bad_input)
    with pytest.raises(SchemaDriftError):
        validators.validate_call(bad)


def make_draft_result(request_id="req_draft", **over) -> dict:
    result = {"contract_version": CONTRACT_VERSION, "request_id": request_id,
              "agent_id": "content_creator", "action": "draft", "status": "ok",
              "data": {"titles": ["标题一", "标题二", "标题三"], "cover_copy": None, "segments": []},
              "questions": [], "issues": [],
              "usage": {"status": "unknown", "total_tokens": None}}
    result.update(over)
    return result


def test_parseable_incomplete_candidate_is_valid_protocol_not_ready(validators):
    call = make_call("draft")
    validators.validate_result(make_draft_result(), call)  # protocol ok; not a content pass


def test_wrong_domain_output_type_rejected(validators):
    call = make_call("draft")
    bad = make_draft_result(data={"titles": "not_a_list", "segments": []})
    with pytest.raises(ProtocolError):
        validators.validate_result(bad, call)


def test_ok_with_null_data_rejected(validators):
    call = make_call("draft")
    with pytest.raises(ProtocolError):
        validators.validate_result(make_draft_result(data=None), call)


def test_correlation_mismatch_rejected(validators):
    call = make_call("draft")
    with pytest.raises(ProtocolError):
        validators.validate_result(make_draft_result(request_id="different_request"), call)


def test_unknown_usage_is_not_zero(validators):
    call = make_call("draft")
    with pytest.raises(ProtocolError):
        validators.validate_result(make_draft_result(usage={"status": "unknown", "total_tokens": 0}), call)


def test_known_usage_requires_nonnegative_int():
    with pytest.raises(ProtocolError):
        Usage.known(True)  # booleans are not token counts
    with pytest.raises(ProtocolError):
        Usage.known(-1)
    assert Usage.known(0).to_dict() == {"status": "known", "total_tokens": 0}


def test_needs_input_question_accepted_for_pause(validators):
    call = make_call("draft")
    result = make_draft_result(status="needs_input", data=None,
                               questions=[{"id": "q1", "question": "目标平台是什么？", "reason": "影响篇幅"}])
    validators.validate_result(result, call)


def test_error_requires_issues_and_null_data(validators):
    call = make_call("draft")
    with pytest.raises(ProtocolError):
        validators.validate_result(make_draft_result(status="error"), call)
    good = make_draft_result(status="error", data=None,
                             issues=[{"id": "i1", "severity": "blocking", "location": "x",
                                      "reason": "y", "requested_change": "z"}])
    validators.validate_result(good, call)


def test_input_hash_is_frozen_and_versioned():
    h1 = frozen_input_hash({"a": 1}, "v1")
    h2 = frozen_input_hash({"a": 1}, "v2")
    h3 = frozen_input_hash({"a": 2}, "v1")
    assert h1 != h2 and h1 != h3
    assert len(h1) == 64
