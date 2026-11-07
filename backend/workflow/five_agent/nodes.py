"""Node functions and conditional routers for the five-agent StateGraph.

Nodes are `node(state) -> StatePatch` with services closed over.  Every node is
idempotent (LangGraph may re-execute a node from its start on resume): agent
calls go through gateway step receipts, gate prep is keyed by subject hash and
domain saves are keyed by deterministic ids.

Model output NEVER routes: route_decision is computed by program logic from
validated results and repository facts only.
"""
from __future__ import annotations

from langgraph.types import interrupt
from backend.agents.analyst import SYSTEM as ANALYSIS_SYSTEM, validate_analysis
from backend.agents.output_contract import prompt_schema_fingerprint
from backend.domain.errors import DomainError as ComponentError
from backend.domain.schemas import Analysis, Envelope, Persona
from backend.memory.material_retrieval import rank_materials
from backend.simulation.analysis_data import single_version_context
from pydantic import ValidationError

from . import projection as proj
from . import program
from .experiment_ledger import record as record_experiment
from .contracts import frozen_input_hash
from .gateway import (AgentUnavailable, BudgetExceeded, CancelledError, GatewayError,
                      InterruptedUnknown)
from .graphstate import FiveAgentState, Services, validate_state_patch
from .repository import DomainError, object_hash
from .registry import (
    BUDGETS, LIMITS, PROMPT_SCHEMA_VERSION, REVIEW_PROMPT_SCHEMA_HASH, SEGMENTER_VERSION,
    step_key_analysis, step_key_audience, step_key_brief, step_key_draft,
    step_key_export, step_key_pr, step_key_repair, step_key_review, step_key_scout,
)

# --------------------------------------------------------------------- helpers


def _fp(payload: dict) -> str:
    return frozen_input_hash(payload, PROMPT_SCHEMA_VERSION)


def _material_refs(svc: Services, task_id: str, material_ids: list) -> list:
    """按任务归属解引用素材，指纹=sha256(canonical({"text": 正文}))（F-03）。

    与真实桥接约定一致（orch_bridge F-O4）：同一素材 ID 指纹随正文变化；
    缺失引用直接拒绝（INPUT_MISSING），不用 ID 冒充正文哈希。"""
    rows = {m["id"]: m for m in svc.repo.list_materials(task_id)}
    refs = []
    for mid in material_ids:
        row = rows.get(mid)
        if row is None:
            raise DomainError(f"missing material {mid}", "INPUT_MISSING")
        refs.append({"id": mid, "sha256": object_hash({"text": row["text"]})})
    return refs


def _gate(state: FiveAgentState, svc: Services, kind: str, subject: dict) -> dict:
    gate_id = f"gate_{object_hash({'run': state['run_id'], 'kind': kind, 'subject': subject})[:24]}"
    return svc.repo.prepare_gate(gate_id, state["run_id"], kind, subject)


def _decide(svc: Services, gate_row: dict) -> dict:
    """Interrupt for an authenticated user decision; validate resume authority.

    The resume value must name the gate and the committed decision_key — a bare
    true/1/'approved' string is not authority and is rejected FAIL_CLOSED.
    """
    payload = {
        "gate_id": gate_row["id"],
        "kind": gate_row["kind"],
        "subject_hash": gate_row["subject_hash"],
    }
    resume = interrupt(payload)
    if not isinstance(resume, dict) or "decision_key" not in resume or "gate_id" not in resume:
        raise DomainError("resume value is not a committed decision", "ORIGIN_DENIED")
    if resume["gate_id"] != gate_row["id"]:
        raise DomainError("resume gate mismatch", "ORIGIN_DENIED")
    return resume


def _consume_decision(svc: Services, gate_row: dict, resume: dict) -> dict:
    """Validate the resume against the committed gate row (the only authority).

    Approved gates consume their pending command and return the committed
    decision payload; rejected gates surface approved=False so the node takes
    its cancel branch.  Anything else is ORIGIN_DENIED (FAIL_CLOSED)."""
    gate = svc.repo.get_gate(gate_row["id"])
    if gate["decision_key"] != resume["decision_key"]:
        raise DomainError("resume value is not a committed decision", "ORIGIN_DENIED")
    if gate["status"] == "rejected":
        return {"approved": False, "payload": {}}
    return svc.repo.consume_gate_resume(gate_row["id"], resume["decision_key"])


def _call(state: FiveAgentState, svc: Services, step_key: str, action: str, input_payload: dict,
          run_id: str | None = None, max_attempts: int = 3, unknown_policy: str = "run_interrupt",
          prompt_schema_version: str | None = None):
    return svc.gateway.invoke(
        run_id or state["run_id"], step_key, action, input_payload,
        account_id=state["account_id"], task_id=state["task_id"],
        prompt_schema_version=prompt_schema_version or PROMPT_SCHEMA_VERSION,
        max_attempts=max_attempts, unknown_policy=unknown_policy)


def _questions_of(outcome) -> list:
    return list(outcome.result.questions or []) if outcome.result else []


def _pending_questions(state, svc, questions, source):
    payload = {"questions": questions, "source": source, "round": state.get("input_round", 0)}
    digest = object_hash(payload)
    key = "pending_" + object_hash({"run": state["run_id"], "payload": digest})[:24]
    svc.repo.save_artifact(key, state["task_id"], state["run_id"], "pending_questions", payload)
    return {"id": key, "sha256": digest}


def _confirmed_brief(state, svc):
    ref = state.get("brief_ref")
    if ref:
        if ref["task_id"] != state["task_id"]:
            raise DomainError("foreign brief", "SCOPE_DENIED")
        brief = svc.repo.get_brief(ref["task_id"], ref["brief_version"])
        if brief["brief_hash"] != ref["brief_hash"]:
            raise DomainError("brief fingerprint changed", "CONDITIONS_MISMATCH")
    else:
        brief = svc.repo.latest_brief(state["task_id"])
    if not brief or not brief["confirmed_at"]:
        raise DomainError("a confirmed brief is required", "ORIGIN_DENIED")
    return brief


def _can_repair(state, svc):
    profile = BUDGETS[state["run_kind"]]
    return (state.get("repair_count", 0) < profile.max_business_repairs
            and svc.gateway.budget.remaining_normal(state["run_id"], state["run_kind"]) >= 2)


def _issues_of(outcome) -> list:
    return list(outcome.result.issues or []) if outcome.result else []


# 子 run 终态映射：AgentResult.status -> run 终态。
# 子 run 的生命周期由创建它的节点负责终结（ok / needs_input / error 三出口全覆盖）。
SUB_RUN_TERMINAL = {"ok": "READY", "needs_input": "WAITING_INPUT", "error": "NEEDS_REVIEW"}


def _finish_sub_run(svc: Services, sub_run_id: str, state_run_id: str, outcome_status: str) -> None:
    """终结内容 run 内创建的显式子 run（scout / pr_intake）。

    独立 run（子 run 即 state run）的终态由 driver 按 state patch 写入，此处跳过。
    """
    if sub_run_id != state_run_id:
        svc.repo.set_run_status(sub_run_id, SUB_RUN_TERMINAL[outcome_status])


def _save_diagnostics(svc: Services, state: FiveAgentState, source: str,
                      *, error_code: str | None = None, issues: list | None = None,
                      field_errors: list | None = None) -> dict:
    """持久化受控诊断（只存错误码/issue 编号/字段路径，不存模型原文），返回真实 Ref。"""
    payload = {"source": source, "error_code": error_code,
               "issue_codes": [i.get("id") for i in (issues or [])],
               "field_errors": list(field_errors or [])}
    art_id = "diag_" + object_hash({"task": state["task_id"], "run": state["run_id"],
                                    "payload": payload})[:20]
    svc.repo.save_artifact(art_id, state["task_id"], state["run_id"], "diagnostics", payload)
    return {"id": art_id, "sha256": object_hash(payload)}


