"""five-agent.v0.2 unified call protocol: AgentCall / AgentResult + schema validation.

Boundary contract per docs: five-agent/agent-interface.json. The validators are a
library port of the handoff tool `five-agent/tools/verify_interfaces.py`, so the
same fixture semantics (correlation, usage-unknown, ok/needs_input/error rules)
are enforced at runtime, not only in the offline checker.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable

from jsonschema import Draft202012Validator

from .resources import load_contract, load_domain_schemas

CONTRACT_VERSION = "seven-agent.v0.1"  # evolution of five-agent.v0.2 (see resources/agent-interface-seven.json)

Status = str  # "ok" | "needs_input" | "error"


class ProtocolError(Exception):
    """Result/call violates the boundary contract. Zero domain commit."""


class SchemaDriftError(ProtocolError):
    pass


def canonical_json(obj: Any) -> bytes:
    """Canonical JSON (UTF-8, sorted keys, no NaN/Infinity) for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def frozen_input_hash(input_payload: dict, prompt_schema_version: str) -> str:
    """input_hash = sha256(canonical JSON of frozen visible input + schema/prompt version)."""
    return sha256_hex(canonical_json({"input": input_payload, "prompt_schema_version": prompt_schema_version}))


@dataclass(frozen=True)
class StepContext:
    account_id: str
    task_id: str
    run_id: str
    step_key: str
    attempt: int
    input_hash: str

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id, "task_id": self.task_id, "run_id": self.run_id,
            "step_key": self.step_key, "attempt": self.attempt, "input_hash": self.input_hash,
        }


@dataclass(frozen=True)
class AgentCall:
    request_id: str
    agent_id: str
    action: str
    context: StepContext
    input: dict
    contract_version: str = CONTRACT_VERSION

    def to_dict(self) -> dict:
        return {
            "contract_version": self.contract_version, "request_id": self.request_id,
            "agent_id": self.agent_id, "action": self.action,
            "context": self.context.to_dict(), "input": self.input,
        }


@dataclass(frozen=True)
class Usage:
    status: str  # "known" | "unknown"
    total_tokens: int | None

    def to_dict(self) -> dict:
        return {"status": self.status, "total_tokens": self.total_tokens}

    @staticmethod
    def known(total_tokens: int) -> "Usage":
        if isinstance(total_tokens, bool) or not isinstance(total_tokens, int) or total_tokens < 0:
            raise ProtocolError("known usage requires nonnegative int total_tokens")
        return Usage("known", total_tokens)

    @staticmethod
    def unknown() -> "Usage":
        return Usage("unknown", None)


@dataclass(frozen=True)
class AgentResult:
    request_id: str
    agent_id: str
    action: str
    status: Status
    data: dict | None
    questions: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    usage: Usage = field(default_factory=Usage.unknown)
    contract_version: str = CONTRACT_VERSION

    def to_dict(self) -> dict:
        return {
            "contract_version": self.contract_version, "request_id": self.request_id,
            "agent_id": self.agent_id, "action": self.action, "status": self.status,
            "data": self.data, "questions": list(self.questions), "issues": list(self.issues),
            "usage": self.usage.to_dict(),
        }

    @staticmethod
    def from_dict(raw: dict) -> "AgentResult":
        usage_raw = raw.get("usage") or {}
        return AgentResult(
            request_id=raw["request_id"], agent_id=raw["agent_id"], action=raw["action"],
            status=raw["status"], data=raw.get("data"), questions=list(raw.get("questions") or []),
            issues=list(raw.get("issues") or []),
            usage=Usage(usage_raw.get("status"), usage_raw.get("total_tokens")),
            contract_version=raw.get("contract_version", CONTRACT_VERSION),
        )


