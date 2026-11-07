import copy
import json
from dataclasses import replace

import pytest
from pydantic import ValidationError

from backend.agents.audience import AudienceAgent
from backend.simulation.audience_session import AudienceSimulator,AudienceSimulationInput,segment_content
from backend.domain.schemas import AudienceInput,AudienceEvent
from backend.domain.hashing import content_hash
from backend.domain.errors import DomainError
from backend.adapters.model.mock import MockAdapter
from backend.adapters.model.protocol import ModelUsage,blank_response


def input_data():
    content={"titles":["轻便相机的取舍","带出门才有机会拍","先考虑使用场景"],"cover_copy":"从通勤经验看便携性的选择",
        "segments":[{"segment_id":"s1","kind":"body","text":"作者通勤时愿意携带轻便的相机，这是个人经验。","source_refs":[]},
                    {"segment_id":"s2","kind":"closing","text":"请先确认使用场景，再比较预算与重量。","source_refs":[]}]}
    return {"confirmed":True,"version_id":"v_"+"a"*32,"content_hash":content_hash(content),"content":content,
        "personas":[{"id":"p1","goal":"选一台方便通勤携带的相机","knowledge":"摄影初学者","preferences":["具体例子","短句"]},
                    {"id":"p2","goal":"理解轻便与功能的取舍","knowledge":"有少量拍摄经验","preferences":["说清前提"]}],
        "max_segments":8,"max_calls":6,"max_active_seconds":1200}


def output_data(context,action="continue"):
    return {"schema_version":"creator-agent.v1","status":"ok","summary":"模拟阅读反应",
        "data":{"segment_id":context["current_segment"]["segment_id"],"action":action,"understanding":"理解了当前可见的信息",
            "question":None,"reaction":"希望继续了解","interactions":[],"comment_text":None},
        "evidence_refs":[context["current_segment"]["segment_id"]],"questions":[],"issues":[]}


class Fixture:
    def __init__(self,transform=None):self.requests=[];self.transform=transform
    def complete(self,request):
        self.requests.append(request);context=json.loads(request.messages[1].content);output=output_data(context)
        if self.transform:output=self.transform(context,output)
        response=MockAdapter({request.call_id:json.dumps(output,ensure_ascii=False)}).complete(replace(request,mode="mock"))
        return replace(response,mode=request.mode,usage=ModelUsage(input=10,output=5,total=15))


def agent(fixture):return AudienceAgent(fixture,mode="live",model_id="fixture")


def first_context():
    snapshot=AudienceSimulationInput.model_validate(input_data())
    return AudienceInput(persona=snapshot.personas[0],current_segment=segment_content(snapshot)[0],visible_history=[],own_previous_reactions=[])


def test_full_mock_consumes_exact_segments_and_reports_simulation_not_predictions():
    snapshot=AudienceSimulationInput.model_validate(input_data());before=snapshot.model_dump()
    result=AudienceSimulator().run(snapshot)
    assert result["status"]=="COMPLETED" and result["calls_attempted"]==6
    assert all(s["outcome"]=="completed" and s["cursor"]==3 for s in result["sessions"])
    assert result["is_simulation"] and not result["predicts_real_traffic"] and not result["automatic_resume"]
    assert result["usage"]=={"known_total_tokens":None,"usage_not_reported_calls":6,"remote_outcome_unknown_calls":0}
    assert snapshot.model_dump()==before
    assert all([e["seq"] for e in s["events"]]==[0,1,2] for s in result["sessions"])


def test_prefix_projection_never_leaks_future_other_persona_or_full_source_metadata():
    data=input_data();data["content"]["segments"][1]["text"]="FUTURE_ONLY_SECRET"
    data["content"]["titles"][1]="UNSELECTED_TITLE_SECRET"
    data["personas"][1]["goal"]="OTHER_PERSONA_SECRET"
    data["content_hash"]=content_hash(data["content"])
    fixture=Fixture();result=AudienceSimulator(agent(fixture)).run(AudienceSimulationInput.model_validate(data))
    assert result["status"]=="COMPLETED"
    for index,request in enumerate(fixture.requests):
        context=json.loads(request.messages[1].content);ordinal=index%3
        assert set(context)=={"persona","current_segment","visible_history","own_previous_reactions"}
        assert len(context["visible_history"])==len(context["own_previous_reactions"])==ordinal
        assert "UNSELECTED_TITLE_SECRET" not in str(request.messages)
        if ordinal<2:assert "FUTURE_ONLY_SECRET" not in str(request.messages)
        if index<3:assert "OTHER_PERSONA_SECRET" not in str(request.messages)
        if ordinal==0:assert context["own_previous_reactions"]==[]


