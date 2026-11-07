"""F-03 回归：主创素材引用必须按真实正文指纹，禁止哈希 ID。

指纹约定 = sha256(canonical JSON of {"text": 正文})，与真实桥接
（birthco-local orch_bridge F-O4 的 orchestration_ref_digest）一致。
"""
from __future__ import annotations

import hashlib

import pytest

from backend.workflow.five_agent import nodes as N
from backend.workflow.five_agent.contracts import canonical_json
from backend.workflow.five_agent.graphstate import Services
from backend.workflow.five_agent.repository import DomainError, Repository, object_hash


def make_svc(task_id="task1", materials=(("mat1", "构图三分法，再练光线。"),)):
    repo = Repository(":memory:")
    repo.create_task(task_id, "acc", {"goal": "g"})
    for mid, text in materials:
        repo.add_material(task_id, mid, text)
    return Services(repo=repo, gateway=None, router=None, account_id="acc")


def bridge_digest(text: str) -> str:
    """真实桥接认可的指纹（orch_bridge F-O4 约定）。"""
    return hashlib.sha256(canonical_json({"text": text})).hexdigest()


def test_fingerprint_is_text_digest_not_id_digest():
    svc = make_svc()
    refs = N._material_refs(svc, "task1", ["mat1"])
    text = "构图三分法，再练光线。"
    assert refs[0]["sha256"] == bridge_digest(text) == object_hash({"text": text})
    assert refs[0]["sha256"] != object_hash({"text": "mat1"}), "禁止哈希 ID 冒充正文指纹"


def test_fingerprint_changes_when_text_changes():
    svc_a = make_svc(materials=(("mat1", "版本 A 的正文"),))
    svc_b = make_svc(materials=(("mat1", "版本 B 的正文"),))
    sha_a = N._material_refs(svc_a, "task1", ["mat1"])[0]["sha256"]
    sha_b = N._material_refs(svc_b, "task1", ["mat1"])[0]["sha256"]
    assert sha_a != sha_b, "同一素材 ID 正文变化，指纹必须变化（缓存/收据不得复用陈旧结果）"


def test_missing_material_rejected_with_input_missing():
    svc = make_svc()
    with pytest.raises(DomainError) as exc:
        N._material_refs(svc, "task1", ["mat1", "mat_ghost"])
    assert exc.value.code == "INPUT_MISSING"


def test_cross_task_material_not_served():
    svc = make_svc(task_id="task_a", materials=(("mat1", "A 的素材"),))
    svc.repo.create_task("task_b", "acc", {"goal": "g"})
    with pytest.raises(DomainError):
        N._material_refs(svc, "task_b", ["mat1"]), "按任务归属解引用，拒绝跨任务素材"


def test_draft_call_carries_real_text_fingerprint():
    """集成锚点：主创调用输入里的指纹 = 真实正文指纹（真实桥接可接受）。"""
    from backend.workflow.five_agent.adapters import AdapterRouter
    from backend.workflow.five_agent.driver import OrchestrationDriver
    repo = Repository(":memory:")
    router = AdapterRouter(repo, mode="mock")
    driver = OrchestrationDriver(repo, router=router)
    text = "拍照入门：先学会构图三分法，再练光线。"
    driver.create_task("t1", {"goal": "写一篇新手拍照入门图文", "user_input": "写一篇新手拍照入门图文",
                              "input_mode": "idea", "purpose": "content",
                              "flags": {"traffic_enabled": False, "goal_clear": True}})
    driver.add_material("t1", "mat1", text)
    snap = driver.start_content_run("t1")
    brief = snap["state"]["brief_ref"]
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True,
                         payload={"brief_version": brief["brief_version"], "brief_hash": brief["brief_hash"]})
    draft_calls = [i for i in router.mock("content_creator").invocations if i["action"] == "draft"]
    assert draft_calls, "应发生主创调用"
    refs = draft_calls[0]["model_visible_input"]["material_refs"]
    assert refs == [{"id": "mat1", "sha256": bridge_digest(text)}]
