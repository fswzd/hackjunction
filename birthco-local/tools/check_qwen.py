"""Bailian Beijing configuration check; live requires --live --max-calls 1."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.adapters.model.qwen import (  # noqa: E402  # deprecated: live 已统一走 check_mimo.py / MiMo
    DEFAULT_BASE_URL, QwenAdapter,
    ModelConfigurationError, validate_base_url,
)
from backend.adapters.model.protocol import ModelMessage, ModelRequest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--live", action="store_true")
    parser.add_argument("--max-calls", type=int, default=0)
    args = parser.parse_args()
    if args.live and args.max_calls != 1:
        parser.error("live mode requires --max-calls 1")
    if args.dry_run and args.max_calls != 0:
        parser.error("dry run cannot reserve model calls")

    base_url = os.environ.get("QWEN_BASE_URL") or DEFAULT_BASE_URL
    try:
        validate_base_url(base_url)
    except ModelConfigurationError as exc:
        print(json.dumps({"status": "CONFIG_ERROR", "reason": str(exc)}))
        return 2
    model_id = os.environ.get("QWEN_MODEL_ID", "").strip()
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not model_id:
        print(json.dumps({"status": "SKIP", "reason": "QWEN_MODEL_ID is not configured", "network_calls": 0}))
        return 0
    if args.dry_run:
        print(json.dumps({"status": "READY", "mode": "dry-run", "network_calls": 0,
                          "model_id": model_id, "json_mode": True}))
        return 0
    if not key:
        print(json.dumps({"status": "SKIP", "reason": "DASHSCOPE_API_KEY is not configured", "network_calls": 0}))
        return 0

    request = ModelRequest(
        call_id="qwen-connection-check", role="connection_check",
        messages=(
            ModelMessage("system", 'Return only JSON with exactly one string field named "status".'),
            ModelMessage("user", 'Return {"status":"ok"}.'),
        ),
        model_id=model_id, max_completion_tokens=128, timeout_seconds=30,
        temperature=0, top_p=1, json_mode=True, mode="live",
    )
    try:
        with QwenAdapter(api_key=key, base_url=base_url,
                         configured_model_id=model_id) as adapter:
            response = adapter.complete(request)
    except ModelConfigurationError as exc:
        print(json.dumps({"status": "CONFIG_ERROR", "reason": str(exc), "network_calls": 0}))
        return 2
    # Do not print provider content, request messages, or the key.
    print(json.dumps({"status": response.status, "mode": "live", "network_calls": 1,
                      "error_code": response.error_code, "response_hash": response.response_hash,
                      "response_bytes": response.response_bytes,
                      "usage": {"input": response.usage.input, "output": response.usage.output,
                                "total": response.usage.total, "cached": response.usage.cached,
                                "reasoning": response.usage.reasoning}}, ensure_ascii=False))
    return 0 if response.status == "received" else 1


if __name__ == "__main__":
    raise SystemExit(main())
