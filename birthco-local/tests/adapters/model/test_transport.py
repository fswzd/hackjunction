"""Transport-security tests for the unified MiMo live stack (offline, no network)."""
import json
import socket

import httpx
import pytest
import backend.adapters.model.mimo as mimo_module

from backend.adapters.model.mimo import (
    APPROVED_PATH, MAX_RESPONSE_BYTES, MiMoAdapter, ModelConfigurationError,
    PinnedHTTPSTransport, _BeforeSendError, _PinnedHTTPSConnection, _public_address,
)
from backend.adapters.model.mock import MockAdapter
from backend.adapters.model.protocol import AdapterResponse, ModelMessage, ModelRequest


def request(mode="live", json_mode=True):
    return ModelRequest(
        call_id="call-1", role="director",
        messages=(ModelMessage("system", "Return JSON."), ModelMessage("user", "Write.")),
        model_id="configured-model", max_completion_tokens=64, timeout_seconds=5,
        temperature=0.3, top_p=1, json_mode=json_mode, mode=mode,
    )


def adapter(handler, **kwargs):
    return MiMoAdapter(api_key="test-key", configured_model_id="configured-model",
                       transport=httpx.MockTransport(handler), **kwargs)


def provider_response(*, usage=True, stop_reason="end_turn"):
    value = {
        "id": "msg_1",
        "content": [{"type": "text", "text": '{"ok":true}'},
                    {"type": "thinking", "thinking": "PRIVATE"}],
        "stop_reason": stop_reason,
    }
    if usage:
        value["usage"] = {"input_tokens": 11, "output_tokens": 8,
                          "cache_read_input_tokens": 3}
    return value


def test_live_request_contract_and_usage_without_reasoning():
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(200, json=provider_response())
    with adapter(handler) as model:
        result = model.complete(request())
    assert len(calls) == 1
    assert str(calls[0].url) == "https://api.xiaomimimo.com" + APPROVED_PATH
    assert calls[0].headers["x-api-key"] == "test-key"
    assert calls[0].headers["anthropic-version"] == "2023-06-01"
    payload = json.loads(calls[0].content)
    assert set(payload) == {"model", "messages", "system", "max_tokens",
                            "temperature", "top_p"}
    assert isinstance(result, AdapterResponse)
    assert result.status == "received" and result.text == '{"ok":true}'
    assert result.usage.input == 11 and result.usage.output == 8 and result.usage.cached == 3
    assert "PRIVATE" not in repr(result)


@pytest.mark.parametrize("status,code", [(401, "MODEL_REJECTED"), (403, "MODEL_REJECTED"),
                                         (429, "MODEL_UNAVAILABLE"), (503, "MODEL_UNAVAILABLE"),
                                         (302, "MODEL_REJECTED")])
def test_http_failures_are_known_and_never_retried(status, code):
    count = 0
    def handler(req):
        nonlocal count
        count += 1
        return httpx.Response(status, headers={"retry-after": "2", "location": "https://elsewhere.test"})
    with adapter(handler) as model:
        result = model.complete(request())
    assert count == 1
    assert result.status == "failed" and result.error_code == code
    assert result.retry_after_seconds == (2 if status in (429, 503) else None)


def test_sent_timeout_is_unknown_and_not_retried():
    count = 0
    def handler(req):
        nonlocal count
        count += 1
        raise httpx.ReadTimeout("sent then timed out")
    with adapter(handler) as model:
        result = model.complete(request())
    assert count == 1 and result.status == "unknown" and result.error_code == "INTERRUPTED"
    assert result.usage.total is None


def test_missing_usage_stays_unknown_and_length_is_structural_failure():
    with adapter(lambda req: httpx.Response(200, json=provider_response(usage=False))) as model:
        received = model.complete(request())
    assert received.status == "received" and received.usage.total is None
    with adapter(lambda req: httpx.Response(200, json=provider_response(stop_reason="max_tokens"))) as model:
        truncated = model.complete(request())
    assert truncated.status == "failed" and truncated.text is None
    assert truncated.finish_reason == "max_tokens" and truncated.usage.total == 19


