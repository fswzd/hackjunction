"""Read-only diagnostics for the seven expert-agent interfaces.

Lets the workbench show exactly which provider each Agent resolves to, without
ever exposing a credential. Configuration is read from process environment
variables only (never from a file or the request body).
"""
from __future__ import annotations

from flask import Blueprint, current_app

from backend.api import success
from backend.adapters.model.factory import agent_registry, PROVIDERS

blueprint = Blueprint("agents", __name__)


@blueprint.get("/api/v1/agents")
def list_agents():
    rows = agent_registry()
    mode = current_app.config.get("MODEL_MODE", "mock")
    return success({
        "model_mode": mode,
        "providers": list(PROVIDERS),
        "count": len(rows),
        "configured_count": sum(1 for row in rows if row["configured"]),
        "ready": mode == "mock" or all(row["configured"] for row in rows),
        "agents": rows,
    })
