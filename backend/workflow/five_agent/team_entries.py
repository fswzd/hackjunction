"""Real teammate entries for AdapterRouter (P0-A integration).

build_reals() lazily imports the birthco-local bridges (namespace package) and
wraps each in a TeamEntry translating bridge failures into gateway semantics:
BridgeUnknownOutcome / DomainError(INTERRUPTED) -> UnknownResult (sent, no auto
resend); BridgePreSendFailure / ValueError (config) -> PreSendFailure; other
DomainError -> deterministic error result (zero retry, zero model cost).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .adapters import PreSendFailure, UnknownResult

REPO_ROOT = Path(__file__).resolve().parents[3]
BC_BACKEND = REPO_ROOT / "birthco-local" / "backend"

AGENT_COMPONENT = {
    "pr_analyst": "pr_analyst",
    "operations_officer": "operator",
    "content_creator": "director",
    "editorial_reviewer": "reviewer",
    "traffic_scout": "scout",
    "data_analyst": "analyst",
    "simulated_audience": "audience",
}


def _ensure_bc_path() -> None:
    import backend  # repo root namespace package
    bc = str(BC_BACKEND)
    if bc not in backend.__path__:
        backend.__path__.append(bc)


class TeamEntry:
    """AgentAdapter-compatible wrapper; bridge constructed lazily per task."""

    mode = "live"  # a real (non-mock) adapter entry, even with an offline model

    def __init__(self, bridge_factory: Callable[[str], Any]):
        self._factory = bridge_factory
        self._cache: dict[str, Any] = {}

    def _bridge(self, task_id: str) -> Any:
        if task_id not in self._cache:
            self._cache[task_id] = self._factory(task_id)
        return self._cache[task_id]

    def invoke(self, call) -> dict:
        from backend.adapters.bridge_common import (
            BridgePreSendFailure, BridgeUnknownOutcome)
        from backend.domain.errors import DomainError
        bridge = self._bridge(call.context.task_id)
        try:
            return bridge.invoke(call)
        except BridgeUnknownOutcome as exc:
            raise UnknownResult(str(exc) or "sent but outcome unknown") from None
        except (BridgePreSendFailure, ValueError) as exc:
            raise PreSendFailure(str(exc) or "bridge pre-send failure") from None
        except DomainError as exc:
            if exc.code == "INTERRUPTED":
                raise UnknownResult(str(exc.cause_hint) or "sent but outcome unknown") from None
            return _domain_error_result(call, exc)


def _domain_error_result(call, exc) -> dict:
    return {"contract_version": getattr(call, "contract_version", "seven-agent.v0.1"),
            "request_id": getattr(call, "request_id", "req_unknown"),
            "agent_id": getattr(call, "agent_id", "unknown"),
            "action": getattr(call, "action", "unknown"),
            "status": "error", "data": None, "questions": [],
            "issues": [{"id": "iss_" + (exc.code or "DOMAIN"), "severity": "blocking",
                        "location": getattr(call, "action", "bridge"),
                        "reason": (exc.cause_hint or exc.code or "unknown error")[:1000],
                        "requested_change": (exc.next_action or "检查输入")[:1000]}],
            "usage": {"status": "unknown", "total_tokens": None}}


def build_reals(repo, mode: str = "mock",
                live_agents: set[str] | None = None) -> dict[str, Any]:
    """Construct the seven real teammate entries (business bridges).

    mode="mock": every bridge uses its business mock model (zero network).
    mode="live": bridges listed in live_agents (default: all seven) get a MiMo
    adapter from the per-agent .env config; the rest keep mock models.
    """
    if mode not in ("mock", "live"):
        raise ValueError("mode must be mock|live")
    _ensure_bc_path()
    from backend.adapters.analyst_bridge import AnalystTeamAdapter
    from backend.adapters.audience_bridge import AudienceTeamAdapter
    from backend.adapters.director_bridge import DirectorTeamAdapter
    from backend.adapters.model import factory as model_factory
    from backend.adapters.orch_bridge import OperatorTeamAdapter
    from backend.adapters.pr_bridge import PRAnalystTeamAdapter
    from backend.adapters.reviewer_bridge import ReviewerTeamAdapter
    from backend.adapters.scout_bridge import ScoutTeamAdapter

    live = set(live_agents) if live_agents is not None else set(AGENT_COMPONENT)
    if mode == "mock":
        live = set()
    unknown = live - set(AGENT_COMPONENT)
    if unknown:
        raise ValueError(f"unknown live_agents: {sorted(unknown)}")

    adapters: dict[str, Any] = {}
    model_ids: dict[str, str | None] = {}
    for agent_id, component in AGENT_COMPONENT.items():
        if agent_id in live:
            adapters[agent_id] = model_factory.create_live_adapter(component)
            model_ids[agent_id] = model_factory.live_model_id(component)
        else:
            adapters[agent_id] = None
            model_ids[agent_id] = None

    def resolve_for(task_id: str):
        def resolve(ref: dict) -> dict:
            for m in repo.list_materials(task_id):
                if m["id"] == ref["id"]:
                    return m
            raise KeyError(ref["id"])
        return resolve

    # Repo-backed resolvers (refs carry all keys; no per-task state needed).
    resolver_kwargs = {
        "resolve_brief": lambda ref: repo.get_brief(ref["task_id"], ref["brief_version"]),
        "resolve_version": lambda ref: repo.get_version(ref["id"]),
        "resolve_artifact": lambda ref: repo.get_artifact(ref["id"])["payload"],
    }
    reviewer_kwargs = {k: resolver_kwargs[k] for k in ("resolve_brief", "resolve_version")}

    def make(agent_id: str, cls, extra_kwargs: dict | None = None):
        def factory(task_id: str):
            kwargs = {"mode": "live" if agent_id in live else "mock"}
            if cls not in (AnalystTeamAdapter, AudienceTeamAdapter):
                # analyst takes repo instead of resolvers; audience takes neither.
                kwargs["resolve_material"] = resolve_for(task_id)
            if agent_id in live:
                kwargs["model_adapter"] = adapters[agent_id]
                kwargs["model_id"] = model_ids[agent_id]
            if cls is AnalystTeamAdapter:
                return cls(repo=repo, **kwargs)
            if extra_kwargs:
                kwargs.update(extra_kwargs)
            return cls(**kwargs)
        return TeamEntry(factory)

    return {
        "pr_analyst": make("pr_analyst", PRAnalystTeamAdapter),
        "operations_officer": make("operations_officer", OperatorTeamAdapter),
        "content_creator": make("content_creator", DirectorTeamAdapter, resolver_kwargs),
        "editorial_reviewer": make("editorial_reviewer", ReviewerTeamAdapter, reviewer_kwargs),
        "traffic_scout": make("traffic_scout", ScoutTeamAdapter),
        "data_analyst": make("data_analyst", AnalystTeamAdapter),
        "simulated_audience": make("simulated_audience", AudienceTeamAdapter),
    }
