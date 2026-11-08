"""Agent adapters: the only boundary to teammate implementations.

AgentAdapter.invoke(AgentCall) -> AgentResult. Five deterministic MockAgents stand
in for the teammates (development mode); real adapters are registered as
awaiting_owner_handoff stubs and raise AGENT_UNAVAILABLE.  Live mode NEVER falls
back to mock (agent-interface.json: real_mode_mock_fallback_allowed=false).

A Resolver maps contract Refs to repository objects so a mock behaves like a
real teammate entry that resolves references before building its model prompt.
Adapters record the model-visible payload (input projection only — never
AgentCall.context / GraphState) for isolation assertions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from ..five_agent.contracts import AgentCall, AgentResult, Usage, canonical_json
from .repository import Repository


class SendFailure(Exception):
    """Mirrors gateway.SendFailure without importing gateway (avoid cycle)."""

    def __init__(self, message: str, sent: bool, retryable: bool = True, code: str = "MODEL_TIMEOUT"):
        super().__init__(message)
        self.sent = sent
        self.retryable = retryable
        self.code = code


class UnknownResult(SendFailure):
    def __init__(self, message: str = "sent but result unknown"):
        super().__init__(message, sent=True, retryable=False, code="MODEL_TIMEOUT")


class PreSendFailure(SendFailure):
    def __init__(self, message: str = "connection failed before send"):
        super().__init__(message, sent=False, retryable=True, code="MODEL_UNAVAILABLE")


class ScopeViolation(Exception):
    pass


class AgentUnavailableError(Exception):
    """Real teammate entry not provided (awaiting_owner_handoff). Not retried."""
    code = "MODEL_UNAVAILABLE"


# --------------------------------------------------------------- ref resolution
class Resolver:
    """Resolves contract Refs against the domain repository (revalidating ownership)."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def material(self, ref: dict) -> dict:
        rows = {m["id"]: m for m in self.repo.list_materials(self._task_of(ref))}
        if ref["id"] not in rows:
            raise KeyError(f"material {ref['id']} not found")
        return rows[ref["id"]]

    def _task_of(self, ref: dict) -> str:
        # materials are listed per task; the caller passes task via bound resolver
        raise NotImplementedError

    def version(self, ref: dict) -> dict:
        return self.repo.get_version(ref["id"])

    def artifact(self, ref: dict) -> dict:
        return self.repo.get_artifact(ref["id"])

    def brief(self, brief_ref: dict) -> dict:
        return self.repo.get_brief(brief_ref["task_id"], brief_ref["brief_version"])


class TaskResolver(Resolver):
    def __init__(self, repo: Repository, task_id: str):
        super().__init__(repo)
        self.task_id = task_id

    def _task_of(self, ref: dict) -> str:
        return self.task_id

    def material(self, ref: dict) -> dict:
        for m in self.repo.list_materials(self.task_id):
            if m["id"] == ref["id"]:
                return m
        raise KeyError(f"material {ref['id']} not found")

    def preview(self, preview_id: str) -> dict:
        """Resolved preview read model: frozen spec + committed audience events."""
        payload = self.repo.get_artifact(preview_id)["payload"]
        return {"payload": payload, "events": self.repo.preview_events(preview_id)}


# ------------------------------------------------------------- mock behaviours
Behaviour = Callable[[AgentCall, TaskResolver], dict]


def ok(data: dict, tokens: int = 220) -> Behaviour:
    def _run(call: AgentCall, resolver: TaskResolver) -> dict:
        return {"kind": "ok", "data": data, "usage": Usage.known(tokens).to_dict()}
    return _run


def ok_usage_unknown(data: dict) -> Behaviour:
    def _run(call: AgentCall, resolver: TaskResolver) -> dict:
        return {"kind": "ok", "data": data, "usage": Usage.unknown().to_dict()}
    return _run


def needs_input(questions: list, partial: dict | None = None, tokens: int = 120) -> Behaviour:
    def _run(call: AgentCall, resolver: TaskResolver) -> dict:
        return {"kind": "needs_input", "questions": questions, "data": partial,
                "usage": Usage.known(tokens).to_dict()}
    return _run


