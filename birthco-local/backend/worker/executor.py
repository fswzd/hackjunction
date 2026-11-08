"""Run the existing agents against the workbench's durable queue and ledger."""
from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
from threading import Event, Thread
from time import monotonic, sleep
from uuid import uuid4

from backend.adapters.model.factory import (
    agent_model_id, agent_registry, create_agent_adapter,
)
from backend.agents.director import FrozenContentRules
from backend.domain.errors import DomainError
from backend.domain.hashing import canonical_bytes, sha256_json
from backend.storage.db import connect, immediate, utc_now, is_transient_db_error
from backend.storage.queue import Queue
from backend.storage.repository import Repository, _event


LOG = logging.getLogger(__name__)
RULES = FrozenContentRules(rule_version="content-rules-v1", title_count=3, max_body_characters=20000)

# Workbench step role -> contract role used by the seven-agent interface registry.
ROLE_TO_AGENT = {
    "pr_analyst": "pr_analyst",
    "operator": "operations_officer",
    "director": "content_creator",
    "reviewer": "editorial_reviewer",
    "scout": "traffic_scout",
    "audience": "simulated_audience",
    "analyst": "data_analyst",
}


def _transient_failure(exc: BaseException) -> bool:
    """Recoverable local storage hiccup, not a business/validation failure."""
    if isinstance(exc, DomainError):
        return exc.code == "STORAGE_UNAVAILABLE" and exc.retryable
    return is_transient_db_error(exc)


def encoded(value):
    return canonical_bytes(value).decode("utf-8")


class Step:
    """One bounded agent invocation. Live calls reserve before transport."""

    def __init__(self, work, key, role, snapshot, system):
        self.work = work
        self.key = key
        self.role = role
        self.snapshot = snapshot
        self.system = system
        self.call_id = None
        self.response = None
        prior = work.read(
            "SELECT coalesce(max(attempt),0)+1 AS attempt, max(status='committed') AS committed "
            "FROM checkpoints WHERE run_id=? AND step=?",
            (work.lease.run_id, key),
        )
        if prior["committed"]:
            raise DomainError("INVALID_TRANSITION", "The step already has a committed outcome",
                              "Inspect the saved result before starting a new run")
        self.attempt = prior["attempt"]

    def reserve(self, model_id, prompt_hash, input_hash, estimate):
        lease = self.work.lease
        if self.call_id is not None:
            raise DomainError("BUDGET_EXCEEDED", "Agent attempted a second call", "Inspect the worker step")
        self.call_id = self.work.repo.reserve_call(
            task_id=lease.task_id, run_id=lease.run_id, owner=lease.owner, epoch=lease.epoch,
            step=self.key, attempt=self.attempt, role=self.role, mode=self.work.mode,
            model_id=model_id, prompt_hash=prompt_hash, input_hash=input_hash,
            token_estimate=estimate,
        )
        self.work.repo.mark_sent(self.call_id)

    def complete(self, request):
        prompt, *inputs = request.messages
        payload = [message.content for message in inputs]
        estimate = len(prompt.content.encode()) + sum(len(item.encode()) for item in payload)
        self.reserve(request.model_id, sha256_json(prompt.content), sha256_json(payload),
                     estimate + request.max_completion_tokens)
        self.response = self.work.adapter.complete(request)
        return self.response

    def run(self, agent_type, method, persist, **options):
        event_step = {"pr_analyst": "pr_intake", "scout": "scout", "operator": "operator",
                      "director": self.key, "reviewer": "review", "audience": "audience", "analyst": "analysis"}[self.role]
        if self.role != "audience":
            with self.work.transaction() as db:
                self.work.event(db, event_step, "角色开始处理")
        if self.work.mode == "mock":
            model_id = f"mock-{self.role}-v1"
            self.reserve(model_id, sha256_json(self.system), sha256_json(self.snapshot), 0)
            agent = agent_type(mode="mock", model_id=model_id)
        else:
            # Each of the seven agents resolves its own provider / endpoint /
            # model. No single hard-wired provider, no silent mock fallback.
            self.work.bind_role(self.role)
            agent = agent_type(self, mode="live", model_id=self.work.model_id)
        try:
            result = getattr(agent, method)(self.snapshot, **options)
        except Exception as exc:
            LOG.exception("Agent step %s/%s raised", self.role, self.key)
            if self.response is not None:
                self.settle(rejected_error=exc if isinstance(exc, DomainError) else None)
            elif self.work.mode == "mock" and self.call_id is not None:
                self.work.repo.finish_call(self.call_id, status="failed", input_tokens=0, output_tokens=0, total_tokens=0)
            raise
        output = result.as_dict()
        if self.work.mode == "live" and self.call_id is None:
            # The agent returned a validation or clarification without transport.
            with self.work.transaction() as db:
                persist(db, result, None)
            return result
        error = getattr(result, "error", None)
        rejected = DomainError(error.code, error.cause_hint, error.next_action) if error else None
        self.settle(output, rejected_error=rejected)
        if self.response is not None and self.response.status != "received":
            unknown = self.response.status == "unknown"
            raise DomainError("INTERRUPTED" if unknown else "MODEL_UNAVAILABLE",
                              "Provider outcome is unknown" if unknown else "Provider call failed",
                              "Inspect the call ledger before resuming")
        if rejected:
            raise rejected
        if self.response is not None and self.response.status != "received":
            unknown = self.response.status == "unknown"
            raise DomainError("INTERRUPTED" if unknown else "MODEL_UNAVAILABLE",
                              "Provider outcome is unknown" if unknown else "Provider call failed",
                              "Inspect the call ledger before resuming")
        lease = self.work.lease
        if not self.work.repo.commit_step(
            task_id=lease.task_id, run_id=lease.run_id, owner=lease.owner, epoch=lease.epoch,
            step=self.key, attempt=self.attempt, output_ref=self.call_id, output_hash=sha256_json(output),
            persist=lambda db: persist(db, result, self.call_id),
        ):
            raise DomainError("VERSION_CONFLICT", "Result arrived after the lease ended", "Reload the task")
        return result

    def settle(self, output=None, *, rejected_error: DomainError | None = None):
        if self.response is None:
            status, usage, fingerprint = "received", (0, 0, 0), sha256_json(output)
        else:
            response = self.response
            status = response.status
            usage = (response.usage.input, response.usage.output, response.usage.total)
            if any(value is None for value in usage):
                usage = (None, None, None)
            fingerprint = response.response_hash
        self.work.repo.finish_call(self.call_id, status=status, input_tokens=usage[0],
                                   output_tokens=usage[1], total_tokens=usage[2],
                                   response_hash=fingerprint, rejected_error=rejected_error)


