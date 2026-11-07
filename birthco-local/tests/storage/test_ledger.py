from datetime import datetime, timezone

import pytest

from backend.domain.errors import DomainError
from backend.storage.db import connect, migrate
from backend.storage.queue import Queue
from backend.storage.repository import Repository
from test_repository import task_payload


def test_unknown_usage_is_null_and_duplicate_step_is_idempotent(tmp_path):
    path = migrate(tmp_path)
    repo = Repository(path)
    account = repo.create_account("账号")
    task = repo.create_task(task_payload(account))
    lease = Queue(path).claim("worker", datetime(2026, 11, 7, tzinfo=timezone.utc))
    call = repo.reserve_call(task_id=task["task_id"], run_id=lease.run_id, owner="worker", epoch=lease.epoch, step="operator", attempt=1, role="operator", mode="mock", model_id="mock", prompt_hash="a" * 64, input_hash="b" * 64, token_estimate=100)
    repo.mark_sent(call)
    repo.finish_call(call, status="received")
    with connect(path) as db:
        usage = db.execute("SELECT input_tokens,output_tokens,total_tokens,usage_status FROM usage_ledger WHERE call_id=?", (call,)).fetchone()
        assert tuple(usage) == (None, None, None, "unknown")
        assert db.execute("SELECT token_reserved FROM runs WHERE id=?", (lease.run_id,)).fetchone()[0] == 100
    assert repo.commit_step(task_id=task["task_id"], run_id=lease.run_id, owner="worker", epoch=lease.epoch, step="operator", attempt=1, output_ref="brief1", output_hash="c" * 64)
    assert repo.commit_step(task_id=task["task_id"], run_id=lease.run_id, owner="worker", epoch=lease.epoch, step="operator", attempt=1, output_ref="brief1", output_hash="c" * 64) is False
    with pytest.raises(DomainError) as info:
        repo.commit_step(task_id=task["task_id"], run_id=lease.run_id, owner="worker", epoch=lease.epoch, step="operator", attempt=1, output_ref="brief2", output_hash="d" * 64)
    assert info.value.code == "VERSION_CONFLICT"
    with connect(path) as db:
        assert db.execute("SELECT count(*) FROM task_events WHERE type='step_committed'").fetchone()[0] == 1


def test_sent_unknown_response_cannot_commit(tmp_path):
    path = migrate(tmp_path)
    repo = Repository(path)
    account = repo.create_account("账号")
    task = repo.create_task(task_payload(account), mode="live")
    lease = Queue(path).claim("worker", datetime(2026, 11, 7, tzinfo=timezone.utc))
    call = repo.reserve_call(task_id=task["task_id"], run_id=lease.run_id, owner="worker", epoch=lease.epoch, step="director", attempt=1, role="director", mode="live", model_id="model", prompt_hash="a" * 64, input_hash="b" * 64, token_estimate=300)
    repo.mark_sent(call)
    repo.finish_call(call, status="unknown")
    with pytest.raises(DomainError) as info:
        repo.commit_step(task_id=task["task_id"], run_id=lease.run_id, owner="worker", epoch=lease.epoch, step="director", attempt=1, output_ref="v1", output_hash="c" * 64)
    assert info.value.code == "INVALID_TRANSITION"
    with pytest.raises(DomainError) as info:
        Queue(path).release(lease, "WAITING")
    assert info.value.code == "INVALID_TRANSITION"
    with connect(path) as db:
        assert db.execute("SELECT total_tokens,usage_status FROM usage_ledger WHERE call_id=?", (call,)).fetchone()[:] == (None, "unknown")
        assert db.execute("SELECT token_reserved FROM runs WHERE id=?", (lease.run_id,)).fetchone()[0] == 300


def test_artifact_write_and_checkpoint_rollback_together(tmp_path):
    path = migrate(tmp_path)
    repo = Repository(path)
    account = repo.create_account("账号")
    task = repo.create_task(task_payload(account))
    lease = Queue(path).claim("worker", datetime(2026, 11, 7, tzinfo=timezone.utc))
    call = repo.reserve_call(task_id=task["task_id"], run_id=lease.run_id, owner="worker", epoch=lease.epoch, step="operator", attempt=1, role="operator", mode="mock", model_id="mock", prompt_hash="a" * 64, input_hash="b" * 64, token_estimate=10)
    repo.finish_call(call, status="received", input_tokens=2, output_tokens=3, total_tokens=5)
    def failing_write(db):
        db.execute("INSERT INTO accounts(id,name) VALUES('temporary','temporary')")
        raise RuntimeError("artifact failed")
    with pytest.raises(RuntimeError):
        repo.commit_step(task_id=task["task_id"], run_id=lease.run_id, owner="worker", epoch=lease.epoch, step="operator", attempt=1, output_ref="brief", output_hash="c" * 64, persist=failing_write)
    with connect(path) as db:
        assert db.execute("SELECT 1 FROM accounts WHERE id='temporary'").fetchone() is None
        assert db.execute("SELECT status FROM checkpoints WHERE run_id=?", (lease.run_id,)).fetchone()[0] == "reserved"
    def successful_write(db):
        db.execute("INSERT INTO accounts(id,name) VALUES('committed','committed')")
        Queue.release_tx(db, lease, "WAITING", "2026-11-07T00:00:05.000Z")
    assert repo.commit_step(task_id=task["task_id"], run_id=lease.run_id, owner="worker", epoch=lease.epoch, step="operator", attempt=1, output_ref="brief", output_hash="c" * 64, persist=successful_write)
    with connect(path) as db:
        assert db.execute("SELECT 1 FROM accounts WHERE id='committed'").fetchone() is not None
        assert db.execute("SELECT state FROM runs WHERE id=?", (lease.run_id,)).fetchone()[0] == "WAITING"


def test_cancelled_lease_discards_late_response_but_keeps_usage(tmp_path):
    path = migrate(tmp_path)
    repo, queue = Repository(path), Queue(path)
    account = repo.create_account("账号")
    task = repo.create_task(task_payload(account), mode="live")
    lease = queue.claim("worker", datetime(2026, 11, 7, tzinfo=timezone.utc))
    call = repo.reserve_call(task_id=task["task_id"], run_id=lease.run_id, owner="worker", epoch=lease.epoch, step="director", attempt=1, role="director", mode="live", model_id="model", prompt_hash="a" * 64, input_hash="b" * 64, token_estimate=100)
    repo.mark_sent(call)
    queue.release(lease, "CANCELLED")
    repo.finish_call(call, status="received", input_tokens=11, output_tokens=12, total_tokens=23, response_hash="c" * 64)
    with connect(path) as db:
        assert db.execute("SELECT status FROM model_calls WHERE id=?", (call,)).fetchone()[0] == "discarded"
        assert db.execute("SELECT total_tokens FROM usage_ledger WHERE call_id=?", (call,)).fetchone()[0] == 23
        assert db.execute("SELECT count(*) FROM task_events WHERE type='step_committed'").fetchone()[0] == 0