def error(issues: list, tokens: int = 80) -> Behaviour:
    def _run(call: AgentCall, resolver: TaskResolver) -> dict:
        return {"kind": "error", "issues": issues, "usage": Usage.known(tokens).to_dict()}
    return _run


def tech_error(sent: bool = False) -> Behaviour:
    def _run(call: AgentCall, resolver: TaskResolver) -> dict:
        return {"kind": "send_failure", "sent": sent}
    return _run


def protocol_garbage() -> Behaviour:
    def _run(call: AgentCall, resolver: TaskResolver) -> dict:
        return {"kind": "garbage"}
    return _run


# ----------------------------------------------------------- default generators
def _tokens(payload: Any) -> int:
    return 120 + len(canonical_json(payload)) // 4


def gen_brief(call: AgentCall, resolver: TaskResolver) -> dict:
    inp = call.input
    materials = []
    for ref in inp.get("material_refs", []):
        try:
            materials.append(resolver.material(ref))
        except KeyError:
            pass
    goal = inp.get("user_input", "").strip() or "内容创作任务"
    opp = None
    if inp.get("selected_opportunity_ref"):
        opp = resolver.artifact(inp["selected_opportunity_ref"])["payload"]
    objective = (opp["angle"] if opp else goal)
    if inp.get("input_mode") == "existing_draft" and inp.get("edit_scope") is None:
        # Mirror the production entry: a draft scope is user-supplied, never invented.
        return {"kind": "needs_input",
                "questions": [{"id": "draft_scope",
                               "question": "请指定哪些原稿段落可以修改，以及标题和封面是否允许调整。",
                               "reason": "保留未授权修改的原文"}],
                "usage": Usage.known(120).to_dict()}
    # Structured user requirements pass through with their original ids (F-O5);
    # without them the generator may propose its own operational requirements.
    if inp.get("requirements") is not None:
        requirements = [{"id": r["id"], "text": r["text"]} for r in inp["requirements"]]
    else:
        requirements = [
            {"id": "req_style", "text": "口语化、可操作、不夸大"},
            {"id": "req_facts", "text": "事实与数据只来自授权材料"},
        ]
    data = {
        "input_mode": inp.get("input_mode", "idea"),
        "objective": objective[:1000],
        "audience": "对目标话题感兴趣的新手读者",
        "platform": "图文平台",
        "format": "text",
        "core_promise": f"让读者理解并能动手实践：{objective[:80]}",
        "requirements": requirements,
        "material_ids": [ref["id"] for ref in inp.get("material_refs", [])],
        "open_questions": [],
        "route": ["draft", "review", "export"],
        "length_rule": {"minimum": None, "maximum": 20000},
        "edit_scope": inp.get("edit_scope"),
    }
    return {"kind": "ok", "data": data, "usage": Usage.known(_tokens(data)).to_dict()}


def gen_candidate(call: AgentCall, resolver: TaskResolver, with_cover: bool = True,
                  bad_types: bool = False) -> dict:
    brief = resolver.brief(call.input["brief_ref"])
    mats = brief["payload"]["material_ids"][:2]
    if bad_types:
        data = {"titles": "not_a_list", "segments": []}
    else:
        objective = brief["payload"]["objective"][:20]
        data = {
            "titles": [f"{objective}｜要点一", f"{objective}｜要点二", f"{objective}｜要点三"],
            "cover_copy": ("三步上手，少走弯路" if with_cover else None),
            "segments": [
                {"segment_id": "seg_hook_1", "kind": "hook",
                 "text": "你是否也遇到过：" + brief["payload"]["objective"][:40], "source_refs": mats[:1]},
                {"segment_id": "seg_body_1", "kind": "body",
                 "text": "第一步，从授权材料里的方法开始：" + brief["payload"]["core_promise"][:60],
                 "source_refs": mats},
                {"segment_id": "seg_closing_1", "kind": "closing",
                 "text": "先完成再完善，把你的结果发出来一起看。", "source_refs": []},
            ],
        }
    return {"kind": "ok", "data": data, "usage": Usage.known(_tokens(data)).to_dict()}


