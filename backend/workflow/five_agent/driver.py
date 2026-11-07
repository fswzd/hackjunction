"""OrchestrationDriver: run lifecycle over the fixed per-kind StateGraphs.

Owns: single-worker admission (global_running_limit=1), user-gate decision
intake (authenticated decisions bound to frozen subjects, idempotent), resume
via Command(resume=...), cancel + epoch fencing, and terminal bookkeeping.
Waiting for a user releases the execution slot.  Recovery re-enters at the
persisted resume_step; agent calls replay from committed receipts (zero calls).
"""
from __future__ import annotations

import threading
import uuid

from langgraph.types import Command

from .adapters import AdapterRouter
from .experiment_ledger import history_for_preview
from .gateway import AgentGateway, GatewayError
from .graph import build_graph
from .graphstate import FiveAgentState, Services
from .repository import ConflictError, DomainError, Repository, object_hash
from .registry import BUDGETS, GRAPH_STATE_SCHEMA, WORKFLOW_VERSION

TERMINAL_STATUSES = ("READY", "NEEDS_REVIEW", "WAITING_INPUT", "CANCELLED", "FAILED",
                     "INTERRUPTED", "EXPORTED")


class RunConflict(DomainError):
    code = "INVALID_TRANSITION"


class OrchestrationDriver:
    def __init__(self, repo: Repository, router: AdapterRouter | None = None,
                 mode: str = "mock", account_id: str = "account1",
                 max_input_rounds: int | None = 3):
        if max_input_rounds is not None and (type(max_input_rounds) is not int or max_input_rounds < 0):
            raise ValueError("max_input_rounds must be a nonnegative integer or None")
        self.max_input_rounds = max_input_rounds
        self.repo = repo
        self.mode = mode
        self.account_id = account_id
        self.router = router or AdapterRouter(repo, mode=mode)
        self.gateway = AgentGateway(repo, self.router)
        self._graphs: dict[str, object] = {}
        self._lock = threading.Lock()
        self._running_run: str | None = None

    # ------------------------------------------------------------------ plumbing
    def _services(self) -> Services:
        return Services(repo=self.repo, gateway=self.gateway, router=self.router,
                        account_id=self.account_id, max_input_rounds=self.max_input_rounds)

    def _compiled(self, run_kind: str):
        if run_kind not in self._graphs:
            self._graphs[run_kind] = build_graph(run_kind, self._services())
        return self._graphs[run_kind]

    def _new_run_id(self, task_id: str, kind: str) -> str:
        return f"run_{task_id}_{kind}_{uuid.uuid4().hex[:8]}"

    def _acquire_slot(self, run_id: str) -> None:
        with self._lock:
            if self._running_run is not None and self._running_run != run_id:
                current = self.repo.get_run(self._running_run)
                if current["status"] == "RUNNING":
                    raise RunConflict(f"global_running_limit=1: {self._running_run} is running")
            self._running_run = run_id

    def _release_slot(self) -> None:
        with self._lock:
            self._running_run = None

    def _base_state(self, task_id: str, run_id: str, run_kind: str, **overrides) -> FiveAgentState:
        state: FiveAgentState = {
            "account_id": self.account_id, "task_id": task_id, "run_id": run_id,
            "run_kind": run_kind, "workflow_version": WORKFLOW_VERSION,
            "graph_state_schema": GRAPH_STATE_SCHEMA, "resume_step": "start",
            "brief_ref": None, "version_ref": None, "rule_ref": None, "review_ref": None,
            "gate_ref": None, "preview_ref": None, "revision_ref": None, "cursor_ref": None,
            "artifact_batch_ref": None, "error_ref": None,
            "route_decision": "", "repair_count": 0, "terminal": None, "input_round": 0,
        }
        state.update(overrides)
        return state

    def _invoke(self, run_id: str, run_kind: str, payload: FiveAgentState | Command) -> dict:
        graph = self._compiled(run_kind)
        # Each audience call traverses project, step, commit and advance.
        limit = 100 + 4 * BUDGETS["preview"].max_normal_calls if run_kind == "preview" else 100
        config = {"configurable": {"thread_id": run_id}, "recursion_limit": limit}
        self._acquire_slot(run_id)
        self.repo.set_run_status(run_id, "RUNNING")
        try:
            result = graph.invoke(payload, config)
        except Exception as exc:
            try:
                if self.repo.get_run(run_id)["status"] == "RUNNING":
                    self.repo.set_run_status(run_id, "FAILED",
                                             error={"code": getattr(exc, "code", "FAILED"), "cause_hint": str(exc)})
                # INTERRUPTED/CANCELLED statuses are set by their own paths and kept
            except DomainError:
                pass  # cancelled/terminal runs keep their status
            self._release_slot()
            raise
        self._release_slot()
        interrupts = result.get("__interrupt__") or ()
        if interrupts:
            self.repo.set_run_status(run_id, "WAITING")
        else:
            terminal = result.get("terminal") or "READY"
            self.repo.set_run_status(run_id, terminal, resume_step=result.get("resume_step"))
        return result

    # ------------------------------------------------------------------- tasks
    def create_task(self, task_id: str, payload: dict, account_id: str | None = None) -> dict:
        return self.repo.create_task(task_id, account_id or self.account_id, payload)

    def add_material(self, task_id: str, material_id: str, text: str, kind: str = "source_text") -> dict:
        return self.repo.add_material(task_id, material_id, text, kind)

    # -------------------------------------------------------------------- runs
    def start_content_run(self, task_id: str, user_input: str = "", input_mode: str = "idea") -> dict:
        task = self.repo.get_task(task_id)
        task["payload"].setdefault("user_input", user_input or task["payload"].get("goal", ""))
        task["payload"].setdefault("input_mode", input_mode)
        self.repo.save_task_payload(task_id, task["payload"])
        run_id = self._new_run_id(task_id, "content")
        self.repo.create_run(run_id, task_id, "content")
        self.repo.log_event(task_id, run_id, "run_started", {"kind": "content"})
        result = self._invoke(run_id, "content", self._base_state(task_id, run_id, "content"))
        return self.snapshot(run_id, result)

    def start_scout_run(self, task_id: str) -> dict:
        run_id = self._new_run_id(task_id, "scout")
        self.repo.create_run(run_id, task_id, "scout")
        result = self._invoke(run_id, "scout", self._base_state(task_id, run_id, "scout"))
        return self.snapshot(run_id, result)

    def start_pr_analysis_run(self, task_id: str) -> dict:
        """Standalone commercial-intake analysis (pr_analyst), like start_scout_run."""
        run_id = self._new_run_id(task_id, "pr")
        self.repo.create_run(run_id, task_id, "pr_intake")
        result = self._invoke(run_id, "pr_intake", self._base_state(task_id, run_id, "pr_intake"))
        return self.snapshot(run_id, result)

    def start_preview_run(self, task_id: str, version_id: str) -> dict:
        version = self.repo.get_version(version_id)
        if version["task_id"] != task_id:
            raise ConflictError("version belongs to another task")
        if version["status"] not in ("ready", "accepted"):
            raise ConflictError("preview requires a qualified frozen version")
        run_id = self._new_run_id(task_id, "preview")
        self.repo.create_run(run_id, task_id, "preview")
        state = self._base_state(task_id, run_id, "preview",
                                 version_ref={"id": version_id, "sha256": version["content_hash"]})
        result = self._invoke(run_id, "preview", state)
        return self.snapshot(run_id, result)

    def preview_history(self, preview_id: str) -> list[dict]:
        return history_for_preview(self.repo, self.account_id, preview_id)

    def start_revision_run(self, task_id: str, revision_request_id: str) -> dict:
        artifact = self.repo.get_artifact(revision_request_id)
        if artifact["task_id"] != task_id or artifact["kind"] != "revision_request":
            raise ConflictError("revision request belongs to another task")
        request = artifact["payload"]
        base = self.repo.get_version(request["base_version_id"])
        if base["task_id"] != task_id:
            raise ConflictError("base version belongs to another task")
        head = self.repo.list_versions(task_id)
        if head and head[-1]["id"] != base["id"]:
            raise ConflictError("revision base is not current head")  # base CAS
        run_id = self._new_run_id(task_id, "revision")
        self.repo.create_run(run_id, task_id, "revision")
        bindings = self.repo.find_artifacts(task_id, "version_brief")
        brief_ref = next((row["payload"]["brief_ref"] for row in bindings
                          if row["payload"]["version_id"] == base["id"]), None)
        state = self._base_state(task_id, run_id, "revision", brief_ref=brief_ref,
                                 version_ref={"id": base["id"], "sha256": base["content_hash"]},
                                 revision_ref={"id": revision_request_id,
                                               "sha256": object_hash(request)})
        result = self._invoke(run_id, "revision", state)
        return self.snapshot(run_id, result)

    def reinvoke(self, run_id: str, state_overrides: dict | None = None) -> dict:
        """Recovery entry: re-run from the persisted resume_step with existing refs.

        Agent steps replay from committed domain receipts — zero new model calls.
        """
        run = self.repo.get_run(run_id)
        if run["status"] in ("CANCELLED",):
            raise RunConflict("cancelled run cannot be reinvoked")
        state = self._base_state(run["task_id"], run_id, run["kind"],
                                 resume_step=run["resume_step"] or "start",
                                 input_round=sum(e["run_id"] == run_id for e in
                                                 self.repo.list_events(run["task_id"], "input_supplied")))
        state.update(state_overrides or {})
        result = self._invoke(run_id, run["kind"], state)
        return self.snapshot(run_id, result)

    # -------------------------------------------------------------------- gates
    def decide(self, run_id: str, gate_id: str, approved: bool = True, payload: dict | None = None,
               idempotency_key: str | None = None) -> dict:
        """Authenticated user decision: commit domain gate/command, then resume."""
        gate = self.repo.get_gate(gate_id)
        if gate["run_id"] != run_id:
            raise ConflictError("gate/run mismatch")
        idem = idempotency_key or f"idec_{object_hash({'gate': gate_id, 'payload': payload or {}, 'approved': approved})[:24]}"
        decision_key = f"dec_{object_hash({'gate': gate_id, 'idem': idem})[:24]}"
        decision = {"decision_key": decision_key, "approved": bool(approved),
                    "payload": payload or {}}
        if gate["status"] in ("approved", "rejected") and gate["decision_key"] == decision_key:
            # double-click with the same idempotency key: return the original
            # response shape without re-invoking the graph or re-calling agents
            return self.snapshot(run_id)
        elif gate["status"] in ("approved", "rejected"):
            raise ConflictError("gate already decided with a different decision")
        else:
            self.repo.apply_gate_decision(gate_id, decision, idem)
        run = self.repo.get_run(run_id)
        result = self._invoke(run_id, run["kind"],
                              Command(resume={"gate_id": gate_id, "decision_key": decision_key}))
        return self.snapshot(run_id, result)

    def reject(self, run_id: str, gate_id: str, idempotency_key: str | None = None) -> dict:
        return self.decide(run_id, gate_id, approved=False, payload={},
                           idempotency_key=idempotency_key)

    # ------------------------------------------------------------ cancel/recovery
    def cancel_run(self, run_id: str, reason: str = "user cancel") -> dict:
        """Domain cancel: bump epoch (late results fenced), obsolete commands."""
        run = self.repo.get_run(run_id)
        if run["status"] in TERMINAL_STATUSES:
            return self.snapshot(run_id)
        epoch = self.repo.bump_epoch(run_id)
        self.repo.set_run_status(run_id, "CANCELLED", error={"code": "CANCELLED", "cause_hint": reason})
        self.repo.obsolete_pending_commands(run_id, reason)
        self.repo.log_event(run["task_id"], run_id, "run_cancelled", {"epoch": epoch, "reason": reason})
        return self.snapshot(run_id)

    def confirm_interrupted_resend(self, run_id: str, cost_risk_confirmed: bool) -> dict:
        """User explicitly accepts cost risk to resend an INTERRUPTED call.

        Re-enters the graph at the interrupted step; the gateway then issues a new
        attempt (no committed receipt exists for an interrupted call)."""
        run = self.repo.get_run(run_id)
        if run["status"] != "INTERRUPTED":
            raise RunConflict(f"run is {run['status']}, nothing to resend")
        if not cost_risk_confirmed:
            raise DomainError("resend requires explicit cost-risk confirmation", "ORIGIN_DENIED")
        interrupted = [c for c in self.repo.list_calls(run_id) if c["status"] == "interrupted"]
        if not interrupted:
            raise RunConflict("no interrupted call to resend")
        step_prefix = interrupted[-1]["step_key"].split(":", 1)[0]
        resume_map = {"draft": "draft", "revise_scoped": "draft_scoped", "brief": "brief",
                      "review": "review", "repair": "repair", "audience": "audience_step",
                      "analysis": "analysis", "scout": "traffic", "pr": "pr_analysis"}
        resume_step = resume_map.get(step_prefix, run["resume_step"] or "start")
        return self.reinvoke(run_id, {"resume_step": resume_step})

    # ---------------------------------------------------------------- snapshot
    def snapshot(self, run_id: str, result: dict | None = None) -> dict:
        run = self.repo.get_run(run_id)
        usage = self.repo.get_usage(run_id)
        gates = self.repo.pending_gates(run_id)
        out = {
            "run_id": run_id, "kind": run["kind"], "status": run["status"],
            "resume_step": run["resume_step"], "epoch": run["epoch"],
            "pending_gates": gates, "usage": usage,
            "calls": self.repo.list_calls(run_id),
            "error": run.get("error_json"),
        }
        if result is not None:
            out["state"] = {k: result.get(k) for k in
                            ("brief_ref", "version_ref", "rule_ref", "review_ref", "gate_ref",
                             "preview_ref", "revision_ref", "cursor_ref", "artifact_batch_ref",
                             "terminal", "repair_count", "resume_step", "route_decision")}
        return out