def test_exit_terminates_only_that_session_and_no_future_content_is_sent():
    def transform(context,output):
        if context["persona"]["id"]=="p1":output["data"]["action"]="exit"
        return output
    fixture=Fixture(transform);result=AudienceSimulator(agent(fixture)).run(AudienceSimulationInput.model_validate(input_data()))
    assert [s["outcome"] for s in result["sessions"]]==["exited","completed"]
    assert result["calls_attempted"]==4 and result["sessions"][0]["cursor"]==1
    assert sum(json.loads(r.messages[1].content)["persona"]["id"]=="p1" for r in fixture.requests)==1


def test_mock_exit_fixture_is_disclosed_and_impossible_in_live_mode():
    result=AudienceSimulator(mock_exit_after=1).run(AudienceSimulationInput.model_validate(input_data()))
    assert result["mock_fixture_exit_ordinal"]==1 and result["calls_attempted"]==4
    assert all(s["outcome"]=="exited" for s in result["sessions"])
    with pytest.raises(ValueError):AudienceSimulator(agent(Fixture()),mock_exit_after=1)


@pytest.mark.parametrize("mutation",["confirm","hash","video","goals","too_many_segments","duplicate_persona","duplicate_titles","cover_collision","blank","version","budget"])
def test_preflight_rejects_unconfirmed_or_ineligible_sources_without_truncation(mutation):
    data=input_data()
    if mutation=="confirm":data["confirmed"]=1
    elif mutation=="hash":data["content"]["cover_copy"]="改封面"
    elif mutation=="video":data["medium"]="video"
    elif mutation=="goals":data["author_target_score"]=100
    elif mutation=="too_many_segments":data["max_segments"]=2
    elif mutation=="duplicate_persona":data["personas"][1]["id"]="p1"
    elif mutation=="duplicate_titles":data["content"]["titles"]=["同一标题"]*3;data["content_hash"]=content_hash(data["content"])
    elif mutation=="cover_collision":data["content"]["segments"][0]["segment_id"]="cover_"+data["version_id"];data["content_hash"]=content_hash(data["content"])
    elif mutation=="blank":data["personas"][0]["knowledge"]="   "
    elif mutation=="version":data["version_id"]="v_short"
    else:data["max_calls"]=0
    with pytest.raises(ValidationError):AudienceSimulationInput.model_validate(data)


@pytest.mark.parametrize("mutation",["future_id","duplicate_like","empty_question","comment_missing","comment_unasked","blank_reaction","future_evidence","schema","needs_input"])
def test_invalid_or_partial_model_event_is_never_committed(mutation):
    def transform(context,output):
        event=output["data"]
        if mutation=="future_id":event["segment_id"]="s2"
        elif mutation=="duplicate_like":event["interactions"]=["like","like"]
        elif mutation=="empty_question":event["question"]="   "
        elif mutation=="comment_missing":event["interactions"]=["comment"];event["comment_text"]=" "
        elif mutation=="comment_unasked":event["comment_text"]="我有评论"
        elif mutation=="blank_reaction":event["reaction"]="   "
        elif mutation=="future_evidence":output["evidence_refs"]=["s2"]
        elif mutation=="schema":event["event_id"]="model_made_id"
        else:output.update(status="needs_input",questions=[{"id":"q1","question":"补充背景?","reason":"缺少信息"}])
        return output
    fixture=Fixture(transform);data=input_data();data["personas"]=data["personas"][:1]
    result=AudienceSimulator(agent(fixture)).run(AudienceSimulationInput.model_validate(data))
    assert result["status"]=="INCOMPLETE" and result["sessions"][0]["events"]==[]
    assert result["sessions"][0]["cursor"]==0 and result["sessions"][0]["outcome"]=="incomplete"
    assert len(fixture.requests)==1