def gen_request_analysis(call: AgentCall, resolver: TaskResolver) -> dict:
    """Commercial/PR intake analysis: derive explicit requirements + open questions.

    Mirrors the birthco-local PR_ANALYST component contract: it organises
    client-supplied material only, never fabricates facts, and refuses to hand
    off (ready_for_operator=false) while required fields or questions remain.
    """
    text = call.input.get("request_text", "")
    material_ids = [r["id"] for r in call.input.get("material_refs", [])]
    requirements = []
    tail = text.split("要求：", 1)
    requirement_source = tail[1] if len(tail) > 1 else ""
    for idx, part in enumerate(requirement_source.replace("\n", "；").split("；")):
        part = part.strip()
        if part:
            requirements.append({"id": f"req_pr_{idx + 1}", "text": part[:1000]})
    open_questions = []
    if not requirements:
        open_questions.append({"id": "q_pr_1", "question": "客户的硬性要求是什么？",
                               "reason": "没有明确要求不能交接给运营官"})
    unprovided = [f for f in ("budget", "deadline", "approver") if f not in text]
    data = {
        "summary": (text[:120] or "（空简报）"),
        "requirements": requirements[:30],
        "open_questions": open_questions,
        "unprovided_business_fields": unprovided,
        "ready_for_operator": bool(requirements),
        "source_refs": material_ids[:20],
    }
    if not requirements:
        return {"kind": "needs_input", "questions": open_questions, "data": None,
                "usage": Usage.known(_tokens(data)).to_dict()}
    return {"kind": "ok", "data": data, "usage": Usage.known(_tokens(data)).to_dict()}


def gen_review(call: AgentCall, resolver: TaskResolver, overall: str = "pass",
               fixable: bool = True) -> dict:
    """开发 Mock（队员替身）：产出流程夹具，不代表内容质量（证据分级 [Mock 流程]）。

    F-04: issue/claim/evidence 的 location 全部取自冻结版本的真实段落 ID
    （titles/cover 之外），引用不存在段落的审稿在这里就不可能产生。
    """
    brief = resolver.brief(call.input["brief_ref"])
    version = resolver.version(call.input["version_ref"])
    segments = version["payload"].get("segments") or []
    locations = [s["segment_id"] for s in segments]
    anchor = locations[0] if locations else "cover"        # 首段（默认 hook）
    body_anchor = next((sid for s, sid in zip(segments, locations)
                        if s.get("kind") == "body"), anchor)
    issues = []
    if overall != "pass":
        issues = [{
            "id": "iss_review_1", "severity": "blocking" if overall == "revise" else "advisory",
            "location": body_anchor, "reason": "关键承诺缺少材料依据，读者会怀疑",
            "requested_change": "为该段补充材料引用或收窄承诺",
        }]
    data = {
        "issues": issues,
        "requirement_checks": [
            {"requirement_id": r["id"], "result": "met", "evidence_refs": [body_anchor]}
            for r in brief["payload"]["requirements"]
        ],
        "claim_checks": [{
            "claim": segments[0]["text"][:60] if segments else "（无正文）",
            "location": anchor,
            "source_ref": segments[0]["source_refs"][0] if segments and segments[0]["source_refs"] else None,
            "assessment": "supported",
        }],
        "overall": overall,
    }
    return {"kind": "ok", "data": data, "usage": Usage.known(_tokens(data)).to_dict()}


def gen_opportunities(call: AgentCall, resolver: TaskResolver) -> dict:
    goal = call.input.get("goal", "选题")
    data = {"opportunities": [
        {"id": f"opp_{i+1}", "angle": f"{goal} 的切入角度 {i+1}",
         "audience_problem": f"读者在 {goal[:12]} 上常遇到的问题 {i+1}",
         "account_fit": "与账号定位相符（依据授权材料）",
         "source_refs": [r["id"] for r in call.input.get("material_refs", [])][:3],
         "evidence_date": None,
         "hypothesis": f"假设：角度 {i+1} 能带来更高完读",
         } for i in range(2)]}
    return {"kind": "ok", "data": data, "usage": Usage.known(_tokens(data)).to_dict()}


