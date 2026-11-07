"""Deterministic transport fixture; never presented as a provider call."""

from __future__ import annotations

import hashlib
import time

from .protocol import AdapterResponse, ModelRequest, ModelUsage


class MockAdapter:
    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self._responses = dict(responses or {})

    def complete(self, request: ModelRequest) -> AdapterResponse:
        started = time.monotonic()
        if request.mode != "mock":
            raise ValueError("MockAdapter requires mode=mock")
        text = self._responses.get(request.call_id, "{}" if request.json_mode else "")
        raw = text.encode("utf-8")
        return AdapterResponse(
            status="received", text=text, finish_reason="stop",
            provider_request_id=None, usage=ModelUsage(), error_code=None,
            retry_after_seconds=None, response_bytes=len(raw),
            response_hash=hashlib.sha256(raw).hexdigest(),
            latency_ms=max(0, round((time.monotonic() - started) * 1000)),
            mode="mock",
        )
