"""编排层 diagnose_preview ↔ 数据分析师本体(AnalystAgent):重建业务自洽痕迹。

编排命名空间与业务命名空间不一致:
- 版本 id:编排 ver_+24hex vs 业务 v_+32hex(content_hash 前 32 位)
- 封面段:编排 cover_v1 vs 业务 cover_<version_id>
- 事件 id evt_{session}_{ordinal} 与正文段 id 两命名空间一致,原样通过。

桥接从 repo 痕迹重建业务侧 AudienceSimulationInput + SimulationReport(经
validate_report 自洽校验),运行分析师后再把 finding 的封面段 id 回映为
cover_v1。重建失败(如中断调用后仍有后续会话事件)返回确定性 error,
编排层 node_analysis 降级为仅指标。
"""
from __future__ import annotations

import re
from typing import Any

from backend.adapters.bridge_common import (
    BridgePreSendFailure, BridgeUnknownOutcome, error_result, issue, usage_dict)
from backend.agents.analyst import AnalystAgent
from backend.domain.hashing import content_hash as business_content_hash, sha256_json
from backend.domain.schemas import (
    AudienceEvent, AudienceInput, ContentDelivery, ErrorDetail, Persona, Segment)
from backend.simulation.analysis_data import (
    AnalystInput, Observation, ObservedCall, ObservedSession, SimulationReport,
    TokenUsage, ViewerUsage, segment_content)
from backend.simulation.audience_session import AudienceSimulationInput

AUDIENCE_STEP_RE = re.compile(r"audience:([^:]+):(\d+):[a-f0-9]{16}")


