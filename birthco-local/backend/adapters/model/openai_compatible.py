"""OpenAI-compatible chat-completions transport for the seven expert agents.

The workbench used to hard-wire a single provider (Bailian/Qwen) for every
role. This module adds a provider-agnostic transport so each agent can be
pointed at any OpenAI-compatible endpoint (a local gateway, a corporate proxy,
an OpenAI-style cloud endpoint, ...) purely through process environment
variables -- no key is ever written to disk.

Only the transport is handled here: no domain logic, no storage, no retry.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from urllib.parse import urlsplit

import httpx

from .protocol import AdapterResponse, ModelRequest, ModelUsage, blank_response

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL_ID = "gpt-4o-mini"
MAX_RESPONSE_BYTES = 1_048_576
MAX_REQUEST_BYTES = 1_048_576


class OpenAIConfigurationError(ValueError):
    """Invalid local provider configuration; messages never include credentials."""


def validate_base_url(base_url: str) -> str:
    try:
        parsed = urlsplit(base_url)
    except (TypeError, ValueError):
        raise OpenAIConfigurationError("invalid OpenAI-compatible base URL") from None
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise OpenAIConfigurationError("base URL must be a plain http(s) endpoint without credentials")
    # Loopback HTTP is allowed for local gateways; anything else should be TLS.
    if parsed.scheme == "http" and parsed.hostname.lower() not in {"127.0.0.1", "localhost", "::1"}:
        raise OpenAIConfigurationError("plain HTTP is only allowed for a local gateway")
    return base_url.rstrip("/")


def _messages(request: ModelRequest) -> list[dict[str, str]]:
    rows = [{"role": message.role, "content": message.content} for message in request.messages]
    if not any(row["role"] == "user" for row in rows):
        raise ValueError("a user message is required")
    return rows


class OpenAICompatibleAdapter:
    """One bounded chat-completions call per `complete`; no hidden retries."""

    mode = "live"

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None,
                 model_id: str | None = None, transport: httpx.BaseTransport | None = None,
                 timeout: float = 90.0) -> None:
        self._api_key = (api_key or os.environ.get("OPENAI_API_KEY")
                         or os.environ.get("AGENT_API_KEY") or "")
        self._base_url = validate_base_url(
            base_url or os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL)
        self._model_id = (model_id or os.environ.get("OPENAI_MODEL_ID")
                          or DEFAULT_MODEL_ID).strip()
        if not self._model_id:
            raise OpenAIConfigurationError("a model id is required")
        # A local gateway may not need a key; a remote endpoint must have one.
        loopback = urlsplit(self._base_url).hostname.lower() in {"127.0.0.1", "localhost", "::1"}
        if not self._api_key.strip() and not loopback:
            raise OpenAIConfigurationError("OPENAI_API_KEY is required for a remote endpoint")
        headers = {"content-type": "application/json", "accept": "application/json"}
        if self._api_key.strip():
            headers["authorization"] = "Bearer " + self._api_key.strip()
        self._headers = headers
        self._client = httpx.Client(
            transport=transport, follow_redirects=False,
            trust_env=True,  # honor HTTP_PROXY / HTTPS_PROXY (e.g. Clash)
            timeout=httpx.Timeout(timeout),
            headers=headers,
        )

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def base_url(self) -> str:
        return self._base_url

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OpenAICompatibleAdapter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def complete(self, request: ModelRequest) -> AdapterResponse:
        started = time.monotonic()

        def elapsed() -> int:
            return max(0, round((time.monotonic() - started) * 1000))

        if request.mode != "live":
            raise ValueError("OpenAICompatibleAdapter requires mode=live")
        if request.model_id != self._model_id:
            return blank_response(status="failed", mode="live",
                                  error_code="MODEL_REJECTED", latency_ms=elapsed())
        try:
            rows = _messages(request)
        except ValueError:
            return blank_response(status="failed", mode="live",
                                  error_code="MODEL_REJECTED", latency_ms=elapsed())
        payload: dict[str, object] = {
            "model": self._model_id,
            "messages": rows,
            "max_tokens": request.max_completion_tokens,
            "temperature": request.temperature,
            "top_p": request.top_p,
        }
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                              allow_nan=False).encode("utf-8")
        except (TypeError, ValueError):
            return blank_response(status="failed", mode="live",
                                  error_code="SCHEMA_INVALID", latency_ms=elapsed())
        if len(body) > MAX_REQUEST_BYTES:
            return blank_response(status="failed", mode="live",
                                  error_code="OUTPUT_TOO_LARGE", latency_ms=elapsed())
        try:
            response = self._client.post(
                self._base_url + "/chat/completions", content=body,
                timeout=request.timeout_seconds,
            )
        except httpx.TimeoutException:
            return blank_response(status="unknown", mode="live",
                                  error_code="MODEL_TIMEOUT", latency_ms=elapsed())
        except httpx.HTTPError:
            return blank_response(status="unknown", mode="live",
                                  error_code="MODEL_UNAVAILABLE", latency_ms=elapsed())
        raw = response.content[:MAX_RESPONSE_BYTES]
        digest = hashlib.sha256(raw).hexdigest()
        if not response.is_success:
            return blank_response(status="failed", mode="live",
                                  error_code="MODEL_REJECTED", latency_ms=elapsed(),
                                  response_bytes=len(raw), response_hash=digest)
        try:
            parsed = json.loads(raw)
            choice = parsed["choices"][0]
            text = choice["message"]["content"]
            finish_reason = choice.get("finish_reason")
            usage_raw = parsed.get("usage") or {}
            provider_id = parsed.get("id")
            if not isinstance(text, str):
                raise ValueError("empty content")
        except (ValueError, KeyError, IndexError, TypeError):
            return blank_response(status="failed", mode="live",
                                  error_code="SCHEMA_INVALID", latency_ms=elapsed(),
                                  response_bytes=len(raw), response_hash=digest)
        input_tokens = usage_raw.get("prompt_tokens") if isinstance(usage_raw.get("prompt_tokens"), int) else None
        output_tokens = usage_raw.get("completion_tokens") if isinstance(usage_raw.get("completion_tokens"), int) else None
        total = usage_raw.get("total_tokens") if isinstance(usage_raw.get("total_tokens"), int) else None
        if total is None and input_tokens is not None and output_tokens is not None:
            total = input_tokens + output_tokens
        return AdapterResponse(
            status="received", text=text,
            finish_reason="stop" if finish_reason in {"length", "content_filter", None} else str(finish_reason),
            provider_request_id=str(provider_id) if provider_id else None,
            usage=ModelUsage(input=input_tokens, output=output_tokens, total=total),
            error_code=None, retry_after_seconds=None,
            response_bytes=len(raw), response_hash=digest,
            latency_ms=elapsed(), mode="live",
            truncated=finish_reason == "length",
        )