def _materials_fp(material_refs: list[dict]) -> list[dict]:
    """指纹输入：素材的内容承诺 = id + 内容 sha256，缺一不可（id 相同正文不同必须换指纹）。"""
    return [{"id": r["id"], "sha256": r["sha256"]} for r in material_refs]


def _ranked_brief_materials(state, svc, brief, phase):
    payload = brief["payload"]
    refs = _material_refs(svc, state["task_id"], payload["material_ids"])
    allowed = {r["id"]: r for r in refs}
    rows = [row for row in svc.repo.list_materials(state["task_id"]) if row["id"] in allowed]
    query = " ".join([payload["objective"], *(r["text"] for r in payload["requirements"])])
    ranked, trace = rank_materials(query, rows)
    ordered = [allowed[row["id"]] for row in ranked]
    retrieval = {"phase": phase, "brief_hash": brief["brief_hash"], "rounds": trace, "material_refs": ordered}
    key = "retrieval_" + object_hash({"run": state["run_id"], "retrieval": retrieval})[:24]
    svc.repo.save_artifact(key, state["task_id"], state["run_id"], "material_retrieval", retrieval)
    return ordered


# ----------------------------------------------------------------- content: route


def node_route(state: FiveAgentState, svc: Services) -> dict:
    task = svc.repo.get_task(state["task_id"])
    payload = task["payload"]
    flags = payload.get("flags", {})
    traffic_enabled = bool(flags.get("traffic_enabled", False))
    goal_clear = bool(flags.get("goal_clear", True))
    has_draft = bool(payload.get("existing_draft") or payload.get("existing_draft_ref"))
    discovery = payload.get("purpose") == "discover_topics"
    commercial = payload.get("purpose") == "commercial_order" or bool(payload.get("client_brief"))
    if commercial:
        # 商单/PR 需求先过商单需求分析员（运营官之前），不走流量捕捉
        decision = "pr_analysis"
    elif discovery or (traffic_enabled and not goal_clear and not has_draft):
        decision = "traffic"
    else:
        decision = "brief"
        if traffic_enabled and (goal_clear or has_draft):
            svc.repo.log_event(state["task_id"], state["run_id"], "traffic_skipped",
                               {"reason": "clear goal or existing draft"})
    return validate_state_patch({"route_decision": decision, "resume_step": "route"})


# ------------------------------------------------------- pr_analyst (商单需求)


def _find_pr_analysis(state: FiveAgentState, svc: Services) -> dict | None:
    for art in svc.repo.find_artifacts(state["task_id"], "pr_analysis"):
        if art["run_id"] == state["run_id"] or art["run_id"].startswith(state["run_id"]):
            return art
    return None


def node_pr_analysis(state: FiveAgentState, svc: Services) -> dict:
    """pr_analyst.analyze_request: organise client-supplied commercial requirements
    before the operator.  Calls are booked to an explicit pr_intake sub-run
    (independent budget), mirroring the scout sub-run pattern."""
    task = svc.repo.get_task(state["task_id"])
    payload = task["payload"]
    materials = svc.repo.list_materials(state["task_id"])
    material_refs = [{"id": m["id"], "sha256": object_hash({"text": m["text"]})} for m in materials]
    request_text = (payload.get("client_brief") or payload.get("user_input")
                    or payload.get("goal") or "商单需求") + "".join(
        f"\n补充：{a}" for a in payload.get("answers", []))
    if state["run_kind"] == "pr_intake":
        pr_run_id = state["run_id"]
    else:
        pr_run_id = f"{state['run_id']}_pr"
        try:
            svc.repo.get_run(pr_run_id)
        except DomainError:
            svc.repo.create_run(pr_run_id, state["task_id"], "pr_intake",
                                parent_run_id=state["run_id"])
            svc.repo.set_run_status(pr_run_id, "RUNNING")
    svc.router.bind_task(state["task_id"])
    input_payload = {"request_text": request_text[:20000], "material_refs": material_refs}
    step_key = step_key_pr(_fp({"request_text": request_text,
                                "materials": _materials_fp(material_refs)})[:16])
    try:
        outcome = _call(state, svc, step_key, "analyze_request", input_payload,
                        run_id=pr_run_id, max_attempts=2)
    except (CancelledError, InterruptedUnknown):
        # 取消/中断各有权威终态路径（CANCELLED / INTERRUPTED），禁止吞入分流
        raise
    except (BudgetExceeded, AgentUnavailable):
        _finish_sub_run(svc, pr_run_id, state["run_id"], "error")
        raise
    except GatewayError:
        _finish_sub_run(svc, pr_run_id, state["run_id"], "error")
        diag = _save_diagnostics(svc, state, "pr_analysis", error_code="MODEL_REJECTED")
        return validate_state_patch({"route_decision": "needs_review", "terminal": SUB_RUN_TERMINAL["error"],
                                     "error_ref": diag,
                                     "resume_step": "pr_analysis"})

    if outcome.status == "ok":
        analysis = outcome.data
        _finish_sub_run(svc, pr_run_id, state["run_id"], "ok")
        art_id = "pranalysis_" + object_hash({"task": state["task_id"], "data": analysis})[:24]
        svc.repo.save_artifact(art_id, state["task_id"], state["run_id"], "pr_analysis", analysis)
        svc.repo.log_event(state["task_id"], state["run_id"], "pr_analysis_committed",
                           {"artifact_id": art_id,
                            "ready_for_operator": analysis["ready_for_operator"]})
        if state["run_kind"] == "pr_intake":
            return validate_state_patch({"route_decision": "stop", "terminal": SUB_RUN_TERMINAL["ok"],
                                         "artifact_batch_ref": {"id": art_id, "sha256": object_hash(analysis)},
                                         "resume_step": "pr_analysis"})
        if analysis["ready_for_operator"]:
            return validate_state_patch({"route_decision": "brief",
                                         "artifact_batch_ref": {"id": art_id, "sha256": object_hash(analysis)},
                                         "resume_step": "pr_analysis"})
        questions_ref = _pending_questions(state, svc, analysis["open_questions"], "pr_analysis")
        return validate_state_patch({"route_decision": "wait_input", "resume_step": "pr_analysis", "questions_ref": questions_ref})

    if outcome.status == "needs_input":
        questions = _questions_of(outcome)
        _finish_sub_run(svc, pr_run_id, state["run_id"], "needs_input")
        questions_ref = _pending_questions(state, svc, questions, "pr_analysis")
        if state["run_kind"] == "pr_intake":
            return validate_state_patch({"route_decision": "stop", "terminal": SUB_RUN_TERMINAL["needs_input"],
                                         "resume_step": "pr_analysis"})
        return validate_state_patch({"route_decision": "wait_input", "resume_step": "pr_analysis", "questions_ref": questions_ref})
    # error: 商单分析不交接，人工处理
    _finish_sub_run(svc, pr_run_id, state["run_id"], "error")
    diag = _save_diagnostics(svc, state, "pr_analysis", issues=_issues_of(outcome))
    return validate_state_patch({"route_decision": "needs_review", "terminal": SUB_RUN_TERMINAL["error"],
                                 "error_ref": diag, "resume_step": "pr_analysis"})


# ----------------------------------------------------------------- traffic/scout


