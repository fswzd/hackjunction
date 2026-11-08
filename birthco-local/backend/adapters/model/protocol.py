"""Transport-only model contract. This module has no domain or storage imports."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Literal, Protocol


ModelMode = Literal["mock", "live"]
ModelStatus = Literal["received", "failed", "unknown"]


@dataclass(frozen=True, slots=True)
class ModelMessage:
    role: Literal["system", "user"]
    content: str

    def __post_init__(self) -> None:
        if self.role not in ("system", "user") or not isinstance(self.content, str):
            raise ValueError("invalid model message")


# MiMo mimo-v2.6-pro 的 max_tokens 上限（实测范围 (0, 131072]）。
# 所有角色的单次输出上限统一取模型上限，不人为截断。
MAX_COMPLETION_TOKENS = 131072


@dataclass(frozen=True, slots=True)
class ModelRequest:
    call_id: str
    role: str
    messages: tuple[ModelMessage, ...]
    model_id: str
    max_completion_tokens: int
    timeout_seconds: float
    temperature: float
    top_p: float
    json_mode: bool
    mode: ModelMode

    def __post_init__(self) -> None:
        if not isinstance(self.call_id, str) or not 1 <= len(self.call_id) <= 64 or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*", self.call_id):
            raise ValueError("invalid call_id")
        if not isinstance(self.role, str) or not self.role.strip():
            raise ValueError("role is required")
        if not isinstance(self.model_id, str) or not self.model_id.strip():
            raise ValueError("model_id is required")
        if not isinstance(self.messages, tuple) or not self.messages or not all(
            isinstance(message, ModelMessage) for message in self.messages
        ):
            raise ValueError("messages must be a nonempty tuple of ModelMessage")
        if isinstance(self.max_completion_tokens, bool) or not isinstance(self.max_completion_tokens, int) or not 0 < self.max_completion_tokens <= MAX_COMPLETION_TOKENS:
            raise ValueError(f"max_completion_tokens must be between 1 and {MAX_COMPLETION_TOKENS}")
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)) or not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 90:
            raise ValueError("timeout_seconds must be between 0 and 90")
        if isinstance(self.temperature, bool) or not isinstance(self.temperature, (int, float)) or not math.isfinite(self.temperature) or not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if isinstance(self.top_p, bool) or not isinstance(self.top_p, (int, float)) or not math.isfinite(self.top_p) or not 0 < self.top_p <= 1:
            raise ValueError("top_p must be between 0 and 1")
        if not isinstance(self.json_mode, bool) or self.mode not in ("mock", "live"):
            raise ValueError("invalid model mode or json_mode")


@dataclass(frozen=True, slots=True)
class ModelUsage:
    input: int | None = None
    output: int | None = None
    total: int | None = None
    cached: int | None = None
    reasoning: int | None = None


@dataclass(frozen=True, slots=True)
class AdapterResponse:
    status: ModelStatus
    text: str | None
    finish_reason: str | None
    provider_request_id: str | None
    usage: ModelUsage
    error_code: str | None
    retry_after_seconds: float | None
    response_bytes: int | None
    response_hash: str | None
    latency_ms: int
    mode: ModelMode
    truncated: bool = False


class ModelAdapter(Protocol):
    def complete(self, request: ModelRequest) -> AdapterResponse: ...


def blank_response(*, status: ModelStatus, mode: ModelMode, error_code: str | None,
                   latency_ms: int = 0, response_bytes: int | None = None,
                   response_hash: str | None = None, truncated: bool = False,
                   retry_after_seconds: float | None = None) -> AdapterResponse:
    return AdapterResponse(
        status=status, text=None, finish_reason=None, provider_request_id=None,
        usage=ModelUsage(), error_code=error_code,
        retry_after_seconds=retry_after_seconds, response_bytes=response_bytes,
        response_hash=response_hash, latency_ms=latency_ms, mode=mode,
        truncated=truncated,
    )
