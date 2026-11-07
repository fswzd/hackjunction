"""独立审稿员真实入口桥接:输入映射/契约包封/mock 语义。"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BC_BACKEND = ROOT / "birthco-local" / "backend"

import backend  # noqa: E402
if str(BC_BACKEND) not in backend.__path__:
    backend.__path__.append(str(BC_BACKEND))

from backend.adapters.bridge_common import orchestration_ref_digest  # noqa: E402
from backend.adapters.reviewer_bridge import ReviewerTeamAdapter  # noqa: E402
from backend.workflow.five_agent.repository import Repository  # noqa: E402

BRIEF_PAYLOAD = {
    "input_mode": "idea", "objective": "写一篇新手拍照入门图文",
    "audience": "对目标话题感兴趣的新手读者", "platform": "图文平台", "format": "text",
    "core_promise": "让读者理解并能动手实践", "requirements": [{"id": "r1", "text": "口语化"}],
    "material_ids": ["m1"], "open_questions": [], "route": ["draft", "review", "export"],
    "length_rule": {"minimum": 300, "maximum": 20000}, "edit_scope": None,
}
VERSION_PAYLOAD = {
    "titles": ["t1", "t2", "t3"], "cover_copy": "封面",
    "segments": [{"segment_id": "s1", "kind": "hook", "text": "你是否也遇到过构图问题", "source_refs": ["m1"]},
                 {"segment_id": "s2", "kind": "body", "text": "第一步，先学会三分法。", "source_refs": ["m1"]},
                 {"segment_id": "s3", "kind": "closing", "text": "先完成再完善。", "source_refs": []}],
}


def _make():
    repo = Repository(":memory:")
    repo.create_task("t1", "account", {"goal": "x"})
    repo.add_material("t1", "m1", "拍照入门：先学会构图三分法，再练光线。")
    repo.save_brief("t1", BRIEF_PAYLOAD, [])
    brief = repo.latest_brief("t1")
    version = repo.save_version("ver_abc", "t1", "run1", None, VERSION_PAYLOAD)
    adapter = ReviewerTeamAdapter(
        resolve_brief=lambda ref: repo.get_brief(ref["task_id"], ref["brief_version"]),
        resolve_material=lambda ref: repo.list_materials("t1")[0],
        resolve_version=lambda ref: repo.get_version(ref["id"]),
        mode="mock")
    return repo, adapter, brief, version


def _call(brief, version):
    return SimpleNamespace(request_id="req_1", agent_id="editorial_reviewer",
                           action="assess_content", contract_version="seven-agent.v0.1",
                           context=SimpleNamespace(task_id="t1", account_id="account"),
                           input={"brief_ref": {"task_id": "t1", "brief_version": brief["brief_version"],
                                                "brief_hash": brief["brief_hash"]},
                                  "version_ref": {"id": version["id"], "sha256": version["content_hash"]},
                                  "rule_report_ref": {"id": "rule_1", "sha256": "0" * 64},
                                  "material_refs": [{"id": "m1",
                                                     "sha256": orchestration_ref_digest(
                                                         "拍照入门：先学会构图三分法，再练光线。")}]})


def test_review_envelope_maps_to_editorial_review():
    repo, adapter, brief, version = _make()
    out = adapter.invoke(_call(brief, version))
    assert out["status"] in ("ok", "needs_input"), out
    if out["status"] == "ok":
        assert set(out["data"]) == {"issues", "requirement_checks", "claim_checks", "overall"}
    else:
        assert out["questions"]  # mock 语义:结构通过但语义待核实 → needs_input
    assert out["usage"]["status"] in ("known", "unknown")


def test_version_hash_mismatch_is_error():
    repo, adapter, brief, version = _make()
    call = _call(brief, version)
    call.input["version_ref"]["sha256"] = "0" * 64
    out = adapter.invoke(call)
    assert out["status"] == "error"


def test_brief_hash_mismatch_is_error():
    repo, adapter, brief, version = _make()
    call = _call(brief, version)
    call.input["brief_ref"]["brief_hash"] = "0" * 64
    out = adapter.invoke(call)
    assert out["status"] == "error"


def test_material_fingerprint_mismatch_is_error():
    repo, adapter, brief, version = _make()
    call = _call(brief, version)
    call.input["material_refs"][0]["sha256"] = "0" * 64
    out = adapter.invoke(call)
    assert out["status"] == "error"


REVISION_PAYLOAD = {
    "titles": ["新手拍照入门", "三步学会构图", "先完成再完善"],
    "cover_copy": "零基础也能看懂的拍照入门",
    "segments": [{"segment_id": "s1", "kind": "hook", "text": "你是否也遇到过构图问题",
                  "source_refs": ["m1"]},
                 {"segment_id": "s2", "kind": "body",
                  "text": "三分法是最基础的构图方法。" * 30,
                  "source_refs": ["m1"]},
                 {"segment_id": "s3", "kind": "closing", "text": "先完成再完善。",
                  "source_refs": []}],
    "change_log": [{"finding_id": None, "issue_id": "i1",
                    "old_segment_id": "s2", "new_segment_id": "s2b",
                    "change": "replace", "reason": "按审稿意见修改该段"}],
}


def test_revision_payload_is_reviewed_not_rejected():
    """修订版四键 Revision 载荷必须正常进入业务审稿,而非确定性桥接拒单
    (ContentCandidate extra=forbid 曾经拒掉一切 change_log 载荷)。"""
    repo = Repository(":memory:")
    repo.create_task("t1", "account", {"goal": "x"})
    repo.add_material("t1", "m1", "拍照入门：先学会构图三分法，再练光线。")
    repo.save_brief("t1", BRIEF_PAYLOAD, [])
    brief = repo.latest_brief("t1")
    version = repo.save_version("ver_rev", "t1", "run1", None, REVISION_PAYLOAD)
    adapter = ReviewerTeamAdapter(
        resolve_brief=lambda ref: repo.get_brief(ref["task_id"], ref["brief_version"]),
        resolve_material=lambda ref: repo.list_materials("t1")[0],
        resolve_version=lambda ref: repo.get_version(ref["id"]),
        mode="mock")
    out = adapter.invoke(_call(brief, version))
    assert out["status"] in ("ok", "needs_input", "error"), out
    if out["status"] == "error":
        reason = out["issues"][0]["reason"]
        assert "bridge input invalid" not in reason
        assert "Extra inputs are not permitted" not in reason
    else:
        # mock 语义:业务规则通过(3 段 hook/body/closing、正文 ≥300 非空白字符)
        # → 结构通过但语义待核实 → needs_input。
        assert out["status"] == "needs_input" and out["questions"], out
    assert "bridge input invalid" not in json.dumps(out, ensure_ascii=False).lower()
    assert "extra inputs are not permitted" not in json.dumps(out, ensure_ascii=False).lower()
