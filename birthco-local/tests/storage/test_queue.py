from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from backend.domain.errors import DomainError
from backend.storage.db import connect, migrate
from backend.storage.queue import Queue
from backend.storage.repository import Repository
from backend.storage.repository import ConfirmBrief, Transition
from test_repository import task_payload


def test_only_one_claim_and_fifo_requeue(tmp_path):
    path = migrate(tmp_path)
    repo, queue = Repository(path), Queue(path)
    account = repo.create_account("账号")
    one, two = [repo.create_task(task_payload(account)) for _ in range(2)]
    t0 = datetime(2026, 11, 7, tzinfo=timezone.utc)
    first = queue.claim("worker-a", t0)
    assert first.run_id == one["run_id"]
    with connect(path) as db:
        assert db.execute("SELECT type,state FROM task_events WHERE task_id=? ORDER BY seq DESC LIMIT 1", (one["task_id"],)).fetchone()[:] == ("claim_planning", "PLANNING")
    assert queue.claim("worker-b", t0) is None
    queue.release(first, "WAITING")
    queue.enqueue(first.run_id)
    next_one = queue.claim("worker-b", t0)
    assert next_one.run_id == two["run_id"]
    with connect(path) as db:
        assert db.execute("SELECT count(*) FROM runs WHERE state='RUNNING'").fetchone()[0] == 1


def test_expired_epoch_cannot_heartbeat_or_commit(tmp_path):
    path = migrate(tmp_path)
    repo, queue = Repository(path), Queue(path)
    account = repo.create_account("账号")
    one, two = [repo.create_task(task_payload(account), mode="live"), repo.create_task(task_payload(account))]
    t0 = datetime(2026, 11, 7, tzinfo=timezone.utc)
    old = queue.claim("worker-a", t0)
    call = repo.reserve_call(task_id=one["task_id"], run_id=old.run_id, owner="worker-a", epoch=old.epoch, step="operator", attempt=1, role="operator", mode="live", model_id="model", prompt_hash="a" * 64, input_hash="b" * 64, token_estimate=100)
    repo.mark_sent(call)
    new = queue.claim("worker-b", t0 + timedelta(seconds=31))
    assert new.run_id == two["run_id"]
    with pytest.raises(DomainError) as info:
        queue.heartbeat(old, t0 + timedelta(seconds=32))
    assert info.value.code == "VERSION_CONFLICT"
    with connect(path) as db:
        assert db.execute("SELECT state FROM runs WHERE id=?", (one["run_id"],)).fetchone()[0] == "INTERRUPTED"
        assert db.execute("SELECT status FROM model_calls WHERE id=?", (call,)).fetchone()[0] == "unknown"
        assert db.execute("SELECT status FROM checkpoints WHERE run_id=?", (old.run_id,)).fetchone()[0] == "unknown"
        assert db.execute("SELECT total_tokens FROM usage_ledger WHERE call_id=?", (call,)).fetchone()[0] is None


def test_two_connections_compete_for_one_active_run(tmp_path):
    path = migrate(tmp_path)
    repo = Repository(path)
    account = repo.create_account("账号")
    repo.create_task(task_payload(account))
    barrier = Barrier(2)
    def contender(worker):
        barrier.wait()
        return Queue(path).claim(worker, datetime(2026, 11, 7, tzinfo=timezone.utc))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(contender, "one")
        second = pool.submit(contender, "two")
        results = [first.result(), second.result()]
    assert sum(result is not None for result in results) == 1
    with connect(path) as db:
        assert db.execute("SELECT count(*) FROM runs WHERE state='RUNNING'").fetchone()[0] == 1


def test_network_step_does_not_hold_sqlite_write_lock(tmp_path):
    path = migrate(tmp_path)
    repo = Repository(path)
    account = repo.create_account("账号")
    task = repo.create_task(task_payload(account))
    lease = Queue(path).claim("worker", datetime(2026, 11, 7, tzinfo=timezone.utc))
    repo.reserve_call(task_id=task["task_id"], run_id=lease.run_id, owner="worker", epoch=lease.epoch, step="operator", attempt=1, role="operator", mode="mock", model_id="mock", prompt_hash="a" * 64, input_hash="b" * 64, token_estimate=10)
    # Simulated remote wait: another connection can write before response commit.
    with connect(path) as independent:
        independent.execute("BEGIN IMMEDIATE")
        independent.execute("INSERT INTO accounts(id,name) VALUES('parallel','parallel')")
        independent.execute("COMMIT")


