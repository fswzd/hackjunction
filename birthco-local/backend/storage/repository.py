"""Short, atomic command boundary for tasks, calls and checkpoints."""
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Callable
from uuid import uuid4

from backend.domain.errors import DomainError
from backend.domain.hashing import canonical_bytes, sha256_json
from backend.domain.schemas import CreateTask
from .db import connect, immediate, utc_now

_TASK_EDGES = set(tuple(line.split()) for line in """
DRAFT PLANNING claim_planning
PLANNING WAITING_CONFIRMATION operator_ok
PLANNING WAITING_INPUT operator_needs_input
WAITING_INPUT PLANNING supply_before_confirmation
WAITING_INPUT PLANNING replan_after_confirmed_input
WAITING_CONFIRMATION WAITING_CONFIRMATION edit_brief
WAITING_CONFIRMATION QUEUED confirm
QUEUED GENERATING claim_generation
QUEUED PLANNING claim_planning
PLANNING PLANNING claim_replanning
QUEUED VALIDATING claim_validation
QUEUED REVISING claim_repair
QUEUED EXPORTING claim_export
GENERATING VALIDATING candidate_saved
VALIDATING REVISING repair
REVISING VALIDATING revision_saved
VALIDATING EXPORTING both_pass
VALIDATING NEEDS_REVIEW repair_exhausted
VALIDATING WAITING_INPUT review_needs_input
EXPORTING READY files_committed
READY ACCEPTED accept
ACCEPTED ACCEPTED accept_new_ready
READY EXPORTING reexport
FAILED EXPORTING reexport_failed
FAILED QUEUED resume_known_failure
INTERRUPTED QUEUED resume
READY FAILED artifact_degraded
ACCEPTED ACCEPTED artifact_degraded
ACCEPTED ACCEPTED reexport_accepted
PLANNING INTERRUPTED lease_expired
PLANNING FAILED technical_stop
GENERATING INTERRUPTED lease_expired
GENERATING FAILED technical_stop
VALIDATING INTERRUPTED lease_expired
VALIDATING FAILED technical_stop
REVISING INTERRUPTED lease_expired
REVISING FAILED technical_stop
EXPORTING INTERRUPTED lease_expired
EXPORTING FAILED technical_stop
READY READY revision_saved
READY READY revision_exported
READY READY restore_head
ACCEPTED ACCEPTED revision_saved
ACCEPTED ACCEPTED revision_exported
ACCEPTED ACCEPTED restore_head
""".strip().splitlines())
_TASK_EDGES.update((state, "CANCELLED", "cancel") for state in ("DRAFT", "PLANNING", "WAITING_CONFIRMATION", "QUEUED", "GENERATING", "VALIDATING", "REVISING", "EXPORTING", "WAITING_INPUT", "NEEDS_REVIEW", "FAILED", "INTERRUPTED"))


def _id(prefix: str) -> str:
    return prefix + uuid4().hex


