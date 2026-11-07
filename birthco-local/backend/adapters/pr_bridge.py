"""编排层 analyze_request ↔ 商单需求分析员本体(PRAnalystAgent)。

输入:contract input {request_text, material_refs};业务侧无结构化 requirements 传入
(contract input_types 不含),桥接注入占位 requirement(req_extract,"从任务中整理交付要求")
——本体校验要求原有 requirement 的 id 与逐字文本必须保留,mock 提取按此回显,不凭空
杜撰客户要求。intake 以 request_text 作为 objective 显式字段(本体校验要求提取结果
逐字保留显式 intake 字段;其余 8 个字段为 null——mock 下因此触发缺必填字段追问)。
素材经 resolve_materials 解引用并核对 sha256 指纹(F-O4);kind 不在业务合法集合时
落 source_text(PR 本体拒绝 existing_draft 素材,届时由 pydantic 确定性拒单)。
输出:PRAnalysisResult.envelope -> RequestAnalysis data;业务 source 引用(material_N)
不回传,source_refs = 全部已解析素材的编排层 id(均已被提供)。unprovided_business_fields
取自 envelope data 中 budget/deadline/approver 三个值为 null 的字段(与本体 as_dict 同义)。
失败映射:指纹不符/无法解析/构造失败 → 已知 error 结果(零模型调用、不烧预算)。
"""
from __future__ import annotations

from typing import Any, Callable

from backend.adapters.bridge_common import (
    LEGAL_MATERIAL_KINDS, PLACEHOLDER_REQUIREMENT, BridgePreSendFailure,
    error_result, resolve_materials, usage_dict)
from backend.agents.pr_analyst import PRAnalysisInput, PRIntake, PRAnalystAgent
from backend.domain.schemas import LengthRule, MaterialInput


class PRAnalystTeamAdapter:
    """编排层 AgentAdapter 兼容入口(duck-typed call)。

    call 需提供 .request_id/.agent_id/.action/.contract_version/.input/.context
    (context 至少含 account_id);`resolve_material(ref) -> row` 由调用方注入
    (授权范围=本 task 的素材)。mock 模式零网络;live 需显式 model_adapter 与
    model_id(与本体门禁一致)。
    """

    def __init__(self, *, resolve_material: Callable[[dict], dict],
                 model_adapter: Any | None = None, mode: str = "mock",
                 model_id: str | None = None):
        self.resolve_material = resolve_material
        self.agent = PRAnalystAgent(model_adapter, mode=mode, model_id=model_id)

    def invoke(self, call) -> dict:
        payload = call.input
        call_dict = {"request_id": getattr(call, "request_id", None),
                     "contract_version": getattr(call, "contract_version", None),
                     "agent_id": getattr(call, "agent_id", "pr_analyst"),
                     "action": getattr(call, "action", "analyze_request")}
        account_id = getattr(call.context, "account_id", None) or "account"
        try:
            rows = resolve_materials(payload, self.resolve_material)
            materials = []
            for row in rows:
                kind = row.get("kind") if row.get("kind") in LEGAL_MATERIAL_KINDS else "source_text"
                materials.append(MaterialInput(kind=kind, label=(row.get("label") or row["id"])[:1000],
                                               text=row["text"], source_url=row.get("source_url"),
                                               authorized=True))
            request_text = (payload.get("request_text") or "").strip() or "商单需求"
            snapshot = PRAnalysisInput(
                analysis_requested=True, account_id=account_id,
                client_brief=None, intake=PRIntake(objective=request_text[:1000]),
                requirements=[dict(r) for r in PLACEHOLDER_REQUIREMENT],
                materials=materials, length_rule=LengthRule(minimum=None, maximum=20000))
        except BridgePreSendFailure as exc:
            return error_result(call_dict, str(exc), location="analyze_request")
        except Exception as exc:  # pydantic 构造失败:确定性拒单
            return error_result(call_dict, f"bridge input invalid: {exc}",
                                location="analyze_request")
        result = self.agent.run(snapshot)
        envelope = result.envelope
        base = {**call_dict, "usage": usage_dict(result.usage)}
        material_ids = [row["id"] for row in rows]
        if envelope.status == "ok":
            data = envelope.data
            unprovided = [f.field for f in data.fields
                          if f.field in {"budget", "deadline", "approver"} and f.value is None]
            return {**base, "status": "ok",
                    "data": {"summary": envelope.summary[:2000],
                             "requirements": [{"id": r.id, "text": r.text}
                                              for r in data.requirements],
                             "open_questions": [q.model_dump(mode="json") for q in envelope.questions],
                             "unprovided_business_fields": unprovided,
                             "ready_for_operator": result.task_draft is not None,
                             "source_refs": material_ids[:20]},
                    "questions": [], "issues": []}
        if envelope.status == "needs_input":
            return {**base, "status": "needs_input", "data": None,
                    "questions": [q.model_dump(mode="json") for q in envelope.questions],
                    "issues": [i.model_dump(mode="json") for i in envelope.issues]}
        return {**base, "status": "error", "data": None, "questions": [],
                "issues": [i.model_dump(mode="json") for i in envelope.issues]}