def test_expired_worker_cannot_release_success_before_reclaim(tmp_path):
    path = migrate(tmp_path)
    repo, queue = Repository(path), Queue(path)
    account = repo.create_account("账号")
    task = repo.create_task(task_payload(account))
    t0 = datetime(2026, 11, 7, tzinfo=timezone.utc)
    lease = queue.claim("worker", t0)
    with pytest.raises(DomainError) as info:
        queue.release(lease, "SUCCEEDED", now="2026-11-07T00:00:31.000Z")
    assert info.value.code == "VERSION_CONFLICT"
    with connect(path) as db:
        assert db.execute("SELECT state FROM runs WHERE id=?", (task["run_id"],)).fetchone()[0] == "RUNNING"
    # Reclaim marks the sent response unknown and prevents a late success.
    assert queue.claim("successor", t0 + timedelta(seconds=31)) is None
    with connect(path) as db:
        assert db.execute("SELECT state FROM runs WHERE id=?", (task["run_id"],)).fetchone()[0] == "INTERRUPTED"


def test_waiting_confirmation_cannot_be_requeued_or_claimed_without_confirm(tmp_path):
    path = migrate(tmp_path)
    repo, queue = Repository(path), Queue(path)
    account = repo.create_account("账号")
    task = repo.create_task(task_payload(account))
    t0 = datetime(2026, 11, 7, tzinfo=timezone.utc)
    lease = queue.claim("worker", t0)
    queue.release(lease, "WAITING")
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO briefs(task_id,version,body_json,brief_hash,rule_json,created_at) VALUES(?,1,'{}',?,'{}','2026-11-07T00:00:00Z')", (task["task_id"], "a" * 64))
        db.execute("UPDATE tasks SET state='WAITING_CONFIRMATION',current_brief_version=1,row_version=row_version+1 WHERE id=?", (task["task_id"],))
        db.execute("COMMIT")
    with pytest.raises(DomainError) as info:
        queue.enqueue(task["run_id"])
    assert info.value.code == "INVALID_TRANSITION"
    with pytest.raises(DomainError):
        repo.apply(Transition(task["task_id"], "WAITING_CONFIRMATION", "QUEUED", "confirm", task["run_id"], "绕过确认"), 2)
    with pytest.raises(DomainError) as info:
        repo.apply(ConfirmBrief(task["task_id"], task["run_id"], 1, "b" * 64), 2)
    assert info.value.code == "VERSION_CONFLICT"
    with connect(path) as db:
        assert db.execute("SELECT state FROM runs WHERE id=?", (task["run_id"],)).fetchone()[0] == "WAITING"
        assert db.execute("SELECT confirmed_at FROM briefs WHERE task_id=?", (task["task_id"],)).fetchone()[0] is None
    assert repo.apply(ConfirmBrief(task["task_id"], task["run_id"], 1, "a" * 64), 2)["state"] == "QUEUED"
    next_lease = queue.claim("worker", t0)
    assert next_lease.phase == "draft"


def test_planning_resume_from_queued_is_claimable(tmp_path):
    path = migrate(tmp_path)
    repo, queue = Repository(path), Queue(path)
    account = repo.create_account("账号")
    task = repo.create_task(task_payload(account))
    t0 = datetime(2026, 11, 7, tzinfo=timezone.utc)
    lease = queue.claim("worker", t0)
    queue.release(lease, "WAITING")
    with connect(path) as db:
        db.execute("UPDATE tasks SET state='QUEUED' WHERE id=?", (task["task_id"],))
    queue.enqueue(task["run_id"])
    resumed = queue.claim("worker", t0)
    assert resumed.phase == "planning"
    with connect(path) as db:
        assert db.execute("SELECT state FROM tasks WHERE id=?", (task["task_id"],)).fetchone()[0] == "PLANNING"
