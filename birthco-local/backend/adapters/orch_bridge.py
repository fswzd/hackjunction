"""桥接夹具：编排层 prepare_brief 调用 ↔ 运营官本体（CreateTask/EditScope）。

设计决策（审计 F-O1/F-O2/F-O3/F-O4/F-O5/F-O6 的落地）：

- **唯一校验入口**：真实调用一律经 `OperatorAgent.run`（含 validate_brief_scope、
  冻结比对、Envelope 校验）；编排层 contracts 的语义校验是第二道闸，mock 与
  真实同受。
- **冻结语义**：`input_mode` 恒冻结；结构化 `requirements`（如商单要求）冻结为
  集合相等（原 id 原文）；`edit_scope` 提供即冻结。`objective/audience/platform/
  length_rule` 在自由文本流里属**推断字段**——模型从任务整理，由用户在
  confirm_brief 闸门看到并确认（对照独立运行的全字段冻结）。
- **F-O2**：open_questions 非空 ⇒ needs_input（本体强制），桥接按此映射。
- **F-O4**：素材引用携带编排层 `sha256 = sha256(canonical({"text": ...}))` 指纹，
  桥接解引用后复算比对；素材正文只经注入的 resolve_material 获取（授权范围=本
  task），kind 缺省 source_text，旧稿流必须恰好一份 existing_draft。
- **F-O6**：`proposal_hash`（本体建议指纹）只作标识；确认 CAS 指纹以编排层
  `save_brief` 的 `object_hash(payload)` 为唯一权威，两者不得混用。
- **失败映射**：结果未知（INTERRUPTED）→ `BridgeUnknownOutcome`（调用方按
  sent-but-unknown 处理，绝不自动重发）；确定性输入拒单（素材超限/指纹不符/
  构造失败）与其余 DomainError → 已知 error 结果（带 cause_hint/next_action 的
  issues，零模型调用或不再重试）；失败调用的 usage 取不回时记 `unknown`
  （不伪造 0）。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from backend.agents.operator import OperatorAgent, material_snapshot
from backend.domain.errors import DomainError
from backend.domain.schemas import CreateTask, EditScope, MaterialInput
from backend.memory.operator_memory import OperatorMemory, iterative_retrieve, terms_of

DEFAULT_DERIVED_AUDIENCE = "任务中描述的读者（可在确认前修改）"
DEFAULT_DERIVED_STYLE = "符合任务要求"
PLACEHOLDER_REQUIREMENT = [{"id": "req_extract", "text": "从任务中整理交付要求"}]
DEFAULT_MEMORY_ASPECTS = ("受众", "平台", "风格", "篇幅", "要求")


class BridgeUnknownOutcome(Exception):
    """Model call sent but the outcome is unknown; explicit resend only."""


class BridgePreSendFailure(Exception):
    """Bridge could not build a valid request (resolution/config failure)."""


def orchestration_ref_digest(text: str) -> str:
    """编排层 material_refs 的 sha256 约定：sha256(canonical JSON of {"text": ...})."""
    blob = json.dumps({"text": text}, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def build_create_task(input_payload: dict, *, account_id: str,
                      materials: list[dict]) -> tuple[CreateTask, EditScope | None, frozenset[str]]:
    """Map the orchestration projection to the production task input.

    `materials` are resolved rows: {id, text, kind?, label?, source_url?}.
    Returns (task, edit_scope, frozen_fields).
    """
    user_input = (input_payload.get("user_input") or "").strip() or "内容创作任务"
    input_mode = input_payload.get("input_mode", "idea")
    structured_reqs = input_payload.get("requirements")
    frozen = {"input_mode"}
    if structured_reqs is not None:
        frozen.add("requirements")
        requirements = [{"id": r["id"], "text": r["text"]} for r in structured_reqs]
    else:
        requirements = [dict(r) for r in PLACEHOLDER_REQUIREMENT]
    legal_kinds = {"user_supplied_experience", "source_text", "existing_draft"}
    material_inputs = [MaterialInput(
        kind=row["kind"] if row.get("kind") in legal_kinds else "source_text",
        label=(row.get("label") or row["id"])[:1000],
        text=row["text"],
        source_url=row.get("source_url"),
        authorized=True,
    ) for row in materials]
    task = CreateTask(
        account_id=account_id,
        input_mode=input_mode,
        objective=user_input[:1000],
        audience=DEFAULT_DERIVED_AUDIENCE,
        platform="generic",
        style=DEFAULT_DERIVED_STYLE,
        requirements=requirements,
        materials=material_inputs,
        length_rule={"minimum": None, "maximum": 20000},
    )
    scope_raw = input_payload.get("edit_scope")
    edit_scope = EditScope.model_validate(scope_raw) if scope_raw is not None else None
    return task, edit_scope, frozenset(frozen)


def resolve_materials(input_payload: dict,
                      resolve_material: Callable[[dict], dict]) -> list[dict]:
    """Resolve refs to rows, verifying each ref's content fingerprint (F-O4)."""
    rows = []
    for ref in input_payload.get("material_refs", []):
        try:
            row = resolve_material(ref)
        except KeyError:
            raise BridgePreSendFailure(f"material {ref.get('id')} cannot be resolved") from None
        text = row.get("text")
        if not isinstance(text, str):
            raise BridgePreSendFailure(f"material {ref.get('id')} has no text")
        expected = ref.get("sha256")
        if expected is not None and expected != orchestration_ref_digest(text):
            raise BridgePreSendFailure(f"material {ref.get('id')} fingerprint mismatch")
        rows.append({**row, "id": ref["id"]})
    return rows


