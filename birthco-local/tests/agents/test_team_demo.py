"""End-to-end handoffs are fixtures, never real approvals or provider calls."""
import json
from pathlib import Path
import socket

import pytest
from backend.agents.director import DirectorInput
from backend.agents.editorial_reviewer import ReviewInput
from backend.domain.hashing import sha256_json
from backend.domain.schemas import CreateTask
from backend.simulation.audience_session import AudienceSimulationInput
from backend.simulation.analysis_data import AnalystInput
from tools.demo_team import DemoInput, run_demo


@pytest.fixture
def source():
    path = Path(__file__).resolve().parents[2] / "examples/team-demo.json"
    return DemoInput.model_validate_json(path.read_text(encoding="utf-8"))


def read(folder, name):
    return json.loads((folder / name).read_text(encoding="utf-8"))


def test_all_six_handoffs_are_bound_and_offline(tmp_path, source, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network/provider access is forbidden in the demo")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    from backend.adapters.model.qwen import QwenAdapter
    monkeypatch.setattr(QwenAdapter, "__init__", forbidden)
    original = source.model_dump(mode="json")
    folder = tmp_path / "run"
    manifest = run_demo(source, folder, acknowledge_mock=True)
    assert manifest["status"] == "mock_demo_completed"
    assert manifest["provider_calls"] == 0
    assert manifest["real_user_confirmed"] is False
    assert manifest["editorial_quality_passed"] is False
    assert manifest["real_workflow_complete"] is False
    assert source.model_dump(mode="json") == original
    for name, schema in (("04-director-input.json", DirectorInput),
                         ("05-reviewer-input.json", ReviewInput),
                         ("06-audience-input.json", AudienceSimulationInput),
                         ("07-analyst-input.json", AnalystInput)):
        schema.model_validate(read(folder, name))
    director = read(folder, "04-director-output.json")
    reviewer = read(folder, "05-reviewer-output.json")
    viewer_input = read(folder, "06-audience-input.json")
    viewer = read(folder, "06-audience-output.json")
    analyst = read(folder, "07-analyst-output.json")
    assert reviewer["envelope"]["data"]["overall"] == "needs_input"
    assert reviewer["envelope"]["status"] == "needs_input"
    assert director["content_hash"] == reviewer["content_hash"] == viewer["content_hash"] == analyst["content_hash"]
    assert viewer["input_hash"] == sha256_json(viewer_input)
    assert viewer["calls_attempted"] == 4
    assert analyst["metrics"]["N"] == 2
    assert analyst["metrics"]["exited"] == 2  # predefined fixture, not a diagnosis
    assert len(manifest["artifacts"]) == 15


def test_acknowledgement_and_no_overwrite(tmp_path, source):
    folder = tmp_path / "run"
    with pytest.raises(ValueError):
        run_demo(source, folder, acknowledge_mock=False)
    assert not folder.exists()
    run_demo(source, folder, acknowledge_mock=True)
    before = (folder / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        run_demo(source, folder, acknowledge_mock=True)
    assert (folder / "manifest.json").read_bytes() == before


def test_missing_materials_stops_before_selection(tmp_path, source):
    source.task = CreateTask.model_validate(source.task.model_dump(mode="python") | {"materials": []})
    folder = tmp_path / "missing"
    result = run_demo(source, folder, acknowledge_mock=True)
    assert result["status"] == "needs_input"
    assert (folder / "02-scout-output.json").exists()
    assert not (folder / "04-director-input.json").exists()


def test_invalid_selection_stops(tmp_path, source):
    source.selected_opportunity_id = "unknown"
    folder = tmp_path / "selection"
    result = run_demo(source, folder, acknowledge_mock=True)
    assert result["status"] == "needs_input"
    assert not (folder / "03-selected-operator-input.json").exists()


def test_rule_failure_never_reaches_viewers(tmp_path, source):
    source.task = CreateTask.model_validate(source.task.model_dump(mode="json") | {"length_rule": {"maximum": 1}})
    folder = tmp_path / "rules"
    result = run_demo(source, folder, acknowledge_mock=True)
    assert result["next_action"] == "repair_content_before_viewer_demo"
    assert not read(folder, "05-reviewer-output.json")["rule_report"]["passed"]
    assert not (folder / "06-audience-input.json").exists()


def test_budget_preserves_incomplete_and_zero_event_sessions(tmp_path, source):
    source.max_calls = 1
    folder = tmp_path / "budget"
    result = run_demo(source, folder, acknowledge_mock=True)
    assert result["status"] == "mock_demo_incomplete"
    metrics = read(folder, "07-analyst-output.json")["metrics"]
    assert (metrics["N"], metrics["S"], metrics["U"], metrics["Z"]) == (2, 1, 2, 1)


def test_account_and_mode_restrictions(source):
    data = source.model_dump(mode="json")
    with pytest.raises(ValueError):
        DemoInput.model_validate(data | {"mode": "live"})
    with pytest.raises(ValueError):
        DemoInput.model_validate(data | {"account": data["account"] | {"account_id": "other"}})


def test_pr_template_preserves_customer_requirements():
    path = Path(__file__).resolve().parents[2] / "examples/pr-operator-task.json"
    from backend.agents.operator import OperatorAgent
    task = CreateTask.model_validate(json.loads(path.read_text(encoding="utf-8"))["task"])
    result = OperatorAgent().run(task)
    assert result.envelope.data.requirements == task.requirements
    assert result.envelope.data.objective == task.objective
    assert result.as_dict()["requires_user_confirmation"] is True
