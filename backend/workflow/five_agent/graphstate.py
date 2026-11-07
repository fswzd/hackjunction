"""GraphState and injected services for the five-agent StateGraph.

State holds immutable artifact references plus small program control fields —
never keys, connections, raw model output, thinking or unbounded messages
(workflow-spec.json state.forbidden).  Domain truth is re-read from Repository.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict


class FiveAgentState(TypedDict, total=False):
    # run binding (server-created)
    account_id: str
    task_id: str
    run_id: str
    run_kind: str            # content | preview | revision | scout | export
    workflow_version: str
    graph_state_schema: str
    resume_step: str
    # typed refs (overwrite only)
    brief_ref: dict | None
    version_ref: dict | None
    rule_ref: dict | None
    review_ref: dict | None
    gate_ref: dict | None
    preview_ref: dict | None
    revision_ref: dict | None
    cursor_ref: dict | None
    artifact_batch_ref: dict | None
    error_ref: dict | None
    # program control
    route_decision: str
    repair_count: int
    terminal: str | None


FORBIDDEN_STATE_KEYS = (
    "api_key", "raw_model_response", "reasoning_content", "http_client",
    "db_connection", "callable", "global_messages", "future_audience_segments",
)


def validate_state_patch(patch: dict) -> dict:
    """Typed patch guard: no forbidden fields, refs are plain dicts."""
    for key in patch:
        if key in FORBIDDEN_STATE_KEYS:
            raise ValueError(f"forbidden state key: {key}")
    return patch


@dataclass
class Services:
    repo: Any            # Repository
    gateway: Any         # AgentGateway
    router: Any          # AdapterRouter
    account_id: str = "account1"
    prompt_schema_version: str = "seven-agent.v0.1.prompt"
