"""Regression for transient SQLite failures on Windows desktop deployments.

A brief "attempt to write a readonly database" used to escape as a permanent
task FAILED. It must be classified as recoverable and retried from the durable
checkpoint instead.
"""
import sqlite3

import pytest

from backend.domain.errors import DomainError
from backend.storage import db as db_module
from backend.storage.db import (IMMEDIATE_MAX_ATTEMPTS, immediate,
                                is_transient_db_error)
from backend.worker.executor import _transient_failure


class FakeDB:
    def __init__(self, failures=()):
        self.failures = list(failures)
        self.calls = 0
        self.statements: list[str] = []
        self.in_transaction = False

    def execute(self, sql):
        self.calls += 1
        self.statements.append(str(sql))
        if self.failures:
            raise self.failures.pop(0)
        return self


def readonly():
    return sqlite3.OperationalError("attempt to write a readonly database")


def test_readonly_and_lock_are_transient():
    assert is_transient_db_error(readonly())
    assert is_transient_db_error(sqlite3.OperationalError("database is locked"))
    assert is_transient_db_error(sqlite3.OperationalError("database is busy"))
    assert not is_transient_db_error(sqlite3.OperationalError("no such table: runs"))
    assert not is_transient_db_error(ValueError("readonly"))


def test_retryable_domain_error_is_transient_for_worker():
    retryable = DomainError("STORAGE_UNAVAILABLE", "busy", "retry", retryable=True)
    fatal = DomainError("INVALID_TRANSITION", "bad state", "reload")
    assert _transient_failure(retryable)
    assert _transient_failure(readonly())
    assert not _transient_failure(fatal)
    assert not _transient_failure(RuntimeError("agent exploded"))


def test_immediate_retries_readonly_then_succeeds(monkeypatch):
    monkeypatch.setattr(db_module.time, "sleep", lambda _: None)
    fake = FakeDB([readonly(), readonly()])
    with immediate(fake) as opened:
        assert opened is fake
    # two transient failures, a successful BEGIN, then the context COMMIT
    assert fake.statements.count("BEGIN IMMEDIATE") == 3
    assert fake.statements[-1] == "COMMIT"


def test_immediate_exhaustion_is_retryable_domain_error(monkeypatch):
    monkeypatch.setattr(db_module.time, "sleep", lambda _: None)
    fake = FakeDB([readonly() for _ in range(IMMEDIATE_MAX_ATTEMPTS)])
    with pytest.raises(DomainError) as info:
        with immediate(fake):
            pass
    assert info.value.code == "STORAGE_UNAVAILABLE"
    assert info.value.retryable is True
    assert _transient_failure(info.value)


def test_connect_does_not_rewrite_wal_on_an_already_wal_database(tmp_path, monkeypatch):
    """Opening a connection must not re-issue the WAL write on every call."""
    from backend.storage.db import migrate

    path = migrate(tmp_path)
    real_connect = db_module.sqlite3.connect
    statements: list[str] = []

    def traced_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(db_module.sqlite3, "connect", traced_connect)
    with db_module.connect(path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert not any("journal_mode=wal" in stmt.lower().replace(" ", "")
                   for stmt in statements), statements


def test_concurrent_first_open_of_a_wal_database_is_writable(tmp_path):
    """Two simultaneous first opens must not poison one connection as readonly.

    Before the setup probe this reproduced as "attempt to write a readonly
    database" on every subsequent BEGIN IMMEDIATE of the losing connection.
    """
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from backend.storage.db import connect, migrate

    path = migrate(tmp_path)
    barrier = Barrier(2)

    def contender(index: int) -> str:
        barrier.wait()
        with connect(path) as opened:
            with immediate(opened):
                opened.execute("INSERT INTO accounts(id,name) VALUES(?,?)",
                               (f"parallel-{index}", f"parallel-{index}"))
        return "ok"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(contender, index) for index in range(2)]
        assert [result.result() for result in results] == ["ok", "ok"]
    with db_module.connect(path) as opened:
        assert opened.execute(
            "SELECT count(*) FROM accounts WHERE id LIKE 'parallel-%'"
        ).fetchone()[0] == 2
