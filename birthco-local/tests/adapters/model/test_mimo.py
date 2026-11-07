"""Offline tests for the MiMo (Anthropic-compatible) live adapter.

Transport is a MockTransport; no network, no credentials, no billable calls.
"""
from __future__ import annotations

import json

import httpx
import pytest

from backend.adapters.model.mimo import (
    APPROVED_PATH, DEFAULT_MODEL_ID, MiMoAdapter,
    ModelConfigurationError, validate_base_url,
)
from backend.adapters.model.protocol import ModelMessage, ModelRequest


def make_request(**over) -> ModelRequest:
    base = dict(
        call_id="call_mimo_1", role="director",
        messages=(ModelMessage("system", "你是审稿助手。输出必须是 JSON。"),
                  ModelMessage("user", "请审阅并以 JSON 回复。")),
        model_id="mimo-v2.6-pro", max_completion_tokens=512,
        timeout_seconds=30.0, temperature=0.2, top_p=0.9,
        json_mode=True, mode="live",
    )
    base.update(over)
    return ModelRequest(**base)


def adapter_with(handler) -> MiMoAdapter:
    return MiMoAdapter(api_key="test-key", configured_model_id="mimo-v2.6-pro",
                       transport=httpx.MockTransport(handler))


def test_request_mapping_and_headers():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "id": "msg_1", "content": [{"type": "text", "text": "{\"ok\":true}"}],
            "stop_reason": "end_turn", "usage": {"input_tokens": 10, "output_tokens": 5},
        }, request=request)

    with adapter_with(handler) as adapter:
        response = adapter.complete(make_request())
    assert response.status == "received"
    assert captured["url"].endswith(APPROVED_PATH)
    assert captured["headers"]["x-api-key"] == "test-key"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    body = captured["body"]
    assert body["model"] == "mimo-v2.6-pro"
    assert body["max_tokens"] == 512
    assert body["temperature"] == 0.2 and body["top_p"] == 0.9
    assert body["system"] == "你是审稿助手。输出必须是 JSON。"
    assert body["messages"] == [{"role": "user", "content": "请审阅并以 JSON 回复。"}]
    assert "response_format" not in body
    assert response.text == "{\"ok\":true}"
    assert response.finish_reason == "stop", "end_turn 必须归一化为协议约定的 stop"
    assert response.usage.input == 10 and response.usage.output == 5 and response.usage.total == 15


def test_stop_reason_max_tokens_is_schema_invalid():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "id": "msg_2", "content": [{"type": "text", "text": "截断了"}],
            "stop_reason": "max_tokens", "usage": {"input_tokens": 1, "output_tokens": 1},
        }, request=request)

    with adapter_with(handler) as adapter:
        response = adapter.complete(make_request(json_mode=False,
                                                 messages=(ModelMessage("user", "hi"),)))
    assert response.status == "failed" and response.error_code == "SCHEMA_INVALID"


def test_garbage_body_is_schema_invalid():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True}, request=request)

    with adapter_with(handler) as adapter:
        response = adapter.complete(make_request())
    assert response.status == "failed" and response.error_code == "SCHEMA_INVALID"


@pytest.mark.parametrize("status,code", [(429, "MODEL_UNAVAILABLE"), (503, "MODEL_UNAVAILABLE"),
                                         (401, "MODEL_REJECTED"), (400, "MODEL_REJECTED"),
                                         (500, "MODEL_UNAVAILABLE")])
def test_http_status_mapping(status, code):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "x"}, request=request,
                              headers={"retry-after": "7"})

    with adapter_with(handler) as adapter:
        response = adapter.complete(make_request())
    assert response.status == "failed" and response.error_code == code
    if status == 429:
        assert response.retry_after_seconds == 7.0


def test_model_id_mismatch_rejected_without_send():
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={}, request=request)

    with adapter_with(handler) as adapter:
        response = adapter.complete(make_request(model_id="other-model"))
    assert response.status == "failed" and response.error_code == "MODEL_REJECTED"
    assert sent == []


def test_before_send_failure_is_failed_after_send_timeout_is_unknown():
    def handler_before(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect timed out", request=request)

    def handler_after(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    with adapter_with(handler_before) as adapter:
        response = adapter.complete(make_request())
    assert response.status == "failed" and response.error_code == "MODEL_UNAVAILABLE"

    with adapter_with(handler_after) as adapter:
        response = adapter.complete(make_request())
    assert response.status == "unknown" and response.error_code == "INTERRUPTED"
    assert response.usage.total is None  # unknown usage stays unknown


def test_json_mode_requires_json_hint():
    with adapter_with(lambda request: httpx.Response(200, json={}, request=request)) as adapter:
        response = adapter.complete(make_request(messages=(ModelMessage("user", "写首诗"),)))
    assert response.status == "failed" and response.error_code == "MODEL_REJECTED"


def test_configuration_requires_api_key(monkeypatch):
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    with pytest.raises(ModelConfigurationError):
        MiMoAdapter(api_key="  ", configured_model_id="mimo-v2.6-pro")


def test_validate_base_url_rejects_bad_endpoints():
    for bad in ("http://api.xiaomimimo.com/anthropic",
                "https://api.xiaomimimo.com/other",
                "https://user:pass@api.xiaomimimo.com/anthropic",
                "https://api.xiaomimimo.com/anthropic?x=1"):
        with pytest.raises(ModelConfigurationError):
            validate_base_url(bad)
    host, port = validate_base_url("https://api.xiaomimimo.com/anthropic")
    assert host == "api.xiaomimimo.com" and port == 443


def test_default_model_id_is_mimo_v26_pro(monkeypatch):
    monkeypatch.delenv("MIMO_MODEL_ID", raising=False)
    from backend.adapters.model.factory import live_model_id
    assert live_model_id() == DEFAULT_MODEL_ID == "mimo-v2.6-pro"