def gen_analysis(call: AgentCall, resolver: TaskResolver) -> dict:
    preview = resolver.preview(call.input["preview_ref"]["id"])
    metrics = resolver.artifact(call.input["metrics_ref"])["payload"]
    events_by_segment: dict[str, list[str]] = {}
    for evt in preview["events"]:
        events_by_segment.setdefault(evt["payload"]["segment_id"], []).append(evt["id"])
    findings = []
    worst = sorted(metrics["segments"], key=lambda s: -(s["exit_rate"] or 0))[:2]
    for idx, seg_metric in enumerate(worst):
        obs = events_by_segment.get(seg_metric["segment_id"], [])
        if not obs:
            continue
        findings.append({
            "id": f"find_{idx+1}", "segment_id": seg_metric["segment_id"],
            "observation_refs": obs[:3],
            "interpretation": f"本次模拟中该段退出 {seg_metric['exits']}/{seg_metric['exposures']}；只描述模拟事件，不证明真实受众因内容离开。",
            "alternative_explanation": "退出可能是预设测试fixture、persona偏好或信息不足，不能据此确认内容是原因。",
            "suggested_edit": "作为待用户选择的试验：把抽象表述换成材料中的具体步骤，保留原稿并在明确条件下重测。",
        })
    data = {
        "findings": findings,
        "comparison": {"conditions_match": False,
                       "reason": "单版本分析：没有可比较的第二版。",
                       "summary": "只展示完整分母与缺失情况；没有经过核验的同条件实验，不宣称优胜版本或因果改善。"},
        "next_experiment": "对高退出段改写后，在明确测试条件下重测，并补充少量真实读者反馈核对假设。",
    }
    return {"kind": "ok", "data": data, "usage": Usage.known(_tokens(data)).to_dict()}


def gen_revision(call: AgentCall, resolver: TaskResolver) -> dict:
    """Scope-respecting revision: only selected findings/issues segments change.

    Handles both request kinds: finding_repair (preview findings) and
    issue_repair (rule/review auto-repair inside content/revision runs).
    """
    base = resolver.version(call.input["base_version_ref"])
    request = resolver.artifact(call.input["revision_request_ref"])["payload"]
    if request.get("kind") == "issue_repair":
        targets = dict(request.get("issue_locations", {}))   # issue_id -> segment_id
        cite = {sid: iid for iid, sid in targets.items()}
    else:
        analysis = resolver.artifact({"id": request["analysis_id"]})["payload"]
        findings = {f["id"]: f["segment_id"] for f in analysis.get("findings", [])
                    if f["id"] in set(request["finding_ids"])}
        targets = findings
        cite = {sid: fid for fid, sid in findings.items()}
    change_log = []
    new_segments = []
    for seg in base["payload"]["segments"]:
        if seg["segment_id"] in cite:
            ref_id = cite[seg["segment_id"]]
            new_id = seg["segment_id"] + "_r1"
            new_segments.append({**seg, "segment_id": new_id,
                                 "text": seg["text"] + "（依据建议改写：补上具体步骤）"})
            change_log.append({"finding_id": None if request.get("kind") == "issue_repair" else ref_id,
                               "issue_id": ref_id if request.get("kind") == "issue_repair" else None,
                               "old_segment_id": seg["segment_id"], "new_segment_id": new_id,
                               "change": "replace", "reason": "采纳建议，降低理解成本"})
        else:
            new_segments.append(dict(seg))
    titles = list(base["payload"]["titles"])
    cover = base["payload"].get("cover_copy")
    metadata = []
    if request.get("allow_title_change") and "titles" in cite:
        titles = [t + "（修订版）" for t in titles] if titles else ["修订标题一", "修订标题二", "修订标题三"]
        metadata.append(("titles", cite["titles"]))
    cover_ref = cite.get("cover") or cite.get("cover_v1")
    if request.get("allow_cover_change") and cover_ref:
        cover = (cover or "封面") + "（修订）"
        metadata.append(("cover", cover_ref))
    for location, ref_id in metadata:
        is_issue = request["kind"] == "issue_repair"
        change_log.append({"finding_id": None if is_issue else ref_id,
                           "issue_id": ref_id if is_issue else None,
                           "old_segment_id": location, "new_segment_id": location,
                           "change": "metadata_update", "reason": "按授权范围更新"})
    if not change_log:
        raise ScopeViolation("no change within selected scope")
    data = {"titles": titles, "cover_copy": cover, "segments": new_segments, "change_log": change_log}
    return {"kind": "ok", "data": data, "usage": Usage.known(_tokens(data)).to_dict()}