def node_traffic(state: FiveAgentState, svc: Services) -> dict:
    task = svc.repo.get_task(state["task_id"])
    goal = task["payload"].get("goal") or task["payload"].get("user_input") or "发现选题"
    materials, retrieval = rank_materials(goal, svc.repo.list_materials(state["task_id"]))
    material_refs = [{"id": m["id"], "sha256": object_hash({"text": m["text"]})} for m in materials]
    if state["run_kind"] == "scout":
        scout_run_id = state["run_id"]
    else:
        scout_run_id = f"{state['run_id']}_scout"
        try:
            svc.repo.get_run(scout_run_id)
        except DomainError:
            svc.repo.create_run(scout_run_id, state["task_id"], "scout", parent_run_id=state["run_id"])
            svc.repo.set_run_status(scout_run_id, "RUNNING")
    svc.router.bind_task(state["task_id"])
    input_payload = proj.build_capture_input(goal, material_refs)
    step_key = step_key_scout(_fp({"goal": goal, "materials": _materials_fp(material_refs)})[:16])
    trace = {"rounds": retrieval, "material_refs": material_refs}
    svc.repo.save_artifact("retrieval_" + object_hash({"run": scout_run_id, "input": trace})[:24],
                           state["task_id"], scout_run_id, "material_retrieval", trace)
    discovery = task["payload"].get("purpose") == "discover_topics"
    try:
        outcome = _call(state, svc, step_key, "capture_opportunities", input_payload,
                        run_id=scout_run_id)
    except (CancelledError, InterruptedUnknown):
        # 取消/中断各有权威终态路径（CANCELLED / INTERRUPTED），禁止吞入失败分流
        raise
    except (GatewayError, BudgetExceeded) as exc:
        _finish_sub_run(svc, scout_run_id, state["run_id"], "error")
        if discovery:
            diag = _save_diagnostics(svc, state, "traffic", error_code=getattr(exc, "code", None))
            return validate_state_patch({"route_decision": "needs_review",
                                         "terminal": SUB_RUN_TERMINAL["error"],
                                         "error_ref": diag, "resume_step": "traffic"})
        svc.repo.log_event(state["task_id"], state["run_id"], "traffic_skipped",
                           {"reason": f"capture failed: {exc}"})
        return validate_state_patch({"route_decision": "brief", "resume_step": "traffic"})

    if outcome.status == "ok":
        _finish_sub_run(svc, scout_run_id, state["run_id"], "ok")
        opp_id = "oppset_" + object_hash({"task": state["task_id"], "data": outcome.data})[:24]
        svc.repo.save_artifact(opp_id, state["task_id"], state["run_id"], "opportunity_set", outcome.data)
        if state["run_kind"] == "scout":
            return validate_state_patch({"route_decision": "stop", "terminal": SUB_RUN_TERMINAL["ok"],
                                         "artifact_batch_ref": {"id": opp_id, "sha256": object_hash(outcome.data)},
                                         "resume_step": "traffic"})
        return validate_state_patch({"route_decision": "wait_opportunity",
                                     "artifact_batch_ref": {"id": opp_id, "sha256": object_hash(outcome.data)},
                                     "resume_step": "traffic"})
    # needs_input / error from scout: 记录、终结子 run、按发现/非发现分流
    _finish_sub_run(svc, scout_run_id, state["run_id"], outcome.status)
    svc.repo.log_event(state["task_id"], state["run_id"], "traffic_skipped",
                       {"reason": f"capture status {outcome.status}", "issues": _issues_of(outcome),
                        "questions": _questions_of(outcome)})
    if outcome.status == "needs_input":
        svc.repo.save_artifact(f"pending_questions_{state['run_id']}_scout", state["task_id"],
                               state["run_id"], "pending_questions",
                               {"questions": _questions_of(outcome), "source": "traffic"})
    terminal = SUB_RUN_TERMINAL[outcome.status]
    if state["run_kind"] == "scout":
        # 独立 scout run 的图只有 stop/needs_review 两个终点；error 走 needs_review 节点落同终态
        patch = {"route_decision": "needs_review" if outcome.status == "error" else "stop",
                 "terminal": terminal, "resume_step": "traffic"}
        if outcome.status == "error":
            patch["error_ref"] = _save_diagnostics(svc, state, "traffic", issues=_issues_of(outcome))
        return validate_state_patch(patch)
    if discovery:
        patch = {"route_decision": "needs_review" if outcome.status == "error" else "stop",
                 "terminal": terminal, "resume_step": "traffic"}
        if outcome.status == "error":
            patch["error_ref"] = _save_diagnostics(svc, state, "traffic", issues=_issues_of(outcome))
        return validate_state_patch(patch)
    # 非发现模式：捕捉是可选分支，失败/缺料继续走 brief（分流规则），子 run 已终结留痕
    return validate_state_patch({"route_decision": "brief", "resume_step": "traffic"})


def node_wait_opportunity(state: FiveAgentState, svc: Services) -> dict:
    opp_ref = state.get("artifact_batch_ref") or {}
    oppset = svc.repo.get_artifact(opp_ref["id"])["payload"] if opp_ref else {"opportunities": []}
    subject = {"opportunity_set_hash": object_hash(oppset),
               "options": [o["id"] for o in oppset.get("opportunities", [])]}
    gate_row = _gate(state, svc, "select_opportunity", subject)
    resume = _decide(svc, gate_row)
    decision = _consume_decision(svc, gate_row, resume)
    if not decision.get("approved"):
        return validate_state_patch({"route_decision": "stop", "terminal": "CANCELLED", "resume_step": "wait_opportunity"})
    selected = (decision.get("payload") or {}).get("selected_opportunity_ref")
    if selected is not None:
        known = {o["id"]: o for o in oppset.get("opportunities", [])}
        if selected["id"] not in known:
            raise DomainError("selected opportunity not in offered set", "SCOPE_DENIED")
        # normalize to a repository-backed Ref (the opportunity itself becomes an artifact)
        opp_payload = known[selected["id"]]
        opp_art_id = "oppsel_" + object_hash({"run": state["run_id"], "opp": opp_payload})[:24]
        svc.repo.save_artifact(opp_art_id, state["task_id"], state["run_id"],
                               "opportunity", opp_payload)
        svc.repo.save_artifact(f"sel_{state['run_id']}", state["task_id"], state["run_id"],
                               "opportunity_selection",
                               {"selected_opportunity_ref": {"id": opp_art_id,
                                                            "sha256": object_hash(opp_payload)},
                                "opportunity_id": selected["id"]})
    else:
        svc.repo.save_artifact(f"sel_{state['run_id']}", state["task_id"], state["run_id"],
                               "opportunity_selection", {"selected_opportunity_ref": None})
    return validate_state_patch({"route_decision": "brief", "gate_ref": {"id": gate_row["id"]},
                                 "resume_step": "wait_opportunity"})


# -------------------------------------------------------------------- brief


def _selected_opportunity(state: FiveAgentState, svc: Services) -> dict | None:
    for art in svc.repo.find_artifacts(state["task_id"], "opportunity_selection"):
        if art["run_id"] == state["run_id"] or art["run_id"].startswith(state["run_id"]):
            return art["payload"].get("selected_opportunity_ref")
    return None


