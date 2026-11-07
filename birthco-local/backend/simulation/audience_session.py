"""Local, sequential simulator. Full content stays here, outside model context."""
import re
import time
from uuid import uuid4

from pydantic import Field,model_validator

from backend.agents.audience import AudienceAgent
from backend.domain.hashing import content_hash,sha256_json
from backend.domain.schemas import Model,Confirmed,Id,Hash,ContentDelivery,Persona,VisibleSegment,AudienceInput


class AudienceSimulationInput(Model):
    confirmed:Confirmed
    version_id:Id
    content_hash:Hash
    content:ContentDelivery
    personas:list[Persona]=Field(min_length=1,max_length=6)
    max_segments:int=Field(default=8,ge=1,le=8)
    max_calls:int=Field(ge=1,le=48)
    max_active_seconds:int=Field(default=1200,ge=1,le=1200)

    @model_validator(mode="after")
    def frozen_content(self):
        if not re.fullmatch(r"v_[a-f0-9]{32}",self.version_id):raise ValueError("version_id must be v_ followed by 32 lowercase hex digits")
        if content_hash(self.content)!=self.content_hash:raise ValueError("content hash mismatch")
        if len({t.strip() for t in self.content.titles})!=3:raise ValueError("the frozen content must have three distinct titles")
        if len(self.content.segments)+1>self.max_segments:raise ValueError("cover plus full body exceeds max_segments; never truncate content")
        if "cover_"+self.version_id in {s.segment_id for s in self.content.segments}:raise ValueError("body ID collides with the synthetic cover ID")
        if any(not s.text.strip() for s in self.content.segments):raise ValueError("body segments cannot be blank")
        if sum(1 for s in self.content.segments for c in s.text if not c.isspace())>20000:raise ValueError("content exceeds 20,000 non-whitespace characters")
        if len({p.id for p in self.personas})!=len(self.personas):raise ValueError("persona IDs must be unique")
        if any(not p.goal.strip() or not p.knowledge.strip() or any(not x.strip() for x in p.preferences) for p in self.personas):raise ValueError("personas must be readable")
        return self


def segment_content(snapshot:AudienceSimulationInput):
    return [VisibleSegment(segment_id="cover_"+snapshot.version_id,kind="cover",text=snapshot.content.titles[0]+"\n"+snapshot.content.cover_copy)]+[
        VisibleSegment(segment_id=s.segment_id,kind=s.kind,text=s.text) for s in snapshot.content.segments]


class AudienceSimulator:
    def __init__(self,agent:AudienceAgent|None=None,*,mock_exit_after:int|None=None,clock=None):
        self.agent=agent or AudienceAgent();self.clock=clock or time.monotonic
        if mock_exit_after is not None:
            if type(mock_exit_after) is not int or not 0<=mock_exit_after<=7:raise ValueError("Mock exit ordinal must be 0-7")
            if self.agent.mode!="mock":raise ValueError("Mock fixture cannot control live viewers")
        self.mock_exit_after=mock_exit_after

    def run(self,snapshot:AudienceSimulationInput):
        if not isinstance(snapshot,AudienceSimulationInput):raise TypeError("snapshot must be AudienceSimulationInput")
        snapshot=AudienceSimulationInput.model_validate(snapshot.model_dump(mode="python"))
        segments=segment_content(snapshot);start=self.clock();sessions=[];calls=[];stop_all=None;interrupted=False
        for persona in snapshot.personas:
            session={"session_id":"session_"+uuid4().hex,"persona_id":persona.id,"outcome":"incomplete","stop_reason":None,"cursor":0,"events":[]}
            sessions.append(session);history=[];own=[]
            if stop_all:session["stop_reason"]=stop_all;continue
            for ordinal,current in enumerate(segments):
                remaining=snapshot.max_active_seconds-(self.clock()-start)
                if len(calls)>=snapshot.max_calls:stop_all="call_budget";session["stop_reason"]=stop_all;break
                if remaining<=0:stop_all="time_budget";session["stop_reason"]=stop_all;break
                # This projection has exactly four fields: no total, full content or other personas.
                context=AudienceInput(persona=persona,current_segment=current,visible_history=list(history),own_previous_reactions=list(own))
                reaction=self.agent.react(context,timeout_seconds=min(90,remaining),mock_exit=self.mock_exit_after==ordinal)
                calls.append({"session_id":session["session_id"],"persona_id":persona.id,"ordinal":ordinal,**reaction.as_dict()})
                if reaction.status!="received":
                    session["stop_reason"]="unknown_remote_outcome" if reaction.status=="unknown" else "invalid_or_failed_response"
                    if reaction.status=="unknown":
                        interrupted=True;stop_all="unknown_remote_outcome"
                    break
                event=reaction.event
                session["events"].append({"event_id":"event_"+uuid4().hex,"seq":ordinal,"call_id":reaction.call_id,"event":event.model_dump(mode="json")})
                session["cursor"]+=1;history.append(current);own.append(event)
                if event.action=="exit":session.update(outcome="exited",stop_reason="viewer_exit");break
                if ordinal==len(segments)-1:session.update(outcome="completed",stop_reason=None)
        known=[c["usage"]["total"] for c in calls if c["usage"]["total"] is not None]
        status="INTERRUPTED" if interrupted else "COMPLETED" if all(s["outcome"] in {"completed","exited"} for s in sessions) else "INCOMPLETE"
        return {"mode":self.agent.mode,"medium":"text","version_id":snapshot.version_id,"content_hash":snapshot.content_hash,
            "input_hash":sha256_json(snapshot),"status":status,"persona_count":len(sessions),"segment_count":len(segments),
            "sessions":sessions,"calls":calls,"calls_attempted":len(calls),"call_budget":snapshot.max_calls,"time_budget_seconds":snapshot.max_active_seconds,
            "usage":{"known_total_tokens":sum(known) if known else None,"usage_not_reported_calls":sum(c["usage"]["total"] is None for c in calls),"remote_outcome_unknown_calls":sum(c["status"]=="unknown" for c in calls)},
            "mock_fixture_exit_ordinal":self.mock_exit_after,"is_simulation":True,"predicts_real_traffic":False,
            "automatic_resume":False,"explicit_new_request_required":True}
