"""SQLite connection and migration boundary; imports have no filesystem effects."""
from datetime import datetime, timezone
from pathlib import Path
from contextlib import closing
import sqlite3
import time

from backend.domain.errors import DomainError

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
MIGRATIONS = (
    (1, MIGRATIONS_DIR / "001_initial.sql"),
    (2, MIGRATIONS_DIR / "002_account_creator_stage.sql"),
)
VERSION = MIGRATIONS[-1][0]

IMMEDIATE_MAX_ATTEMPTS = 8
IMMEDIATE_DEADLINE_SECONDS = 20.0


class ManagedConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, traceback):
        try:
            return super().__exit__(exc_type, exc, traceback)
        finally:
            self.close()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# Short-lived SQLite/OS failures. They must be retried, never escalated into a
# permanent task failure: on Windows a concurrent connection switching journal
# mode can briefly surface as "attempt to write a readonly database".
TRANSIENT_DB_MESSAGES = (
    "locked", "busy", "readonly", "read-only", "disk i/o error", "disk full",
)


def is_transient_db_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return isinstance(exc, sqlite3.OperationalError) and any(
        token in text for token in TRANSIENT_DB_MESSAGES
    )


def connect(path: Path | str, *, require_migrated: bool = True) -> sqlite3.Connection:
    path = Path(path)
    if not path.is_file():
        raise DomainError("STORAGE_UNAVAILABLE", "Database is not migrated", "Run the migrate command")
    last: sqlite3.Error | None = None
    for attempt in range(IMMEDIATE_MAX_ATTEMPTS):
        db = sqlite3.connect(path, timeout=5, isolation_level=None,
                             check_same_thread=False, factory=ManagedConnection)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=5000")
            # WAL is a persistent property of the database file, set once by
            # migrate(). Re-issuing it on EVERY connection is a write requiring
            # an exclusive lock; with the API, worker and preview processes
            # opening connections concurrently it can produce spurious
            # readonly errors. Only repair a file switched to another mode.
            mode = str(db.execute("PRAGMA journal_mode").fetchone()[0] or "").lower()
            if mode != "wal":
                db.execute("PRAGMA journal_mode=WAL")
            if require_migrated:
                row = db.execute("SELECT max(version) FROM schema_migrations").fetchone()
                if not row or row[0] != VERSION:
                    raise DomainError("STORAGE_UNAVAILABLE", "Unsupported database schema", "Run migrate or restore a compatible backup")
            # Two connections opening a freshly migrated WAL database at the
            # same instant race while creating the -wal/-shm files. The loser
            # then reports "attempt to write a readonly database" on EVERY
            # later write, and retrying on that same connection never
            # recovers. A no-op write transaction here serialises that
            # one-time setup under SQLite's own busy handler; on a transient
            # failure we discard the poisoned connection and open a fresh one.
            db.execute("BEGIN IMMEDIATE")
            db.execute("COMMIT")
            return db
        except DomainError:
            db.close()
            raise
        except sqlite3.Error as exc:
            db.close()
            if not is_transient_db_error(exc):
                raise DomainError("STORAGE_UNAVAILABLE", "Database schema unavailable", "Run migrate") from exc
            last = exc
            time.sleep(min(0.02 * (2 ** min(attempt, 5)), 0.2))
    raise DomainError("STORAGE_UNAVAILABLE", "本地数据库暂时繁忙或不可写",
                      "稍后重试同一请求；已提交的步骤会跳过，不会重复计费",
                      retryable=True) from last


class immediate:
    """Bounded exponential backoff for transient SQLite contention.

    Removing the redundant per-connection WAL write means two local processes
    can now reach ``BEGIN IMMEDIATE`` at the same instant. A short backoff lets
    the loser acquire the lease on the next attempt instead of surfacing a
    storage error that would fail the whole task.

    The number of attempts is the real bound: SQLite's own ``busy_timeout``
    (5s here) can consume most of a wall-clock deadline in a single attempt,
    so bailing out on elapsed time alone made concurrent claims fail on a
    loaded machine even though every failure was retryable.
    """
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def __enter__(self):
        deadline = time.monotonic() + IMMEDIATE_DEADLINE_SECONDS
        last: sqlite3.OperationalError | None = None
        for attempt in range(IMMEDIATE_MAX_ATTEMPTS):
            try:
                self.db.execute("BEGIN IMMEDIATE")
                return self.db
            except sqlite3.OperationalError as exc:
                if not is_transient_db_error(exc):
                    raise
                last = exc
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(0.05 * (2 ** min(attempt, 5)), 0.25, remaining))
        raise DomainError(
            "STORAGE_UNAVAILABLE",
            "本地数据库暂时繁忙或不可写",
            "稍后重试同一请求；已提交的步骤会跳过，不会重复计费",
            retryable=True,
        ) from last

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.db.execute("COMMIT")
        elif self.db.in_transaction:
            self.db.execute("ROLLBACK")
        return False


def migrate(data_dir: Path | str) -> Path:
    """Explicit migration only. Existing DBs are backed up before any DDL."""
    data_dir = Path(data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "db.sqlite"
    applied = 0
    if path.exists():
        with closing(sqlite3.connect(path)) as probe:
            user_version = probe.execute("PRAGMA user_version").fetchone()[0]
            try:
                recorded = probe.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
            except sqlite3.OperationalError:
                recorded = None
            if recorded == VERSION:
                return path
            tables = probe.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            if recorded in (None, 0):
                if tables:
                    raise DomainError(
                        "STORAGE_UNAVAILABLE",
                        "Unversioned database has tables",
                        "Inspect or restore this database; migration is refused",
                    )
                applied = 0
            elif recorded > VERSION or user_version > VERSION:
                raise DomainError(
                    "STORAGE_UNAVAILABLE",
                    "Unknown schema version",
                    "Restore a compatible database",
                )
            else:
                applied = recorded
                # Never run DDL on an existing versioned database without a copy.
                backup = data_dir / "backups" / utc_now().replace(":", "-") / "db.sqlite"
                backup.parent.mkdir(parents=True, exist_ok=False)
                with sqlite3.connect(backup) as target:
                    probe.backup(target)
    db = sqlite3.connect(path, timeout=5, isolation_level=None)
    try:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        for migration_version, migration_path in MIGRATIONS:
            if migration_version <= applied:
                continue
            script = migration_path.read_text(encoding="utf-8")
            # executescript commits an existing transaction, so the script owns it.
            db.executescript(
                "BEGIN IMMEDIATE;\n"
                + script
                + "\nINSERT INTO schema_migrations(version,applied_at) VALUES("
                + str(migration_version)
                + ",'"
                + utc_now()
                + "');\nCOMMIT;"
            )
        db.execute(f"PRAGMA user_version={VERSION}")
        db.execute("PRAGMA journal_mode=WAL")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    finally:
        db.close()
    return path