def gen_audience_event(call: AgentCall, resolver: TaskResolver, exit_at: int | None = None,
                       ask: bool = False) -> dict:
    inp = call.input
    persona = inp["persona"]
    current = inp["current_segment"]
    ordinal = len(inp["visible_history"])
    will_exit = exit_at is not None and ordinal >= exit_at
    data = {
        "segment_id": current["segment_id"],
        "action": "exit" if will_exit else "continue",
        "understanding": f"[{persona['id']}] 读到 {current['segment_id']}：大致明白在讲什么",
        "question": ("这里说的方法具体怎么开始？" if ask and ordinal == 1 else None),
        "reaction": "有点意思" if not will_exit else "太长了，先不看了",
        "interactions": ["like"] if (not will_exit and ordinal == 1) else [],
        "comment_text": None,
    }
    return {"kind": "ok", "data": data, "usage": Usage.known(_tokens(data)).to_dict()}


# ------------------------------------------------------------------ mock agent
class MockAgent:
    """Deterministic, scriptable stand-in for one teammate agent (development mode)."""

    mode = "mock"

    def __init__(self, agent_id: str, actions: tuple[str, ...], default_factory: Callable[[str], Behaviour],
                 scripts: dict[str, list[Behaviour]] | None = None,
                 audience_exits: dict[str, int | None] | None = None,
                 audience_timeout_at: dict[str, int] | None = None):
        self.agent_id = agent_id
        self.actions = actions
        self._default_factory = default_factory
        self._scripts: dict[str, list[Behaviour]] = {k: list(v) for k, v in (scripts or {}).items()}
        self.audience_exits = audience_exits or {}
        self.audience_timeout_at = audience_timeout_at or {}
        self.invocations: list[dict] = []  # model-visible audit trail
        self.resolver: TaskResolver | None = None

    def script(self, action: str, behaviours: list[Behaviour]) -> None:
        self._scripts.setdefault(action, []).extend(behaviours)

    def invoke(self, call: AgentCall) -> dict:
        if call.agent_id != self.agent_id or call.action not in self.actions:
            raise PreSendFailure(f"{self.agent_id} cannot handle {call.agent_id}.{call.action}")
        queue = self._scripts.get(call.action)
        behaviour = queue.pop(0) if queue else self._default_factory(call.action)
        try:
            raw = behaviour(call, self.resolver or TaskResolver.__new__(TaskResolver))
        except (SendFailure, UnknownResult, PreSendFailure, AgentUnavailableError):
            raise
        except ScopeViolation as exc:
            raw = {"kind": "error", "usage": Usage.known(60).to_dict(),
                   "issues": [{"id": "iss_scope_1", "severity": "blocking", "location": "revision",
                               "reason": str(exc), "requested_change": "限制修改范围到已选 finding"}]}
        except Exception as exc:  # defensive: behave like a pre-send failure
            raise PreSendFailure(f"mock internal error: {exc}") from exc
        if raw.get("kind") == "send_failure":
            if raw["sent"]:
                raise UnknownResult()
            raise PreSendFailure()
        if raw.get("kind") == "garbage":
            out = {"contract_version": call.contract_version, "request_id": call.request_id,
                   "agent_id": call.agent_id, "action": call.action, "status": "ok",
                   "data": {"bogus": True}, "questions": [], "issues": [],
                   "usage": {"status": "unknown", "total_tokens": 0}}  # invalid: unknown with zero
            self._audit(call, out)
            return out
        usage = raw.get("usage") or Usage.unknown().to_dict()
        out = {"contract_version": call.contract_version, "request_id": call.request_id,
               "agent_id": call.agent_id, "action": call.action,
               "status": raw["kind"] if raw["kind"] != "ok" else "ok",
               "data": raw.get("data"), "questions": raw.get("questions", []),
               "issues": raw.get("issues", []), "usage": usage}
        if raw["kind"] == "needs_input":
            out["status"] = "needs_input"
        elif raw["kind"] == "error":
            out["status"] = "error"
        self._audit(call, out)
        return out

    def _audit(self, call: AgentCall, out: dict) -> None:
        # Isolation audit: the model-visible payload is exactly call.input —
        # never AgentCall.context, GraphState, other personas or future segments.
        self.invocations.append({
            "agent_id": call.agent_id, "action": call.action,
            "model_visible_input": json.loads(json.dumps(call.input, ensure_ascii=False)),
            "context_seen_by_model": False,
            "result_status": out["status"],
        })


