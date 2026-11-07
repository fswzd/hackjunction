"""Mock-only handoff example. Not a production runner or approval mechanism."""
import argparse
import json
from pathlib import Path
import sys
from typing import Literal
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pydantic import Field, model_validator
from backend.agents.operator import OperatorAgent, material_snapshot
from backend.agents.scout import ScoutAgent, ScoutInput, ScoutAccount
from backend.agents.director import ContentDirectorAgent, DirectorInput
from backend.agents.editorial_reviewer import EditorialReviewerAgent, ReviewInput
from backend.agents.analyst import AnalystAgent
from backend.domain.schemas import Model, CreateTask, Persona, Id, ContentCandidate
from backend.domain.hashing import brief_hash
from backend.domain.errors import DomainError
from backend.simulation.audience_session import AudienceSimulator, AudienceSimulationInput
from backend.simulation.analysis_data import AnalystInput


class DemoInput(Model):
    mode: Literal["mock"]
    task: CreateTask
    account: ScoutAccount
    selected_opportunity_id: Id
    personas: list[Persona] = Field(min_length=1, max_length=6)
    max_calls: int = Field(default=6, ge=1, le=48)
    mock_exit_after: int | None = Field(default=None, ge=0, le=7)

    @model_validator(mode="after")
    def demo_scope(self):
        if self.task.input_mode != "idea":
            raise ValueError("this demonstration supports new ideas only")
        if self.task.account_id != self.account.account_id:
            raise ValueError("task and account must match")
        return self