def node_brief(state: FiveAgentState, svc: Services) -> dict:
    task = svc.repo.get_task(state["task_id"])
    payload = task["payload"]
    materials = svc.repo.list_materials(state["task_id"])
    material_refs = [{"id": m["id"], "sha256": object_hash({"text": m["text"]})} for m in materials]
    selected = _selected_opportunity(state, svc)
    user_input = (payload.get("user_input") or payload.get("goal") or "内容创作任务") + "".join(
        f"\n补充：{a}" for a in payload.get("answers", []))
    input_mode = payload.get("input_mode", "idea")
    planning = {"user_input": user_input, "input_mode": input_mode,
                "materials": _materials_fp(material_refs),
                "selected_opportunity_ref": selected}
    # 商单链：把 pr_analyst 已就绪的客户硬性要求并入需求整理输入（可追溯到 artifact）
    # 结构化 requirements 带原始 requirement_id 传递（F-O5），文本并入仅作叙述；
    # edit_scope 通道承载旧稿授权修改范围（F-O3，payload 携带时生效）。
    pr = _find_pr_analysis(state, svc)
    structured_requirements = None
    if pr and pr["payload"].get("ready_for_operator"):
        reqs = [{"id": r["id"], "text": r["text"]} for r in pr["payload"].get("requirements", [])]
        if reqs:
            structured_requirements = reqs
            user_input += "\n客户要求：" + "；".join(r["text"] for r in reqs)
        planning["pr_analysis_id"] = pr["id"]
    step_key = step_key_brief(_fp(planning)[:16])
    input_payload = proj.build_prepare_brief_input(
        user_input, input_mode, material_refs, selected,
        requirements=structured_requirements,
        edit_scope=payload.get("edit_scope") if input_mode == "existing_draft" else None)
    svc.router.bind_task(state["task_id"])
    outcome = _call(state, svc, step_key, "prepare_brief", input_payload)

    if outcome.status == "ok":
        brief_payload = outcome.data
        open_questions = list(brief_payload.get("open_questions") or [])
        saved = svc.repo.save_brief(state["task_id"], brief_payload, open_questions)
        brief_ref = {"task_id": saved["task_id"], "brief_version": saved["brief_version"],
                     "brief_hash": saved["brief_hash"]}
        if open_questions:
            questions_ref = _pending_questions(state, svc, open_questions, "brief")
            return validate_state_patch({"brief_ref": brief_ref, "route_decision": "wait_input", "questions_ref": questions_ref,
                                         "resume_step": "brief"})
        return validate_state_patch({"brief_ref": brief_ref, "route_decision": "wait_brief_confirm",
                                     "resume_step": "brief"})
    if outcome.status == "needs_input":
        questions = _questions_of(outcome)
        questions_ref = _pending_questions(state, svc, questions, "brief")
        return validate_state_patch({"route_decision": "wait_input", "questions_ref": questions_ref, "resume_step": "brief"})
    return validate_state_patch({"route_decision": "needs_review", "terminal": "NEEDS_REVIEW",
                                 "error_ref": {"id": state["run_id"]}, "resume_step": "brief"})


def node_wait_input(state: FiveAgentState, svc: Services) -> dict:
    current_round = state.get("input_round", 0)
    limit = svc.max_input_rounds
    if limit is not None and current_round >= limit:
        diag = _save_diagnostics(svc, state, "supply_input", error_code="BUDGET_EXCEEDED")
        return validate_state_patch({"route_decision": "stop", "terminal": "NEEDS_REVIEW",
                                     "error_ref": diag, "resume_step": "wait_input"})
    ref = state.get("questions_ref")
    if ref:
        pending = svc.repo.get_artifact(ref["id"])["payload"]
    else:
        rows = svc.repo.find_artifacts(state["task_id"], "pending_questions")
        pending = next((r["payload"] for r in reversed(rows) if r["run_id"] == state["run_id"]), {})
    profile = BUDGETS[state["run_kind"]]
    usage = svc.repo.get_usage(state["run_id"])
    call_run_id = state["run_id"] + "_pr" if pending.get("source") == "pr_analysis" else state["run_id"]
    call_kind = "pr_intake" if pending.get("source") == "pr_analysis" else state["run_kind"]
    remaining = svc.gateway.budget.remaining_normal(call_run_id, call_kind)
    if remaining == 0:
        diag = _save_diagnostics(svc, state, "supply_input", error_code="BUDGET_EXCEEDED")
        return validate_state_patch({"route_decision": "stop", "terminal": "NEEDS_REVIEW",
                                     "error_ref": diag, "resume_step": "wait_input"})
    subject = {"questions": pending.get("questions", []), "round": current_round + 1,
               "rounds_remaining": None if limit is None else limit - current_round,
               "normal_calls_remaining": remaining,
               "calls_remaining": max(0, profile.max_total_calls - usage["calls_reserved"])}
    gate_row = _gate(state, svc, "supply_input", subject)
    resume = _decide(svc, gate_row)
    decision = _consume_decision(svc, gate_row, resume)
    if not decision.get("approved"):
        return validate_state_patch({"route_decision": "stop", "terminal": "WAITING_INPUT",
                                     "resume_step": "wait_input"})
    svc.repo.apply_supplement(state["task_id"], state["run_id"], gate_row["id"], decision.get("payload") or {})
    # 商单链：需求分析未就绪时回到 pr_analysis 重规划，就绪后才进运营官
    task = svc.repo.get_task(state["task_id"])
    commercial = task["payload"].get("purpose") == "commercial_order" or bool(task["payload"].get("client_brief"))
    pr = _find_pr_analysis(state, svc)
    route = "pr_analysis" if (commercial and not (pr and pr["payload"].get("ready_for_operator"))) else "brief"
    return validate_state_patch({"route_decision": route, "gate_ref": {"id": gate_row["id"]},
                                 "input_round": current_round + 1, "resume_step": "wait_input"})


def node_wait_brief_confirm(state: FiveAgentState, svc: Services) -> dict:
    brief_ref = state["brief_ref"]
    profile = BUDGETS["content"]
    subject = {"task_id": brief_ref["task_id"], "brief_version": brief_ref["brief_version"],
               "brief_hash": brief_ref["brief_hash"],
               "budget": {"max_total_calls": profile.max_total_calls,
                          "max_business_repairs": profile.max_business_repairs,
                          "max_total_tokens": profile.max_total_tokens}}
    gate_row = _gate(state, svc, "confirm_brief", subject)
    resume = _decide(svc, gate_row)
    decision = _consume_decision(svc, gate_row, resume)
    if not decision.get("approved"):
        return validate_state_patch({"route_decision": "stop", "terminal": "CANCELLED",
                                     "resume_step": "wait_brief_confirm"})
    payload = decision.get("payload") or {}
    if payload.get("brief_version") != brief_ref["brief_version"] or payload.get("brief_hash") != brief_ref["brief_hash"]:
        raise DomainError("confirmation does not match frozen brief", "CONDITIONS_MISMATCH")
    brief = svc.repo.get_brief(brief_ref["task_id"], brief_ref["brief_version"])
    svc.repo.confirm_brief(brief_ref["task_id"], brief_ref["brief_version"], brief_ref["brief_hash"],
                           expected_row_version=brief["row_version"])
    return validate_state_patch({"route_decision": "draft", "gate_ref": {"id": gate_row["id"]},
                                 "resume_step": "wait_brief_confirm"})


# --------------------------------------------------------------------- draft/revise


def node_draft(state: FiveAgentState, svc: Services) -> dict:
    svc.router.bind_task(state["task_id"])
    if state["run_kind"] == "revision":
        return _scoped_revise(state, svc)
    brief_ref = state.get("brief_ref")
    if not brief_ref:
        # recovery path: fall back to the latest confirmed brief of this task
        latest = svc.repo.latest_brief(state["task_id"])
        if latest is None or not latest["confirmed_at"]:
            raise DomainError("unconfirmed brief: zero creator calls allowed", "ORIGIN_DENIED")
        brief_ref = {"task_id": latest["task_id"], "brief_version": latest["brief_version"],
                     "brief_hash": latest["brief_hash"]}
    brief = svc.repo.get_brief(brief_ref["task_id"], brief_ref["brief_version"])
    if not brief["confirmed_at"]:
        raise DomainError("unconfirmed brief: zero creator calls allowed", "ORIGIN_DENIED")
    material_refs = _ranked_brief_materials(state, svc, brief, "draft")
    input_payload = proj.build_draft_input(brief_ref, material_refs)
    step_key = step_key_draft(_fp(input_payload)[:16])
    try:
        outcome = _call(state, svc, step_key, "draft", input_payload)
    except (BudgetExceeded, AgentUnavailable, CancelledError, InterruptedUnknown):
        raise
    except GatewayError as exc:
        return validate_state_patch({"route_decision": "needs_review", "terminal": "NEEDS_REVIEW",
                                     "error_ref": {"id": state["run_id"]}, "resume_step": "draft"})
    if outcome.status == "ok":
        version = _save_candidate(state, svc, outcome.data, base_version_id=None, step_key=step_key)
        return validate_state_patch({"version_ref": {"id": version["id"], "sha256": version["content_hash"]},
                                     "route_decision": "rules", "resume_step": "draft"})
    if outcome.status == "needs_input":
        # facts missing after confirmation -> pause run; new facts need new Brief/run
        svc.repo.save_artifact(f"pending_questions_{state['run_id']}", state["task_id"],
                               state["run_id"], "pending_questions", {"questions": _questions_of(outcome)})
        return validate_state_patch({"route_decision": "stop", "terminal": "WAITING_INPUT",
                                     "resume_step": "draft"})
    return validate_state_patch({"route_decision": "needs_review", "terminal": "NEEDS_REVIEW",
                                 "resume_step": "draft"})


