"""运营官记忆层测试：准入纪律、supersede 决策、三轮迭代检索、桥接注入。"""
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.adapters.model.mock import MockAdapter
from backend.adapters.orch_bridge import OperatorTeamAdapter
from backend.memory.operator_memory import (
    MemoryAdmissionError, OperatorMemory, iterative_retrieve, terms_of,
)
from backend.storage.db import connect, migrate


@pytest.fixture()
def memory(tmp_path):
    path = migrate(tmp_path)
    db = connect(path)
    try:
        db.execute("INSERT INTO accounts (id, name, row_version) VALUES ('acct','测试账号',0)")
        yield OperatorMemory(db)
    finally:
        db.close()


def test_create_read_returns_active_only(memory):
    memory.create("acct", kind="user_preference", statement="受众偏好：摄影新手",
                  source_ref="user_statement:u1")
    old_id = memory.create("acct", kind="user_preference", statement="平台偏好：小红书",
                           source_ref="user_statement:u1")
    memory.supersede("acct", old_id, statement="平台偏好：B站", source_ref="user_statement:u2")
    rows = memory.read("acct", keywords=["偏好"])
    statements = [r["statement"] for r in rows]
    assert "平台偏好：B站" in statements and "平台偏好：小红书" not in statements
    assert memory.history("acct", old_id)["status"] == "superseded"


def test_admission_rejects_secrets_and_unsourced_preferences(memory):
    with pytest.raises(MemoryAdmissionError):
        memory.create("acct", kind="observed_feedback", statement="key sk-abcdefghijklmno123456",
                      source_ref="agent:run1")
    with pytest.raises(MemoryAdmissionError):
        memory.create("acct", kind="user_preference", statement="风格偏好：克制",
                      source_ref="agent:inferred")
    with pytest.raises(MemoryAdmissionError):
        memory.create("acct", kind="invented", statement="x", source_ref="user_statement:u1")


def test_agent_assertions_cannot_supersede_user_facts(memory):
    user_id = memory.create("acct", kind="user_preference", statement="受众偏好：摄影新手",
                            source_ref="user_statement:u1")
    with pytest.raises(MemoryAdmissionError):
        memory.supersede("acct", user_id, statement="受众偏好：专业玩家", source_ref="agent:inferred")
    assert memory.history("acct", user_id)["status"] == "active"


def test_user_correction_supersedes_anything(memory):
    agent_id = memory.create("acct", kind="simulation_hypothesis", statement="风格猜测：活泼",
                             source_ref="agent:run1")
    new_id = memory.supersede("acct", agent_id, statement="风格偏好：克制",
                              source_ref="user_statement:u2")
    assert memory.history("acct", agent_id)["status"] == "superseded"
    assert memory.history("acct", new_id)["supersedes_id"] == agent_id


def test_withdraw_and_record_brief_decision(memory):
    assert memory.record_brief_decision("acct", {"audience": "新手", "platform": "小红书"},
                                        accepted=False, source_ref="user_statement:u1") == []
    created = memory.record_brief_decision("acct", {"audience": "新手", "platform": "小红书"},
                                           accepted=True, source_ref="user_statement:u1")
    assert len(created) == 2
    rows = memory.read("acct", kinds=("user_preference",))
    assert {r["statement"] for r in rows} == {"受众偏好：新手", "平台偏好：小红书"}
    memory.withdraw("acct", created[0])
    assert memory.history("acct", created[0])["status"] == "withdrawn"


def test_iterative_retrieve_refines_gaps_within_three_rounds(memory):
    memory.create("acct", kind="user_preference", statement="受众偏好：摄影新手",
                  source_ref="user_statement:u1")
    memory.create("acct", kind="user_preference", statement="风格偏好：清楚、克制",
                  source_ref="user_statement:u1")
    memory.create("acct", kind="user_preference", statement="平台偏好：小红书",
                  source_ref="user_statement:u1")
    report = iterative_retrieve(memory, "acct", seed_terms=["偏好"],
                                aspects=["受众", "平台", "风格", "篇幅", "要求"])
    assert report["trust"] == "unreviewed"
    assert report["rounds_used"] <= 3
    assert set(report["covered_aspects"]) == {"受众", "平台", "风格"}
    assert report["gaps"] == ["篇幅", "要求"]
    assert {s["statement"] for s in report["statements"]} >= {"受众偏好：摄影新手"}


def test_terms_of_extracts_cjk_bigrams_and_words():
    terms = terms_of("写一篇新手拍照入门图文 for photographers", limit=30)
    assert "写一篇新手拍照入门图文" in terms and "新手" in terms and "photographers" in terms


class FixtureAdapter:
    def __init__(self, output):
        self.output, self.requests = output, []

    def complete(self, request):
        self.requests.append(request)
        result = MockAdapter({request.call_id: json.dumps(self.output, ensure_ascii=False)}).complete(
            replace(request, mode="mock"))
        return replace(result, mode=request.mode)


def test_bridge_injects_memory_as_untrusted_user_data_not_system(memory):
    memory.create("acct", kind="user_preference", statement="受众偏好：摄影新手",
                  source_ref="user_statement:u1")
    call = SimpleNamespace(
        request_id="req_1", agent_id="operations_officer", action="prepare_brief",
        contract_version="seven-agent.v0.1", context=SimpleNamespace(account_id="acct"),
        input={"user_input": "写一篇新手拍照入门图文", "input_mode": "idea",
               "material_refs": [], "selected_opportunity_ref": None})
    mock_adapter = OperatorTeamAdapter(resolve_material=lambda ref: {}, memory=memory)
    first = mock_adapter.invoke(call)
    assert first["status"] == "ok"
    assert mock_adapter.last_retrieval["statements"], "检索结果已记录"
    envelope = {"schema_version": "creator-agent.v1", "status": "ok", "summary": "fixture",
                "data": first["data"], "evidence_refs": [], "questions": [], "issues": []}
    live = OperatorTeamAdapter(resolve_material=lambda ref: {}, memory=memory,
                               model_adapter=FixtureAdapter(envelope),
                               mode="live", model_id="fixture-model")
    result = live.invoke(call)
    assert result["status"] == "ok"
    request = live.agent.adapter.requests[0]
    assert "受众偏好：摄影新手" in request.messages[1].content, "记忆进 user 数据区"
    assert "受众偏好" not in request.messages[0].content, "记忆绝不进 system 指令区"
    assert "trust=unreviewed" in request.messages[1].content
