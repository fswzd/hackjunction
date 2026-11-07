"""编排层 assess_content ↔ 独立审稿员本体(EditorialReviewerAgent)。"""
from __future__ import annotations

from typing import Any, Callable

from backend.adapters.bridge_common import (
    LEGAL_MATERIAL_KINDS, BridgePreSendFailure, error_result, resolve_materials,
    usage_dict)
from backend.agents.editorial_reviewer import (
    EditorialReviewerAgent, ReviewInput, ReviewMaterial)
from backend.domain.hashing import content_hash as business_content_hash
from backend.domain.schemas import Brief, ContentCandidate, Revision
from backend.workflow.five_agent.repository import object_hash


class ReviewerTeamAdapter:
    def __init__(self, *, resolve_material: Callable[[dict], dict],
                 resolve_brief: Callable[[dict], dict] | None = None,
                 resolve_version: Callable[[dict], dict] | None = None,
                 model_adapter: Any | None = None, mode: str = "mock",
                 model_id: str | None = None):
        self.resolve_material = resolve_material
        self.resolve_brief = resolve_brief
        self.resolve_version = resolve_version
        self.agent = EditorialReviewerAgent(model_adapter, mode=mode, model_id=model_id)

    def invoke(self, call) -> dict:
        payload = call.input
        call_dict = {"request_id": getattr(call, "request_id", None),
                     "contract_version": getattr(call, "contract_version", None),
                     "agent_id": getattr(call, "agent_id", "editorial_reviewer"),
                     "action": getattr(call, "action", "assess_content")}
        try:
            if self.resolve_brief is None or self.resolve_version is None:
                raise BridgePreSendFailure("reviewer requires resolve_brief/resolve_version")
            brief_ref = payload["brief_ref"]
            brief_row = self.resolve_brief(brief_ref)
            if brief_row["brief_hash"] != brief_ref.get("brief_hash"):
                raise BridgePreSendFailure("brief fingerprint mismatch")
            brief = Brief.model_validate(brief_row["payload"])
            version_row = self.resolve_version(payload["version_ref"])
            if version_row["content_hash"] != payload["version_ref"].get("sha256"):
                raise BridgePreSendFailure("version fingerprint mismatch")
            version_payload = version_row["payload"]
            if "change_log" in version_payload:
                # 修订版载荷为四键 Revision:编排 content_hash 覆盖全部四键,
                # 以编排口径复核存储载荷完整性;业务口径(business_content_hash
                # 只选 titles/cover_copy/segments 三键)由 ReviewInput 自洽校验。
                content = Revision.model_validate(version_payload)
                if object_hash(version_payload) != version_row["content_hash"]:
                    raise BridgePreSendFailure("version content hash mismatch")
            else:
                content = ContentCandidate.model_validate(version_payload)
                if business_content_hash(content) != version_row["content_hash"]:
                    raise BridgePreSendFailure("version content hash mismatch")
            rows = resolve_materials(payload, self.resolve_material)
            materials = []
            for row in rows:
                kind = row.get("kind") if row.get("kind") in LEGAL_MATERIAL_KINDS else "source_text"
                materials.append(ReviewMaterial(material_id=row["id"], kind=kind,
                                                label=(row.get("label") or row["id"])[:1000],
                                                text=row["text"]))
            # ReviewInput 的业务自洽校验要求 content_hash == content_hash(content)
            # (业务三键口径):3-key 候选时等于编排 content_hash,4-key 修订时必须
            # 换用业务口径哈希,不能把编排四键 object_hash 传入业务模型。
            snapshot = ReviewInput(confirmed=True, version_id=version_row["id"],
                                   content_hash=business_content_hash(content),
                                   brief=brief, content=content, materials=materials)
        except BridgePreSendFailure as exc:
            return error_result(call_dict, str(exc), location="assess_content")
        except Exception as exc:
            return error_result(call_dict, f"bridge input invalid: {exc}",
                                location="assess_content")
        result = self.agent.run(snapshot)
        envelope = result.envelope
        base = {**call_dict, "usage": usage_dict(result.usage)}
        if envelope.status == "ok" and envelope.data is not None:
            return {**base, "status": "ok", "data": envelope.data.model_dump(mode="json"),
                    "questions": [], "issues": []}
        if envelope.status == "needs_input":
            return {**base, "status": "needs_input", "data": None,
                    "questions": [q.model_dump(mode="json") for q in envelope.questions],
                    "issues": [i.model_dump(mode="json") for i in envelope.issues]}
        return {**base, "status": "error", "data": None, "questions": [],
                "issues": [i.model_dump(mode="json") for i in envelope.issues]}
