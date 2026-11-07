"""Prompt-visible rules for envelope constraints enforced after parsing."""
from backend.domain.hashing import sha256_json


ENVELOPE_RULES = (
    "外层包络硬规则：status=ok 时 data 必填，questions 和 issues 为空数组。"
    "status=needs_input 时至少一条 question。status=error 时至少一条 issue。"
    "只输出 JSON，不使用 Markdown 围栏。"
)


def prompt_schema_fingerprint(system: str, schema) -> str:
    return sha256_json({"system": system, "output_schema": schema.model_json_schema()})
