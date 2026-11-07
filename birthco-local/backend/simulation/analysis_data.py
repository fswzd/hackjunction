"""Validate the local Audience trace and calculate metrics without a model."""
from typing import Literal

from pydantic import Field,model_validator

from backend.agents.audience import validate_event
from backend.domain.errors import DomainError
from backend.domain.hashing import content_hash, sha256_json
from backend.domain.schemas import (
    Model, Id, Hash, Confirmed, AudienceEvent, AudienceInput, ErrorDetail,
    ContentDelivery, Persona, VisibleSegment,
)
from backend.simulation.audience_session import AudienceSimulationInput,segment_content


class TokenUsage(Model):
    input:int|None=Field(default=None,ge=0)
    output:int|None=Field(default=None,ge=0)
    total:int|None=Field(default=None,ge=0)
    cached:int|None=Field(default=None,ge=0)
    reasoning:int|None=Field(default=None,ge=0)


class Observation(Model):
    event_id:Id
    seq:int=Field(ge=0,le=7)
    call_id:Id
    event:AudienceEvent


class ObservedSession(Model):
    session_id:Id
    persona_id:Id
    outcome:Literal["completed","exited","incomplete"]
    stop_reason:Literal["viewer_exit","call_budget","time_budget","unknown_remote_outcome","invalid_or_failed_response"]|None
    cursor:int=Field(ge=0,le=8)
    events:list[Observation]=Field(max_length=8)


class ObservedCall(Model):
    session_id:Id
    persona_id:Id
    ordinal:int=Field(ge=0,le=7)
    mode:Literal["mock","live"]
    call_id:Id
    input_hash:Hash
    status:Literal["received","failed","unknown"]
    event:AudienceEvent|None
    usage:TokenUsage
    error:ErrorDetail|None

    @model_validator(mode="after")
    def consistent_status(self):
        if self.status=="received" and (self.event is None or self.error is not None):raise ValueError("received call requires exactly a valid event")
        if self.status!="received" and (self.event is not None or self.error is None):raise ValueError("failed call requires error and no event")
        if self.status=="unknown" and self.error.code!="INTERRUPTED":raise ValueError("unknown call must be interrupted")
        return self


class ViewerUsage(Model):
    known_total_tokens:int|None=Field(ge=0)
    usage_not_reported_calls:int=Field(ge=0,le=48)
    remote_outcome_unknown_calls:int=Field(ge=0,le=48)


class SimulationReport(Model):
    mode:Literal["mock","live"]
    medium:Literal["text"]
    version_id:Id
    content_hash:Hash
    input_hash:Hash
    status:Literal["COMPLETED","INCOMPLETE","INTERRUPTED"]
    persona_count:int=Field(ge=1,le=6)
    segment_count:int=Field(ge=1,le=8)
    sessions:list[ObservedSession]=Field(min_length=1,max_length=6)
    calls:list[ObservedCall]=Field(max_length=48)
    calls_attempted:int=Field(ge=0,le=48)
    call_budget:int=Field(ge=1,le=48)
    time_budget_seconds:int=Field(ge=1,le=1200)
    usage:ViewerUsage
    mock_fixture_exit_ordinal:int|None=Field(ge=0,le=7)
    is_simulation:Literal[True]
    predicts_real_traffic:Literal[False]
    automatic_resume:Literal[False]
    explicit_new_request_required:Literal[True]