def test_response_byte_limit_stops_before_parsing():
    class BigStream(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(18):
                yield b"x" * 65_536
    with adapter(lambda req: httpx.Response(200, stream=BigStream())) as model:
        result = model.complete(request())
    assert result.status == "failed" and result.error_code == "OUTPUT_TOO_LARGE"
    assert result.truncated and result.response_bytes == MAX_RESPONSE_BYTES + 1
    assert result.text is None


def test_mock_and_live_share_response_type_without_provider_identity():
    mock = MockAdapter({"call-1": '{"ok":true}'}).complete(request(mode="mock"))
    with adapter(lambda req: httpx.Response(200, json=provider_response())) as model:
        live = model.complete(request())
    assert type(mock) is type(live) is AdapterResponse
    assert mock.mode == "mock" and mock.provider_request_id is None
    assert mock.usage.total is None and live.mode == "live"


def test_json_guard_and_model_mismatch_fail_before_request():
    def cannot_send(req):
        pytest.fail("request must not be sent")
    missing_keyword = ModelRequest(
        call_id="json-guard", role="director",
        messages=(ModelMessage("user", "Write an object."),),
        model_id="configured-model", max_completion_tokens=64,
        timeout_seconds=5, temperature=0, top_p=1,
        json_mode=True, mode="live",
    )
    with adapter(cannot_send) as model:
        assert model.complete(missing_keyword).status == "failed"
    mismatched = request()
    object.__setattr__(mismatched, "model_id", "different-model")
    with adapter(cannot_send) as model:
        assert model.complete(mismatched).status == "failed"


def test_origin_guards_reject_bad_base_urls():
    for bad in ("http://api.xiaomimimo.com/anthropic",
                "https://elsewhere.test/anthropic",
                "https://api.xiaomimimo.com/other"):
        with pytest.raises(ModelConfigurationError):
            MiMoAdapter(api_key="test-key", configured_model_id="configured-model",
                        base_url=bad)
    with adapter(lambda req: httpx.Response(200, json=provider_response())) as model:
        assert model.complete(request()).status == "received"


def test_private_dns_answer_rejected_before_connect(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(_BeforeSendError):
        _public_address("api.xiaomimimo.com", 443)


def test_peer_mismatch_closes_socket_before_tls_or_headers(monkeypatch):
    class FakeSocket:
        closed = False
        def getpeername(self):
            return ("127.0.0.1", 443)
        def close(self):
            self.closed = True
    fake = FakeSocket()
    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: fake)
    conn = _PinnedHTTPSConnection("api.xiaomimimo.com", 443, "8.8.8.8", 5)
    with pytest.raises(OSError):
        conn._create_connection(("api.xiaomimimo.com", 443), 5)
    assert fake.closed


def test_default_https_port_uses_pinned_transport_before_sending(monkeypatch):
    events = []
    class FakeResponse:
        status = 200
        def read(self, size):
            assert size == MAX_RESPONSE_BYTES + 1
            return b"{}"
        def getheaders(self):
            return [("content-type", "application/json")]
    class FakeConnection:
        def __init__(self, host, port, ip, timeout):
            events.append(("init", host, port, ip))
        def connect(self):
            events.append(("tls",))
        def request(self, method, path, body, headers):
            events.append(("send", method, path, headers["x-api-key"]))
        def getresponse(self):
            return FakeResponse()
        def close(self):
            events.append(("close",))
    monkeypatch.setattr(mimo_module, "_public_address", lambda host, port: "8.8.8.8")
    monkeypatch.setattr(mimo_module, "_PinnedHTTPSConnection", FakeConnection)
    req = httpx.Request("POST", "https://api.xiaomimimo.com" + APPROVED_PATH,
                        content=b"{}", headers={"x-api-key": "test-key"})
    response = PinnedHTTPSTransport("api.xiaomimimo.com", 443).handle_request(req)
    assert response.status_code == 200
    assert events[0] == ("init", "api.xiaomimimo.com", 443, "8.8.8.8")
    assert events[1] == ("tls",)
    assert events[2] == ("send", "POST", APPROVED_PATH, "test-key")
    assert events[-1] == ("close",)
