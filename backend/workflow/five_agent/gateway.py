"""Central AgentGateway: the only path to any of the five agents.

Per-call protocol (five-agent interaction design §4/§6):
  lookup committed receipt -> reserve budget/call -> mark send intent -> adapter
  -> validate result -> persist typed output + call + usage atomically -> return.

- Same step_key with a committed receipt replays with ZERO new calls.
- Technical failures before send consume the shared retry pool (new attempt).
- Sent-but-unknown results become INTERRUPTED; never auto-resent, usage unknown.
- Protocol/schema mismatches commit zero domain data; classified, may retry.
- Cancel bumps run epoch; results arriving later are discarded, never commit.
- usage unknown stays unknown (total_tokens None), never zero-filled.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .adapters import AgentUnavailableError, PreSendFailure, SendFailure, UnknownResult
from .contracts import (
    AgentCall, AgentResult, ProtocolError, StepContext, Usage,
    default_validators, frozen_input_hash,
)
from .registry import BUDGETS, BudgetProfile
from .repository import Repository


class GatewayError(Exception):
    code = "MODEL_REJECTED"

    def __init__(self, message: str, code: str | None = None, retryable: bool = False):
        super().__init__(message)
        if code:
            self.code = code
        self.retryable = retryable


class BudgetExceeded(GatewayError):
    code = "BUDGET_EXCEEDED"


class AgentUnavailable(GatewayError):
    code = "MODEL_UNAVAILABLE"


class InterruptedUnknown(GatewayError):
    code = "INTERRUPTED"


class CancelledError(GatewayError):
    code = "INVALID_TRANSITION"


@dataclass
class StepOutcome:
    """Result of one logical step (after replay/retry accounting)."""
    result: AgentResult | None
    replayed: bool = False
    call_id: str | None = None
    output_id: str | None = None
    attempts_used: int = 1
    unknown: bool = False  # sent-but-unknown under step_incomplete policy

    @property
    def status(self) -> str:
        return "unknown" if self.unknown else self.result.status

    @property
    def data(self) -> dict | None:
        return None if self.unknown else self.result.data


@dataclass
class BudgetGate:
    """Central budget ledger. Every adapter invocation attempt passes through here.

    Settlement model: counters are committed exactly once per attempt, together
    with the attempt's terminal call row (received / failed_* / interrupted) in
    Repository.  In-flight rows left by a crash are settled by
    Repository.reconcile_orphan_calls before the next attempt on the run is
    reserved, so no attempt can escape accounting.
    """
    repo: Repository

    def check_and_reserve(self, run_id: str, kind: str, attempt: int, action: str) -> None:
        profile: BudgetProfile = BUDGETS[kind]
        usage = self.repo.get_usage(run_id)
        is_retry = attempt > 1
        if is_retry:
            if usage["tech_retries"] + 1 > profile.max_tech_retries:
                raise BudgetExceeded(f"tech retry pool exhausted for run {run_id}")
        else:
            if usage["normal_calls"] + 1 > profile.max_normal_calls:
                raise BudgetExceeded(f"normal call budget exhausted for run {run_id}")
        if usage["calls_reserved"] + 1 > profile.max_total_calls:
            raise BudgetExceeded(f"total call budget exhausted for run {run_id}")
        if usage["tokens_known"] >= profile.max_total_tokens:
            raise BudgetExceeded(f"token budget exhausted for run {run_id}")


class AgentGateway:
    def __init__(self, repo: Repository, adapter_router: Callable[[str], Any],
                 validators=None, clock: Callable[[], float] = time.monotonic):
        self.repo = repo
        self._router = adapter_router
        self.validators = validators or default_validators()
        self.budget = BudgetGate(repo)
        self._clock = clock
        self._locks_guard = threading.Lock()
        self._run_locks: dict[str, threading.RLock] = {}

    def _run_lock(self, run_id: str) -> threading.RLock:
        """One logical run executes its calls serially; the lock makes
        'no adapter invocation is executing for this run' a checkable fact at
        invoke entry, so in-flight rows can be reconciled without heuristics."""
        with self._locks_guard:
            return self._run_locks.setdefault(run_id, threading.RLock())

    # ------------------------------------------------------------------ guards
    def _guard_run(self, run_id: str) -> dict:
        run = self.repo.get_run(run_id)
        if run["status"] == "CANCELLED":
            raise CancelledError(f"run {run_id} cancelled")
        return run

    # ------------------------------------------------------------------ invoke
    def invoke(self, run_id: str, step_key: str, action: str, input_payload: dict,
               account_id: str, task_id: str, prompt_schema_version: str,
               max_attempts: int = 3, unknown_policy: str = "run_interrupt") -> StepOutcome:
        """unknown_policy:
        - run_interrupt: sent-but-unknown raises InterruptedUnknown, run -> INTERRUPTED.
        - step_incomplete: (read_segment only) returns StepOutcome(unknown=True) and
          leaves run running; caller marks the audience session incomplete.
        """
        with self._run_lock(run_id):
            self.repo.reconcile_orphan_calls(run_id)
            return self._invoke_inner(run_id, step_key, action, input_payload,
                                      account_id, task_id, prompt_schema_version,
                                      max_attempts, unknown_policy)

    def _invoke_inner(self, run_id: str, step_key: str, action: str, input_payload: dict,
                      account_id: str, task_id: str, prompt_schema_version: str,
                      max_attempts: int, unknown_policy: str) -> StepOutcome:
        run = self._guard_run(run_id)
        agent_id = self.validators.contract["actions"][action]["agent_id"]

        input_hash = frozen_input_hash(input_payload, prompt_schema_version)
        # 1) idempotent replay from a committed receipt produced from IDENTICAL
        #    input (input_hash).  A receipt under the same step_key but from a
        #    different input is a stale artifact and must never be replayed.
        receipt = self.repo.get_step_output(run_id, step_key, input_hash)
        if receipt is not None:
            result = AgentResult.from_dict(receipt["payload"])
            return StepOutcome(result=result, replayed=True, call_id=receipt["call_id"],
                               output_id=receipt["id"], attempts_used=0)
        last_error: Exception | None = None
        attempt = 1
        while attempt <= max_attempts:
            run = self._guard_run(run_id)
            epoch_at_reserve = run["epoch"]
            self.budget.check_and_reserve(run_id, run["kind"], attempt, action)
            call_id = f"call_{uuid.uuid4().hex[:16]}"
            request_id = f"req_{uuid.uuid4().hex[:16]}"
            context = StepContext(account_id=account_id, task_id=task_id, run_id=run_id,
                                  step_key=step_key, attempt=attempt, input_hash=input_hash)
            call = AgentCall(request_id=request_id, agent_id=agent_id, action=action,
                             context=context, input=input_payload)
            self.validators.validate_call(call)
            self.repo.reserve_call(call_id, run_id, step_key, attempt, agent_id, action,
                                   request_id, input_hash)
            adapter = self._router(action)
            self.repo.mark_send_intent(call_id)

            try:
                raw_result = adapter.invoke(call)
            except AgentUnavailableError as exc:
                # missing teammate implementation: AGENT_UNAVAILABLE, never mock fallback
                self.repo.fail_call(call_id, run_id, attempt, status="failed_pre_send")
                raise AgentUnavailable(str(exc)) from exc
            except SendFailure as exc:
                if exc.sent:
                    # sent but result unknown -> usage unknown, no auto resend
                    self.repo.interrupt_call(call_id, run_id, attempt)
                    if unknown_policy == "step_incomplete":
                        return StepOutcome(result=None, replayed=False, call_id=call_id,
                                           attempts_used=attempt, unknown=True)
                    self.repo.set_run_status(run_id, "INTERRUPTED", error={
                        "code": "INTERRUPTED", "call_id": call_id,
                        "cause_hint": str(exc), "next_action": "confirm cost risk then resend explicitly"})
                    raise InterruptedUnknown(
                        f"call {call_id} sent but result unknown; manual cost-risk confirmation required") from exc
                self.repo.fail_call(call_id, run_id, attempt, status="failed_pre_send")
                last_error = exc
                if not exc.retryable or attempt >= max_attempts:
                    raise GatewayError(str(exc), code=exc.code, retryable=exc.retryable) from exc
                attempt += 1
                continue
            except Exception as exc:  # unexpected adapter crash: treat as pre-send retryable
                self.repo.fail_call(call_id, run_id, attempt, status="failed_pre_send")
                last_error = exc
                if attempt >= max_attempts:
                    raise GatewayError(f"adapter crashed: {exc}", code="MODEL_UNAVAILABLE") from exc
                attempt += 1
                continue

            # cancel/epoch fence: a late result after cancel must never commit
            run_now = self.repo.get_run(run_id)
            if run_now["status"] == "CANCELLED" or run_now["epoch"] != epoch_at_reserve:
                late_usage = None
                try:
                    late_usage = AgentResult.from_dict(raw_result).usage.to_dict()
                except Exception:
                    late_usage = None
                self.repo.discard_call(call_id, "cancel_epoch_fence", late_usage)
                raise CancelledError(
                    f"call {call_id} result arrived after cancel/epoch bump; discarded")

            # post-send protocol validation
            try:
                result_raw = self.validators.validate_result(raw_result, call)
            except ProtocolError as exc:
                self.repo.fail_call(call_id, run_id, attempt, status="failed_protocol")
                last_error = exc
                if attempt >= max_attempts:
                    raise GatewayError(f"protocol failure: {exc}", code="SCHEMA_INVALID") from exc
                attempt += 1
                continue

            result = AgentResult.from_dict(result_raw)
            usage = result.usage
            output_id = f"out_{uuid.uuid4().hex[:16]}"
            self.repo.complete_call(call_id, step_key, run_id, attempt, action, input_hash,
                                    result_raw, usage.to_dict(), output_id)
            return StepOutcome(result=result, replayed=False, call_id=call_id,
                               output_id=output_id, attempts_used=attempt)

        raise GatewayError(f"step {step_key} exhausted attempts: {last_error}", code="MODEL_REJECTED")

    # --------------------------------------------------------- late/cancel path
    def record_late_result(self, call_id: str, usage: Usage | None, reason: str = "cancelled") -> None:
        """A result arriving after cancel/epoch bump: usage recorded, nothing committed."""
        self.repo.discard_call(call_id, reason, usage.to_dict() if usage else None)

    def resend_after_interrupt(self, run_id: str, step_key: str, action: str, input_payload: dict,
                               account_id: str, task_id: str, prompt_schema_version: str,
                               cost_risk_confirmed: bool) -> StepOutcome:
        """Explicit user-confirmed resend of an INTERRUPTED call (new attempt)."""
        if not cost_risk_confirmed:
            raise GatewayError("resend requires explicit user cost-risk confirmation", code="ORIGIN_DENIED")
        with self._run_lock(run_id):
            run = self.repo.get_run(run_id)
            if run["status"] != "INTERRUPTED":
                raise GatewayError(f"run {run_id} is {run['status']}, cannot resend", code="INVALID_TRANSITION")
            attempts_used = len(self.repo.list_calls(run_id))
            self.repo.set_run_status(run_id, "RUNNING")
            return self.invoke(run_id, step_key, action, input_payload, account_id, task_id,
                               prompt_schema_version, max_attempts=2)