def _save_candidate(state: FiveAgentState, svc: Services, data: dict,
                    base_version_id: str | None, step_key: str) -> dict:
    version_id = "ver_" + object_hash({"run": state["run_id"], "step": step_key})[:24]
    version = svc.repo.save_version(version_id, state["task_id"], state["run_id"],
                                    base_version_id, data, status="candidate")
    brief = _confirmed_brief(state, svc)
    ref = {key: brief[key] for key in ("task_id", "brief_version", "brief_hash")}
    svc.repo.save_artifact("binding_" + version_id, state["task_id"], state["run_id"],
                           "version_brief", {"version_id": version_id, "brief_ref": ref})
    if base_version_id and state.get("revision_ref"):
        record_experiment(svc.repo, state["task_id"], state["run_id"], "revision_candidate",
                          {"request_id": state["revision_ref"]["id"], "base_version_id": base_version_id,
                           "version_id": version_id})
    return version


def _scoped_revise(state: FiveAgentState, svc: Services) -> dict:
    """revision run entry: content_creator.revise inside the frozen finding scope."""
    base = svc.repo.get_version(state["version_ref"]["id"])
    request = svc.repo.get_artifact(state["revision_ref"]["id"])["payload"]
    brief = _confirmed_brief(state, svc)
    brief_ref = {"task_id": state["task_id"], "brief_version": brief["brief_version"],
                 "brief_hash": brief["brief_hash"]}
    base_version_ref = {"id": base["id"], "sha256": base["content_hash"]}
    revision_request_ref = {"id": state["revision_ref"]["id"],
                            "sha256": object_hash(request)}
    step_key = f"revise_scoped:{_fp({'base': base_version_ref, 'req': revision_request_ref})[:16]}"
    input_payload = proj.build_revise_input(brief_ref, base_version_ref, revision_request_ref)
    try:
        outcome = _call(state, svc, step_key, "revise", input_payload)
    except (BudgetExceeded, AgentUnavailable, CancelledError, InterruptedUnknown):
        raise
    except GatewayError:
        return validate_state_patch({"route_decision": "needs_review", "terminal": "NEEDS_REVIEW",
                                     "error_ref": {"id": state["run_id"]}, "resume_step": "draft_scoped"})
    if outcome.status == "ok":
        finding_segment = request.get("finding_segment", {})
        try:
            program.validate_revision(base["payload"], outcome.data,
                                      bool(request.get("allow_title_change")),
                                      bool(request.get("allow_cover_change")),
                                      finding_segment, {})
        except program.ScopeError as exc:
            svc.repo.log_event(state["task_id"], state["run_id"], "scope_denied", {"problems": exc.problems})
            return validate_state_patch({"route_decision": "needs_review", "terminal": "NEEDS_REVIEW",
                                         "error_ref": {"id": state["run_id"]}, "resume_step": "draft_scoped"})
        version = _save_candidate(state, svc, outcome.data, base_version_id=base["id"], step_key=step_key)
        return validate_state_patch({"version_ref": {"id": version["id"], "sha256": version["content_hash"]},
                                     "route_decision": "rules", "resume_step": "draft_scoped"})
    if outcome.status == "needs_input":
        return validate_state_patch({"route_decision": "stop", "terminal": "WAITING_INPUT",
                                     "resume_step": "draft_scoped"})
    return validate_state_patch({"route_decision": "needs_review", "terminal": "NEEDS_REVIEW",
                                 "resume_step": "draft_scoped"})


# ------------------------------------------------------------------- rules/review


def node_rules(state: FiveAgentState, svc: Services) -> dict:
    version = svc.repo.get_version(state["version_ref"]["id"])
    brief = _confirmed_brief(state, svc)
    report = program.run_rules(version["id"], version["payload"], brief["payload"]["length_rule"])
    rule_id = f"rule_{version['id']}"
    svc.repo.save_artifact(rule_id, state["task_id"], state["run_id"], "rule_report", report)
    if report["passed"]:
        decision = "review"
    elif _can_repair(state, svc):
        decision = "repair"  # rule failure skips the first review
    else:
        decision = "needs_review"
    patch = {"rule_ref": {"id": rule_id, "sha256": object_hash(report)},
             "route_decision": decision, "resume_step": "rules"}
    if decision == "needs_review":
        patch.update({"terminal": "NEEDS_REVIEW"})
    return validate_state_patch(patch)


def node_review(state: FiveAgentState, svc: Services) -> dict:
    brief = _confirmed_brief(state, svc)
    brief_ref = {"task_id": state["task_id"], "brief_version": brief["brief_version"],
                 "brief_hash": brief["brief_hash"]}
    version = svc.repo.get_version(state["version_ref"]["id"])
    rule_report = svc.repo.get_artifact(state["rule_ref"]["id"])["payload"]
    material_refs = _ranked_brief_materials(state, svc, brief, "review")
    step_key = step_key_review(version["id"])
    input_payload = proj.build_assess_input(
        brief_ref, {"id": version["id"], "sha256": version["content_hash"]},
        {"id": state["rule_ref"]["id"], "sha256": object_hash(rule_report)}, material_refs)
    svc.router.bind_task(state["task_id"])
    try:
        outcome = _call(state, svc, step_key, "assess_content", input_payload,
                        prompt_schema_version=f"{PROMPT_SCHEMA_VERSION}+review:{REVIEW_PROMPT_SCHEMA_HASH[:16]}")
    except (BudgetExceeded, AgentUnavailable, CancelledError, InterruptedUnknown):
        raise
    except GatewayError:
        return validate_state_patch({"route_decision": "needs_review", "terminal": "NEEDS_REVIEW",
                                     "error_ref": {"id": state["run_id"]}, "resume_step": "review"})
    if outcome.status == "needs_input":
        svc.repo.save_artifact(f"pending_questions_{state['run_id']}", state["task_id"],
                               state["run_id"], "pending_questions", {"questions": _questions_of(outcome)})
        return validate_state_patch({"route_decision": "stop", "terminal": "WAITING_INPUT",
                                     "resume_step": "review"})
    if outcome.status != "ok":
        return validate_state_patch({"route_decision": "needs_review", "terminal": "NEEDS_REVIEW",
                                     "resume_step": "review"})
    review = outcome.data
    review_id = f"review_{version['id']}"
    svc.repo.save_artifact(review_id, state["task_id"], state["run_id"], "editorial_review", review)
    patch = {"review_ref": {"id": review_id, "sha256": object_hash(review)}, "resume_step": "review"}
    if review["overall"] == "pass":
        patch["route_decision"] = "export"
    elif review["overall"] == "needs_input":
        patch.update({"route_decision": "stop", "terminal": "WAITING_INPUT"})
    elif _can_repair(state, svc):
        patch["route_decision"] = "repair"
    else:
        patch.update({"route_decision": "needs_review", "terminal": "NEEDS_REVIEW"})
    return validate_state_patch(patch)


# ---------------------------------------------------------------------- repair