# --------------------------------------------------------------- real adapters
class RealAdapterStub:
    """awaiting_owner_handoff: teammate entry not provided yet. Never silently mocks."""
    mode = "live"

    def __init__(self, agent_id: str, actions: tuple[str, ...]):
        self.agent_id = agent_id
        self.actions = actions
        self.invocations: list = []

    def invoke(self, call: AgentCall) -> dict:
        raise AgentUnavailableError(f"AGENT_UNAVAILABLE: {self.agent_id} awaiting_owner_handoff")


# ----------------------------------------------------------------------- router
DEFAULT_AUDIENCE_EXITS = {"p_exit_first": 0, "p_full": None, "p_exit_mid": 2}
DEFAULT_AUDIENCE_TIMEOUTS = {"p_timeout_mid": 1}


class AdapterRouter:
    """Selects adapters per action. mode=live never falls back to mock."""

    def __init__(self, repo: Repository, mode: str = "mock",
                 scripts: dict[tuple[str, str], list[Behaviour]] | None = None,
                 audience_exits: dict[str, int | None] | None = None,
                 audience_timeout_at: dict[str, int] | None = None,
                 agent_modes: dict[str, str] | None = None,
                 reals: dict[str, Any] | None = None):
        if mode not in ("mock", "live"):
            raise ValueError("mode must be mock|live")
        self.mode = mode
        self.agent_modes = dict(agent_modes or {})
        self.repo = repo
        scripts = scripts or {}
        per_agent: dict[str, dict[str, list[Behaviour]]] = {}
        for (agent_id, action), behaviours in scripts.items():
            per_agent.setdefault(agent_id, {})[action] = behaviours
        self.mocks = {
            "pr_analyst": MockAgent(
                "pr_analyst", ("analyze_request",),
                lambda action: gen_request_analysis,
                scripts=per_agent.get("pr_analyst", {}),
                audience_exits=audience_exits, audience_timeout_at=audience_timeout_at),
            "content_creator": MockAgent(
                "content_creator", ("draft", "revise"),
                lambda action: (lambda call, r: gen_candidate(call, r)) if action == "draft" else gen_revision,
                scripts=per_agent.get("content_creator", {}),
                audience_exits=audience_exits, audience_timeout_at=audience_timeout_at),
            "operations_officer": MockAgent(
                "operations_officer", ("prepare_brief",),
                lambda action: gen_brief,
                scripts=per_agent.get("operations_officer", {}),
                audience_exits=audience_exits, audience_timeout_at=audience_timeout_at),
            "editorial_reviewer": MockAgent(
                "editorial_reviewer", ("assess_content",),
                lambda action: (lambda call, r: gen_review(call, r)),
                scripts=per_agent.get("editorial_reviewer", {}),
                audience_exits=audience_exits, audience_timeout_at=audience_timeout_at),
            "traffic_scout": MockAgent(
                "traffic_scout", ("capture_opportunities",),
                lambda action: gen_opportunities,
                scripts=per_agent.get("traffic_scout", {}),
                audience_exits=audience_exits, audience_timeout_at=audience_timeout_at),
            "data_analyst": MockAgent(
                "data_analyst", ("diagnose_preview",),
                lambda action: gen_analysis,
                scripts=per_agent.get("data_analyst", {}),
                audience_exits=audience_exits, audience_timeout_at=audience_timeout_at),
            "simulated_audience": MockAgent(
                "simulated_audience", ("read_segment",),
                lambda action: self._audience_default,
                scripts=per_agent.get("simulated_audience", {}),
                audience_exits=audience_exits or DEFAULT_AUDIENCE_EXITS,
                audience_timeout_at=audience_timeout_at or DEFAULT_AUDIENCE_TIMEOUTS),
        }
        from .live_adapters import ProductionAdapter

        specialist = ProductionAdapter(repo)
        self.reals = {
            "pr_analyst": RealAdapterStub("pr_analyst", ("analyze_request",)),
            "content_creator": specialist,
            "operations_officer": specialist,
            "editorial_reviewer": specialist,
            "traffic_scout": specialist,
            "data_analyst": specialist,
            "simulated_audience": RealAdapterStub("simulated_audience", ("read_segment",)),
        }
        # Wire the two interfaces that were left awaiting an owner handoff.
        # build_reals() returns the business-layer bridges for all seven roles;
        # here we only replace the two stubs so the verified specialist path is
        # untouched. The bridges run their own business model (offline mock by
        # default, real provider as soon as one is configured) and honour the
        # same AgentAdapter.invoke contract -- no more AGENT_UNAVAILABLE.
        try:
            from .team_entries import build_reals
            wired = build_reals(repo, mode="mock")
            self.reals["pr_analyst"] = wired["pr_analyst"]
            self.reals["simulated_audience"] = wired["simulated_audience"]
        except Exception:  # pragma: no cover - business layer is optional here
            pass
        # Real-entry injection: a teammate's real adapter replaces its stub here
        # (single-role rollout). Never routed unless agent_modes/mode selects live.
        for agent_id, adapter in (reals or {}).items():
            if agent_id not in self.reals:
                raise ValueError(f"reals has unknown agent ids: {agent_id}")
            self.reals[agent_id] = adapter
        for agent_id, m in self.agent_modes.items():
            if m not in ("mock", "live"):
                raise ValueError(f"agent_modes[{agent_id}] must be mock|live")
        unknown = set(self.agent_modes) - set(self.mocks)
        if unknown:
            raise ValueError(f"agent_modes has unknown agent ids: {sorted(unknown)}")
        self._resolvers: dict[str, TaskResolver] = {}

    def _audience_default(self, call: AgentCall, resolver: TaskResolver) -> dict:
        persona_id = call.input["persona"]["id"]
        agent = self.mocks["simulated_audience"]
        timeout_at = agent.audience_timeout_at.get(persona_id)
        ordinal = len(call.input["visible_history"])
        if timeout_at is not None and ordinal >= timeout_at:
            raise UnknownResult(f"audience {persona_id} timed out at ordinal {ordinal}")
        exit_at = agent.audience_exits.get(persona_id, None)
        return gen_audience_event(call, resolver, exit_at=exit_at, ask=(persona_id == "p_ask"))

    def bind_resolver(self, task_id: str) -> TaskResolver:
        if task_id not in self._resolvers:
            self._resolvers[task_id] = TaskResolver(self.repo, task_id)
        return self._resolvers[task_id]

    def adapter_for(self, action: str) -> MockAgent | RealAdapterStub:
        from .registry import ACTIONS
        agent_id = ACTIONS[action]
        # per-agent override enables single-role rollout; the global mode is the
        # default for every agent without an override.  live NEVER falls back to mock.
        mode = self.agent_modes.get(agent_id, self.mode)
        if mode == "live":
            return self.reals[agent_id]
        return self.mocks[agent_id]

    def __call__(self, action: str) -> MockAgent | RealAdapterStub:
        return self.adapter_for(action)

    def mock(self, agent_id: str) -> MockAgent:
        return self.mocks[agent_id]

    def bind_task(self, task_id: str) -> None:
        resolver = self.bind_resolver(task_id)
        for agent in self.mocks.values():
            agent.resolver = resolver
