"""复现用例：审稿员架构审计缺陷修复（F-01/F-02/F-04）。

每条测试标注对应审计发现。证据分级：mock 流程 / 接口检查。
"""
import json

import pytest

from backend.workflow.five_agent import adapters as A
from backend.workflow.five_agent.contracts import (
    AgentCall, StepContext, default_validators, frozen_input_hash,
)
from backend.workflow.five_agent.gateway import AgentGateway
from backend.workflow.five_agent.registry import (
    PROMPT_SCHEMA_VERSION, REVIEW_PROMPT_SCHEMA_HASH, step_key_review,
)
from backend.workflow.five_agent.repository import DomainError, Repository

from test_branches import make_driver, new_task, run_content_to_accept


def _review_binding() -> str:
    return f"{PROMPT_SCHEMA_VERSION}+review:{REVIEW_PROMPT_SCHEMA_HASH[:16]}"


# ------------------------------------------------- F-01 material content hash


def test_f01_review_input_binds_material_content_hash():
    """素材 id 相同、正文不同 → assess 输入指纹必须不同。"""
    refs1 = [{"id": "m1", "sha256": "a" * 64}]
    refs2 = [{"id": "m1", "sha256": "b" * 64}]
    base = {"brief_ref": {"task_id": "t", "brief_version": 1, "brief_hash": "h" * 64},
            "version_ref": {"id": "v", "sha256": "c" * 64},
            "rule_report_ref": {"id": "r", "sha256": "d" * 64}}
    h1 = frozen_input_hash({**base, "material_refs": refs1}, _review_binding())
    h2 = frozen_input_hash({**base, "material_refs": refs2}, _review_binding())
    assert h1 != h2, "素材内容 hash 必须进入 assess 输入指纹"


def test_f01_material_change_does_not_replay_stale_review():
    """端到端：素材正文变更后从 review 恢复，不得重放陈旧审稿。"""
    repo, driver = make_driver()
    new_task(driver)
    snap = run_content_to_accept(driver)
    run_id = snap["run_id"]
    review_calls = [c for c in repo.list_calls(run_id) if c["action"] == "assess_content"]
    assert len(review_calls) == 1

    repo._exec("UPDATE materials SET text=? WHERE id='mat1'",
               ("全新素材正文：光线与白平衡。",))
    driver.reinvoke(run_id, {"resume_step": "review",
                             "brief_ref": snap["state"]["brief_ref"],
                             "version_ref": snap["state"]["version_ref"],
                             "rule_ref": snap["state"]["rule_ref"],
                             "repair_count": 0})
    review_calls = [c for c in repo.list_calls(run_id) if c["action"] == "assess_content"]
    assert len(review_calls) == 2, "素材正文变更后必须重新审稿，不得重放旧收据"

    driver.reinvoke(run_id, {"resume_step": "review",
                             "brief_ref": snap["state"]["brief_ref"],
                             "version_ref": snap["state"]["version_ref"],
                             "rule_ref": snap["state"]["rule_ref"],
                             "repair_count": 0})
    assert len([c for c in repo.list_calls(run_id) if c["action"] == "assess_content"]) == 2, \
        "输入未再变时重放零新调用"


def test_f01_review_rejects_brief_referencing_unknown_material():
    repo, driver = make_driver()
    new_task(driver)
    snap = run_content_to_accept(driver)
    brief = repo.latest_brief("task1")
    payload = dict(brief["payload"])
    payload["material_ids"] = ["mat1", "ghost"]
    repo._exec("UPDATE briefs SET payload_json=? WHERE task_id=? AND brief_version=?",
               (json.dumps(payload), "task1", brief["brief_version"]))
    with pytest.raises(DomainError) as err:
        driver.reinvoke(snap["run_id"], {"resume_step": "review",
                                        "brief_ref": snap["state"]["brief_ref"],
                                        "version_ref": snap["state"]["version_ref"],
                                        "rule_ref": snap["state"]["rule_ref"],
                                        "repair_count": 0})
    assert err.value.code == "INPUT_MISSING"


# ------------------------------------------------------- F-02 prompt freeze


