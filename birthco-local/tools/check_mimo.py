"""MiMo configuration check; live requires --live --max-calls 1.

Usage (from birthco-local/):
  python tools/check_mimo.py --dry-run          # 只校验配置，不发请求
  python tools/check_mimo.py --live --max-calls 1   # 发一次最小真实请求（计费）
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.adapters.model.mimo import (  # noqa: E402
    DEFAULT_BASE_URL, DEFAULT_MODEL_ID, MiMoAdapter,
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

    try:
        adapter = MiMoAdapter()
    except ModelConfigurationError as exc:
        print(json.dumps({"status": "config_error", "error": str(exc)}, ensure_ascii=False))
        return 2
    try:
        report = {
            "status": "configured",
            "base_url_configured": True,
            "model_id": adapter._model_id,
            "expected_model_id": DEFAULT_MODEL_ID,
            "expected_base_url": DEFAULT_BASE_URL,
        }
        if args.dry_run:
            print(json.dumps(report, ensure_ascii=False))
            return 0
        request = ModelRequest(
            call_id="check_mimo_1", role="check",
            messages=(ModelMessage("user", '连通性检查。请只回复一个 JSON 对象：{"ok":true}'),
                      ModelMessage("system", "Reply with JSON only.")),
            model_id=adapter._model_id, max_completion_tokens=64,
            timeout_seconds=30.0, temperature=0.0, top_p=1.0,
            json_mode=True, mode="live",
        )
        response = adapter.complete(request)
        report.update({
            "call_status": response.status,
            "error_code": response.error_code,
            "finish_reason": response.finish_reason,
            "provider_request_id": response.provider_request_id,
            "usage": {"input": response.usage.input, "output": response.usage.output,
                      "total": response.usage.total},
            "latency_ms": response.latency_ms,
            "response_bytes": response.response_bytes,
            "response_hash": response.response_hash,
            "text_preview": (response.text or "")[:80],
            "evidence_class": "real_model_single_connectivity_call",
        })
        print(json.dumps(report, ensure_ascii=False))
        return 0 if response.status == "received" else 3
    finally:
        adapter.close()


if __name__ == "__main__":
    raise SystemExit(main())