def _rebuild_trace(repo, preview_id: str, run_id: str,
                   mode: str) -> tuple[AudienceSimulationInput, SimulationReport]:
    """从编排 repo 痕迹重建业务自洽的 (source, report);重建失败抛异常。"""
    preview = repo.get_artifact(preview_id)["payload"]
    version = repo.get_version(preview["version_id"])
    payload = version["payload"]
    titles = payload.get("titles") or []
    cover = payload.get("cover_copy")
    if len(titles) != 3 or not isinstance(cover, str) or not cover.strip():
        raise BridgePreSendFailure("analysis requires exactly 3 titles and a non-blank cover_copy")
    content = ContentDelivery(titles=[titles[0], titles[1], titles[2]], cover_copy=cover,
                              segments=[Segment.model_validate(s) for s in payload.get("segments", [])])
    # 修订版(4-key Revision 载荷)的编排 content_hash 覆盖 change_log,不能直接
    # 进入业务快照:业务 AudienceSimulationInput 校验 content_hash(content)
    # (仅 titles/cover_copy/segments 三键),统一以业务口径哈希重建。
    biz_hash = business_content_hash(content)
    synth_version = "v_" + version["content_hash"][:32]
    persons = [Persona.model_validate(p) for p in preview["scenario"]["personas"]]
    sessions = repo.sessions_for_preview(preview_id)

    calls_by_step: dict[tuple[str, int], dict] = {}
    for row in repo.list_calls(run_id):
        if row["agent_id"] != "simulated_audience":
            continue
        match = AUDIENCE_STEP_RE.fullmatch(row["step_key"] or "")
        if match is None:
            continue
        key = (match.group(1), int(match.group(2)))
        prev = calls_by_step.get(key)
        if prev is None or row["attempt"] > prev["attempt"]:
            calls_by_step[key] = row

    max_calls = min(48, max(1, len(calls_by_step)))
    source = AudienceSimulationInput(
        confirmed=True, version_id=synth_version, content_hash=biz_hash,
        content=content, personas=persons, max_segments=min(8, len(content.segments) + 1),
        max_calls=max_calls, max_active_seconds=1200)
    segments = segment_content(source)
    biz_personas = {p.id: p for p in persons}

    calls_by_session: dict[str, list[tuple[int, dict]]] = {}
    for key, row in calls_by_step.items():
        calls_by_session.setdefault(key[0], []).append((key[1], row))

    rebuilt_sessions: list[ObservedSession] = []
    rebuilt_calls: list[ObservedCall] = []
    # 业务语义(AudienceSimulator.run):会话因 call_budget/time_budget/
    # unknown_remote_outcome 停下后,全部后续会话继承同一 stop_reason、
    # cursor 0 且零调用;后续会话若有事件或调用,该痕迹无法用业务模型表示。
    global_stop: str | None = None
    for sess in sessions:
        events: list[dict] = []
        for event_row in repo.session_events(sess["id"]):
            mapped = dict(event_row["payload"])
            if event_row["ordinal"] == 0 and mapped.get("segment_id") == "cover_v1":
                mapped["segment_id"] = "cover_" + synth_version
            events.append({"event_id": event_row["id"], "seq": event_row["ordinal"],
                           "call_id": None, "event": mapped})
        persona = biz_personas.get(sess["persona_id"])
        if persona is None:
            raise BridgePreSendFailure(
                f"session {sess['id']} persona not in frozen scenario")
        calls: list[ObservedCall] = []
        any_unknown = any_failed = False
        for ordinal, row in sorted(calls_by_session.get(sess["id"], [])):
            if ordinal >= len(segments):
                raise BridgePreSendFailure(f"call {row['id']} beyond visible segments")
            own = [AudienceEvent.model_validate(e["event"]) for e in events if e["seq"] < ordinal]
            context = AudienceInput(persona=persona, current_segment=segments[ordinal],
                                    visible_history=segments[:ordinal],
                                    own_previous_reactions=own)
            input_hash = sha256_json(context)
            if row["status"] == "received":
                matched = next((e for e in events if e["seq"] == ordinal), None)
                if matched is None:
                    raise BridgePreSendFailure(
                        f"received call {row['id']} has no committed event at ordinal {ordinal}")
                calls.append(ObservedCall(
                    session_id=sess["id"], persona_id=sess["persona_id"], ordinal=ordinal,
                    mode=mode, call_id=row["id"], input_hash=input_hash, status="received",
                    event=AudienceEvent.model_validate(matched["event"]),
                    usage=TokenUsage(total=row["usage_tokens"]), error=None))
                matched["call_id"] = row["id"]
            elif row["status"] == "interrupted":
                any_unknown = True
                calls.append(ObservedCall(
                    session_id=sess["id"], persona_id=sess["persona_id"], ordinal=ordinal,
                    mode=mode, call_id=row["id"], input_hash=input_hash, status="unknown",
                    event=None, usage=TokenUsage(total=row["usage_tokens"]),
                    error=ErrorDetail(code="INTERRUPTED", retryable=False,
                                      cause_hint="remote outcome unknown",
                                      next_action="explicit resend only", field_errors=[],
                                      current_row_version=None)))
            else:
                any_failed = True
                calls.append(ObservedCall(
                    session_id=sess["id"], persona_id=sess["persona_id"], ordinal=ordinal,
                    mode=mode, call_id=row["id"], input_hash=input_hash, status="failed",
                    event=None, usage=TokenUsage(total=row["usage_tokens"]),
                    error=ErrorDetail(code="MODEL_UNAVAILABLE", retryable=False,
                                      cause_hint="viewer call failed",
                                      next_action="inspect provider", field_errors=[],
                                      current_row_version=None)))
        for e in events:
            if e["call_id"] is None:
                raise BridgePreSendFailure(f"event {e['event_id']} has no received call")
        if sess["status"] == "exited":
            outcome, stop_reason = "exited", "viewer_exit"
        elif sess["status"] == "completed":
            outcome, stop_reason = "completed", None
        else:
            outcome = "incomplete"
            if any_unknown:
                stop_reason = "unknown_remote_outcome"
            elif any_failed:
                stop_reason = "invalid_or_failed_response"
            elif len(rebuilt_calls) + len(calls) == max_calls:
                stop_reason = "call_budget"
            else:
                stop_reason = "time_budget"
        if global_stop is not None:
            if not events and not calls:
                # 全局停牌后的空会话:继承 stop_reason(cursor 已为 0、零调用)。
                outcome, stop_reason = "incomplete", global_stop
            else:
                raise BridgePreSendFailure(
                    "trace not reconstructible: session continues after a global stop")
        if stop_reason in {"call_budget", "time_budget", "unknown_remote_outcome"}:
            global_stop = stop_reason
        rebuilt_sessions.append(ObservedSession(
            session_id=sess["id"], persona_id=sess["persona_id"], outcome=outcome,
            stop_reason=stop_reason, cursor=sess["next_ordinal"],
            events=[Observation(event_id=e["event_id"], seq=e["seq"], call_id=e["call_id"],
                                event=AudienceEvent.model_validate(e["event"])) for e in events]))
        rebuilt_calls.extend(calls)

    any_unknown_call = any(c.status == "unknown" for c in rebuilt_calls)
    status = ("INTERRUPTED" if any_unknown_call else
              "COMPLETED" if all(s.outcome in {"completed", "exited"} for s in rebuilt_sessions)
              else "INCOMPLETE")
    known = [c.usage.total for c in rebuilt_calls if c.usage.total is not None]
    report = SimulationReport(
        mode=mode, medium="text", version_id=synth_version,
        content_hash=biz_hash, input_hash=sha256_json(source),
        status=status, persona_count=len(rebuilt_sessions), segment_count=len(segments),
        sessions=rebuilt_sessions, calls=rebuilt_calls,
        calls_attempted=len(rebuilt_calls), call_budget=max_calls,
        time_budget_seconds=1200,
        usage=ViewerUsage(
            known_total_tokens=sum(known) if known else None,
            usage_not_reported_calls=sum(c.usage.total is None for c in rebuilt_calls),
            remote_outcome_unknown_calls=sum(c.status == "unknown" for c in rebuilt_calls)),
        mock_fixture_exit_ordinal=None, is_simulation=True, predicts_real_traffic=False,
        automatic_resume=False, explicit_new_request_required=True)
    return source, report