def _ident() -> dict:
    return {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"}


def _digest() -> dict:
    return {"type": "string", "pattern": "^[a-f0-9]{64}$"}


def _obj(properties: dict) -> dict:
    return {"type": "object", "required": list(properties), "properties": properties,
            "additionalProperties": False}


class ContractValidators:
    """Validates AgentCall / AgentResult envelopes and action I/O DTOs."""

    def __init__(self, contract: dict | None = None, domain: dict | None = None):
        self.contract = contract or load_contract()
        self.domain = domain or load_domain_schemas()
        if self.contract["contract_version"] != CONTRACT_VERSION:
            raise SchemaDriftError("contract_version drift")
        self._build()

    def _build(self) -> None:
        contract, domain = self.contract, self.domain
        ref = _obj({"id": _ident(), "sha256": _digest()})
        brief_ref = _obj({"task_id": _ident(), "brief_version": {"type": "integer", "minimum": 1},
                          "brief_hash": _digest()})
        types = {
            "text": {"type": "string", "minLength": 1, "maxLength": 20000},
            "idea|existing_draft": {"enum": ["idea", "existing_draft"]},
            "Ref": ref, "Ref[]": {"type": "array", "items": ref, "maxItems": 20},
            "Ref|null": {"anyOf": [ref, {"type": "null"}]}, "BriefRef": brief_ref,
            # operator bridge extensions (opt: prefix marks an optional input field)
            "Requirement[]": {"type": "array", "maxItems": 30,
                              "items": domain["Brief"]["$defs"]["Requirement"]},
            "EditScope|null": {"anyOf": [domain["Brief"]["$defs"]["EditScope"], {"type": "null"}]},
        }
        context = _obj({
            "account_id": _ident(), "task_id": _ident(), "run_id": _ident(),
            "step_key": {"type": "string", "minLength": 1},
            "attempt": {"type": "integer", "minimum": 1}, "input_hash": _digest()})
        call = _obj({
            "contract_version": {"const": CONTRACT_VERSION}, "request_id": _ident(),
            "agent_id": {"enum": list(contract["roles"])}, "action": {"enum": list(contract["actions"])},
            "context": context, "input": {"type": "object"}})
        result = _obj({
            "contract_version": {"const": CONTRACT_VERSION}, "request_id": _ident(),
            "agent_id": {"enum": list(contract["roles"])}, "action": {"enum": list(contract["actions"])},
            "status": {"enum": contract["result"]["status"]},
            "data": {"type": ["object", "null"]},
            "questions": {"type": "array", "maxItems": 20}, "issues": {"type": "array", "maxItems": 30},
            "usage": _obj({"status": {"enum": ["known", "unknown"]},
                           "total_tokens": {"type": ["integer", "null"], "minimum": 0}})})
        self._call_validators: dict[str, Draft202012Validator] = {}
        self._output_validators: dict[str, Draft202012Validator] = {}
        for action, descriptor in contract["actions"].items():
            action_call = deepcopy(call)
            action_call["properties"]["agent_id"] = {"const": descriptor["agent_id"]}
            action_call["properties"]["action"] = {"const": action}
            input_type = contract["input_types"][action]
            if isinstance(input_type, dict):
                props, optional = {}, []
                for key, type_name in input_type.items():
                    if isinstance(type_name, str) and type_name.startswith("opt:"):
                        props[key] = types[type_name[4:]]
                        optional.append(key)
                    else:
                        props[key] = types[type_name]
                input_schema = _obj(props)
                input_schema["required"] = [k for k in input_type if k not in optional]
                action_call["properties"]["input"] = input_schema
            self._call_validators[action] = Draft202012Validator(action_call)
            self._output_validators[action] = Draft202012Validator(domain[descriptor["output_schema"]])
        self._result_validator = Draft202012Validator(result)
        self._audience_input_validator = Draft202012Validator(domain["AudienceInput"])
        self._question_validator = Draft202012Validator(domain["Question"])
        self._issue_validator = Draft202012Validator(domain["Issue"])

    # -- calls -------------------------------------------------------------
    def validate_call(self, message: dict | AgentCall) -> None:
        raw = message.to_dict() if isinstance(message, AgentCall) else message
        action = raw.get("action")
        if action not in self._call_validators:
            raise SchemaDriftError(f"unregistered action: {action!r}")
        try:
            self._call_validators[action].validate(raw)
        except Exception as exc:  # jsonschema ValidationError
            raise SchemaDriftError(f"call schema violation for {action}: {exc.message}") from exc
        if action == "read_segment":
            try:
                self._audience_input_validator.validate(raw["input"])
            except Exception as exc:
                raise SchemaDriftError(f"AudienceInput violation: {exc.message}") from exc
        if "brief_ref" in raw["input"]:
            if raw["input"]["brief_ref"]["task_id"] != raw["context"]["task_id"]:
                raise SchemaDriftError("BriefRef task mismatch")

    # -- results -----------------------------------------------------------
    def validate_result(self, message: dict | AgentResult, request: dict | AgentCall) -> dict:
        raw = message.to_dict() if isinstance(message, AgentResult) else message
        req = request.to_dict() if isinstance(request, AgentCall) else request
        try:
            self._result_validator.validate(raw)
        except Exception as exc:
            raise ProtocolError(f"result envelope violation: {exc.message}") from exc
        for key in ("contract_version", "request_id", "agent_id", "action"):
            if raw[key] != req[key]:
                raise ProtocolError(f"response correlation mismatch: {key}")
        usage = raw["usage"]
        known_ok = (usage["status"] == "known" and isinstance(usage["total_tokens"], int)
                    and not isinstance(usage["total_tokens"], bool))
        unknown_ok = usage["status"] == "unknown" and usage["total_tokens"] is None
        if not (known_ok or unknown_ok):
            raise ProtocolError("usage unknown is not zero")
        for question in raw["questions"]:
            try:
                self._question_validator.validate(question)
            except Exception as exc:
                raise ProtocolError(f"Question violation: {exc.message}") from exc
        for issue in raw["issues"]:
            try:
                self._issue_validator.validate(issue)
            except Exception as exc:
                raise ProtocolError(f"Issue violation: {exc.message}") from exc
        if raw["status"] == "ok":
            if raw["data"] is None or raw["questions"]:
                raise ProtocolError("ok requires typed data and no question")
        elif raw["status"] == "needs_input":
            if not raw["questions"]:
                raise ProtocolError("needs_input requires questions")
        else:
            if not raw["issues"] or raw["data"] is not None:
                raise ProtocolError("error requires issues and null data")
        if raw["data"] is not None:
            try:
                self._output_validators[raw["action"]].validate(raw["data"])
            except Exception as exc:
                raise ProtocolError(f"domain output violation for {raw['action']}: {exc.message}") from exc
        if raw["action"] == "prepare_brief" and raw["status"] == "ok":
            self._check_prepare_brief(raw, req)
        return raw

    def _check_prepare_brief(self, raw: dict, req: dict) -> None:
        """Semantic freeze at the orchestration boundary (audit F-O1/F-O2/F-O5).

        Applies to every producer — mock generator and real bridge alike:
        open_questions require needs_input; input_mode / material refs / route /
        edit_scope stay inside the user's declared envelope; structured
        requirements pass through with their original ids and texts.
        """
        data = raw["data"]
        if data.get("open_questions"):
            raise ProtocolError("prepare_brief: open_questions require needs_input")
        if data.get("input_mode") != req["input"].get("input_mode"):
            raise ProtocolError("prepare_brief: input_mode changed")
        refs = {r["id"] for r in req["input"].get("material_refs", [])}
        if not set(data.get("material_ids") or []) <= refs:
            raise ProtocolError("prepare_brief: material_ids outside supplied refs")
        if set(data.get("route") or []) - {"draft", "review", "export"}:
            raise ProtocolError("prepare_brief: route outside the P0 content path")
        reqs_in = req["input"].get("requirements")
        if reqs_in is not None:
            expected = {r["id"]: r["text"] for r in reqs_in}
            actual = {r["id"]: r["text"] for r in data.get("requirements") or []}
            if actual != expected:
                raise ProtocolError("prepare_brief: requirements must keep supplied ids and texts")
        scope_in = req["input"].get("edit_scope")
        if scope_in is not None:
            scope_out = data.get("edit_scope") or {}
            # the production entry may fill preserve segments (unselected paragraphs
            # are always preserved); targets and flags must be exactly as authorised
            if (scope_out.get("target_segment_ids") != scope_in.get("target_segment_ids")
                    or scope_out.get("allow_title_change") != scope_in.get("allow_title_change")
                    or scope_out.get("allow_cover_change") != scope_in.get("allow_cover_change")
                    or not set(scope_in.get("preserve_segment_ids") or [])
                    <= set(scope_out.get("preserve_segment_ids") or [])):
                raise ProtocolError("prepare_brief: edit_scope changed")


_default_validators: ContractValidators | None = None


def default_validators() -> ContractValidators:
    global _default_validators
    if _default_validators is None:
        _default_validators = ContractValidators()
    return _default_validators