def node_repair(state: FiveAgentState, svc: Services) -> dict:
    """One business repair: content_creator.revise targeting rule/review issues."""
    base = svc.repo.get_version(state["version_ref"]["id"])
    brief = _confirmed_brief(state, svc)
    brief_ref = {"task_id": state["task_id"], "brief_version": brief["brief_version"],
                 "brief_hash": brief["brief_hash"]}
    issue_locations: dict[str, str] = {}
    issue_details: dict[str, str] = {}
    issue_ids: list[str] = []
    allow_title = allow_cover = False
    report = None
    if state.get("rule_ref"):
        report = svc.repo.get_artifact(state["rule_ref"]["id"])["payload"]
        for check in program.failed_checks(report):
            issue_ids.append(check["rule_id"])
            issue_details[check["rule_id"]] = check["reason"]
            if check.get("segment_id"):
                issue_locations[check["rule_id"]] = check["segment_id"]
            if check.get("segment_id") == "titles":
                allow_title = True
            if check.get("segment_id") == "cover":
                allow_cover = True
    if state.get("review_ref"):
        review = svc.repo.get_artifact(state["review_ref"]["id"])["payload"]
        for issue in review.get("issues", []):
            issue_ids.append(issue["id"])
            issue_details[issue["id"]] = issue["requested_change"]
            if issue.get("location"):
                issue_locations[issue["id"]] = issue["location"]
            allow_title |= issue.get("location") == "titles"
            allow_cover |= issue.get("location") == "cover"
    if not issue_ids:
        issue_ids = ["iss_generic_1"]
        issue_locations["iss_generic_1"] = base["payload"]["segments"][0]["segment_id"] \
            if base["payload"].get("segments") else "seg_hook_1"
    request = {
        "kind": "issue_repair",
        "expected_head_version_id": base["id"],
        "base_version_id": base["id"],
        "base_content_hash": base["content_hash"],
        "issue_ids": issue_ids,
        "issue_locations": issue_locations,
        "issue_details": issue_details,
        "instructions": "只修复列出的问题，未提及的片段保持原样",
        "allow_title_change": allow_title,
        "allow_cover_change": allow_cover,
    }
    req_id = "repairreq_" + object_hash({"base": base["id"], "issues": sorted(issue_ids)})[:24]
    svc.repo.save_artifact(req_id, state["task_id"], state["run_id"], "revision_request", request)
    scope_fp = _fp({"base": base["id"], "issues": sorted(issue_ids)})[:16]
    step_key = step_key_repair(base["id"], scope_fp)
    input_payload = proj.build_revise_input(
        brief_ref, {"id": base["id"], "sha256": base["content_hash"]},
        {"id": req_id, "sha256": object_hash(request)})
    svc.router.bind_task(state["task_id"])
    try:
        outcome = _call(state, svc, step_key, "revise", input_payload)
    except (BudgetExceeded, AgentUnavailable, CancelledError, InterruptedUnknown):
        raise
    except GatewayError:
        return validate_state_patch({"route_decision": "needs_review", "terminal": "NEEDS_REVIEW",
                                     "error_ref": {"id": state["run_id"]}, "resume_step": "repair"})
    if outcome.status == "ok":
        try:
            program.validate_revision(base["payload"], outcome.data, allow_title, allow_cover,
                                      {}, issue_locations)
        except program.ScopeError as exc:
            svc.repo.log_event(state["task_id"], state["run_id"], "scope_denied", {"problems": exc.problems})
            return validate_state_patch({"route_decision": "needs_review", "terminal": "NEEDS_REVIEW",
                                         "error_ref": {"id": state["run_id"]}, "resume_step": "repair"})
        version = _save_candidate(state, svc, outcome.data, base_version_id=base["id"], step_key=step_key)
        return validate_state_patch({"version_ref": {"id": version["id"], "sha256": version["content_hash"]},
                                     "repair_count": int(state.get("repair_count", 0)) + 1,
                                     "route_decision": "rules", "resume_step": "repair"})
    return validate_state_patch({"route_decision": "needs_review", "terminal": "NEEDS_REVIEW",
                                 "error_ref": {"id": state["run_id"]}, "resume_step": "repair"})


# ------------------------------------------------------------------- export/accept


def node_export(state: FiveAgentState, svc: Services) -> dict:
    """Program export: zero model calls.  Version becomes ready (not accepted)."""
    version = svc.repo.get_version(state["version_ref"]["id"])
    batch_id = f"batch_{version['id']}"
    md = _render_markdown(version["payload"])
    files = {"article.md": md, "article.txt": md.replace("# ", "")}
    batch = {"version_id": version["id"], "content_hash": version["content_hash"],
             "exporter_version": "exporter-v1", "files": files}
    svc.repo.save_artifact(batch_id, state["task_id"], state["run_id"], "export_batch", batch)
    if version["status"] == "candidate":
        svc.repo.set_version_status(version["id"], "ready", expected="candidate")
    svc.repo.log_event(state["task_id"], state["run_id"], "exported",
                       {"version_id": version["id"], "batch_id": batch_id})
    return validate_state_patch({"artifact_batch_ref": {"id": batch_id, "sha256": object_hash(batch)},
                                 "route_decision": "wait_accept", "resume_step": "export"})


def _render_markdown(payload: dict) -> str:
    lines = ["# " + (payload["titles"][0] if payload.get("titles") else "未命名"), ""]
    if payload.get("cover_copy"):
        lines += ["> " + payload["cover_copy"], ""]
    for seg in payload.get("segments", []):
        lines += [seg["text"], ""]
    return "\n".join(lines)


def node_wait_accept(state: FiveAgentState, svc: Services) -> dict:
    version = svc.repo.get_version(state["version_ref"]["id"])
    batch_id = (state.get("artifact_batch_ref") or {}).get("id")
    subject = {"version_id": version["id"], "content_hash": version["content_hash"],
               "batch_id": batch_id}
    gate_row = _gate(state, svc, "accept_delivery", subject)
    resume = _decide(svc, gate_row)
    decision = _consume_decision(svc, gate_row, resume)
    if not decision.get("approved"):
        # qualified & downloadable stays ready; generation != acceptance
        return validate_state_patch({"route_decision": "stop", "terminal": "EXPORTED",
                                     "resume_step": "wait_accept"})
    svc.repo.set_version_status(version["id"], "accepted", expected="ready")
    svc.repo.log_event(state["task_id"], state["run_id"], "version_accepted", {"version_id": version["id"]})
    return validate_state_patch({"route_decision": "stop", "terminal": "READY",
                                 "gate_ref": {"id": gate_row["id"]}, "resume_step": "wait_accept"})


def node_needs_review(state: FiveAgentState, svc: Services) -> dict:
    try:
        svc.repo.set_run_status(state["run_id"], "NEEDS_REVIEW",
                                error={"code": "NEEDS_REVIEW", "cause_hint": "automatic repair exhausted or unfixable"})
    except DomainError:
        pass  # run already cancelled/terminal; keep the recorded status
    return validate_state_patch({"route_decision": "stop", "terminal": "NEEDS_REVIEW"})


def node_stop(state: FiveAgentState, svc: Services) -> dict:
    return validate_state_patch({"resume_step": "stop"})


# ------------------------------------------------------------------- preview


