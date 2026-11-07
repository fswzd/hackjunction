import sqlite3

import pytest

from backend.domain.errors import DomainError
from backend.domain.schemas import CreateTask
from backend.storage.db import VERSION, connect, migrate
from backend.storage.repository import Repository, Transition, ConfirmBrief
from backend.manage import backup, reconcile


def task_payload(account_id):
    return CreateTask.model_validate({"account_id": account_id, "input_mode": "existing_draft", "objective": "修改文章", "audience": "初学者", "platform": "generic", "format": "text", "style": "简洁", "requirements": [{"id": "r1", "text": "保持事实"}], "materials": [], "preview_requested": False, "length_rule": {"minimum": None, "maximum": None}})


def test_migration_applies_foreign_keys_and_immutability(tmp_path):
    path = migrate(tmp_path)
    with connect(path) as db:
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert db.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == VERSION
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0] >= 35
        assert "creator_stage" in {
            row[1] for row in db.execute("PRAGMA table_info(accounts)")
        }
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO runs(id,task_id,kind,state,phase,limits_json,created_at,updated_at) VALUES('r','missing','content','QUEUED','planning','{}','x','x')")


def test_migration_refuses_unknown_unversioned_database(tmp_path):
    path = tmp_path / "db.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE unrelated(secret TEXT)")
    with pytest.raises(DomainError) as info:
        migrate(tmp_path)
    assert info.value.code == "STORAGE_UNAVAILABLE"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='unrelated'").fetchone() is not None


def test_create_idempotency_and_cas_are_atomic(tmp_path):
    repo = Repository(migrate(tmp_path))
    account = repo.create_account("个人账号")
    payload = task_payload(account)
    first = repo.create_task(payload, idempotency_key="0123456789abcdef")
    assert repo.create_task(payload, idempotency_key="0123456789abcdef") == first
    with connect(repo.db_path) as db:
        assert db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM task_events").fetchone()[0] == 1
    changed = payload.model_copy(update={"objective": "另一目标"})
    with pytest.raises(DomainError) as info:
        repo.create_task(changed, idempotency_key="0123456789abcdef")
    assert info.value.code == "IDEMPOTENCY_CONFLICT"
    transition = Transition(first["task_id"], "DRAFT", "CANCELLED", "cancel", first["run_id"], "取消")
    assert repo.apply(transition, 0)["row_version"] == 1
    with pytest.raises(DomainError) as info:
        repo.apply(transition, 0)
    assert info.value.code == "VERSION_CONFLICT"
    with connect(repo.db_path) as db:
        assert db.execute("SELECT count(*) FROM task_events").fetchone()[0] == 2


def test_unlisted_transition_and_foreign_run_have_no_write(tmp_path):
    repo = Repository(migrate(tmp_path))
    account = repo.create_account("账号")
    first = repo.create_task(task_payload(account))
    second = repo.create_task(task_payload(account))
    with pytest.raises(DomainError) as info:
        repo.apply(Transition(first["task_id"], "DRAFT", "READY", "skip", first["run_id"], "bad"), 0)
    assert info.value.code == "INVALID_TRANSITION"
    with pytest.raises(DomainError) as info:
        repo.apply(Transition(first["task_id"], "DRAFT", "CANCELLED", "cancel", second["run_id"], "bad"), 0)
    assert info.value.code == "SCOPE_DENIED"
    with connect(repo.db_path) as db:
        assert db.execute("SELECT state,row_version FROM tasks WHERE id=?", (first["task_id"],)).fetchone()[:] == ("DRAFT", 0)


def test_mode_is_frozen_and_part_of_idempotency_fingerprint(tmp_path):
    from datetime import datetime, timezone
    from backend.storage.queue import Queue
    repo = Repository(migrate(tmp_path))
    account = repo.create_account("账号")
    payload = task_payload(account)
    task = repo.create_task(payload, mode="mock", idempotency_key="0123456789abcdef")
    with pytest.raises(DomainError) as info:
        repo.create_task(payload, mode="live", idempotency_key="0123456789abcdef")
    assert info.value.code == "IDEMPOTENCY_CONFLICT"
    with connect(repo.db_path) as db:
        assert db.execute("SELECT mode FROM tasks WHERE id=?", (task["task_id"],)).fetchone()[0] == "mock"
        assert db.execute("SELECT mode FROM runs WHERE id=?", (task["run_id"],)).fetchone()[0] == "mock"
    lease = Queue(repo.db_path).claim("worker", datetime(2026, 11, 7, tzinfo=timezone.utc))
    with pytest.raises(DomainError) as info:
        repo.reserve_call(task_id=task["task_id"], run_id=lease.run_id, owner="worker", epoch=lease.epoch, step="operator", attempt=1, role="operator", mode="live", model_id="model", prompt_hash="a" * 64, input_hash="b" * 64, token_estimate=10)
    assert info.value.code == "CONDITIONS_MISMATCH"