def test_f02_review_prompt_hash_is_frozen_not_placeholder():
    assert REVIEW_PROMPT_SCHEMA_HASH != "b" * 64, "占位符不得再存在"
    assert len(REVIEW_PROMPT_SCHEMA_HASH) == 64


def test_f02_prompt_change_invalidates_receipt_replay():
    """prompt/schema 版本参与指纹：换版本不得命中旧收据。"""
    def trivial_review(call, resolver):
        return {"kind": "ok", "usage": A.Usage.known(20).to_dict(),
                "data": {"issues": [], "requirement_checks": [], "claim_checks": [],
                         "overall": "pass"}}

    repo = Repository(":memory:")
    router = A.AdapterRouter(repo, mode="mock",
                             scripts={("editorial_reviewer", "assess_content"): [trivial_review] * 5})
    gateway = AgentGateway(repo, router, validators=default_validators())
    repo.create_task("t1", "acc1", {"goal": "x"})
    repo.create_run("r1", "t1", "content")
    router.bind_task("t1")
    inp = {"brief_ref": {"task_id": "t1", "brief_version": 1, "brief_hash": "a" * 64},
           "version_ref": {"id": "v1", "sha256": "b" * 64},
           "rule_report_ref": {"id": "r1", "sha256": "c" * 64}, "material_refs": []}
    out1 = gateway.invoke("r1", step_key_review("v1"), "assess_content", inp,
                          account_id="acc1", task_id="t1",
                          prompt_schema_version=_review_binding())
    assert out1.replayed is False
    out2 = gateway.invoke("r1", step_key_review("v1"), "assess_content", inp,
                          account_id="acc1", task_id="t1",
                          prompt_schema_version=PROMPT_SCHEMA_VERSION)  # 旧 prompt 版本
    assert out2.replayed is False, "prompt 版本不同不得重放"
    out3 = gateway.invoke("r1", step_key_review("v1"), "assess_content", inp,
                          account_id="acc1", task_id="t1",
                          prompt_schema_version=_review_binding())
    assert out3.replayed is True, "同 prompt 版本同输入的重放零新调用"


# --------------------------------------------- F-04 mock location integrity


def _version_with(segment_ids):
    return {"titles": ["t1", "t2", "t3"], "cover_copy": "封面",
            "segments": [{"segment_id": sid, "kind": "body",
                          "text": f"{sid} 的正文内容", "source_refs": ["mat1"]}
                         for sid in segment_ids]}


class _Resolver:
    def __init__(self, version, requirements):
        self._version = version
        self._requirements = requirements

    def brief(self, ref):
        return {"payload": {"requirements": self._requirements}}

    def version(self, ref):
        return {"payload": self._version}


def test_f04_mock_review_only_references_real_segments():
    call = AgentCall(
        request_id="req1", agent_id="editorial_reviewer", action="assess_content",
        context=StepContext(account_id="a", task_id="t", run_id="r",
                            step_key="review:v", attempt=1, input_hash="h" * 64),
        input={"brief_ref": {}, "version_ref": {}})
    resolver = _Resolver(_version_with(["seg_自定义", "s2"]), [{"id": "r1", "text": "要求"}])
    out = A.gen_review(call, resolver, overall="revise")
    data = out["data"]
    allowed = {"seg_自定义", "s2", "titles", "cover"}
    assert data["issues"][0]["location"] in allowed
    for check in data["requirement_checks"]:
        assert set(check["evidence_refs"]) <= allowed
    for claim in data["claim_checks"]:
        assert claim["location"] in allowed


def test_f04_mock_review_without_segments_anchors_cover():
    call = AgentCall(
        request_id="req2", agent_id="editorial_reviewer", action="assess_content",
        context=StepContext(account_id="a", task_id="t", run_id="r",
                            step_key="review:v", attempt=1, input_hash="h" * 64),
        input={"brief_ref": {}, "version_ref": {}})
    resolver = _Resolver({"titles": ["t"], "cover_copy": "c", "segments": []}, [])
    out = A.gen_review(call, resolver, overall="pass")
    data = out["data"]
    assert data["claim_checks"][0]["location"] == "cover"