class Work:
    def __init__(self, db_path, lease):
        self.db_path, self.lease = db_path, lease
        self.queue, self.repo = Queue(db_path), Repository(db_path)
        self.mode = self.run()["mode"]
        self.model_id = "mock-local-v1"
        self.adapter = None
        self._adapters: dict[str, object] = {}

    def bind_role(self, role: str) -> None:
        """Resolve the interface for one agent, lazily and once per run.

        Live mode never falls back to Mock: a missing provider configuration is
        a typed, actionable failure instead of a silent downgrade.
        """
        agent_id = ROLE_TO_AGENT.get(role, role)
        self.model_id = agent_model_id(agent_id)
        if agent_id not in self._adapters:
            try:
                adapter = create_agent_adapter(agent_id)
            except ValueError as exc:
                raise DomainError("MODEL_UNAVAILABLE", str(exc),
                                  "在设置中配置 Agent 接口，或切回离线 Mock 模式") from None
            if adapter is None:
                raise DomainError("MODEL_UNAVAILABLE",
                                  f"{agent_id} 未配置真实模型接口（当前为离线 Mock）",
                                  "在设置中配置 AGENT_API_KEY / AGENT_BASE_URL，或切回离线 Mock 模式")
            self._adapters[agent_id] = adapter
        self.adapter = self._adapters[agent_id]

    def close_adapters(self) -> None:
        for adapter in self._adapters.values():
            try:
                adapter.close()
            except Exception:
                LOG.exception("Failed to close a model adapter")
        self._adapters.clear()
        self.adapter = None

    def read(self, sql, params, *, many=False):
        with connect(self.db_path) as db:
            cursor = db.execute(sql, params)
            return cursor.fetchall() if many else cursor.fetchone()

    def run(self):
        return self.read("SELECT * FROM runs WHERE id=?", (self.lease.run_id,))

    def task(self):
        return self.read("SELECT * FROM tasks WHERE id=?", (self.lease.task_id,))

    @contextmanager
    def transaction(self):
        with connect(self.db_path) as db, immediate(db):
            lease = self.lease
            row = db.execute("SELECT state,lease_owner,lease_epoch,lease_until FROM runs WHERE id=?",
                             (lease.run_id,)).fetchone()
            if (row["state"], row["lease_owner"], row["lease_epoch"]) != ("RUNNING", lease.owner, lease.epoch) or row["lease_until"] <= utc_now():
                raise DomainError("VERSION_CONFLICT", "Lease is no longer current", "Reload the task")
            yield db

    def step(self, key, role, snapshot, system):
        return Step(self, key, role, snapshot, system)

    def event(self, db, step, summary, state=None):
        lease = self.lease
        if state is None:
            state = db.execute("SELECT state FROM tasks WHERE id=?", (lease.task_id,)).fetchone()[0]
        _event(db, lease.task_id, lease.run_id, "agent_progress", step, state, summary, utc_now())

    def state(self, db, state, pending=None):
        db.execute("UPDATE tasks SET state=?,pending_json=?,row_version=row_version+1,updated_at=? WHERE id=? AND current_run_id=?",
                   (state, encoded(pending) if pending else None, utc_now(), self.lease.task_id, self.lease.run_id))

    def phase(self, db, phase, state):
        db.execute("UPDATE runs SET phase=?,updated_at=? WHERE id=?", (phase, utc_now(), self.lease.run_id))
        self.state(db, state)
        self.event(db, phase, f"Worker phase: {phase}", state)

    def stop(self, db, run_state, task_state, pending=None):
        self.state(db, task_state, pending)
        Queue.release_tx(db, self.lease, run_state, utc_now())

    def fail(self, error):
        state = "INTERRUPTED" if error.code == "INTERRUPTED" else "FAILED"
        try:
            with self.transaction() as db:
                lease = self.lease
                db.execute("UPDATE runs SET error_json=? WHERE id=?", (encoded(error.detail()), lease.run_id))
                if lease.kind == "content":
                    row = db.execute("SELECT pending_json FROM tasks WHERE id=?", (lease.task_id,)).fetchone()
                    pending = json.loads(row["pending_json"] or "{}")
                    self.state(db, state, {**pending, "action": "inspect_error"})
                if lease.kind == "preview":
                    db.execute("UPDATE preview_runs SET state=?,analysis_status='failed',row_version=row_version+1 WHERE run_id=?",
                               (state, lease.run_id))
                self.event(db, "worker_error", error.code, state)
                Queue.release_tx(db, lease, state, utc_now())
        except DomainError as exc:
            if exc.code != "VERSION_CONFLICT":
                raise

    def execute(self):
        from .content import run_content
        from .preview import run_preview

        if self.mode == "live":
            # Fail fast with a single readable message instead of seven
            # half-configured agents each failing at a different step.
            missing = [row["agent_id"] for row in agent_registry()
                       if not row["configured"]]
            if missing:
                raise DomainError("MODEL_UNAVAILABLE",
                                  "以下 Agent 接口尚未配置凭据：" + "、".join(missing),
                                  "设置 AGENT_API_KEY / AGENT_BASE_URL 后重启，或切回离线 Mock 模式")
        if self.lease.kind == "content":
            run_content(self)
        elif self.lease.kind == "preview":
            run_preview(self)
        else:
            raise DomainError("INVALID_TRANSITION", "Unsupported queued run type", "Inspect the run kind")