def node_wait_conditions(state: FiveAgentState, svc: Services) -> dict:
    version = svc.repo.get_version(state["version_ref"]["id"])
    if version["status"] not in ("ready", "accepted"):
        raise DomainError("preview requires a qualified frozen version", "CONDITIONS_MISMATCH")
    subject = {"version_id": version["id"], "content_hash": version["content_hash"],
               "budget": {"max_total_calls": BUDGETS["preview"].max_total_calls,
                          "max_total_tokens": BUDGETS["preview"].max_total_tokens}}
    gate_row = _gate(state, svc, "preview_conditions", subject)
    resume = _decide(svc, gate_row)
    decision = _consume_decision(svc, gate_row, resume)
    if not decision.get("approved"):
        return validate_state_patch({"route_decision": "stop", "terminal": "CANCELLED",
                                     "resume_step": "wait_conditions"})
    scenario = (decision.get("payload") or {}).get("scenario") or {}
    if type(scenario.get("blind", False)) is not bool:
        raise DomainError("blind must be boolean", "SCHEMA_INVALID")
    if scenario.get("retest_of"):
        prior = svc.repo.get_artifact(scenario["retest_of"])
        if prior["task_id"] != state["task_id"] or prior["kind"] != "preview":
            raise DomainError("retest must refer to a preview in this task", "SCOPE_DENIED")
        if prior["payload"]["version_id"] not in (version["id"], version["base_version_id"]):
            raise DomainError("retest version is not linked to prior preview", "CONDITIONS_MISMATCH")
    personas = scenario.get("personas") or []
    if not personas or len(personas) > LIMITS["personas"]:
        raise DomainError("scenario personas invalid", "CONDITIONS_MISMATCH")
    try:
        personas = [Persona.model_validate(p).model_dump(mode="json") for p in personas]
    except ValidationError:
        raise DomainError("scenario persona fields invalid", "SCHEMA_INVALID") from None
    if len({p["id"] for p in personas}) != len(personas):
        raise DomainError("scenario persona IDs must be unique", "CONDITIONS_MISMATCH")
    scenario = {**scenario, "personas": personas}
    preview_id = "preview_" + object_hash({"version": version["id"], "run": state["run_id"]})[:24]
    preview_payload = {"version_id": version["id"], "content_hash": version["content_hash"],
                       "scenario": scenario, "segmenter_version": SEGMENTER_VERSION}
    svc.repo.save_artifact(preview_id, state["task_id"], state["run_id"], "preview", preview_payload)
    first_session_id = None
    for persona in personas:
        sid = "sess_" + object_hash({"preview": preview_id, "persona": persona["id"]})[:24]
        svc.repo.create_session(sid, preview_id, persona["id"])
        first_session_id = first_session_id or sid
    svc.repo.log_event(state["task_id"], state["run_id"], "preview_frozen",
                       {"preview_id": preview_id, "personas": [p["id"] for p in personas]})
    return validate_state_patch({"preview_ref": {"id": preview_id, "sha256": object_hash(preview_payload)},
                                 "cursor_ref": {"id": first_session_id,
                                                "sha256": object_hash({"o": 0})},
                                 "route_decision": "project", "resume_step": "wait_conditions"})


def _segments_of(state: FiveAgentState, svc: Services) -> list[dict]:
    preview = svc.repo.get_artifact(state["preview_ref"]["id"])["payload"]
    version = svc.repo.get_version(preview["version_id"])
    return proj.visible_segments(version["payload"])


def node_project(state: FiveAgentState, svc: Services) -> dict:
    """Validate the next (session, ordinal) projection is legal (isolation asserts)."""
    cursor = state.get("cursor_ref") or {}
    session = svc.repo.get_session(cursor["id"])
    segments = _segments_of(state, svc)
    persona = _persona_of(state, svc, session["persona_id"])
    own_events = [e["payload"] for e in svc.repo.session_events(session["id"])]
    proj.build_audience_input(persona, segments, session["next_ordinal"], own_events)
    return validate_state_patch({"cursor_ref": {"id": session["id"], "sha256": object_hash({"o": session["next_ordinal"]})},
                                 "route_decision": "audience_step", "resume_step": "project"})


def _persona_of(state: FiveAgentState, svc: Services, persona_id: str) -> dict:
    preview = svc.repo.get_artifact(state["preview_ref"]["id"])["payload"]
    for persona in preview["scenario"]["personas"]:
        if persona["id"] == persona_id:
            return persona
    raise DomainError(f"persona {persona_id} not in frozen scenario", "NOT_FOUND")


def node_audience_step(state: FiveAgentState, svc: Services) -> dict:
    session = svc.repo.get_session(state["cursor_ref"]["id"])
    segments = _segments_of(state, svc)
    ordinal = session["next_ordinal"]
    persona = _persona_of(state, svc, session["persona_id"])
    own_events = [e["payload"] for e in svc.repo.session_events(session["id"])]
    audience_input = proj.build_audience_input(persona, segments, ordinal, own_events)
    step_key = step_key_audience(session["id"], ordinal, proj.projection_hash(audience_input))
    svc.router.bind_task(state["task_id"])
    outcome = _call(state, svc, step_key, "read_segment", audience_input,
                    max_attempts=2, unknown_policy="step_incomplete")
    if outcome.unknown:
        # audience timeout/unknown: session incomplete, never faked as exit
        svc.repo.mark_session_incomplete(session["id"])
        svc.repo.log_event(state["task_id"], state["run_id"], "audience_incomplete",
                           {"session_id": session["id"], "ordinal": ordinal})
        return validate_state_patch({"route_decision": "advance", "resume_step": "audience_step"})
    if outcome.status != "ok":
        svc.repo.mark_session_incomplete(session["id"])
        return validate_state_patch({"route_decision": "advance", "resume_step": "audience_step"})
    event = outcome.data
    current_id = segments[ordinal]["segment_id"]
    if event["segment_id"] != current_id:
        # audience over-reach: SCOPE_DENIED, call counted, no event written
        svc.repo.log_event(state["task_id"], state["run_id"], "audience_scope_denied",
                           {"session_id": session["id"], "expected": current_id,
                            "got": event["segment_id"]})
        return validate_state_patch({"route_decision": "needs_review", "terminal": "NEEDS_REVIEW",
                                     "error_ref": {"id": state["run_id"]}, "resume_step": "audience_step"})
    return validate_state_patch({"route_decision": "commit_event", "resume_step": "audience_step"})


def node_commit_event(state: FiveAgentState, svc: Services) -> dict:
    session = svc.repo.get_session(state["cursor_ref"]["id"])
    segments = _segments_of(state, svc)
    ordinal = session["next_ordinal"]
    step_key = step_key_audience(session["id"], ordinal,
                                 proj.projection_hash(proj.build_audience_input(
                                     _persona_of(state, svc, session["persona_id"]), segments, ordinal,
                                     [e["payload"] for e in svc.repo.session_events(session["id"])])))
    receipt = svc.repo.get_step_output(state["run_id"], step_key)
    if receipt is None:
        raise DomainError("no committed audience receipt to replay", "NOT_FOUND")
    event = receipt["payload"]["data"]
    if event["action"] == "exit":
        next_status = "exited"
    elif ordinal >= len(segments) - 1:
        next_status = "completed"
    else:
        next_status = None
    saved = svc.repo.save_event_and_advance(session["id"], ordinal, event["segment_id"], event, next_status)
    svc.repo.log_event(state["task_id"], state["run_id"], "audience_event",
                       {"session_id": session["id"], "ordinal": ordinal,
                        "segment_id": event["segment_id"], "action": event["action"],
                        "event_id": saved["event_id"]})
    return validate_state_patch({"route_decision": "advance", "resume_step": "commit_event"})


def node_advance(state: FiveAgentState, svc: Services) -> dict:
    preview_id = state["preview_ref"]["id"]
    segments = _segments_of(state, svc)
    sessions = svc.repo.sessions_for_preview(preview_id)
    current = svc.repo.get_session(state["cursor_ref"]["id"])
    if current["status"] == "active" and current["next_ordinal"] < len(segments):
        return validate_state_patch({"route_decision": "project", "resume_step": "advance"})
    for sess in sessions:
        if sess["status"] == "active":
            return validate_state_patch({"cursor_ref": {"id": sess["id"], "sha256": object_hash({"o": sess["next_ordinal"]})},
                                         "route_decision": "project", "resume_step": "advance"})
    return validate_state_patch({"route_decision": "metrics", "resume_step": "advance"})