def _issue(reason: str, requested_change: str) -> dict:
    return {"id": "iss_" + hashlib.sha256(reason.encode()).hexdigest()[:16],
            "severity": "blocking", "location": "prepare_brief",
            "reason": reason[:1000],
            "requested_change": (requested_change or "检查输入")[:1000]}


def _error_result(call_dict: dict, reason: str, requested_change: str = "检查输入后显式重发") -> dict:
    """确定性输入拒单 = 已知 error 结果（零模型调用、零重试、不烧预算）。"""
    return {**call_dict, "status": "error", "data": None, "questions": [],
            "issues": [_issue(reason, requested_change)],
            "usage": {"status": "unknown", "total_tokens": None}}


def _usage_dict(usage) -> dict:
    if usage.total is None:
        return {"status": "unknown", "total_tokens": None}
    return {"status": "known", "total_tokens": usage.total}


def map_envelope(result, call: dict, *, id_map: dict[str, str] | None = None) -> dict:
    """OperatorResult -> AgentResult-shaped dict (contract envelope fields).

    `id_map` translates the production entry's internal material ids back to the
    orchestration namespace (F-O4): downstream draft steps resolve Brief.material_ids
    against repository materials, so the bridge must not leak internal ids.
    """
    envelope = result.envelope
    base = {"contract_version": call.get("contract_version"), "request_id": call["request_id"],
            "agent_id": call.get("agent_id", "operations_officer"),
            "action": call.get("action", "prepare_brief"),
            "usage": _usage_dict(result.usage), "issues": []}
    if envelope.status == "ok" and envelope.data is not None:
        data = envelope.data.model_dump(mode="json")
        if id_map:
            data["material_ids"] = [id_map.get(mid, mid) for mid in data.get("material_ids", [])]
        return {**base, "status": "ok", "data": data,
                "questions": []}
    if envelope.status == "needs_input":
        return {**base, "status": "needs_input", "data": None,
                "questions": [q.model_dump(mode="json") for q in envelope.questions],
                "issues": [i.model_dump(mode="json") for i in envelope.issues]}
    # 本体 ok 必带 data；防御性地按 error 归类（不伪造 ok）
    return {**base, "status": "error", "data": None,
            "issues": [{"id": "iss_envelope_1", "severity": "blocking", "location": "prepare_brief",
                        "reason": "envelope carries no brief and no questions",
                        "requested_change": "检查输入后显式重发"}]}


class OperatorTeamAdapter:
    """编排层 AgentAdapter 兼容入口（duck-typed call）。

    call 需提供 .request_id/.agent_id/.action/.contract_version/.input/.context
    （context 至少含 account_id）；`resolve_material(ref) -> row` 由调用方注入
    （授权范围=本 task 的素材）。mock 模式零网络；live 需显式 model_adapter 与
    model_id（与本体门禁一致）。
    """

    def __init__(self, *, resolve_material: Callable[[dict], dict],
                 model_adapter: Any | None = None, mode: str = "mock",
                 model_id: str | None = None,
                 memory: OperatorMemory | None = None,
                 memory_aspects: tuple[str, ...] = DEFAULT_MEMORY_ASPECTS):
        self.resolve_material = resolve_material
        self.memory = memory
        self.memory_aspects = tuple(memory_aspects)
        self.last_retrieval: dict | None = None
        self.agent = OperatorAgent(model_adapter, mode=mode, model_id=model_id)

    def invoke(self, call) -> dict:
        payload = call.input
        account_id = getattr(call.context, "account_id", None) or "account"
        call_dict = {"request_id": getattr(call, "request_id", None),
                     "contract_version": getattr(call, "contract_version", None),
                     "agent_id": getattr(call, "agent_id", "operations_officer"),
                     "action": getattr(call, "action", "prepare_brief")}
        try:
            rows = resolve_materials(payload, self.resolve_material)
            task, edit_scope, frozen = build_create_task(
                payload, account_id=account_id, materials=rows)
        except BridgePreSendFailure as exc:
            return _error_result(call_dict, str(exc))
        except (ValueError, KeyError, TypeError):
            return _error_result(call_dict, "bridge input invalid")
        memory_notes: list[str] = []
        if self.memory is not None:
            # 三轮迭代检索（≤3）：记忆以未复核数据注入，绝不进 system 指令区
            retrieval = iterative_retrieve(
                self.memory, account_id, seed_terms=terms_of(payload.get("user_input", "")),
                aspects=list(self.memory_aspects))
            self.last_retrieval = retrieval
            memory_notes = [f"{row['statement']}（来源:{row['source_ref']}，trust=unreviewed）"
                            for row in retrieval["statements"]]
        try:
            result = self.agent.run(task, edit_scope=edit_scope, frozen_fields=frozen,
                                    memory_notes=memory_notes)
        except DomainError as exc:
            if exc.code == "INTERRUPTED":
                raise BridgeUnknownOutcome(str(exc.cause_hint)) from None
            return _error_result(call_dict, exc.cause_hint or exc.code, exc.next_action)
        id_map = {snap["material_id"]: row["id"]
                  for snap, row in zip(material_snapshot(task), rows)}
        return map_envelope(result, call_dict, id_map=id_map)
