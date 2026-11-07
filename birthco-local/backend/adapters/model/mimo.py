"""MiMo (Anthropic-compatible Messages API) model adapter.

统一 live 后端：所有专家 agent 的真实模型调用经此适配器注入（方式 A），
模型默认 `mimo-v2.6-pro`，端点默认 `https://api.xiaomimimo.com/anthropic`。

传输安全与 qwen.py 同一姿态：DNS 只收公网地址、连接固定到解析出的 IP、
TLS 校验原始主机名、单次 POST 白名单路径、无代理/重定向/自动重试、
响应限 1 MiB、凭据只从环境（或仓库根 .env）读取且永不出现在错误信息里。
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
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .protocol import AdapterResponse, ModelRequest, ModelUsage, blank_response

DEFAULT_BASE_URL = "https://api.xiaomimimo.com/anthropic"
DEFAULT_MODEL_ID = "mimo-v2.6-pro"
ANTHROPIC_VERSION = "2023-06-01"
APPROVED_PATH = "/anthropic/v1/messages"
MAX_RESPONSE_BYTES = 1_048_576
MAX_REQUEST_BYTES = 1_048_576
_DNS_HOST = re.compile(r"^[A-Za-z0-9.-]+$")


class ModelConfigurationError(ValueError):
    """Invalid local model configuration; messages never include credentials."""


class _BeforeSendError(Exception):
    pass


class _AfterSendError(Exception):
    pass


def _load_env_file() -> None:
    """Minimal .env loader: walk up from this file to the repo root for `.env`.

    Existing environment variables always win; .env only fills the gaps.
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".env"
        if candidate.is_file():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
            return


def validate_base_url(base_url: str) -> tuple[str, int]:
    try:
        parsed = urlsplit(base_url)
        host = parsed.hostname
        port = parsed.port or 443
    except (TypeError, ValueError):
        raise ModelConfigurationError("invalid MiMo base URL") from None
    if (
        parsed.scheme != "https" or not host or not _DNS_HOST.fullmatch(host)
        or host.lower() != "api.xiaomimimo.com"
        or parsed.username is not None or parsed.password is not None
        or parsed.path.rstrip("/") != "/anthropic" or parsed.query or parsed.fragment
        or port != 443
    ):
        raise ModelConfigurationError("MiMo base URL must be an HTTPS /anthropic endpoint")
    return host.lower(), port


def _public_address(host: str, port: int) -> str:
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise _BeforeSendError("DNS resolution failed") from None
    if not answers:
        raise _BeforeSendError("DNS resolution failed") from None
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
        if request.method != "POST" or url.path != APPROVED_PATH:
            raise _BeforeSendError("request operation is not approved")
        body = request.read()
        if len(body) > MAX_REQUEST_BYTES:
            raise _BeforeSendError("request exceeds byte limit")
        pinned_ip = _public_address(self.host, self.port)
        timeout = request.extensions.get("timeout", {}).get("connect", 90.0)
        conn = _PinnedHTTPSConnection(self.host, self.port, pinned_ip, timeout)
        try:
            try:
                conn.connect()  # TLS hostname verification finishes before the key is sent.
            except (OSError, ssl.SSLError, TimeoutError):
                raise _BeforeSendError("secure connection failed") from None
            try:
                headers = dict(request.headers.items())
                conn.request("POST", APPROVED_PATH, body=body, headers=headers)
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
    def number(value: object) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
    input_tokens = number(data.get("input_tokens"))
    output_tokens = number(data.get("output_tokens"))
    total = None if input_tokens is None and output_tokens is None else (input_tokens or 0) + (output_tokens or 0)
    return ModelUsage(input=input_tokens, output=output_tokens, total=total,
                      cached=number(data.get("cache_read_input_tokens")))


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if 0 < seconds <= 3600 else None


