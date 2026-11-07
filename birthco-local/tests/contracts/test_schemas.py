import copy
import json
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from backend.domain import schemas as s
from backend.domain.errors import DomainError, require_owned_refs, validate_audience_scope, validate_brief_scope, validate_candidate_scope
from backend.domain import states


CASES = json.loads((Path(__file__).resolve().parents[3] / "docs/agent-system/implementation-design/fixtures/contract-cases.json").read_text(encoding="utf-8"))["cases"]


def model_for(name):
    return s.ROLE_MODELS[name.removeprefix("Role_").replace("_", "-")] if name.startswith("Role_") else getattr(s, name)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_design_contract_cases(case):
    cls = model_for(case["schema"])
    if case["valid"]:
        cls.model_validate(case["payload"])
    else:
        with pytest.raises(ValidationError):
            cls.model_validate(case["payload"])


def test_all_seven_roles_have_positive_and_negative_examples():
    role_cases = {case["schema"] for case in CASES if case["schema"].startswith("Role_")}
    assert role_cases == {"Role_" + name.replace("-", "_") for name in s.ROLE_MODELS}
    for name in role_cases:
        assert {case["valid"] for case in CASES if case["schema"] == name} == {True, False}


def test_unexpected_fields_and_wrong_types_fail():
    good = next(case["payload"] for case in CASES if case["id"] == "operator_valid")
    extra = copy.deepcopy(good)
    extra["data"]["fictional_extra"] = "no"
    with pytest.raises(ValidationError):
        s.ROLE_MODELS["operator"].model_validate(extra)
    wrong = copy.deepcopy(good)
    wrong["data"]["requirements"] = "not an array"
    with pytest.raises(ValidationError):
        s.ROLE_MODELS["operator"].model_validate(wrong)


def test_incomplete_candidate_is_valid_but_cannot_be_delivered():
    candidate = {"titles": ["一个标题"], "cover_copy": None, "segments": []}
    s.ContentCandidate.model_validate(candidate)
    with pytest.raises(ValidationError):
        s.ContentDelivery.model_validate(candidate)


def test_brief_and_scope_cross_field_rules():
    brief = copy.deepcopy(next(case["payload"]["data"] for case in CASES if case["id"] == "operator_valid"))
    brief["requirements"].append(brief["requirements"][0])
    with pytest.raises(ValidationError, match="unique"):
        s.Brief.model_validate(brief)
    brief["requirements"].pop()
    brief["input_mode"] = "existing_draft"
    with pytest.raises(ValidationError, match="edit_scope"):
        s.Brief.model_validate(brief)
    brief["edit_scope"] = {"target_segment_ids": ["s1"], "preserve_segment_ids": ["s1"], "allow_title_change": False, "allow_cover_change": False}
    with pytest.raises(ValidationError, match="overlap"):
        s.Brief.model_validate(brief)


def test_existing_draft_task_intake_allows_missing_draft_for_waiting_input():
    base = {
        "account_id": "acct1", "input_mode": "existing_draft", "objective": "修改旧稿",
        "audience": "入门者", "platform": "generic", "format": "text", "style": "清楚",
        "requirements": [{"id": "r1", "text": "保留结论"}], "materials": [],
        "preview_requested": False, "length_rule": {"minimum": None, "maximum": None},
    }
    # Intake is accepted; the workflow decides WAITING_INPUT instead of HTTP 400.
    assert s.CreateTask.model_validate(base).materials == []
    draft = {"kind": "existing_draft", "label": "旧稿", "text": "原文", "source_url": None, "authorized": True}
    assert len(s.CreateTask.model_validate({**base, "materials": [draft]}).materials) == 1
    with pytest.raises(ValidationError, match="at most one"):
        s.CreateTask.model_validate({**base, "materials": [draft, draft]})


def test_repository_scope_interface_rejects_foreign_reference():
    require_owned_refs({"m1"}, {"m1", "m2"})
    with pytest.raises(DomainError) as info:
        require_owned_refs({"m3"}, {"m1", "m2"})
    assert info.value.detail().code == "SCOPE_DENIED"


def test_brief_scope_checks_owned_material_and_disabled_route():
    brief = s.Brief.model_validate(copy.deepcopy(next(case["payload"]["data"] for case in CASES if case["id"] == "operator_valid")))
    validate_brief_scope(brief, material_kinds={"mat1": "source_text"}, existing_segment_ids=set())
    with pytest.raises(DomainError) as info:
        validate_brief_scope(brief, material_kinds={"other": "source_text"}, existing_segment_ids=set())
    assert info.value.code == "SCOPE_DENIED"
    research = brief.model_copy(update={"route": ["research", "draft"]})
    with pytest.raises(DomainError, match="disabled"):
        validate_brief_scope(research, material_kinds={"mat1": "source_text"}, existing_segment_ids=set())


def test_audience_future_segment_rejected():
    event = s.AudienceEvent(segment_id="s2", action="exit", understanding="", question=None, reaction="", interactions=[], comment_text=None)
    with pytest.raises(DomainError) as info:
        validate_audience_scope(event, current_segment_id="s1", visible_segment_ids={"s1"})
    assert info.value.code == "SCOPE_DENIED"


def test_candidate_source_refs_reject_foreign_material():
    candidate = s.ContentCandidate(titles=[], cover_copy=None, segments=[s.Segment(segment_id="s1", kind="body", text="正文", source_refs=["foreign"])])
    with pytest.raises(DomainError) as info:
        validate_candidate_scope(candidate, allowed_material_ids={"own"})
    assert info.value.code == "SCOPE_DENIED"


def test_persisted_enums_match_contract_literals():
    for enum, literal in [(states.TaskState, s.TaskState), (states.RunState, s.RunState), (states.PreviewState, s.PreviewState)]:
        assert {item.value for item in enum} == set(get_args(literal))


def test_calendar_invalid_but_regex_matching_timestamp_rejected():
    with pytest.raises(ValidationError):
        s.Opportunity.model_validate({"id": "o1", "angle": "x", "audience_problem": "x", "account_fit": "x", "source_refs": [], "evidence_date": "2026-02-30T00:00:00Z", "hypothesis": "x"})


def test_revision_metadata_and_reference_exclusivity():
    base = {"finding_id": None, "issue_id": "RULE_COVER", "old_segment_id": "cover", "new_segment_id": "cover", "change": "metadata_update", "reason": "补齐封面"}
    s.Change.model_validate(base)
    both = {**base, "finding_id": "f1"}
    with pytest.raises(ValidationError):
        s.Change.model_validate(both)
    illegal = {**base, "change": "replace"}
    with pytest.raises(ValidationError):
        s.Change.model_validate(illegal)
