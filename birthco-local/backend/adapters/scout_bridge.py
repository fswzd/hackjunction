"""编排层 capture_opportunities ↔ 流量捕捉者本体(ScoutAgent)。

编排 input 无账号档案/任务书:account 与 brief 由桥接派生缺省(明确标注为派生,
不进真实素材)。素材 id 与编排命名空间一致,输出无需回映。
"""
from __future__ import annotations

from typing import Any, Callable

from backend.adapters.bridge_common import (
    DEFAULT_DERIVED_AUDIENCE, DEFAULT_DERIVED_STYLE, LEGAL_MATERIAL_KINDS,
    BridgePreSendFailure, error_result, resolve_materials, usage_dict)
from backend.agents.scout import ScoutAccount, ScoutAgent, ScoutInput, ScoutMaterial
from backend.domain.schemas import Brief


class ScoutTeamAdapter:
    def __init__(self, *, resolve_material: Callable[[dict], dict],
                 model_adapter: Any | None = None, mode: str = "mock",
                 model_id: str | None = None):
        self.resolve_material = resolve_material
        self.agent = ScoutAgent(model_adapter, mode=mode, model_id=model_id)

    def invoke(self, call) -> dict:
        payload = call.input
        call_dict = {"request_id": getattr(call, "request_id", None),
                     "contract_version": getattr(call, "contract_version", None),
                     "agent_id": getattr(call, "agent_id", "traffic_scout"),
                     "action": getattr(call, "action", "capture_opportunities")}
        account_id = getattr(call.context, "account_id", None) or "account"
        try:
            rows = resolve_materials(payload, self.resolve_material)
            materials = []
            for row in rows:
                kind = row.get("kind") if row.get("kind") in LEGAL_MATERIAL_KINDS else "source_text"
                materials.append(ScoutMaterial(material_id=row["id"], kind=kind,
                                               label=(row.get("label") or row["id"])[:1000],
                                               text=row["text"], authorized=True,
                                               source_url=row.get("source_url")))
            goal = (payload.get("goal") or "选题").strip()
            brief = Brief(input_mode="idea", objective=goal[:1000],
                          audience=DEFAULT_DERIVED_AUDIENCE, platform="generic",
                          format="text", core_promise=f"围绕目标整理选题：{goal[:80]}",
                          requirements=[{"id": "req_extract", "text": "从任务中整理交付要求"}],
                          material_ids=[m.material_id for m in materials],
                          open_questions=[], route=["draft", "review", "export"],
                          length_rule={"minimum": None, "maximum": 20000},
                          edit_scope=None)
            account = ScoutAccount(account_id=account_id,
                                   positioning=f"围绕任务目标：{goal[:500]}",
                                   audience=DEFAULT_DERIVED_AUDIENCE,
                                   style=DEFAULT_DERIVED_STYLE)
            snapshot = ScoutInput(research_requested=True, account=account, brief=brief,
                                  materials=materials, max_opportunities=3)
        except BridgePreSendFailure as exc:
            return error_result(call_dict, str(exc), location="capture_opportunities")
        except Exception as exc:
            return error_result(call_dict, f"bridge input invalid: {exc}",
                                location="capture_opportunities")
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
