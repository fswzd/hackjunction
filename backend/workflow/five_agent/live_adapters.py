"""Join the five specialist entries to the workflow's scoped references."""
from __future__ import annotations

from contextlib import contextmanager
from functools import cached_property

from backend.adapters.model.factory import create_live_adapter, live_config_report, live_model_id
from backend.adapters.model.protocol import ModelUsage
from backend.adapters.orch_bridge import OperatorTeamAdapter, BridgeUnknownOutcome
from backend.agents import analyst, director, editorial_reviewer, operator, scout
from backend.agents.analyst import AnalystAgent
from backend.agents.output_contract import prompt_schema_fingerprint
from backend.agents.director import ContentDirectorAgent, DirectorInput, WorkflowRevisionInput
from backend.agents.editorial_reviewer import EditorialReviewerAgent, ReviewInput
from backend.agents.scout import ScoutAgent, ScoutInput
from backend.domain.errors import DomainError as ComponentError
from backend.domain.hashing import brief_hash, content_hash
from backend.domain.schemas import Analysis, Brief, ContentCandidate, EditorialReview, EditScope, Envelope, Issue, OpportunitySet, Revision
from backend.simulation.analysis_data import PreviewAnalysisInput, summarize_sessions

from .adapters import AgentUnavailableError, UnknownResult
from .contracts import AgentResult, Usage
from .program import normalized_sessions, project_metrics, run_rules
from .projection import visible_segments
from .repository import DomainError, object_hash


@contextmanager
def model_provider(role):
    try:
        adapter = create_live_adapter(role)
        model = live_model_id(role)
    except (OSError, ValueError):
        raise AgentUnavailableError(f"Configure the model for {role}") from None
    with adapter:
        yield adapter, model


class ObservedModel:
    def __init__(self, adapter):
        self.adapter = adapter
        self.sent = False
        self.usage = ModelUsage(total=0)

    def complete(self, request):
        self.sent = True
        self.usage = ModelUsage()
        try:
            response = self.adapter.complete(request)
            self.usage = response.usage
        except Exception:
            raise UnknownResult() from None
        return response


class ScopedInput:
    def __init__(self, repo, call):
        self.repo = repo
        self.call = call
        self.task_id = call.context.task_id
        self.task = repo.get_task(self.task_id)
        run = repo.get_run(call.context.run_id)
        if self.task["account_id"] != call.context.account_id or run["task_id"] != self.task_id:
            raise DomainError("workflow task scope differs", "SCOPE_DENIED")

    @cached_property
    def materials(self):
        return {m["id"]: m for m in self.repo.list_materials(self.task_id)}

    def material(self, ref):
        row = self.materials[ref["id"]]
        if object_hash({"text": row["text"]}) != ref["sha256"]:
            raise DomainError("material fingerprint changed", "CONDITIONS_MISMATCH")
        return row

    def artifact(self, ref, kind):
        row = self.repo.get_artifact(ref["id"])
        if row["task_id"] != self.task_id or row["kind"] != kind:
            raise DomainError("artifact outside action scope", "SCOPE_DENIED")
        if object_hash(row["payload"]) != ref["sha256"]:
            raise DomainError("artifact fingerprint changed", "CONDITIONS_MISMATCH")
        return row

    def version(self, ref):
        row = self.repo.get_version(ref["id"])
        if row["task_id"] != self.task_id or row["content_hash"] != ref["sha256"]:
            raise DomainError("version outside frozen scope", "SCOPE_DENIED")
        return row

    def brief(self):
        ref = self.call.input["brief_ref"]
        if ref["task_id"] != self.task_id:
            raise DomainError("brief outside task scope", "SCOPE_DENIED")
        row = self.repo.get_brief(self.task_id, ref["brief_version"])
        if not row["confirmed_at"] or row["brief_hash"] != ref["brief_hash"]:
            raise DomainError("brief is not confirmed at this fingerprint", "ORIGIN_DENIED")
        return Brief.model_validate(row["payload"])

    def material_inputs(self, refs):
        return [self.project_material(self.material(ref)) for ref in refs]

    @staticmethod
    def project_material(row):
        kind = row["kind"] if row["kind"] in {"existing_draft", "user_supplied_experience"} else "source_text"
        return {"material_id": row["id"], "kind": kind, "label": row["id"], "text": row["text"]}