def _event(db, task_id: str, run_id: str, kind: str, step: str, state: str, summary: str, now: str) -> None:
    seq = db.execute("SELECT coalesce(max(seq),0)+1 FROM task_events WHERE task_id=?", (task_id,)).fetchone()[0]
    db.execute("INSERT INTO task_events(id,task_id,run_id,seq,type,step,state,summary,refs_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (_id("e_"), task_id, run_id, seq, kind, step, state, summary, "[]", now))


@dataclass(frozen=True)
class Transition:
    task_id: str
    from_state: str
    to_state: str
    action: str
    run_id: str
    summary: str


@dataclass(frozen=True)
class ConfirmBrief:
    task_id: str
    run_id: str
    expected_brief_version: int
    brief_hash: str


class Repository:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)

    def create_account(self, name: str) -> str:
        account_id = _id("a_")
        with connect(self.db_path) as db:
            with immediate(db):
                db.execute("INSERT INTO accounts(id,name) VALUES(?,?)", (account_id, name))
        return account_id

    def create_task(self, task: CreateTask, *, mode: str = "mock", idempotency_key: str | None = None) -> dict:
        if mode not in {"mock", "live"}:
            raise ValueError("invalid mode")
        now = utc_now()
        task_id, run_id = _id("t_"), _id("r_")
        scope, operation, request_hash = "local_operator", "POST /api/v1/tasks", sha256_json({"task": task.model_dump(mode="json"), "mode": mode})
        with connect(self.db_path) as db:
            with immediate(db):
                if idempotency_key:
                    existing = db.execute("SELECT request_hash,http_status,response_json FROM idempotency WHERE scope=? AND operation=? AND key=?", (scope, operation, idempotency_key)).fetchone()
                    if existing:
                        if existing["request_hash"] != request_hash:
                            raise DomainError("IDEMPOTENCY_CONFLICT", "Key already used with another request", "Use a new key for changed input")
                        import json
                        return json.loads(existing["response_json"])
                if db.execute("SELECT 1 FROM accounts WHERE id=?", (task.account_id,)).fetchone() is None:
                    raise DomainError("NOT_FOUND", "Account not found", "Choose an existing account")
                seq = db.execute("UPDATE queue_sequence SET next_seq=next_seq+1 WHERE id=1 RETURNING next_seq").fetchone()[0]
                db.execute("INSERT INTO tasks(id,account_id,input_json,state,mode,current_run_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (task_id, task.account_id, canonical_bytes(task).decode(), "DRAFT", mode, run_id, now, now))
                db.execute("INSERT INTO runs(id,task_id,kind,state,mode,phase,limits_json,created_at,updated_at,queue_seq) VALUES(?,?,?,?,?,?,?,?,?,?)", (run_id, task_id, "content", "QUEUED", mode, "planning", '{"max_model_calls":7,"max_total_tokens":60000}', now, now, seq))
                for item in task.materials:
                    material_id = _id("m_")
                    db.execute("INSERT INTO materials(id,account_id,task_id,kind,label,text,source_url,content_hash,authorized_at) VALUES(?,?,?,?,?,?,?,?,?)", (material_id, task.account_id, task_id, item.kind, item.label, item.text, item.source_url, sha256_json(item.text), now))
                _event(db, task_id, run_id, "task_created", "planning", "DRAFT", "Task accepted", now)
                response = {"task_id": task_id, "run_id": run_id, "state": "DRAFT", "row_version": 0, "mode": mode}
                if idempotency_key:
                    db.execute("INSERT INTO idempotency(scope,operation,key,request_hash,http_status,response_json,created_at) VALUES(?,?,?,?,?,?,?)", (scope, operation, idempotency_key, request_hash, 202, canonical_bytes(response).decode(), now))
                return response

    def apply(self, command: Transition | ConfirmBrief, expected_row_version: int) -> dict:
        """State CAS with the design's explicit transition action allowlist."""
        if isinstance(command, ConfirmBrief):
            return self._confirm_brief(command, expected_row_version)
        if (command.from_state, command.to_state, command.action) not in _TASK_EDGES:
            raise DomainError("INVALID_TRANSITION", "Unlisted task transition", "Reload task state")
        if command.action != "cancel":
            raise DomainError("INVALID_TRANSITION", "This action requires its domain command", "Use the specific transactional command")
        now = utc_now()
        with connect(self.db_path) as db:
            with immediate(db):
                row = db.execute("SELECT state,row_version,current_run_id FROM tasks WHERE id=?", (command.task_id,)).fetchone()
                if row is None:
                    raise DomainError("NOT_FOUND", "Task not found", "Reload tasks")
                if row["row_version"] != expected_row_version or row["state"] != command.from_state:
                    raise DomainError("VERSION_CONFLICT", "Task version changed", "Reload task", current_row_version=row["row_version"])
                owned = db.execute("SELECT 1 FROM runs WHERE id=? AND task_id=?", (command.run_id, command.task_id)).fetchone()
                if owned is None:
                    raise DomainError("SCOPE_DENIED", "Run belongs to another task", "Use task run")
                db.execute("UPDATE tasks SET state=?,row_version=row_version+1,updated_at=? WHERE id=?", (command.to_state, now, command.task_id))
                if command.action == "cancel":
                    active = db.execute("SELECT id,lease_owner,lease_epoch FROM runs WHERE task_id=? AND state IN ('QUEUED','RUNNING','WAITING','INTERRUPTED')", (command.task_id,)).fetchall()
                    for run in active:
                        db.execute("UPDATE model_calls SET status='unknown',finished_at=? WHERE run_id=? AND status='sent'", (now, run["id"]))
                        db.execute("UPDATE model_calls SET status='failed',finished_at=? WHERE run_id=? AND status='reserved'", (now, run["id"]))
                        db.execute("UPDATE checkpoints SET status='unknown' WHERE run_id=? AND status='reserved' AND EXISTS (SELECT 1 FROM model_calls c WHERE c.run_id=checkpoints.run_id AND c.step=checkpoints.step AND c.attempt=checkpoints.attempt AND c.status='unknown')", (run["id"],))
                        db.execute("UPDATE checkpoints SET status='rejected' WHERE run_id=? AND status='reserved'", (run["id"],))
                        db.execute("UPDATE runs SET state='CANCELLED',lease_owner=NULL,lease_until=NULL,lease_epoch=lease_epoch+1,queue_seq=NULL,finished_at=?,updated_at=?,row_version=row_version+1 WHERE id=?", (now, now, run["id"]))
                        if run["lease_owner"]:
                            db.execute("UPDATE worker_slot SET owner=NULL,lease_until=NULL,epoch=epoch+1 WHERE id=1 AND owner=? AND epoch=?", (run["lease_owner"], run["lease_epoch"]))
                _event(db, command.task_id, command.run_id, command.action, command.action, command.to_state, command.summary, now)
                return {"task_id": command.task_id, "state": command.to_state, "row_version": expected_row_version + 1}

    def _confirm_brief(self, command: ConfirmBrief, expected_row_version: int) -> dict:
        from .queue import Queue
        now = utc_now()
        with connect(self.db_path) as db:
            with immediate(db):
                task = db.execute("SELECT state,row_version,current_run_id,current_brief_version FROM tasks WHERE id=?", (command.task_id,)).fetchone()
                if task is None:
                    raise DomainError("NOT_FOUND", "Task not found", "Reload tasks")
                if task["row_version"] != expected_row_version or task["state"] != "WAITING_CONFIRMATION" or task["current_run_id"] != command.run_id or task["current_brief_version"] != command.expected_brief_version:
                    raise DomainError("VERSION_CONFLICT", "Task or Brief changed", "Reload the Brief", current_row_version=task["row_version"])
                brief = db.execute("SELECT brief_hash,confirmed_at FROM briefs WHERE task_id=? AND version=?", (command.task_id, command.expected_brief_version)).fetchone()
                run = db.execute("SELECT kind,state,phase FROM runs WHERE id=? AND task_id=?", (command.run_id, command.task_id)).fetchone()
                if brief is None or brief["brief_hash"] != command.brief_hash or brief["confirmed_at"] is not None or run is None or (run["kind"], run["state"], run["phase"]) != ("content", "WAITING", "planning"):
                    raise DomainError("VERSION_CONFLICT", "Brief confirmation preconditions failed", "Reload the Brief")
                db.execute("UPDATE briefs SET confirmed_at=? WHERE task_id=? AND version=?", (now, command.task_id, command.expected_brief_version))
                db.execute("UPDATE tasks SET state='QUEUED',row_version=row_version+1,updated_at=? WHERE id=?", (now, command.task_id))
                db.execute("UPDATE runs SET phase='draft',brief_version=?,brief_hash=? WHERE id=?", (command.expected_brief_version, command.brief_hash, command.run_id))
                Queue.enqueue_tx(db, command.run_id, now)
                _event(db, command.task_id, command.run_id, "confirm", "draft", "QUEUED", "Brief confirmed", now)
                return {"task_id": command.task_id, "state": "QUEUED", "row_version": expected_row_version + 1}

    def reserve_call(self, *, task_id: str, run_id: str, owner: str, epoch: int, step: str, attempt: int, role: str, mode: str, model_id: str, prompt_hash: str, input_hash: str, token_estimate: int) -> str:
        if attempt < 1 or token_estimate < 0:
            raise ValueError("invalid reservation")
        now, call_id = utc_now(), _id("c_")
        with connect(self.db_path) as db:
            with immediate(db):
                run = db.execute("SELECT state,mode,lease_owner,lease_epoch,lease_until,calls_reserved,token_known,token_reserved,limits_json FROM runs WHERE id=? AND task_id=?", (run_id, task_id)).fetchone()
                if run is None or (run["state"], run["lease_owner"], run["lease_epoch"]) != ("RUNNING", owner, epoch) or run["lease_until"] <= now:
                    raise DomainError("VERSION_CONFLICT", "Lease expired", "Stop this model call")
                if run["mode"] != mode:
                    raise DomainError("CONDITIONS_MISMATCH", "Run mode is frozen", "Use the run's persisted mode")
                import json
                limits = json.loads(run["limits_json"])
                if run["calls_reserved"] + 1 > limits.get("max_model_calls", 7) or run["token_known"] + run["token_reserved"] + token_estimate > limits.get("max_total_tokens", 60000):
                    raise DomainError("BUDGET_EXCEEDED", "Run budget exhausted", "Stop and request a new run")
                if db.execute("SELECT 1 FROM checkpoints WHERE task_id=? AND run_id=? AND step=? AND attempt=?", (task_id, run_id, step, attempt)).fetchone():
                    raise DomainError("IDEMPOTENCY_CONFLICT", "Step attempt already reserved", "Use the persisted call")
                db.execute("INSERT INTO checkpoints(task_id,run_id,step,attempt,status,input_hash,created_at) VALUES(?,?,?,?,?,?,?)", (task_id, run_id, step, attempt, "reserved", input_hash, now))
                db.execute("INSERT INTO model_calls(id,task_id,run_id,step,attempt,role,mode,model_id,prompt_hash,input_hash,status,reserved_tokens,lease_epoch,started_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (call_id, task_id, run_id, step, attempt, role, mode, model_id, prompt_hash, input_hash, "reserved", token_estimate, epoch, now))
                db.execute("INSERT INTO usage_ledger(call_id,usage_status,cost_status,updated_at) VALUES(?,'unknown','unknown',?)", (call_id, now))
                db.execute("UPDATE runs SET calls_reserved=calls_reserved+1,token_reserved=token_reserved+?,updated_at=? WHERE id=?", (token_estimate, now, run_id))
                return call_id

    def mark_sent(self, call_id: str) -> None:
        with connect(self.db_path) as db:
            with immediate(db):
                now = utc_now()
                changed = db.execute("UPDATE model_calls SET status='sent' WHERE id=? AND status='reserved' AND EXISTS (SELECT 1 FROM runs r WHERE r.id=model_calls.run_id AND r.state='RUNNING' AND r.lease_epoch=model_calls.lease_epoch AND r.lease_until>?)", (call_id, now)).rowcount
                if changed != 1:
                    raise DomainError("INVALID_TRANSITION", "Call is not reserved", "Read call ledger")

    def finish_call(self, call_id: str, *, status: str, input_tokens: int | None = None, output_tokens: int | None = None, total_tokens: int | None = None, response_hash: str | None = None) -> None:
        if status not in {"received", "failed", "unknown", "discarded"}:
            raise ValueError("invalid call status")
        known = all(x is not None for x in (input_tokens, output_tokens, total_tokens))
        if any(x is not None for x in (input_tokens, output_tokens, total_tokens)) and not known:
            raise ValueError("usage must be complete or unknown")
        now = utc_now()
        with connect(self.db_path) as db:
            with immediate(db):
                call = db.execute("SELECT run_id,status,reserved_tokens,lease_epoch FROM model_calls WHERE id=?", (call_id,)).fetchone()
                if call is None or call["status"] not in {"reserved", "sent", "unknown"} or (call["status"] == "unknown" and status != "received"):
                    raise DomainError("INVALID_TRANSITION", "Call is already settled", "Read call ledger")
                run = db.execute("SELECT state,lease_epoch,lease_until FROM runs WHERE id=?", (call["run_id"],)).fetchone()
                effective_status = "discarded" if status == "received" and (call["status"] == "unknown" or run["state"] != "RUNNING" or run["lease_epoch"] != call["lease_epoch"] or run["lease_until"] <= now) else status
                db.execute("UPDATE model_calls SET status=?,response_hash=?,finished_at=? WHERE id=?", (effective_status, response_hash, now, call_id))
                db.execute("UPDATE usage_ledger SET input_tokens=?,output_tokens=?,total_tokens=?,usage_status=?,cost_status=?,updated_at=? WHERE call_id=?", (input_tokens, output_tokens, total_tokens, "known" if known else "unknown", "unpriced" if known else "unknown", now, call_id))
                if known:
                    changed = db.execute("UPDATE runs SET token_reserved=token_reserved-?,token_known=token_known+? WHERE id=? AND token_reserved>=?", (call["reserved_tokens"], total_tokens, call["run_id"], call["reserved_tokens"]))
                    if changed.rowcount != 1:
                        raise DomainError("STORAGE_UNAVAILABLE", "Token reservation mismatch", "Stop this run and inspect ledger")
                # Unknown usage keeps the reservation against the run budget.

    def commit_step(self, *, task_id: str, run_id: str, owner: str, epoch: int, step: str, attempt: int, output_ref: str, output_hash: str, persist: Callable[[sqlite3.Connection], None] | None = None) -> bool:
        """Commit output writes and checkpoint together. persist must be local, bounded SQL only."""
        now = utc_now()
        with connect(self.db_path) as db:
            with immediate(db):
                prior = db.execute("SELECT status,output_hash FROM checkpoints WHERE task_id=? AND run_id=? AND step=? AND attempt=?", (task_id, run_id, step, attempt)).fetchone()
                if prior is None:
                    raise DomainError("NOT_FOUND", "Checkpoint missing", "Reserve the call first")
                if prior["status"] == "committed":
                    if prior["output_hash"] == output_hash:
                        return False
                    raise DomainError("VERSION_CONFLICT", "Step output hash changed", "Inspect persisted checkpoint")
                run = db.execute("SELECT state,lease_owner,lease_epoch,lease_until,kind,phase,brief_version,brief_hash,base_version_id FROM runs WHERE id=? AND task_id=?", (run_id, task_id)).fetchone()
                if run is None or (run["state"], run["lease_owner"], run["lease_epoch"]) != ("RUNNING", owner, epoch) or run["lease_until"] <= now:
                    db.execute("UPDATE model_calls SET status='discarded' WHERE run_id=? AND step=? AND attempt=? AND status IN ('received','unknown')", (run_id, step, attempt))
                    return False
                if run["kind"] == "content":
                    current = db.execute("SELECT current_run_id,current_brief_version FROM tasks WHERE id=?", (task_id,)).fetchone()
                    if current["current_run_id"] != run_id:
                        raise DomainError("SCOPE_DENIED", "Content run is no longer current", "Stop this step")
                    if run["phase"] not in {"planning", "operator"}:
                        frozen = db.execute("SELECT brief_hash,confirmed_at FROM briefs WHERE task_id=? AND version=?", (task_id, run["brief_version"])).fetchone()
                        if frozen is None or frozen["brief_hash"] != run["brief_hash"] or frozen["confirmed_at"] is None or current["current_brief_version"] != run["brief_version"]:
                            raise DomainError("VERSION_CONFLICT", "Confirmed Brief changed", "Stop this content run")
                elif run["kind"] == "revision":
                    bound = db.execute("SELECT 1 FROM revision_requests WHERE task_id=? AND run_id=? AND base_version_id=?", (task_id, run_id, run["base_version_id"])).fetchone()
                    if bound is None:
                        raise DomainError("SCOPE_DENIED", "Revision run binding missing", "Reload revision")
                elif run["kind"] == "preview":
                    bound = db.execute("SELECT 1 FROM preview_runs WHERE task_id=? AND run_id=?", (task_id, run_id)).fetchone()
                    if bound is None:
                        raise DomainError("SCOPE_DENIED", "Preview run binding missing", "Reload preview")
                elif run["kind"] == "scout":
                    bound = db.execute("SELECT 1 FROM scouts WHERE task_id=? AND run_id=?", (task_id, run_id)).fetchone()
                    if bound is None:
                        raise DomainError("SCOPE_DENIED", "Scout run binding missing", "Reload scout")
                elif run["kind"] == "export":
                    bound = db.execute("SELECT 1 FROM export_batches WHERE task_id=? AND run_id=?", (task_id, run_id)).fetchone()
                    if bound is None:
                        raise DomainError("SCOPE_DENIED", "Export run binding missing", "Reload export")
                call = db.execute("SELECT status FROM model_calls WHERE run_id=? AND step=? AND attempt=?", (run_id, step, attempt)).fetchone()
                if call is None or call["status"] != "received":
                    raise DomainError("INVALID_TRANSITION", "Only a received response can commit", "Preserve unknown or failed call and stop")
                if db.execute("SELECT 1 FROM checkpoints WHERE run_id=? AND step=? AND status='committed'", (run_id, step)).fetchone():
                    raise DomainError("VERSION_CONFLICT", "Logical step already committed", "Read checkpoint")
                if persist is not None:
                    persist(db)
                db.execute("UPDATE checkpoints SET status='committed',output_ref=?,output_hash=? WHERE task_id=? AND run_id=? AND step=? AND attempt=?", (output_ref, output_hash, task_id, run_id, step, attempt))
                db.execute("UPDATE runs SET checkpoint_step=?,updated_at=? WHERE id=?", (step, now, run_id))
                state = db.execute("SELECT state FROM tasks WHERE id=?", (task_id,)).fetchone()[0]
                _event(db, task_id, run_id, "step_committed", step, state, "Step committed", now)
                return True
