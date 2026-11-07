"""Explicit maintenance commands; no arbitrary SQL or shell execution."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3

from backend.storage.db import connect, immediate, migrate, utc_now
from backend.storage.repository import _event
from backend.domain.errors import DomainError


def _safe_artifact(root: Path, relative: str) -> Path:
    path = Path(relative)
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if path.is_absolute() or not path.parts or path.parts[0] != "artifacts" or any(part in {"..", "."} or ":" in part or "\\" in part or part.rstrip(" .") != part or part.split(".")[0].upper() in reserved for part in path.parts):
        raise ValueError("invalid artifact path")
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("symlink artifact path")
    if not current.resolve().is_relative_to(root.resolve()):
        raise ValueError("artifact escapes data directory")
    return current


def backup(data_dir: Path) -> Path:
    data_dir = data_dir.resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = data_dir / "backups" / stamp
    with connect(data_dir / "db.sqlite") as source:
        with immediate(source):
            slot = source.execute("SELECT owner FROM worker_slot WHERE id=1").fetchone()
            running = source.execute("SELECT 1 FROM runs WHERE state='RUNNING' LIMIT 1").fetchone()
            if slot["owner"] or running:
                raise DomainError("INVALID_TRANSITION", "Worker is active", "Stop the worker before backup")
            until = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            source.execute("UPDATE worker_slot SET owner='maintenance-backup',epoch=epoch+1,lease_until=? WHERE id=1", (until,))
        try:
            target.mkdir(parents=True, exist_ok=False)
            records = []
            with sqlite3.connect(target / "db.sqlite") as destination:
                source.backup(destination)
                destination.execute("UPDATE worker_slot SET owner=NULL,lease_until=NULL WHERE id=1 AND owner='maintenance-backup'")
            for row in source.execute("SELECT relative_path,file_hash,byte_size FROM artifacts WHERE status='available'"):
                artifact = _safe_artifact(data_dir, row["relative_path"])
                blob = artifact.read_bytes()
                digest = hashlib.sha256(blob).hexdigest()
                if digest != row["file_hash"] or len(blob) != row["byte_size"]:
                    raise ValueError("registered artifact hash mismatch")
                copied = target / row["relative_path"]
                copied.parent.mkdir(parents=True, exist_ok=True)
                copied.write_bytes(blob)
                records.append({"path": row["relative_path"], "sha256": digest, "size": len(blob)})
            db_hash = hashlib.sha256((target / "db.sqlite").read_bytes()).hexdigest()
            manifest = {"created_at": utc_now(), "database_sha256": db_hash, "artifacts": records}
            (target / "backup-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
            return target
        finally:
            with immediate(source):
                source.execute("UPDATE worker_slot SET owner=NULL,lease_until=NULL WHERE id=1 AND owner='maintenance-backup'")


def reconcile(data_dir: Path) -> dict:
    data_dir = data_dir.resolve()
    changed, orphans = [], []
    with connect(data_dir / "db.sqlite") as db:
        with immediate(db):
            registered = set()
            for row in db.execute("SELECT id,task_id,relative_path,file_hash,byte_size,status FROM artifacts"):
                registered.add(row["relative_path"])
                try:
                    path = _safe_artifact(data_dir, row["relative_path"])
                    actual = path.read_bytes()
                    status = "available" if hashlib.sha256(actual).hexdigest() == row["file_hash"] and len(actual) == row["byte_size"] else "corrupt"
                except (OSError, ValueError):
                    status = "missing"
                if status != row["status"]:
                    db.execute("UPDATE artifacts SET status=? WHERE id=?", (status, row["id"]))
                    changed.append({"id": row["id"], "status": status})
                    if status != "available":
                        task = db.execute("SELECT state,current_run_id FROM tasks WHERE id=?", (row["task_id"],)).fetchone()
                        if task["state"] in {"READY", "ACCEPTED"}:
                            next_state = "FAILED" if task["state"] == "READY" else "ACCEPTED"
                            action = "reexport" if task["state"] == "READY" else "delivery_degraded"
                            now = utc_now()
                            db.execute("UPDATE tasks SET state=?,pending_json=?,row_version=row_version+1,updated_at=? WHERE id=?", (next_state, json.dumps({"action": action}), now, row["task_id"]))
                            _event(db, row["task_id"], task["current_run_id"], "artifact_degraded", "reconcile", next_state, "Registered artifact unavailable", now)
    root = data_dir / "artifacts"
    if root.exists():
        for item in root.rglob("*"):
            if item.is_file() and not item.is_symlink() and str(item.relative_to(data_dir)).replace("\\", "/") not in registered:
                relative = str(item.relative_to(data_dir)).replace("\\", "/")
                quarantined = data_dir / "orphans" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") / relative
                quarantined.parent.mkdir(parents=True, exist_ok=True)
                os.replace(item, quarantined)
                orphans.append({"original": relative, "quarantined": str(quarantined.relative_to(data_dir)).replace("\\", "/")})
    # Orphans are isolated, never adopted as successful exports or deleted.
    return {"changed": changed, "orphans": orphans}


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("migrate", "backup", "reconcile"):
        sub.add_parser(name).add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "migrate":
        result = {"database": str(migrate(args.data_dir))}
    elif args.command == "backup":
        result = {"backup": str(backup(args.data_dir))}
    else:
        result = reconcile(args.data_dir)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