class AnalystTeamAdapter:
    def __init__(self, *, repo, model_adapter: Any | None = None,
                 mode: str = "mock", model_id: str | None = None):
        self.repo = repo
        self.agent = AnalystAgent(model_adapter, mode=mode, model_id=model_id)

    def invoke(self, call) -> dict:
        payload = call.input
        call_dict = {"request_id": getattr(call, "request_id", None),
                     "contract_version": getattr(call, "contract_version", None),
                     "agent_id": getattr(call, "agent_id", "data_analyst"),
                     "action": getattr(call, "action", "diagnose_preview")}
        run_id = getattr(getattr(call, "context", None), "run_id", None)
        try:
            preview_id = payload["preview_ref"]["id"]
            source, report = _rebuild_trace(self.repo, preview_id, run_id, self.agent.mode)
            snapshot = AnalystInput(analysis_requested=True, source=source,
                                    simulation=report, comparison_source=None,
                                    comparison_simulation=None,
                                    allow_descriptive_comparison=False)
        except BridgePreSendFailure as exc:
            return error_result(call_dict, str(exc), location="diagnose_preview")
        except ValueError:
            # 业务模型校验(含 validate_report / pydantic ValidationError)拒单:
            # 原因不外泄(pydantic 原文、源码片段一律不进入 issue),确定性降级。
            return error_result(call_dict, "trace not reconstructible",
                                location="diagnose_preview")
        except Exception as exc:
            return error_result(call_dict, f"trace rebuild failed: {exc}",
                                location="diagnose_preview")
        result = self.agent.run(snapshot)
        base = {**call_dict, "usage": usage_dict(result.usage)}
        if result.analysis_status == "interrupted":
            raise BridgeUnknownOutcome(
                result.error.cause_hint if result.error else "analysis outcome unknown")
        if result.analysis_status == "failed":
            err = result.error
            return {**base, "status": "error", "data": None, "questions": [],
                    "issues": [issue(err.cause_hint if err else "analysis failed",
                                     err.next_action if err else "检查输入后显式重发",
                                     "diagnose_preview")]}
        envelope = result.envelope
        if envelope is None:
            return error_result(call_dict, "analysis produced no envelope",
                                location="diagnose_preview")
        if envelope.status == "needs_input":
            return {**base, "status": "needs_input", "data": None,
                    "questions": [q.model_dump(mode="json") for q in envelope.questions],
                    "issues": [i.model_dump(mode="json") for i in envelope.issues]}
        if envelope.status == "error":
            return {**base, "status": "error", "data": None, "questions": [],
                    "issues": [i.model_dump(mode="json") for i in envelope.issues]}
        data = envelope.data.model_dump(mode="json")
        cover_biz = "cover_" + source.version_id
        for finding in data.get("findings", []):
            if finding.get("segment_id") == cover_biz:
                finding["segment_id"] = "cover_v1"
        return {**base, "status": "ok", "data": data, "questions": [], "issues": []}
