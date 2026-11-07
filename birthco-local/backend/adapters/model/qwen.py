"""Alibaba Cloud Bailian Beijing Chat Completions adapter.

The network transport resolves once, rejects non-public answers, connects to a
numeric address, verifies the connected peer, and lets TLS verify the original
host name before any request header (including the API key) is sent.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import time
from urllib.parse import urlsplit

import httpx

from .protocol import AdapterResponse, ModelRequest, ModelUsage, blank_response


DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MAX_RESPONSE_BYTES = 1_048_576
MAX_REQUEST_BYTES = 1_048_576
_DNS_HOST = re.compile(r"^[A-Za-z0-9.-]+$")


class ModelConfigurationError(ValueError):
    """Invalid local model configuration; messages never include credentials."""


class _BeforeSendError(Exception):
    pass


class _AfterSendError(Exception):
    pass


def validate_base_url(base_url: str) -> tuple[str, int]:
    try:
        parsed = urlsplit(base_url)
        host = parsed.hostname
        port = parsed.port or 443
    except (TypeError, ValueError) as exc:
        raise ModelConfigurationError("invalid Bailian base URL") from None
    if (
        parsed.scheme != "https" or not host or not _DNS_HOST.fullmatch(host)
        or parsed.username is not None or parsed.password is not None
        or parsed.path.rstrip("/") != "/compatible-mode/v1" or parsed.query or parsed.fragment
        or port != 443
    ):
        raise ModelConfigurationError("Bailian base URL must be an HTTPS Beijing compatible-mode/v1 endpoint")
    if host.lower() != "dashscope.aliyuncs.com" and not re.fullmatch(
        r"[a-z0-9][a-z0-9-]*\.cn-beijing\.maas\.aliyuncs\.com", host.lower()
    ):
        raise ModelConfigurationError("Bailian endpoint must be in the Beijing region")
    return host, port


def _public_address(host: str, port: int) -> str:
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise _BeforeSendError("DNS resolution failed") from None
    if not answers:
        raise _BeforeSendError("DNS resolution failed")
    ips: list[str] = []
    for answer in answers:
        try:
            address = ipaddress.ip_address(answer[4][0])
        except (IndexError, ValueError):
            raise _BeforeSendError("DNS answer is invalid") from None
        if not address.is_global:
            raise _BeforeSendError("DNS answer is not public")
        ips.append(str(address))
    return ips[0]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, pinned_ip: str, timeout: float) -> None:
        super().__init__(host, port=port, timeout=timeout,
                         context=ssl.create_default_context())
        self._pinned_ip = pinned_ip
        # HTTPConnection.__init__ assigns an instance attribute named
        # _create_connection, so a subclass method alone would be shadowed.
        self._create_connection = self._dial_pinned

    def _dial_pinned(self, address: tuple[str, int], timeout: float,
                     source_address: tuple[str, int] | None = None) -> socket.socket:
        sock = socket.create_connection((self._pinned_ip, address[1]), timeout,
                                        source_address=source_address)
        try:
            actual = ipaddress.ip_address(sock.getpeername()[0])
            if str(actual) != self._pinned_ip or not actual.is_global:
                raise OSError("connected peer does not match approved address")
            return sock
        except BaseException:
            sock.close()
            raise


class PinnedHTTPSTransport(httpx.BaseTransport):
    """One fresh HTTPS connection per request; no proxy, redirect, or retry."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.scheme != "https" or url.host != self.host or (url.port or 443) != self.port:
            raise _BeforeSendError("request destination changed")
        if request.method != "POST" or url.path != "/compatible-mode/v1/chat/completions":
            raise _BeforeSendError("request operation is not approved")
        body = request.read()
        if len(body) > MAX_REQUEST_BYTES:
            raise _BeforeSendError("request exceeds byte limit")
        pinned_ip = _public_address(self.host, self.port)
        timeout = request.extensions.get("timeout", {}).get("connect", 90.0)
        conn = _PinnedHTTPSConnection(self.host, self.port, pinned_ip, timeout)
        try:
            try:
                conn.connect()  # TLS hostname verification finishes before Authorization is sent.
            except (OSError, ssl.SSLError, TimeoutError):
                raise _BeforeSendError("secure connection failed") from None
            try:
                headers = dict(request.headers.items())
                conn.request("POST", "/compatible-mode/v1/chat/completions", body=body, headers=headers)
                response = conn.getresponse()
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                return httpx.Response(
                    status_code=response.status,
                    headers=dict(response.getheaders()),
                    content=raw,
                    request=request,
                )
            except (OSError, TimeoutError, http.client.HTTPException):
                raise _AfterSendError("delivery outcome is unknown") from None
        finally:
            conn.close()


def _usage(data: object) -> ModelUsage:
    if not isinstance(data, dict):
        return ModelUsage()
    def count(value: object) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
    prompt = data.get("prompt_tokens_details")
    completion = data.get("completion_tokens_details")
    return ModelUsage(
        input=count(data.get("prompt_tokens")),
        output=count(data.get("completion_tokens")),
        total=count(data.get("total_tokens")),
        cached=count(prompt.get("cached_tokens")) if isinstance(prompt, dict) else None,
        reasoning=count(completion.get("reasoning_tokens")) if isinstance(completion, dict) else None,
    )


def _retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if 0 <= seconds <= 90 else None