def test_cancel_revokes_active_lease_and_blocks_new_reservations(tmp_path):
    from datetime import datetime, timezone
    from backend.storage.queue import Queue
    repo = Repository(migrate(tmp_path))
    account = repo.create_account("账号")
    task = repo.create_task(task_payload(account), mode="live")
    lease = Queue(repo.db_path).claim("worker", datetime(2026, 11, 7, tzinfo=timezone.utc))
    call = repo.reserve_call(task_id=task["task_id"], run_id=lease.run_id, owner="worker", epoch=lease.epoch, step="operator", attempt=1, role="operator", mode="live", model_id="model", prompt_hash="a" * 64, input_hash="b" * 64, token_estimate=100)
    repo.mark_sent(call)
    repo.apply(Transition(task["task_id"], "PLANNING", "CANCELLED", "cancel", lease.run_id, "用户取消"), 1)
    with pytest.raises(DomainError) as info:
        repo.reserve_call(task_id=task["task_id"], run_id=lease.run_id, owner="worker", epoch=lease.epoch, step="director", attempt=1, role="director", mode="live", model_id="model", prompt_hash="a" * 64, input_hash="b" * 64, token_estimate=100)
    assert info.value.code == "VERSION_CONFLICT"
    repo.finish_call(call, status="received", input_tokens=10, output_tokens=20, total_tokens=30)
    with connect(repo.db_path) as db:
        assert db.execute("SELECT state,lease_epoch FROM runs WHERE id=?", (lease.run_id,)).fetchone()[:] == ("CANCELLED", lease.epoch + 1)
        assert db.execute("SELECT status FROM model_calls WHERE id=?", (call,)).fetchone()[0] == "discarded"
        assert db.execute("SELECT total_tokens FROM usage_ledger WHERE call_id=?", (call,)).fetchone()[0] == 30
        assert db.execute("SELECT owner FROM worker_slot WHERE id=1").fetchone()[0] is None


def test_cancel_before_claim_removes_queued_run_atomically(tmp_path):
    from datetime import datetime, timezone
    from backend.storage.queue import Queue
    repo = Repository(migrate(tmp_path))
    account = repo.create_account("账号")
    task = repo.create_task(task_payload(account))
    repo.apply(Transition(task["task_id"], "DRAFT", "CANCELLED", "cancel", task["run_id"], "用户取消"), 0)
    assert Queue(repo.db_path).claim("worker", datetime(2026, 11, 7, tzinfo=timezone.utc)) is None
    with connect(repo.db_path) as db:
        assert db.execute("SELECT state,queue_seq FROM runs WHERE id=?", (task["run_id"],)).fetchone()[:] == ("CANCELLED", None)
        assert db.execute("SELECT state FROM tasks WHERE id=?", (task["task_id"],)).fetchone()[0] == "CANCELLED"


def test_backup_manifest_and_orphan_reconcile(tmp_path):
    path = migrate(tmp_path)
    repo = Repository(path)
    repo.create_account("账号")
    target = backup(tmp_path)
    assert (target / "db.sqlite").is_file()
    import json, hashlib
    manifest = json.loads((target / "backup-manifest.json").read_text(encoding="utf-8"))
    assert manifest["database_sha256"] == hashlib.sha256((target / "db.sqlite").read_bytes()).hexdigest()
    with sqlite3.connect(target / "db.sqlite") as copied:
        assert copied.execute("SELECT owner FROM worker_slot WHERE id=1").fetchone()[0] is None
    orphan = tmp_path / "artifacts" / "unregistered.txt"
    orphan.parent.mkdir()
    orphan.write_text("unregistered", encoding="utf-8")
    result = reconcile(tmp_path)
    assert result["changed"] == []
    assert result["orphans"][0]["original"] == "artifacts/unregistered.txt"
    assert not orphan.exists()
    assert (tmp_path / result["orphans"][0]["quarantined"]).read_text(encoding="utf-8") == "unregistered"


def test_backup_rejects_active_worker(tmp_path):
    from datetime import datetime, timezone
    from backend.storage.queue import Queue
    repo = Repository(migrate(tmp_path))
    account = repo.create_account("账号")
    repo.create_task(task_payload(account))
    Queue(repo.db_path).claim("worker", datetime(2026, 11, 7, tzinfo=timezone.utc))
    with pytest.raises(DomainError) as info:
        backup(tmp_path)
    assert info.value.code == "INVALID_TRANSITION"


def test_reconcile_missing_registered_artifact_degrades_ready_task(tmp_path):
    path = migrate(tmp_path)
    repo = Repository(path)
    account = repo.create_account("账号")
    task = repo.create_task(task_payload(account))
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO briefs(task_id,version,body_json,brief_hash,rule_json,created_at) VALUES(?,1,'{}',?,'{}','2026-11-07T00:00:00Z')", (task["task_id"], "a" * 64))
        db.execute("INSERT INTO content_versions(id,task_id,run_id,ordinal,brief_version,brief_hash,content_json,content_hash,created_at) VALUES('v1',?,?,1,1,?,'{}',?,'2026-11-07T00:00:00Z')", (task["task_id"], task["run_id"], "a" * 64, "b" * 64))
        db.execute("INSERT INTO export_batches(id,task_id,version_id,run_id,status,formats_json) VALUES('batch',?,'v1',?,'committed','[\"txt\"]')", (task["task_id"], task["run_id"]))
        db.execute("INSERT INTO artifacts(id,batch_id,task_id,version_id,format,relative_path,file_hash,byte_size,status) VALUES('file','batch',?,'v1','txt','artifacts/missing.txt',?,1,'available')", (task["task_id"], "c" * 64))
        db.execute("UPDATE tasks SET state='READY',ready_version_id='v1' WHERE id=?", (task["task_id"],))
        db.execute("COMMIT")
    result = reconcile(tmp_path)
    assert result["changed"] == [{"id": "file", "status": "missing"}]
    with connect(path) as db:
        assert db.execute("SELECT state FROM tasks WHERE id=?", (task["task_id"],)).fetchone()[0] == "FAILED"
        assert db.execute("SELECT status FROM artifacts WHERE id='file'").fetchone()[0] == "missing"
