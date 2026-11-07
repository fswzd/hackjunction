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


class ManagedConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, traceback):
        try:
            return super().__exit__(exc_type, exc, traceback)
        finally:
            self.close()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def connect(path: Path | str, *, require_migrated: bool = True) -> sqlite3.Connection:
    path = Path(path)
    if not path.is_file():
        raise DomainError("STORAGE_UNAVAILABLE", "Database is not migrated", "Run the migrate command")
    db = sqlite3.connect(path, timeout=5, isolation_level=None, check_same_thread=False, factory=ManagedConnection)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=5000")
        if require_migrated:
            row = db.execute("SELECT max(version) FROM schema_migrations").fetchone()
            if not row or row[0] != VERSION:
                raise DomainError("STORAGE_UNAVAILABLE", "Unsupported database schema", "Run migrate or restore a compatible backup")
        return db
    except (sqlite3.Error, DomainError) as exc:
        db.close()
        if isinstance(exc, DomainError):
            raise
        raise DomainError("STORAGE_UNAVAILABLE", "Database schema unavailable", "Run migrate") from exc


class immediate:
    """At most two SQLITE_BUSY retries inside five seconds; no network in block."""
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def __enter__(self):
        deadline = time.monotonic() + 5
        for attempt in range(3):
            try:
                self.db.execute("BEGIN IMMEDIATE")
                return self.db
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                    raise
                if attempt == 2 or time.monotonic() >= deadline:
                    raise DomainError("STORAGE_UNAVAILABLE", "Database is busy", "Retry with the same idempotency key", retryable=True) from exc
                time.sleep(min(0.05 * (attempt + 1), max(0, deadline - time.monotonic())))

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