class QwenAdapter:
    def __init__(
        self, *, api_key: str | None = None, base_url: str | None = None,
        supports_json_object: bool = True,
        configured_model_id: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get("DASHSCOPE_API_KEY")
        if not self._api_key or not self._api_key.strip():
            raise ModelConfigurationError("DASHSCOPE_API_KEY is required")
        self._model_id = configured_model_id if configured_model_id is not None else os.environ.get("QWEN_MODEL_ID")
        if not self._model_id or not self._model_id.strip():
            raise ModelConfigurationError("QWEN_MODEL_ID is required")
        self._base_url = base_url or os.environ.get("QWEN_BASE_URL") or DEFAULT_BASE_URL
        self._host, self._port = validate_base_url(self._base_url)
        self._supports_json_object = supports_json_object
        self._client = httpx.Client(
            transport=transport or PinnedHTTPSTransport(self._host, self._port),
            follow_redirects=False, trust_env=False, verify=True,
            timeout=httpx.Timeout(90.0),
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "QwenAdapter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def complete(self, request: ModelRequest) -> AdapterResponse:
        started = time.monotonic()
        def elapsed() -> int:
            return max(0, round((time.monotonic() - started) * 1000))

        if request.mode != "live":
            raise ValueError("QwenAdapter requires mode=live")
        if request.model_id != self._model_id:
            return blank_response(status="failed", mode="live", error_code="MODEL_REJECTED", latency_ms=elapsed())
        if request.json_mode and not self._supports_json_object:
            return blank_response(status="failed", mode="live", error_code="MODEL_REJECTED", latency_ms=elapsed())
        if request.json_mode and not any("json" in message.content.lower() for message in request.messages):
            return blank_response(status="failed", mode="live", error_code="MODEL_REJECTED", latency_ms=elapsed())

        payload: dict[str, object] = {
            "model": request.model_id,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "stream": False,
            "max_completion_tokens": request.max_completion_tokens,
            "temperature": request.temperature,
            "top_p": request.top_p,
        }
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(body) > MAX_REQUEST_BYTES:
            return blank_response(status="failed", mode="live", error_code="OUTPUT_TOO_LARGE", latency_ms=elapsed())

        try:
            with self._client.stream(
                "POST", self._base_url.rstrip("/") + "/chat/completions",
                content=body,
                headers={"authorization": "Bearer " + self._api_key, "content-type": "application/json",
                         "accept": "application/json", "accept-encoding": "identity"},
                timeout=request.timeout_seconds,
            ) as response:
                digest = hashlib.sha256()
                chunks: list[bytes] = []
                captured = 0
                truncated = False
                if response.is_stream_consumed:
                    # In-memory test transports and the pinned live transport have
                    # already bounded their payload before constructing Response.
                    source = (response.content[i:i + 65_536]
                              for i in range(0, len(response.content), 65_536))
                else:
                    source = response.iter_raw(chunk_size=65_536)
                for chunk in source:
                    take = chunk[:MAX_RESPONSE_BYTES + 1 - captured]
                    chunks.append(take)
                    digest.update(take)
                    captured += len(take)
                    if captured > MAX_RESPONSE_BYTES:
                        truncated = True
                        break
                raw = b"".join(chunks)
                response_hash = digest.hexdigest()
                if truncated:
                    return blank_response(status="failed", mode="live", error_code="OUTPUT_TOO_LARGE",
                                          latency_ms=elapsed(), response_bytes=captured,
                                          response_hash=response_hash, truncated=True)
                if 300 <= response.status_code < 400:
                    return blank_response(status="failed", mode="live", error_code="MODEL_REJECTED",
                                          latency_ms=elapsed(), response_bytes=captured, response_hash=response_hash)
                if response.status_code in (429, 503):
                    return blank_response(status="failed", mode="live", error_code="MODEL_UNAVAILABLE",
                                          latency_ms=elapsed(), response_bytes=captured, response_hash=response_hash,
                                          retry_after_seconds=_retry_after(response.headers.get("retry-after")))
                if response.status_code != 200:
                    code = "MODEL_REJECTED" if response.status_code in (400, 401, 403) else "MODEL_UNAVAILABLE"
                    return blank_response(status="failed", mode="live", error_code=code,
                                          latency_ms=elapsed(), response_bytes=captured, response_hash=response_hash)
                try:
                    document = json.loads(raw)
                    choice = document["choices"][0]
                    text = choice["message"]["content"]
                    finish_reason = choice["finish_reason"]
                    if not isinstance(text, str) or not isinstance(finish_reason, str):
                        raise ValueError("invalid choice")
                except (ValueError, UnicodeError, TypeError, KeyError, IndexError):
                    return blank_response(status="failed", mode="live", error_code="SCHEMA_INVALID",
                                          latency_ms=elapsed(), response_bytes=captured, response_hash=response_hash)
                provider_id = document.get("id")
                if not isinstance(provider_id, str) or len(provider_id) > 256:
                    provider_id = None
                usage = _usage(document.get("usage"))
                if finish_reason != "stop":
                    return AdapterResponse("failed", None, finish_reason, provider_id, usage,
                                           "SCHEMA_INVALID", None, captured, response_hash, elapsed(), "live")
                return AdapterResponse("received", text, finish_reason, provider_id, usage,
                                       None, None, captured, response_hash, elapsed(), "live")
        except (_BeforeSendError, httpx.ConnectError, httpx.ConnectTimeout):
            return blank_response(status="failed", mode="live", error_code="MODEL_UNAVAILABLE", latency_ms=elapsed())
        except (_AfterSendError, httpx.TimeoutException, httpx.TransportError):
            return blank_response(status="unknown", mode="live", error_code="INTERRUPTED", latency_ms=elapsed())