def validate_report(source:AudienceSimulationInput,report:SimulationReport):
    segments=segment_content(source);segment_ids=[s.segment_id for s in segments]
    if (report.version_id!=source.version_id or report.content_hash!=source.content_hash or report.input_hash!=sha256_json(source)
        or report.persona_count!=len(source.personas) or report.segment_count!=len(segments)
        or report.call_budget!=source.max_calls or report.time_budget_seconds!=source.max_active_seconds):
        raise ValueError("report does not match the frozen Audience input")
    if report.calls_attempted!=len(report.calls) or len(report.calls)>source.max_calls:
        raise ValueError("call count does not match the trace or budget")
    if report.mode=="live" and report.mock_fixture_exit_ordinal is not None:raise ValueError("live report cannot use a Mock fixture")
    if [s.persona_id for s in report.sessions]!=[p.id for p in source.personas]:raise ValueError("all frozen personas must be present in order")
    if len({s.session_id for s in report.sessions})!=len(report.sessions):raise ValueError("duplicate session IDs")
    ids=set();event_calls=set();sessions={s.session_id:s for s in report.sessions}
    for session in report.sessions:
        if session.cursor!=len(session.events):raise ValueError("cursor disagrees with committed prefix")
        if session.cursor>len(segments):raise ValueError("too many events")
        for index,record in enumerate(session.events):
            if record.seq!=index or record.event.segment_id!=segment_ids[index]:raise ValueError("event is not a contiguous visible prefix")
            validate_event(record.event,segment_ids[index])
            if record.event_id in ids or record.call_id in event_calls:raise ValueError("event IDs and event call IDs must be globally unique")
            ids.add(record.event_id);event_calls.add(record.call_id)
            if record.event.action=="exit" and index!=len(session.events)-1:raise ValueError("events continue after exit")
        exits=bool(session.events and session.events[-1].event.action=="exit")
        if session.outcome=="exited":
            if not exits or session.stop_reason!="viewer_exit":raise ValueError("exited session has no final exit")
        elif exits:raise ValueError("exit event has a non-exited outcome")
        elif session.outcome=="completed":
            if session.cursor!=len(segments) or session.stop_reason is not None:raise ValueError("completed session is not complete")
        elif session.cursor==len(segments) or session.stop_reason is None:raise ValueError("incomplete session has invalid cursor or reason")
    received={sid:0 for sid in sessions};failed=set();call_ids=set();last_order=-1;unknown_seen=False
    order={s.session_id:i for i,s in enumerate(report.sessions)};by_persona={p.id:p for p in source.personas}
    for call in report.calls:
        if call.call_id in call_ids:raise ValueError("duplicate call ID")
        call_ids.add(call.call_id)
        if call.session_id not in sessions:raise ValueError("call belongs to an unknown session")
        session=sessions[call.session_id];cursor=received[call.session_id]
        if call.persona_id!=session.persona_id or call.mode!=report.mode or call.ordinal!=cursor or call.ordinal>=len(segments):raise ValueError("call scope or ordinal mismatch")
        if order[call.session_id]<last_order or call.session_id in failed or unknown_seen:raise ValueError("call occurs after stop or violates sequential order")
        last_order=order[call.session_id]
        context=AudienceInput(persona=by_persona[session.persona_id],current_segment=segments[cursor],visible_history=segments[:cursor],own_previous_reactions=[r.event for r in session.events[:cursor]])
        if call.input_hash!=sha256_json(context):raise ValueError("call was not bound to the exact persona and prefix")
        if call.status=="received":
            if cursor>=len(session.events):raise ValueError("received call has no committed observation")
            record=session.events[cursor]
            if call.event!=record.event or call.call_id!=record.call_id:raise ValueError("call and observation disagree")
            received[call.session_id]+=1
            if call.event.action=="exit":failed.add(call.session_id)
        else:
            if session.outcome!="incomplete":raise ValueError("failed call cannot close a viewer session successfully")
            expected="unknown_remote_outcome" if call.status=="unknown" else "invalid_or_failed_response"
            if session.stop_reason!=expected:raise ValueError("failure reason mismatch")
            failed.add(call.session_id);unknown_seen=call.status=="unknown"
    for session in report.sessions:
        if received[session.session_id]!=len(session.events):raise ValueError("observation has no received call")
        if session.outcome=="incomplete":
            if session.stop_reason=="call_budget" and len(report.calls)!=source.max_calls:raise ValueError("call budget was not exhausted")
            if session.stop_reason=="unknown_remote_outcome" and not unknown_seen:raise ValueError("no unknown call explains interrupted session")
            if session.stop_reason=="invalid_or_failed_response" and session.session_id not in failed:raise ValueError("no failed call explains incomplete session")
    global_stop=None
    called_sessions={c.session_id for c in report.calls}
    for session in report.sessions:
        if global_stop and (session.outcome!="incomplete" or session.cursor or session.session_id in called_sessions or session.stop_reason!=global_stop):
            raise ValueError("session continues after a global stop")
        if session.outcome=="incomplete" and session.stop_reason in {"call_budget","time_budget","unknown_remote_outcome"}:global_stop=session.stop_reason
    expected_status="INTERRUPTED" if unknown_seen else "COMPLETED" if all(s.outcome in {"completed","exited"} for s in report.sessions) else "INCOMPLETE"
    if report.status!=expected_status:raise ValueError("report status disagrees with outcomes")
    known=[c.usage.total for c in report.calls if c.usage.total is not None]
    expected_usage={"known_total_tokens":sum(known) if known else None,"usage_not_reported_calls":sum(c.usage.total is None for c in report.calls),"remote_outcome_unknown_calls":sum(c.status=="unknown" for c in report.calls)}
    if report.usage.model_dump()!=expected_usage:raise ValueError("viewer usage summary does not match call records")


