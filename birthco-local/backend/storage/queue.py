"""One persistent worker slot and monotonic FIFO sequence."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.domain.errors import DomainError
from .db import connect, immediate, utc_now
from .repository import _event


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Lease:
    run_id: str
    task_id: str
    kind: str
    phase: str
    owner: str
    epoch: int
    lease_until: str


def _phase_allowed(phase: str, task_state: str) -> bool:
    if phase in {"planning", "operator"}:
        return task_state in {"DRAFT", "PLANNING", "QUEUED"}
    if phase in {"draft", "rule", "review", "repair", "export"}:
        return task_state == "QUEUED"
    return False


class Queue:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)

    @staticmethod
    def enqueue_tx(db, run_id: str, now: str) -> int:
        run = db.execute("SELECT r.kind,r.phase,t.state AS task_state,t.current_run_id FROM runs r JOIN tasks t ON t.id=r.task_id WHERE r.id=?", (run_id,)).fetchone()
        if run is None or (run["kind"] == "content" and (run["current_run_id"] != run_id or not _phase_allowed(run["phase"], run["task_state"]))):
            raise DomainError("INVALID_TRANSITION", "Run phase is not eligible for queue", "Confirm or update the task before enqueue")
        db.execute("UPDATE queue_sequence SET next_seq=next_seq+1 WHERE id=1")
        seq = db.execute("SELECT next_seq FROM queue_sequence WHERE id=1").fetchone()[0]
        result = db.execute("UPDATE runs SET state='QUEUED',queue_seq=?,lease_owner=NULL,lease_until=NULL,updated_at=?,row_version=row_version+1 WHERE id=? AND state IN ('WAITING','INTERRUPTED','FAILED')", (seq, now, run_id))
        if result.rowcount != 1:
            raise DomainError("INVALID_TRANSITION", "Run cannot be enqueued", "Reload the run")
        return seq

    def enqueue(self, run_id: str, now: str | None = None) -> int:
        with connect(self.db_path) as db:
            with immediate(db):
                return self.enqueue_tx(db, run_id, now or utc_now())

    @staticmethod
    def has_unresolved_calls_tx(db, run_id) -> bool:
        return db.execute(
            "SELECT 1 FROM model_calls c JOIN checkpoints s ON s.run_id=c.run_id AND s.step=c.step AND s.attempt=c.attempt "
            "WHERE c.run_id=? AND (c.status IN ('sent','unknown') OR (c.status='received' AND s.status='reserved'))",
            (run_id,)).fetchone() is not None

    @staticmethod
    def check_resumable_tx(db, run_id, strategy):
        if strategy != "continue_checkpoint":
            raise DomainError("INVALID_TRANSITION", "Unknown calls require reconciliation", "Inspect the call ledger")
        if Queue.has_unresolved_calls_tx(db, run_id):
            raise DomainError("INVALID_TRANSITION", "A call has no committed result", "Reconcile the call before a new run")

    def claim(self, worker_id: str, now: datetime | None = None) -> Lease | None:
        now = now or datetime.now(timezone.utc)
        stamp, deadline = _stamp(now), _stamp(now + timedelta(seconds=30))
        with connect(self.db_path) as db:
            with immediate(db):
                slot = db.execute("SELECT owner,epoch,lease_until FROM worker_slot WHERE id=1").fetchone()
                if slot["owner"] and slot["lease_until"] and slot["lease_until"] > stamp:
                    return None
                if slot["owner"]:
                    expired = db.execute("SELECT id,task_id,kind FROM runs WHERE lease_owner=? AND state='RUNNING'", (slot["owner"],)).fetchall()
                    for run in expired:
                        db.execute("UPDATE model_calls SET status='unknown',finished_at=? WHERE run_id=? AND status='sent'", (stamp, run["id"]))
                        db.execute("UPDATE model_calls SET status='failed',finished_at=? WHERE run_id=? AND status='reserved'", (stamp, run["id"]))
                        db.execute("UPDATE checkpoints SET status='unknown' WHERE run_id=? AND status='reserved' AND EXISTS (SELECT 1 FROM model_calls c WHERE c.run_id=checkpoints.run_id AND c.step=checkpoints.step AND c.attempt=checkpoints.attempt AND c.status='unknown')", (run["id"],))
                        db.execute("UPDATE checkpoints SET status='rejected' WHERE run_id=? AND status='reserved' AND EXISTS (SELECT 1 FROM model_calls c WHERE c.run_id=checkpoints.run_id AND c.step=checkpoints.step AND c.attempt=checkpoints.attempt AND c.status='failed')", (run["id"],))
                        db.execute("UPDATE runs SET state='INTERRUPTED',lease_owner=NULL,lease_until=NULL,queue_seq=NULL,lease_epoch=lease_epoch+1,row_version=row_version+1,updated_at=? WHERE id=?", (stamp, run["id"]))
                        if run["kind"] == "content":
                            db.execute("UPDATE tasks SET state='INTERRUPTED',row_version=row_version+1,updated_at=? WHERE id=? AND current_run_id=?", (stamp, run["task_id"], run["id"]))
                        if run["kind"] == "preview":
                            db.execute("UPDATE preview_runs SET state='INTERRUPTED',row_version=row_version+1 WHERE run_id=?", (run["id"],))
                        _event(db, run["task_id"], run["id"], "lease_expired", "recovery", "INTERRUPTED", "Worker lease expired", stamp)
                    db.execute("UPDATE worker_slot SET owner=NULL,epoch=epoch+1,lease_until=NULL WHERE id=1")
                run = db.execute("SELECT r.id,r.task_id,r.kind,r.phase,t.state AS task_state FROM runs r JOIN tasks t ON t.id=r.task_id WHERE r.state='QUEUED' AND (r.kind!='content' OR t.current_run_id=r.id) ORDER BY r.queue_seq,r.id LIMIT 1").fetchone()
                if run is None:
                    return None
                if run["kind"] == "content" and not _phase_allowed(run["phase"], run["task_state"]):
                    raise DomainError("INVALID_TRANSITION", "Queued run phase disagrees with task state", "Repair persisted task before claim")
                epoch = db.execute("SELECT epoch FROM worker_slot WHERE id=1").fetchone()[0] + 1
                db.execute("UPDATE worker_slot SET owner=?,epoch=?,lease_until=? WHERE id=1", (worker_id, epoch, deadline))
                db.execute("UPDATE runs SET state='RUNNING',queue_seq=NULL,lease_owner=?,lease_epoch=?,lease_until=?,started_at=coalesce(started_at,?),updated_at=?,row_version=row_version+1 WHERE id=?", (worker_id, epoch, deadline, stamp, stamp, run["id"]))
                if run["kind"] == "content":
                    phase_state = {"planning": "PLANNING", "operator": "PLANNING", "draft": "GENERATING", "rule": "VALIDATING", "review": "VALIDATING", "repair": "REVISING", "export": "EXPORTING"}
                    state = phase_state.get(run["phase"])
                    if state is None:
                        raise DomainError("INVALID_TRANSITION", "Unknown content phase", "Repair persisted run phase")
                    db.execute("UPDATE tasks SET state=?,row_version=row_version+1,updated_at=? WHERE id=? AND current_run_id=?", (state, stamp, run["task_id"], run["id"]))
                    action = {"planning": "claim_planning", "operator": "claim_planning", "draft": "claim_generation", "rule": "claim_validation", "review": "claim_validation", "repair": "claim_repair", "export": "claim_export"}[run["phase"]]
                    _event(db, run["task_id"], run["id"], action, run["phase"], state, "Worker claimed run", stamp)
                return Lease(run["id"], run["task_id"], run["kind"], run["phase"], worker_id, epoch, deadline)


    def heartbeat(self, lease: Lease, now: datetime | None = None, active_ms: int = 0) -> Lease:
        if active_ms < 0:
            raise ValueError("active_ms must be nonnegative")
        now = now or datetime.now(timezone.utc)
        stamp, deadline = _stamp(now), _stamp(now + timedelta(seconds=30))
        with connect(self.db_path) as db:
            with immediate(db):
                row = db.execute("SELECT state,lease_owner,lease_epoch,lease_until FROM runs WHERE id=?", (lease.run_id,)).fetchone()
                if row is None or row["state"] != "RUNNING" or row["lease_owner"] != lease.owner or row["lease_epoch"] != lease.epoch or row["lease_until"] <= stamp:
                    raise DomainError("VERSION_CONFLICT", "Lease is no longer current", "Stop this worker step")
                slot = db.execute("SELECT owner,epoch FROM worker_slot WHERE id=1").fetchone()
                if slot["owner"] != lease.owner or slot["epoch"] != lease.epoch:
                    raise DomainError("VERSION_CONFLICT", "Worker slot has changed", "Stop this worker step")
                db.execute("UPDATE runs SET lease_until=?,active_ms=active_ms+?,updated_at=? WHERE id=?", (deadline, active_ms, stamp, lease.run_id))
                db.execute("UPDATE worker_slot SET lease_until=? WHERE id=1", (deadline,))
                return Lease(lease.run_id, lease.task_id, lease.kind, lease.phase, lease.owner, lease.epoch, deadline)

    def release(self, lease: Lease, state: str, now: str | None = None) -> None:
        with connect(self.db_path) as db:
            with immediate(db):
                self.release_tx(db, lease, state, now or utc_now())

    @staticmethod
    def release_tx(db, lease: Lease, state: str, now: str) -> None:
        """Use inside a caller's transaction to make output and release atomic."""
        if state not in {"WAITING", "SUCCEEDED", "FAILED", "INTERRUPTED", "CANCELLED"}:
            raise ValueError("invalid released state")
        row = db.execute("SELECT state,lease_owner,lease_epoch,lease_until FROM runs WHERE id=?", (lease.run_id,)).fetchone()
        slot = db.execute("SELECT owner,epoch,lease_until FROM worker_slot WHERE id=1").fetchone()
        if row is None or (row["state"], row["lease_owner"], row["lease_epoch"]) != ("RUNNING", lease.owner, lease.epoch) or row["lease_until"] <= now or (slot["owner"], slot["epoch"]) != (lease.owner, lease.epoch) or slot["lease_until"] <= now:
            raise DomainError("VERSION_CONFLICT", "Lease is no longer current", "Stop this worker step")
        pending_sent = db.execute("SELECT 1 FROM model_calls WHERE run_id=? AND status IN ('sent','unknown') LIMIT 1", (lease.run_id,)).fetchone()
        if state in {"WAITING", "SUCCEEDED"} and pending_sent:
            raise DomainError("INVALID_TRANSITION", "Remote call outcome is unknown", "Interrupt and reconcile the call")
        if state in {"FAILED", "INTERRUPTED", "CANCELLED"}:
            db.execute("UPDATE model_calls SET status='unknown',finished_at=? WHERE run_id=? AND status='sent'", (now, lease.run_id))
            db.execute("UPDATE model_calls SET status='failed',finished_at=? WHERE run_id=? AND status='reserved'", (now, lease.run_id))
            db.execute("UPDATE checkpoints SET status='unknown' WHERE run_id=? AND status='reserved' AND EXISTS (SELECT 1 FROM model_calls c WHERE c.run_id=checkpoints.run_id AND c.step=checkpoints.step AND c.attempt=checkpoints.attempt AND c.status='unknown')", (lease.run_id,))
            db.execute("UPDATE checkpoints SET status='rejected' WHERE run_id=? AND status='reserved' AND EXISTS (SELECT 1 FROM model_calls c WHERE c.run_id=checkpoints.run_id AND c.step=checkpoints.step AND c.attempt=checkpoints.attempt AND c.status='failed')", (lease.run_id,))
        db.execute("UPDATE runs SET state=?,lease_owner=NULL,lease_until=NULL,queue_seq=NULL,updated_at=?,finished_at=CASE WHEN ?='WAITING' THEN finished_at ELSE ? END,row_version=row_version+1 WHERE id=?", (state, now, state, now, lease.run_id))
        db.execute("UPDATE worker_slot SET owner=NULL,lease_until=NULL WHERE id=1 AND owner=? AND epoch=?", (lease.owner, lease.epoch))
        task_state = db.execute("SELECT state FROM tasks WHERE id=?", (lease.task_id,)).fetchone()[0]
        _event(db, lease.task_id, lease.run_id, "run_released", lease.phase, task_state, "Run released: " + state, now)
