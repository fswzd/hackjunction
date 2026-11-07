"""编排层 read_segment ↔ 模拟观众本体(AudienceAgent.react)。

输入投影即业务 AudienceInput(同 schema)。reaction.status 语义:
received -> ok+event;unknown(已发送结果未知)-> BridgeUnknownOutcome;
failed -> 已知 error 结果(error 详情取自 reaction.error)。
"""
from __future__ import annotations

from typing import Any

from backend.adapters.bridge_common import BridgeUnknownOutcome, error_result, usage_dict
from backend.agents.audience import AudienceAgent
from backend.domain.schemas import AudienceInput

TIMEOUT_SECONDS = 90


class AudienceTeamAdapter:
    def __init__(self, *, timeout_seconds: int = TIMEOUT_SECONDS,
                 model_adapter: Any | None = None, mode: str = "mock",
                 model_id: str | None = None):
        self.timeout_seconds = timeout_seconds
        self.agent = AudienceAgent(model_adapter, mode=mode, model_id=model_id)

    def invoke(self, call) -> dict:
        call_dict = {"request_id": getattr(call, "request_id", None),
                     "contract_version": getattr(call, "contract_version", None),
                     "agent_id": getattr(call, "agent_id", "simulated_audience"),
                     "action": getattr(call, "action", "read_segment")}
        try:
            context = AudienceInput.model_validate(call.input)
        except Exception as exc:
            return error_result(call_dict, f"bridge input invalid: {exc}",
                                location="read_segment")
        # 业务 react 对前置校验违规(空白内容/历史投影/cover-first/已退出)直接抛
        # DomainError —— 桥接不拦截,由 TeamEntry 转换(INTERRUPTED→UnknownResult,
        # 其余→确定性 error 结果)。
        reaction = self.agent.react(context, timeout_seconds=self.timeout_seconds,
                                    mock_exit=False)
        base = {**call_dict, "usage": usage_dict(reaction.usage)}
        if reaction.status == "received" and reaction.event is not None:
            return {**base, "status": "ok",
                    "data": reaction.event.model_dump(mode="json"),
                    "questions": [], "issues": []}
        if reaction.status == "unknown":
            hint = reaction.error.cause_hint if reaction.error else "remote outcome unknown"
            raise BridgeUnknownOutcome(hint)
        err = reaction.error
        return error_result(call_dict,
                            (err.cause_hint if err else "viewer call failed") or "viewer call failed",
                            (err.next_action if err else "检查输入后显式重发") or "检查输入后显式重发",
                            location="read_segment")