class AnalystInput(Model):
    analysis_requested:Confirmed
    source:AudienceSimulationInput
    simulation:SimulationReport
    comparison_source:AudienceSimulationInput|None=None
    comparison_simulation:SimulationReport|None=None
    allow_descriptive_comparison:bool=False

    @model_validator(mode="after")
    def validated_observations(self):
        try:validate_report(self.source,self.simulation)
        except Exception as exc:
            # No raw source text or provider error message is echoed.
            raise ValueError("invalid frozen viewer trace") from None
        if (self.comparison_source is None)!=(self.comparison_simulation is None):raise ValueError("provide both comparison source and report")
        if self.comparison_source is not None:
            if not self.allow_descriptive_comparison:raise ValueError("comparison conditions cannot be fully verified; explicit descriptive permission is required")
            if self.comparison_source.version_id==self.source.version_id:raise ValueError("comparison needs a different version ID")
            try:validate_report(self.comparison_source,self.comparison_simulation)
            except Exception:raise ValueError("invalid comparison viewer trace") from None
            for collection,attr in (("sessions","session_id"),("calls","call_id")):
                if {getattr(x,attr) for x in getattr(self.simulation,collection)}&{getattr(x,attr) for x in getattr(self.comparison_simulation,collection)}:
                    raise ValueError("versions must have independent sessions and calls")
            if {r.event_id for s in self.simulation.sessions for r in s.events}&{r.event_id for s in self.comparison_simulation.sessions for r in s.events}:
                raise ValueError("observation IDs cannot be reused across versions")
        elif self.allow_descriptive_comparison:raise ValueError("descriptive comparison permission has no second version")
        return self


class PreviewObservation(Model):
    event_id: Id
    event: AudienceEvent


class PreviewSession(Model):
    session_id: Id
    persona_id: Id
    outcome: Literal["completed", "exited", "incomplete"]
    events: list[PreviewObservation] = Field(max_length=8)


class PreviewAnalysisInput(Model):
    """The workflow persists validated events, not the standalone transport trace."""

    version_id: Id
    content_hash: Hash
    content: ContentDelivery
    personas: list[Persona] = Field(min_length=1, max_length=6)
    segments: list[VisibleSegment] = Field(min_length=1, max_length=8)
    sessions: list[PreviewSession] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def bind_trace(self):
        if content_hash(self.content) != self.content_hash:
            raise ValueError("preview content fingerprint differs")
        if self.segments[0].kind != "cover" or self.segments[0].text != self.content.cover_copy:
            raise ValueError("preview cover differs from the frozen content")
        if [s.model_dump() for s in self.segments[1:]] != [
                s.model_dump(exclude={"source_refs"}) for s in self.content.segments[:7]]:
            raise ValueError("preview segments differ from the frozen prefix")
        segment_ids = [s.segment_id for s in self.segments]
        if len(set(segment_ids)) != len(segment_ids):
            raise ValueError("preview segment IDs must be distinct")
        personas = [p.id for p in self.personas]
        if len(set(personas)) != len(personas) or [s.persona_id for s in self.sessions] != personas:
            raise ValueError("preview sessions must match the frozen personas")
        if len({s.session_id for s in self.sessions}) != len(self.sessions):
            raise ValueError("duplicate preview session ID")
        observed = set()
        for session in self.sessions:
            ids = [r.event.segment_id for r in session.events]
            if ids != segment_ids[:len(ids)]:
                raise ValueError("preview session is not a continuous prefix")
            for ordinal, observation in enumerate(session.events):
                if observation.event_id in observed:
                    raise ValueError("duplicate preview event ID")
                observed.add(observation.event_id)
                try:
                    validate_event(observation.event, ids[ordinal])
                except DomainError:
                    raise ValueError("invalid audience event") from None
                if observation.event.action == "exit" and ordinal != len(ids) - 1:
                    raise ValueError("preview has events after an exit")
            exited = bool(session.events and session.events[-1].event.action == "exit")
            expected = "exited" if exited else "completed" if len(ids) == len(segment_ids) else "incomplete"
            if session.outcome != expected:
                raise ValueError("preview session outcome disagrees with its events")
        return self


