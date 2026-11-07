"""编排层 draft/revise ↔ 内容主创本体(ContentDirectorAgent)。

draft: 校验 brief_ref 完整性后构造 DirectorInput(业务 brief_hash 自算,
reserved_segment_ids 桥接生成)。revise: 业务本体只接受 existing_draft 修订流,
桥接合成业务 brief(input_mode=existing_draft + edit_scope 取 revision_request
授权范围)与 draft 素材(段落空行连接,逐字等于 base 段落)。

指纹口径(F-O4): 素材引用指纹标准口径 = sha256(canonical {"text": 正文})。
node_draft 已按正文指纹发送素材引用,桥接对 draft 素材执行严格正文指纹校验
(经注入的 resolve_material 从仓库取得正文),非此口径一律确定性拒单。
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable

from backend.adapters.bridge_common import (
    DEFAULT_DERIVED_STYLE, LEGAL_MATERIAL_KINDS, BridgePreSendFailure,
    error_result, resolve_materials, usage_dict)
from backend.agents.director import (
    ContentDirectorAgent, DirectorInput, DirectorMaterial, FrozenContentRules)
from backend.domain.hashing import brief_hash as business_brief_hash
from backend.domain.schemas import Brief, ContentCandidate, EditScope, Issue
from backend.workflow.five_agent.repository import object_hash


def _reserved_pool(brief_hash: str, count: int = 32) -> list[str]:
    stem = hashlib.sha256(f"res:{brief_hash}".encode()).hexdigest()[:16]
    return [f"res_{stem}_{i}" for i in range(count)]


def _synthesized_brief(orchestration_brief: dict, *, input_mode: str,
                       material_ids: list[str], edit_scope: dict | None) -> Brief:
    return Brief(input_mode=input_mode,
                 objective=orchestration_brief.get("objective") or "内容创作任务",
                 audience=orchestration_brief.get("audience") or DEFAULT_DERIVED_STYLE,
                 platform=orchestration_brief.get("platform") or "generic",
                 format="text",
                 core_promise=orchestration_brief.get("core_promise") or "让读者理解并动手",
                 requirements=[dict(r) for r in orchestration_brief.get("requirements") or []] or
                              [{"id": "req_extract", "text": "符合任务书要求"}],
                 material_ids=material_ids, open_questions=[],
                 route=["draft", "review", "export"],
                 length_rule=dict(orchestration_brief.get("length_rule") or
                                  {"minimum": None, "maximum": 20000}),
                 edit_scope=edit_scope)


class DirectorTeamAdapter:
    def __init__(self, *, resolve_material: Callable[[dict], dict],
                 resolve_brief: Callable[[dict], dict] | None = None,
                 resolve_version: Callable[[dict], dict] | None = None,
                 resolve_artifact: Callable[[dict], dict] | None = None,
                 model_adapter: Any | None = None, mode: str = "mock",
                 model_id: str | None = None):
        self.resolve_material = resolve_material
        self.resolve_brief = resolve_brief
        self.resolve_version = resolve_version
        self.resolve_artifact = resolve_artifact
        self.agent = ContentDirectorAgent(model_adapter, mode=mode, model_id=model_id)

    def invoke(self, call) -> dict:
        payload = call.input
        call_dict = {"request_id": getattr(call, "request_id", None),
                     "contract_version": getattr(call, "contract_version", None),
                     "agent_id": getattr(call, "agent_id", "content_creator"),
                     "action": getattr(call, "action", "draft")}
        try:
            if call.action == "draft":
                snapshot, _ = self._build_draft(payload)
            else:
                snapshot, _ = self._build_revise(payload)
        except BridgePreSendFailure as exc:
            return error_result(call_dict, str(exc), location=call.action)
        except Exception as exc:
            return error_result(call_dict, f"bridge input invalid: {exc}", location=call.action)
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

    @staticmethod
    def _material(row: dict) -> DirectorMaterial:
        kind = row.get("kind") if row.get("kind") in LEGAL_MATERIAL_KINDS else "source_text"
        return DirectorMaterial(material_id=row["id"], kind=kind,
                                label=(row.get("label") or row["id"])[:1000],
                                text=row["text"])

    def _draft_materials(self, payload: dict) -> list[DirectorMaterial]:
        """解引用 draft 素材引用并校验指纹(标准口径:严格正文指纹)。"""
        rows = resolve_materials(payload, self.resolve_material)
        return [self._material(row) for row in rows]

    def _build_draft(self, payload: dict) -> tuple[DirectorInput, list[DirectorMaterial]]:
        ref = payload.get("brief_ref") or {}
        if not ref or self.resolve_brief is None:
            raise BridgePreSendFailure("draft requires brief_ref + resolve_brief")
        brief_row = self.resolve_brief(ref)
        if object_hash(brief_row["payload"]) != ref.get("brief_hash"):
            raise BridgePreSendFailure("brief fingerprint mismatch")
        brief = Brief.model_validate(brief_row["payload"])
        if brief.input_mode != "idea":
            raise BridgePreSendFailure("draft requires an idea-mode brief")
        frozen = FrozenContentRules(rule_version="content-rules-v1", title_count=3,
                                    max_body_characters=20000)
        bh = business_brief_hash(brief, frozen.model_dump(mode="json"))
        materials = self._draft_materials(payload)
        snapshot = DirectorInput(confirmed=True, brief=brief, brief_hash=bh,
                                 frozen_rules=frozen, style=DEFAULT_DERIVED_STYLE,
                                 materials=materials,
                                 reserved_segment_ids=_reserved_pool(bh),
                                 base_version_id=None, base_content_hash=None,
                                 base_content=None, edit_requests=[])
        return snapshot, materials

    def _build_revise(self, payload: dict) -> tuple[DirectorInput, list[DirectorMaterial]]:
        if self.resolve_version is None or self.resolve_artifact is None:
            raise BridgePreSendFailure("revise requires resolve_version/resolve_artifact")
        base = self.resolve_version(payload["base_version_ref"])
        if base["content_hash"] != payload["base_version_ref"].get("sha256"):
            raise BridgePreSendFailure("base version fingerprint mismatch")
        request = self.resolve_artifact(payload["revision_request_ref"])
        base_content = ContentCandidate.model_validate(base["payload"])
        if request.get("kind") == "issue_repair":
            locations = request.get("issue_locations", {})
            issue_items = [Issue(id=iid, severity="blocking", location=loc,
                                 reason="按审稿意见修改该段",
                                 requested_change=(request.get("instructions")
                                                   or "只修改该段并保留其余原文"))
                           for iid, loc in locations.items()]
        else:
            locations = request.get("finding_segment", {})
            issue_items = [Issue(id=fid, severity="blocking", location=loc,
                                 reason="按试映发现修改该段",
                                 requested_change=(request.get("instructions")
                                                   or "只修改该段并保留其余原文"))
                           for fid, loc in locations.items()]
        targets = list(locations.values())
        if not issue_items:
            raise BridgePreSendFailure("revision request has no targets")
        old_ids = [s.segment_id for s in base_content.segments]
        preserve = [sid for sid in old_ids if sid not in targets]
        edit_scope = EditScope(target_segment_ids=targets, preserve_segment_ids=preserve,
                               allow_title_change=bool(request.get("allow_title_change")),
                               allow_cover_change=bool(request.get("allow_cover_change")))
        draft_id = "draft_" + hashlib.sha256(base["content_hash"].encode()).hexdigest()[:16]
        draft_text = "\n\n".join(s.text for s in base_content.segments)
        ref = payload.get("brief_ref") or {}
        if not ref or self.resolve_brief is None:
            raise BridgePreSendFailure("revise requires brief_ref + resolve_brief")
        orchestration_brief = self.resolve_brief(ref)["payload"]
        brief = _synthesized_brief(
            orchestration_brief, input_mode="existing_draft",
            material_ids=[draft_id] + list(orchestration_brief.get("material_ids") or []),
            edit_scope=edit_scope.model_dump(mode="json"))
        frozen = FrozenContentRules(rule_version="content-rules-v1", title_count=3,
                                    max_body_characters=20000)
        bh = business_brief_hash(brief, frozen.model_dump(mode="json"))
        draft_material = DirectorMaterial(material_id=draft_id, kind="existing_draft",
                                          label="原稿", text=draft_text)
        # 业务校验要求 materials 恰好覆盖 brief.material_ids 全集:合成草稿素材 +
        # 编排层 brief 声明的原始素材(revise 契约输入没有 material_refs,按 id 直解)。
        materials = [draft_material]
        for mid in orchestration_brief.get("material_ids") or []:
            try:
                row = self.resolve_material({"id": mid})
            except KeyError:
                raise BridgePreSendFailure(f"brief material {mid} cannot be resolved") from None
            if not isinstance(row.get("text"), str):
                raise BridgePreSendFailure(f"material {mid} has no text")
            materials.append(self._material({**row, "id": mid}))
        snapshot = DirectorInput(confirmed=True, brief=brief, brief_hash=bh,
                                 frozen_rules=frozen, style=DEFAULT_DERIVED_STYLE,
                                 materials=materials,
                                 reserved_segment_ids=_reserved_pool(bh),
                                 base_version_id=base["id"],
                                 base_content_hash=base["content_hash"],
                                 base_content=base_content, edit_requests=issue_items)
        return snapshot, materials