def test_valid_comment_and_question_are_retained_as_simulated_intents():
    def transform(context,output):
        output["data"].update(interactions=["comment","save"],question="预算需要多少？",comment_text="请说明预算范围。")
        return output
    response=agent(Fixture(transform)).react(first_context())
    assert response.status=="received" and response.event.comment_text=="请说明预算范围。"


def test_previous_exit_blocks_any_new_model_call():
    context=first_context();previous=AudienceEvent(segment_id=context.current_segment.segment_id,action="exit",understanding="已看封面",question=None,reaction="不再继续",interactions=[],comment_text=None)
    snapshot=AudienceSimulationInput.model_validate(input_data());fixture=Fixture()
    next_context=AudienceInput(persona=context.persona,current_segment=segment_content(snapshot)[1],visible_history=[context.current_segment],own_previous_reactions=[previous])
    with pytest.raises(DomainError):agent(fixture).react(next_context)
    assert not fixture.requests


def test_call_budget_preserves_zero_event_sessions_without_faking_exits():
    data=input_data();data["max_calls"]=1
    result=AudienceSimulator().run(AudienceSimulationInput.model_validate(data))
    assert result["status"]=="INCOMPLETE" and result["calls_attempted"]==1
    assert [s["cursor"] for s in result["sessions"]]==[1,0]
    assert all(s["outcome"]=="incomplete" and s["stop_reason"]=="call_budget" for s in result["sessions"])


def test_time_budget_stops_before_next_call():
    data=input_data();data["max_active_seconds"]=1
    ticks=iter([0,0,2]);result=AudienceSimulator(clock=lambda:next(ticks)).run(AudienceSimulationInput.model_validate(data))
    assert result["calls_attempted"]==1 and result["status"]=="INCOMPLETE"
    assert all(s["stop_reason"]=="time_budget" for s in result["sessions"])


@pytest.mark.parametrize("failure",["unknown","exception","failed","truncated","mode","json"])
def test_model_failures_keep_cursor_and_usage_and_never_blindly_retry(failure):
    class Bad(Fixture):
        def complete(self,request):
            response=super().complete(request)
            if failure=="unknown":return blank_response(status="unknown",mode="live",error_code="INTERRUPTED")
            if failure=="exception":raise RuntimeError("SECRET-API-KEY")
            if failure=="failed":return replace(response,status="failed",text=None,error_code="MODEL_UNAVAILABLE")
            if failure=="truncated":return replace(response,finish_reason="length")
            if failure=="mode":return replace(response,mode="mock")
            return replace(response,text="bad-json")
    fixture=Bad();result=AudienceSimulator(agent(fixture)).run(AudienceSimulationInput.model_validate(input_data()))
    assert all(s["events"]==[] and s["cursor"]==0 and s["outcome"]=="incomplete" for s in result["sessions"])
    assert "SECRET-API-KEY" not in json.dumps(result)
    if failure in {"unknown","exception"}:
        assert len(fixture.requests)==1 and result["status"]=="INTERRUPTED"
        assert result["usage"]["known_total_tokens"] is None
    else:assert len(fixture.requests)==2 and result["status"]=="INCOMPLETE"


@pytest.mark.parametrize("mutation",["length","repeat_id","current_seen","no_cover","wrong_reaction_id","blank_content","blank_persona"])
def test_direct_reaction_rejects_invalid_prefix_before_call(mutation):
    original=first_context();snapshot=AudienceSimulationInput.model_validate(input_data());fixture=Fixture()
    previous=AudienceEvent(segment_id=original.current_segment.segment_id,action="continue",understanding="理解封面",question=None,reaction="继续",interactions=[],comment_text=None)
    context=AudienceInput(persona=original.persona,current_segment=segment_content(snapshot)[1],visible_history=[original.current_segment],own_previous_reactions=[previous])
    if mutation=="length":context.own_previous_reactions=[]
    elif mutation=="repeat_id":context.visible_history*=2;context.own_previous_reactions*=2
    elif mutation=="current_seen":context.current_segment=original.current_segment
    elif mutation=="no_cover":context.visible_history=[];context.own_previous_reactions=[]
    elif mutation=="wrong_reaction_id":context.own_previous_reactions[0].segment_id="other"
    elif mutation=="blank_content":context.current_segment.text="   "
    else:context.persona.goal="  "
    with pytest.raises(DomainError):agent(fixture).react(context)
    assert not fixture.requests