def run_demo(source: DemoInput, output_dir: Path, *, acknowledge_mock: bool):
    if acknowledge_mock is not True:
        raise ValueError("explicit Mock demonstration acknowledgement is required")
    # Validate again in case a Python caller used model_copy without validation.
    source = DemoInput.model_validate(source.model_dump(mode="python"))
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "mode": "mock", "demo_only": True, "status": "running",
        "provider_calls": 0, "real_user_confirmed": False,
        "editorial_quality_passed": False, "real_workflow_complete": False,
        "decision_policy": "Preselected topic and confirmed=true inputs are demonstration placeholders only. Mock review is never a semantic pass.",
        "artifacts": [], "next_action": "inspect_saved_files",
    }

    def save(name, value):
        text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        (output_dir / name).write_text(text, encoding="utf-8")
        manifest["artifacts"].append(name)

    def finish(status, next_action):
        manifest.update(status=status, next_action=next_action)
        (output_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output_dir / "请先读我.md").write_text(
            "# 六角色 Mock 交接演示\n\n"
            "此目录只有离线模拟，模型接口请求数为 0。\n\n"
            "01 运营官整理 → 02 Scout给选题 → 03 按预选编号生成新的待确认任务书 → "
            "04 导演写模板 → 05 独立审稿 → 06 模拟观众 → 07 分析师。\n\n"
            "confirmed=true 是演示占位，不是已取得真实用户确认。05 Mock审稿不能检查语义，"
            "返回 needs_input；演示继续运行06/07只为检查文件交接，绝不代表审核通过。"
            "预设退出不是内容缺陷或真实读者反馈。\n\n"
            f"演示状态：{status}；下一步：{next_action}。\n\n"
            "真实工作需要人工选题、确认需求、独立审稿与选择修改建议；"
            "正式持久化调度、归属校验、预算账本和故障恢复尚未集成。\n",
            encoding="utf-8")
        return manifest

    save("00-demo-input.json", source.model_dump(mode="json"))
    try:
        save("01-operator-input.json", {"task": source.task.model_dump(mode="json")})
        proposal = OperatorAgent().run(source.task)
        save("01-operator-output.json", proposal.as_dict())
        if proposal.envelope.status != "ok":
            return finish("needs_input", "resolve_operator_questions")
        materials = material_snapshot(source.task)
        scout = ScoutInput(research_requested=True, account=source.account, brief=proposal.envelope.data,
            materials=[{k: m[k] for k in ("material_id", "kind", "label", "text", "source_url")} |
                       {"authorized": True} for m in materials])
        save("02-scout-input.json", scout.model_dump(mode="json"))
        opportunities = ScoutAgent().run(scout)
        save("02-scout-output.json", opportunities.as_dict())
        if opportunities.envelope.status != "ok":
            return finish("needs_input", "supply_authorized_research_materials")
        selected = next((o for o in opportunities.envelope.data.opportunities
                         if o.id == source.selected_opportunity_id), None)
        if selected is None:
            return finish("needs_input", "select_an_existing_opportunity_in_a_new_demo_request")
        # Make a fresh task; the original user objective remains in 00/01.
        chosen_task = CreateTask.model_validate(source.task.model_dump(mode="python") | {"objective": selected.angle})
        save("03-selected-operator-input.json", {"task": chosen_task.model_dump(mode="json")})
        chosen = OperatorAgent().run(chosen_task)
        save("03-selected-operator-output.json", chosen.as_dict())
        if chosen.envelope.status != "ok":
            return finish("needs_input", "resolve_selected_brief_questions")
        brief = chosen.envelope.data
        rules = {"rule_version": "content-rules-v1", "title_count": 3, "max_body_characters": 20000}
        content_materials = [{k: m[k] for k in ("material_id", "kind", "label", "text")} for m in materials]
        director = DirectorInput(confirmed=True, brief=brief, brief_hash=brief_hash(brief, rules),
            frozen_rules=rules, style=chosen.style, materials=content_materials,
            reserved_segment_ids=["s_" + uuid4().hex])
        save("04-director-input.json", director.model_dump(mode="json"))
        candidate = ContentDirectorAgent().run(director)
        save("04-director-output.json", candidate.as_dict())
        if candidate.envelope.status != "ok" or candidate.envelope.data is None:
            return finish("needs_input", "resolve_director_questions_or_errors")
        content = ContentCandidate.model_validate(candidate.envelope.data.model_dump(mode="json"))
        review = ReviewInput(confirmed=True, version_id=candidate.version_id,
            content_hash=candidate.rule_report.content_hash, brief=brief, content=content, materials=content_materials)
        save("05-reviewer-input.json", review.model_dump(mode="json"))
        reviewed = EditorialReviewerAgent().run(review)
        save("05-reviewer-output.json", reviewed.as_dict())
        if not reviewed.rule_report.passed:
            return finish("needs_input", "repair_content_before_viewer_demo")
        # Deliberately unreviewed fixture. This bypass exists ONLY in this Mock-only CLI.
        audience = AudienceSimulationInput.model_validate({"confirmed": True, "version_id": candidate.version_id,
            "content_hash": candidate.rule_report.content_hash, "content": content.model_dump(mode="json"),
            "personas": [p.model_dump(mode="json") for p in source.personas],
            "max_segments": 8, "max_calls": source.max_calls, "max_active_seconds": 1200})
        save("06-audience-input.json", audience.model_dump(mode="json"))
        simulation = AudienceSimulator(mock_exit_after=source.mock_exit_after).run(audience)
        save("06-audience-output.json", simulation)
        analyst = AnalystInput(analysis_requested=True, source=audience, simulation=simulation)
        save("07-analyst-input.json", analyst.model_dump(mode="json"))
        analyzed = AnalystAgent().run(analyst)
        save("07-analyst-output.json", analyzed.as_dict())
        complete = simulation["status"] == "COMPLETED" and analyzed.analysis_status == "completed"
        return finish("mock_demo_completed" if complete else "mock_demo_incomplete",
                      "inspect_handoffs_and_unpassed_mock_review")
    except (DomainError, ValueError):
        # Keep partial handoffs without echoing user materials or provider errors.
        return finish("failed", "inspect_last_saved_stage_and_correct_input_in_a_new_directory")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True, help="A new directory; never overwrites an earlier run")
    parser.add_argument("--confirm-mock-demo", action="store_true", required=True,
                        help="Acknowledge fixture decisions and unreviewed content; no real approvals")
    args = parser.parse_args()
    if args.input.stat().st_size > 1048576:
        parser.error("input exceeds 1 MiB")
    source = DemoInput.model_validate_json(args.input.read_text(encoding="utf-8"))
    result = run_demo(source, args.output_dir, acknowledge_mock=args.confirm_mock_demo)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "mock_demo_completed" else 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError):
        print("Check the Mock input and choose a new output directory. No provider request was made.", file=sys.stderr)
        raise SystemExit(2)
