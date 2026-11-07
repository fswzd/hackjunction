"""共享桥接工具:编排层 <-> 业务 agent 适配器公共部分(运营官桥接原定义上抽)。"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable


class BridgeUnknownOutcome(Exception):
    """Model call sent but the outcome is unknown; explicit resend only."""


class BridgePreSendFailure(Exception):
    """Bridge could not build a valid request (resolution/config failure)."""


def orchestration_ref_digest(text: str) -> str:
    """编排层 material_refs 的 sha256 约定:sha256(canonical JSON of {"text": ...})."""
    blob = json.dumps({"text": text}, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def resolve_materials(input_payload: dict,
                      resolve_material: Callable[[dict], dict]) -> list[dict]:
    """Resolve refs to rows, verifying each ref's content fingerprint (F-O4)."""
    rows = []
    for ref in input_payload.get("material_refs", []):
        try:
            row = resolve_material(ref)
        except KeyError:
            raise BridgePreSendFailure(f"material {ref.get('id')} cannot be resolved") from None
        text = row.get("text")
        if not isinstance(text, str):
            raise BridgePreSendFailure(f"material {ref.get('id')} has no text")
        expected = ref.get("sha256")
        if expected is not None and expected != orchestration_ref_digest(text):
            raise BridgePreSendFailure(f"material {ref.get('id')} fingerprint mismatch")
        rows.append({**row, "id": ref["id"]})
    return rows


def issue(reason: str, requested_change: str, location: str = "bridge") -> dict:
    return {"id": "iss_" + hashlib.sha256(reason.encode()).hexdigest()[:16],
            "severity": "blocking", "location": location[:1000],
            "reason": reason[:1000],
            "requested_change": (requested_change or "检查输入")[:1000]}


def error_result(call_dict: dict, reason: str, requested_change: str = "检查输入后显式重发",
                 location: str = "bridge") -> dict:
    """确定性输入拒单 = 已知 error 结果(零模型调用、零重试、不烧预算)。"""
    return {**call_dict, "status": "error", "data": None, "questions": [],
            "issues": [issue(reason, requested_change, location)],
            "usage": {"status": "unknown", "total_tokens": None}}


def usage_dict(usage: Any) -> dict:
    if usage.total is None:
        return {"status": "unknown", "total_tokens": None}
    return {"status": "known", "total_tokens": usage.total}


DEFAULT_DERIVED_AUDIENCE = "任务中描述的读者（可在确认前修改）"
DEFAULT_DERIVED_STYLE = "符合任务要求"
PLACEHOLDER_REQUIREMENT = [{"id": "req_extract", "text": "从任务中整理交付要求"}]
LEGAL_MATERIAL_KINDS = {"user_supplied_experience", "source_text", "existing_draft"}