def ratio(numerator,denominator):
    return {"numerator":numerator,"denominator":denominator,"value":numerator/denominator if denominator else None}


def summarize_sessions(sessions: list[dict], segment_ids: list[str]) -> dict:
    """Authoritative metric definitions for normalized, validated simulation events."""
    started = sum(bool(session["events"]) for session in sessions)
    completed = sum(session["outcome"] == "completed" for session in sessions)
    observations = [record for session in sessions for record in session["events"]]
    per_segment = []
    for segment_id in segment_ids:
        events = [r["event"] for r in observations if r["event"]["segment_id"] == segment_id]
        exits = sum(event["action"] == "exit" for event in events)
        per_segment.append({"segment_id": segment_id, "seen_sessions": len(events),
                            "exit_sessions": exits, "exit_rate": ratio(exits, len(events))})
    intentions = {}
    for name in ("like", "comment", "save"):
        count = sum(any(name in r["event"].get("interactions", []) for r in session["events"])
                    for session in sessions)
        intentions[name] = ratio(count, started)
    return {"scope": "simulated_sessions_not_humans", "N": len(sessions), "S": started,
            "C": completed, "U": sum(s["outcome"] == "incomplete" for s in sessions),
            "Z": sum(not s["events"] for s in sessions),
            "exited": sum(s["outcome"] == "exited" for s in sessions),
            "coverage_ratio": ratio(started, len(sessions)), "completion_ratio": ratio(completed, started),
            "segments": per_segment, "interaction_intentions": intentions,
            "comments": [{"event_id": r["event_id"], "segment_id": r["event"]["segment_id"],
                          "text": r["event"]["comment_text"]} for r in observations
                         if r["event"].get("comment_text") is not None]}


def summarize(source: AudienceSimulationInput, report: SimulationReport):
    metrics = summarize_sessions([s.model_dump(mode="json") for s in report.sessions],
                                 [segment.segment_id for segment in segment_content(source)])
    return {**metrics, "viewer_calls": report.calls_attempted,
            "failed_calls": sum(c.status == "failed" for c in report.calls),
            "unknown_outcome_calls": sum(c.status == "unknown" for c in report.calls),
            "viewer_usage": report.usage.model_dump(), "viewer_mode": report.mode,
            "mock_fixture_exit_ordinal": report.mock_fixture_exit_ordinal}


def single_version_context() -> dict:
    return {"conditions_match": False, "reason": "单版本分析：没有可比较的第二版。",
            "descriptive_only": True, "alignment_verified": False, "differences": ["no_second_version"]}


def comparison_context(snapshot:AnalystInput):
    if snapshot.comparison_source is None:
        return single_version_context()
    left,right=snapshot.source,snapshot.comparison_source;a,b=snapshot.simulation,snapshot.comparison_simulation
    differences=["model_and_prompt_conditions_not_recorded_or_verified","no_verified_segment_lineage"]
    if left.personas!=right.personas:differences.append("persona_definition_or_order")
    if a.mode!=b.mode:differences.append("viewer_model_mode")
    if left.max_calls!=right.max_calls or left.max_active_seconds!=right.max_active_seconds:differences.append("viewer_budgets")
    if left.max_segments!=right.max_segments:differences.append("segment_limit")
    if a.mock_fixture_exit_ordinal!=b.mock_fixture_exit_ordinal:differences.append("mock_exit_fixture")
    if a.segment_count!=b.segment_count:differences.append("segment_count")
    if [len(s.text) for s in segment_content(left)]!=[len(s.text) for s in segment_content(right)]:differences.append("segment_lengths")
    return {"conditions_match":False,"reason":"仅描述比较：模型、提示词及片段谱系未完整核验，不能宣称同条件实验。","descriptive_only":True,"alignment_verified":False,"differences":differences}