class MiMoAdapter:
    def __init__(
        self, *, api_key: str | None = None, base_url: str | None = None,
        configured_model_id: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        _load_env_file()
        self._api_key = api_key if api_key is not None else os.environ.get("MIMO_API_KEY")
        if not self._api_key or not self._api_key.strip():
            raise ModelConfigurationError("MIMO_API_KEY is required")
        self._model_id = (configured_model_id if configured_model_id is not None
                          else os.environ.get("MIMO_MODEL_ID") or DEFAULT_MODEL_ID)
        if not self._model_id.strip():
            raise ModelConfigurationError("MIMO_MODEL_ID is required")
        self._base_url = base_url or os.environ.get("MIMO_BASE_URL") or DEFAULT_BASE_URL
        self._host, self._port = validate_base_url(self._base_url)
        self._client = httpx.Client(
            transport=transport or PinnedHTTPSTransport(self._host, self._port),
            follow_redirects=False, trust_env=False, verify=True,
            timeout=httpx.Timeout(90.0),
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "MiMoAdapter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def complete(self, request: ModelRequest) -> AdapterResponse:
        started = time.monotonic()

        def elapsed() -> int:
            return max(0, round((time.monotonic() - started) * 1000))

        if request.mode != "live":
            raise ValueError("MiMoAdapter requires mode=live")
        if request.model_id != self._model_id:
            return blank_response(status="failed", mode="live", error_code="MODEL_REJECTED", latency_ms=elapsed())
        # Anthropic 兼容协议没有 response_format；JSON 由提示词层约定（沿用既有防护）。
        if request.json_mode and not any("json" in message.content.lower() for message in request.messages):
            return blank_response(status="failed", mode="live", error_code="MODEL_REJECTED", latency_ms=elapsed())

        system_parts = [m.content for m in request.messages if m.role == "system"]
        user_messages = [{"role": "user", "content": m.content}
                         for m in request.messages if m.role == "user"]
        if not user_messages:
            return blank_response(status="failed", mode="live", error_code="MODEL_REJECTED", latency_ms=elapsed())
        payload: dict[str, object] = {
            "model": request.model_id,
            "max_tokens": request.max_completion_tokens,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "messages": user_messages,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(body) > MAX_REQUEST_BYTES:
            return blank_response(status="failed", mode="live", error_code="OUTPUT_TOO_LARGE", latency_ms=elapsed())

        try:
            with self._client.stream(
                "POST", self._base_url.rstrip("/") + "/v1/messages",
                content=body,
                headers={"x-api-key": self._api_key, "content-type": "application/json",
                         "anthropic-version": ANTHROPIC_VERSION,
                         "accept": "application/json", "accept-encoding": "identity"},
                timeout=request.timeout_seconds,
            ) as response:
                digest = hashlib.sha256()
                chunks: list[bytes] = []
                captured = 0
                truncated = False
                if response.is_stream_consumed:
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
                    blocks = document["content"]
                    text = "".join(block["text"] for block in blocks
                                   if isinstance(block, dict) and block.get("type") == "text"
                                   and isinstance(block.get("text"), str))
                    stop_reason = document.get("stop_reason")
                    if not isinstance(blocks, list) or not blocks or not isinstance(stop_reason, str):
                        raise ValueError("invalid content")
                except (ValueError, UnicodeError, TypeError, KeyError, IndexError):
                    return blank_response(status="failed", mode="live", error_code="SCHEMA_INVALID",
                                          latency_ms=elapsed(), response_bytes=captured, response_hash=response_hash)
                provider_id = document.get("id")
                if not isinstance(provider_id, str) or len(provider_id) > 256:
                    provider_id = None
                usage = _usage(document.get("usage"))
                if stop_reason not in ("end_turn", "stop"):
                    return AdapterResponse("failed", None, stop_reason, provider_id, usage,
                                           "SCHEMA_INVALID", None, captured, response_hash, elapsed(), "live")
                # 协议约定 finish_reason="stop"（全部 agent 的完成判定口径，与 OpenAI 风格
                # 适配器一致）；Anthropic 风格的 end_turn 在传输边界归一化，不向上泄漏线格式。
                return AdapterResponse("received", text, "stop", provider_id, usage,
                                       None, None, captured, response_hash, elapsed(), "live")
        except (_BeforeSendError, httpx.ConnectError, httpx.ConnectTimeout):
            return blank_response(status="failed", mode="live", error_code="MODEL_UNAVAILABLE", latency_ms=elapsed())
        except (_AfterSendError, httpx.TimeoutException, httpx.TransportError):
            return blank_response(status="unknown", mode="live", error_code="INTERRUPTED", latency_ms=elapsed())