def _usage(usage):
    return Usage.unknown() if usage.total is None else Usage.known(usage.total)


def _result(call, status, usage, *, data=None, questions=(), issues=()):
    return AgentResult(call.request_id, call.agent_id, call.action, status, data,
                       list(questions), list(issues), _usage(usage)).to_dict()


def _error(call, code, usage):
    return _result(call, "error", usage, issues=[{
        "id": code, "severity": "blocking", "location": call.action,
        "reason": "本步骤未能完成校验或模型调用",
        "requested_change": "核对冻结资料与调用诊断后再显式发起请求",
    }])


def _envelope(call, result):
    env = result.envelope
    return _result(call, env.status, result.usage,
                   data=env.data.model_dump(mode="json") if env.status == "ok" else None,
                   questions=[q.model_dump(mode="json") for q in env.questions],
                   issues=[i.model_dump(mode="json") for i in env.issues])


def _content(row):
    payload = row["payload"]
    return ContentCandidate.model_validate({key: payload[key] for key in ("titles", "cover_copy", "segments")
                                            if key in payload})


RULES = {"rule_version": "content-rules-v1", "title_count": 3, "max_body_characters": 20000}


class ProductionAdapter:
    mode = "live"
    single_attempt = True

    def __init__(self, repo, provider=model_provider):
        self.repo = repo
        self.provider = provider

    def replay_binding(self, action, task_id, role):
        task = self.repo.get_task(task_id)["payload"]
        config = live_config_report(role) if self.provider is model_provider else {}
        return object_hash({
            "prompt": self.prompt_fingerprint(action),
            "model": config.get("model_id"), "endpoint": config.get("base_url"),
            "fields": {key: task.get(key) for key in ("audience", "platform", "style", "positioning")},
            "material_kinds": [(row["id"], row["kind"]) for row in self.repo.list_materials(task_id)]
            if action != "diagnose_preview" else [],
        })

    @staticmethod
    def prompt_fingerprint(action):
        system, schema = {
            "prepare_brief": (operator.SYSTEM, Brief),
            "capture_opportunities": (scout.SYSTEM, OpportunitySet),
            "draft": (director.SYSTEM, ContentCandidate),
            "revise": (director.SYSTEM, Revision),
            "assess_content": (editorial_reviewer.SYSTEM, EditorialReview),
            "diagnose_preview": (analyst.SYSTEM, Analysis),
        }[action]
        return prompt_schema_fingerprint(system, Envelope[schema])

    def invoke(self, call):
        tracker = None
        try:
            scoped = ScopedInput(self.repo, call)
            with self.provider(call.agent_id) as (transport, model_id):
                tracker = ObservedModel(transport)
                handler = getattr(self, "_" + call.action)
                return handler(scoped, tracker, model_id)
        except (BridgeUnknownOutcome, UnknownResult):
            raise UnknownResult() from None
        except (ComponentError, DomainError) as exc:
            if exc.code == "INTERRUPTED":
                raise UnknownResult() from None
            return _error(call, exc.code, tracker.usage if tracker else ModelUsage(total=0))
        except (ValueError, KeyError):
            return _error(call, "SCHEMA_INVALID", tracker.usage if tracker else ModelUsage(total=0))
        except AgentUnavailableError:
            raise
        except Exception:
            if tracker is not None and tracker.sent:
                raise UnknownResult() from None
            return _error(call, "MODEL_UNAVAILABLE", ModelUsage(total=0))

    def _prepare_brief(self, scoped, model, model_id):
        call = scoped.call
        ref = call.input.get("selected_opportunity_ref")
        if ref:
            opportunity = scoped.artifact(ref, "opportunity")["payload"]
            call = type(call)(call.request_id, call.agent_id, call.action, call.context,
                {**call.input, "user_input": f"已选选题：{opportunity['angle']}\n{call.input['user_input']}"}, call.contract_version)
        return OperatorTeamAdapter(resolve_material=scoped.material, model_adapter=model,
                                   mode="live", model_id=model_id).invoke(call)

    def _capture_opportunities(self, scoped, model, model_id):
        call = scoped.call
        goal = call.input["goal"]
        task = scoped.task["payload"]
        materials = scoped.material_inputs(call.input["material_refs"])
        audience = task.get("audience") or "任务指定的目标读者"
        style = task.get("style") or "依据任务要求"
        brief = Brief(input_mode="idea", objective=goal, audience=audience,
                      platform=task.get("platform") or "generic", format="text", core_promise=goal,
                      requirements=[{"id": "scope", "text": "根据已有授权材料给出选题"}],
                      material_ids=[m["material_id"] for m in materials], open_questions=[],
                      route=["research"], length_rule={}, edit_scope=None)
        snapshot = ScoutInput(research_requested=True,
            account={"account_id": scoped.task["account_id"], "positioning": task.get("positioning") or goal,
                     "audience": audience, "style": style}, brief=brief,
            materials=[{**m, "authorized": True, "source_url": None} for m in materials])
        return _envelope(call, ScoutAgent(model, mode="live", model_id=model_id).run(snapshot))

    def _director(self, scoped, model, model_id, brief, materials, **revision):
        used = {m["material_id"] for m in materials}
        if revision:
            used |= {s.segment_id for s in revision["base_content"].segments}
        # Deterministic reservations bind retries to this frozen step.
        reserved = ["s_" + object_hash({"input": scoped.call.context.input_hash, "ordinal": i})[:24]
                    for i in range(32)]
        cls = WorkflowRevisionInput if revision else DirectorInput
        snapshot = cls(confirmed=True, brief=brief, brief_hash=brief_hash(brief, RULES),
            frozen_rules=RULES, style=scoped.task["payload"].get("style") or "遵循任务书要求",
            materials=materials, reserved_segment_ids=[sid for sid in reserved if sid not in used],
            **revision)
        return ContentDirectorAgent(model, mode="live", model_id=model_id).run(snapshot)

    def _draft(self, scoped, model, model_id):
        brief = scoped.brief()
        if brief.input_mode != "idea":
            return _result(scoped.call, "needs_input", ModelUsage(total=0), questions=[{
                "id": "base_version", "question": "请先选择已入库的旧稿版本，再发起定向修订。",
                "reason": "按已确认版本的范围修改，保护未授权段落",
            }])
        materials = scoped.material_inputs(scoped.call.input["material_refs"])
        return _envelope(scoped.call, self._director(scoped, model, model_id, brief, materials))

    def _revise(self, scoped, model, model_id):
        call = scoped.call
        brief = scoped.brief()
        base = scoped.version(call.input["base_version_ref"])
        request = scoped.artifact(call.input["revision_request_ref"], "revision_request")["payload"]
        if request["base_version_id"] != base["id"] or request["base_content_hash"] != base["content_hash"]:
            raise DomainError("revision request is for another version", "SCOPE_DENIED")
        candidate = _content(base)
        finding_mode = request["kind"] == "finding_repair"
        if not finding_mode and request["kind"] != "issue_repair":
            raise DomainError("unknown revision request", "SCHEMA_INVALID")
        targets = request["finding_segment"] if finding_mode else request["issue_locations"]
        if finding_mode:
            analysis = self.repo.get_artifact(request["analysis_id"])
            if analysis["task_id"] != scoped.task_id or analysis["kind"] != "analysis":
                raise DomainError("analysis outside revision scope", "SCOPE_DENIED")
            if request.get("analysis_sha256", object_hash(analysis["payload"])) != object_hash(analysis["payload"]):
                raise DomainError("selected analysis changed", "CONDITIONS_MISMATCH")
            findings = {f["id"]: f for f in analysis["payload"]["findings"]}
            if any(findings[key]["segment_id"] != location for key, location in targets.items()):
                raise DomainError("selected findings do not match the authorized locations", "SCOPE_DENIED")
            details = {key: findings[key]["suggested_edit"] for key in targets}
        else:
            details = request.get("issue_details", {})
        sources_by_location = {}
        for source_id, location in targets.items():
            if location == "cover_v1":
                location = "cover"
            sources_by_location.setdefault(location, []).append(source_id)
        segment_ids = [s.segment_id for s in candidate.segments]
        edited = [sid for sid in segment_ids if sid in sources_by_location]
        scope = EditScope(target_segment_ids=edited, preserve_segment_ids=[sid for sid in segment_ids if sid not in edited],
            allow_title_change=request["allow_title_change"], allow_cover_change=request["allow_cover_change"])
        instructions = request.get("instructions") or "按已选择的审稿或试映问题修改该位置"
        issues = []
        for loc, source_ids in sources_by_location.items():
            text = "\n".join([instructions, *(details[sid] for sid in source_ids if details.get(sid))])
            issues.append(Issue(id=source_ids[0], location=loc, severity="blocking",
                                reason="已冻结的改稿范围", requested_change=text))
        # The original confirmed requirements remain intact. The revision gate defines edit scope.
        brief = Brief.model_validate({**brief.model_dump(), "input_mode": "existing_draft", "edit_scope": scope.model_dump()})
        materials = [scoped.project_material(scoped.materials[mid]) for mid in brief.material_ids]
        outcome = _envelope(call, self._director(scoped, model, model_id, brief, materials,
            base_version_id=base["id"], base_content_hash=content_hash(candidate), base_content=candidate, edit_requests=issues))
        if finding_mode and outcome["status"] == "ok":
            for change in outcome["data"]["change_log"]:
                change["finding_id"], change["issue_id"] = change["issue_id"], None
        return outcome

    def _assess_content(self, scoped, model, model_id):
        call = scoped.call
        brief = scoped.brief()
        row = scoped.version(call.input["version_ref"])
        report = scoped.artifact(call.input["rule_report_ref"], "rule_report")["payload"]
        if report != run_rules(row["id"], row["payload"], brief.length_rule.model_dump()):
            raise DomainError("review rule report differs from the frozen candidate", "CONDITIONS_MISMATCH")
        content = _content(row)
        snapshot = ReviewInput(confirmed=True, version_id=row["id"], content_hash=content_hash(content),
                              brief=brief, content=content,
                              materials=scoped.material_inputs(call.input["material_refs"]))
        return _envelope(call, EditorialReviewerAgent(model, mode="live", model_id=model_id).run(snapshot))

    def _diagnose_preview(self, scoped, model, model_id):
        call = scoped.call
        artifact = scoped.artifact(call.input["preview_ref"], "preview")
        if artifact["run_id"] != call.context.run_id:
            raise DomainError("preview belongs to another run", "SCOPE_DENIED")
        preview = artifact["payload"]
        row = scoped.version(call.input["version_ref"])
        if preview["version_id"] != row["id"] or preview["content_hash"] != row["content_hash"]:
            raise DomainError("preview and content version differ", "CONDITIONS_MISMATCH")
        content = _content(row)
        segments = visible_segments(row["payload"])
        personas = preview["scenario"]["personas"]
        sessions = normalized_sessions(self.repo.sessions_for_preview(artifact["id"]),
                                       self.repo.preview_events(artifact["id"]))
        order = {p["id"]: i for i, p in enumerate(personas)}
        sessions.sort(key=lambda s: order[s["persona_id"]])
        snapshot = PreviewAnalysisInput(version_id=row["id"], content_hash=content_hash(content),
            content=content.model_dump(), personas=personas, segments=segments, sessions=sessions)
        metrics = project_metrics(summarize_sessions(sessions, [s["segment_id"] for s in segments]))
        metrics_art = scoped.artifact(call.input["metrics_ref"], "metrics")
        if metrics_art["run_id"] != artifact["run_id"] or metrics_art["payload"] != metrics:
            raise DomainError("preview metrics disagree with persisted observations", "CONDITIONS_MISMATCH")
        result = AnalystAgent(model, mode="live", model_id=model_id).run_preview(snapshot)
        if result.analysis_status == "interrupted":
            raise UnknownResult()
        if result.envelope is None:
            return _error(call, result.error.code, result.usage)
        return _envelope(call, result)