def node_metrics(state: FiveAgentState, svc: Services) -> dict:
    preview_id = state["preview_ref"]["id"]
    segments = _segments_of(state, svc)
    sessions = svc.repo.sessions_for_preview(preview_id)
    events = svc.repo.preview_events(preview_id)
    metrics = program.compute_metrics(sessions, events, [s["segment_id"] for s in segments])
    metrics_id = f"metrics_{preview_id}"
    svc.repo.save_artifact(metrics_id, state["task_id"], state["run_id"], "metrics", metrics)
    preview = svc.repo.get_artifact(preview_id)["payload"]
    if preview["scenario"].get("retest_of"):
        record_experiment(svc.repo, state["task_id"], state["run_id"], "retest",
                          {"preview_id": preview_id, "retest_of": preview["scenario"]["retest_of"],
                           "version_id": preview["version_id"], "metrics_id": metrics_id})
    svc.repo.log_event(state["task_id"], state["run_id"], "metrics_computed",
                       {"metrics_id": metrics_id, "started": metrics["started"],
                        "completed": metrics["completed"], "exited": metrics["exited"],
                        "incomplete": metrics["incomplete"]})
    return validate_state_patch({"route_decision": "analysis", "resume_step": "metrics",
                                 "artifact_batch_ref": {"id": metrics_id, "sha256": object_hash(metrics)}})


def node_analysis(state: FiveAgentState, svc: Services) -> dict:
    preview = svc.repo.get_artifact(state["preview_ref"]["id"])["payload"]
    metrics_art = svc.repo.get_artifact(f"metrics_{state['preview_ref']['id']}")["payload"]
    version = svc.repo.get_version(preview["version_id"])
    input_payload = proj.build_diagnose_input(
        state["preview_ref"], {"id": version["id"], "sha256": version["content_hash"]},
        {"id": f"metrics_{state['preview_ref']['id']}", "sha256": object_hash(metrics_art)})
    fingerprint = object_hash({"metrics": metrics_art, "events": svc.repo.preview_events(state["preview_ref"]["id"]),
                               "prompt": prompt_schema_fingerprint(ANALYSIS_SYSTEM, Envelope[Analysis])})
    step_key = step_key_analysis(state["preview_ref"]["id"], version["id"], fingerprint)
    svc.router.bind_task(state["task_id"])
    try:
        outcome = _call(state, svc, step_key, "diagnose_preview", input_payload,
                        max_attempts=3, unknown_policy="run_interrupt")
    except (CancelledError, InterruptedUnknown):
        raise
    except (GatewayError, BudgetExceeded, AgentUnavailable):
        outcome = None  # soft-degrade below
    analysis_id = f"analysis_{state['preview_ref']['id']}"
    if outcome is not None and outcome.status == "ok":
        if _analysis_refs_valid(state, svc, outcome.data):
            svc.repo.save_artifact(analysis_id, state["task_id"], state["run_id"], "analysis", outcome.data)
            record_experiment(svc.repo, state["task_id"], state["run_id"], "hypotheses",
                              {"preview_id": state["preview_ref"]["id"], "analysis_id": analysis_id,
                               "version_id": version["id"], "finding_ids": [f["id"] for f in outcome.data["findings"]]})
            return validate_state_patch({"route_decision": "show", "resume_step": "analysis",
                                         "review_ref": {"id": analysis_id, "sha256": object_hash(outcome.data)}})
        svc.repo.log_event(state["task_id"], state["run_id"], "analysis_rejected",
                           {"reason": "findings reference unknown observations"})
    # analysis failed or findings invalid: show deterministic metrics, mark analysis missing
    svc.repo.save_artifact(analysis_id, state["task_id"], state["run_id"], "analysis_missing",
                           {"status": "missing", "reason": "analysis unavailable or rejected"})
    return validate_state_patch({"route_decision": "show", "resume_step": "analysis"})


def _analysis_refs_valid(state: FiveAgentState, svc: Services, analysis: dict) -> bool:
    preview_id = state["preview_ref"]["id"]
    observations = {e["id"]: e["payload"]["segment_id"] for e in svc.repo.preview_events(preview_id)}
    try:
        data = Analysis.model_validate(analysis)
        envelope = Envelope[Analysis](schema_version="creator-agent.v1", status="ok",
            summary="工作流试映分析", data=data, questions=[], issues=[],
            evidence_refs=sorted({ref for finding in data.findings for ref in finding.observation_refs}))
        validate_analysis(envelope, observations, single_version_context())
        return True
    except (ValidationError, ComponentError):
        return False


def node_show_suggestions(state: FiveAgentState, svc: Services) -> dict:
    """Template render of the analyst output — zero model calls."""
    metrics_art = svc.repo.get_artifact(f"metrics_{state['preview_ref']['id']}")["payload"]
    analysis_id = f"analysis_{state['preview_ref']['id']}"
    analysis = None
    try:
        art = svc.repo.get_artifact(analysis_id)
        analysis = art["payload"] if art["kind"] == "analysis" else None
    except DomainError:
        analysis = None
    workbench = {
        "metrics_summary": {"started": metrics_art["started"], "completed": metrics_art["completed"],
                            "exited": metrics_art["exited"], "incomplete": metrics_art["incomplete"]},
        "segment_metrics": metrics_art["segments"],
        "analysis_available": analysis is not None,
        "findings": (analysis or {}).get("findings", []),
        "renderer": "template-v1",
    }
    suggestions_id = f"suggestions_{state['preview_ref']['id']}"
    svc.repo.save_artifact(suggestions_id, state["task_id"], state["run_id"], "suggestions", workbench)
    return validate_state_patch({"route_decision": "wait_suggestions", "resume_step": "show",
                                 "artifact_batch_ref": {"id": suggestions_id, "sha256": object_hash(workbench)}})


def node_wait_suggestions(state: FiveAgentState, svc: Services) -> dict:
    analysis_id = f"analysis_{state['preview_ref']['id']}"
    subject = {"analysis_id": analysis_id, "version_id": (state.get("version_ref") or {}).get("id"),
               "budget": {"max_total_calls": BUDGETS["revision"].max_total_calls}}
    gate_row = _gate(state, svc, "select_findings", subject)
    resume = _decide(svc, gate_row)
    decision = _consume_decision(svc, gate_row, resume)
    payload = decision.get("payload") or {}
    finding_ids = list(payload.get("finding_ids") or [])
    if not decision.get("approved") or not finding_ids:
        # no selection -> zero scoped revisions (never auto-edit)
        return validate_state_patch({"route_decision": "stop", "terminal": "READY",
                                     "resume_step": "wait_suggestions"})
    analysis = svc.repo.get_artifact(analysis_id)["payload"]
    finding_segment = {f["id"]: f["segment_id"] for f in analysis.get("findings", [])
                       if f["id"] in finding_ids}
    missing = [fid for fid in finding_ids if fid not in finding_segment]
    if missing:
        raise DomainError(f"selected findings not in analysis: {missing}", "SCOPE_DENIED")
    preview = svc.repo.get_artifact(state["preview_ref"]["id"])["payload"]
    base = svc.repo.get_version(preview["version_id"])
    request = {
        "kind": "finding_repair",
        "expected_head_version_id": base["id"],
        "base_version_id": base["id"],
        "base_content_hash": base["content_hash"],
        "analysis_id": analysis_id,
        "analysis_sha256": object_hash(analysis),
        "finding_ids": finding_ids,
        "finding_segment": finding_segment,
        "instructions": payload.get("instructions"),
        "allow_title_change": bool(payload.get("allow_title_change")),
        "allow_cover_change": bool(payload.get("allow_cover_change")),
    }
    req_id = "revreq_" + object_hash({"run": state["run_id"], "request": request})[:24]
    svc.repo.save_artifact(req_id, state["task_id"], state["run_id"], "revision_request", request)
    record_experiment(svc.repo, state["task_id"], state["run_id"], "selected",
                      {"preview_id": state["preview_ref"]["id"], "analysis_id": analysis_id,
                       "version_id": base["id"], "request_id": req_id, "finding_ids": finding_ids})
    return validate_state_patch({"revision_ref": {"id": req_id, "sha256": object_hash(request)},
                                 "gate_ref": {"id": gate_row["id"]},
                                 "route_decision": "stop", "terminal": "READY",
                                 "resume_step": "wait_suggestions"})


# --------------------------------------------------------------------- routers


def route_after_route(state: FiveAgentState) -> str:
    return state["route_decision"]


def route_generic(state: FiveAgentState) -> str:
    return state["route_decision"]