class Worker:
    def __init__(self, data_dir: Path):
        self.db_path = data_dir / "db.sqlite"
        self.queue = Queue(self.db_path)
        self.owner = "worker_" + uuid4().hex

    def once(self):
        try:
            lease = self.queue.claim(self.owner)
        except Exception:
            # A transient SQLite/permission error must never terminate the whole
            # worker: it would leave every queued task stuck forever with no log.
            LOG.exception("Worker could not claim a run; will retry")
            return False
        if lease is None:
            return False
        stop = Event()

        def keep_alive():
            last = monotonic()
            while not stop.wait(5):
                now = monotonic()
                try:
                    self.queue.heartbeat(lease, active_ms=int((now - last) * 1000))
                except DomainError:
                    return
                last = now

        heartbeat = Thread(target=keep_alive, daemon=True)
        heartbeat.start()
        try:
            # A transient storage hiccup (WAL/journal contention, brief
            # read-only window, busy file) is not a task failure. Re-run from
            # the durable checkpoint before giving up, so users never see a
            # permanent "后端错误" for a recoverable local condition.
            for attempt in range(3):
                work = Work(self.db_path, lease)
                try:
                    work.execute()
                    break
                except Exception as exc:
                    if _transient_failure(exc) and attempt < 2:
                        LOG.warning(
                            "Transient storage error on run %s (attempt %s/3), "
                            "retrying from checkpoint: %s",
                            lease.run_id, attempt + 1, exc,
                        )
                        sleep(0.4 * (attempt + 1))
                        continue
                    if isinstance(exc, DomainError):
                        work.fail(exc)
                    else:
                        LOG.exception("Worker run %s failed", lease.run_id)
                        work.fail(DomainError("STORAGE_UNAVAILABLE", "Worker step failed",
                                              "Inspect the worker log"))
                    break
                finally:
                    work.close_adapters()
        finally:
            stop.set()
            heartbeat.join()
        return True

    def serve(self):
        LOG.info("Worker ready")
        idle = Event()
        failures = 0
        while True:
            try:
                worked = self.once()
                failures = 0
            except Exception:
                # once() handles per-run failures; this guard keeps the service
                # alive even if setup/teardown itself throws (stale DB, disk
                # full, read-only file, interrupted shutdown, ...).
                failures += 1
                LOG.exception("Worker loop iteration failed (%s consecutive)", failures)
                worked = False
            if not worked:
                idle.wait(min(0.25 * (2 ** min(failures, 4)), 4.0))
