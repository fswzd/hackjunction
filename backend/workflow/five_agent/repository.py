"""Domain repository (SQLite) — the source of truth for tasks, versions, gates,
step receipts, audience events and the usage ledger.

Design rules encoded here:
- Brief has no independent id: composite (task_id, brief_version) + brief_hash.
- Confirmation/gate decisions are CAS against a frozen subject hash; model text
  is never an authority.
- Step outputs are immutable receipts UNIQUE(run_id, step, attempt); replay reads
  them instead of calling agents again.
- Cancel bumps run.epoch; late results are recorded as discarded, never commit.
- usage unknown stays unknown (total_tokens NULL), never zero-filled.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .contracts import canonical_json, sha256_hex


class DomainError(Exception):
    code = "INVALID_TRANSITION"

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code


class NotFoundError(DomainError):
    code = "NOT_FOUND"


class ConflictError(DomainError):
    code = "VERSION_CONFLICT"


class IdempotencyConflict(DomainError):
    code = "IDEMPOTENCY_CONFLICT"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def object_hash(payload: Any) -> str:
    return sha256_hex(canonical_json(payload))


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY, account_id TEXT NOT NULL, status TEXT NOT NULL,
  payload_json TEXT NOT NULL, row_version INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS materials (
  id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
  kind TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS briefs (
  task_id TEXT NOT NULL, brief_version INTEGER NOT NULL,
  brief_hash TEXT NOT NULL, payload_json TEXT NOT NULL,
  open_questions_json TEXT NOT NULL, confirmed_at TEXT,
  row_version INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
  PRIMARY KEY (task_id, brief_version)
);
CREATE TABLE IF NOT EXISTS content_versions (
  id TEXT PRIMARY KEY, task_id TEXT NOT NULL, run_id TEXT NOT NULL,
  base_version_id TEXT, content_hash TEXT NOT NULL,
  status TEXT NOT NULL, payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
  id TEXT PRIMARY KEY, task_id TEXT NOT NULL, run_id TEXT NOT NULL,
  kind TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, task_id TEXT NOT NULL, kind TEXT NOT NULL,
  status TEXT NOT NULL, epoch INTEGER NOT NULL DEFAULT 0,
  resume_step TEXT NOT NULL DEFAULT 'start', parent_run_id TEXT,
  error_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_calls (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_key TEXT NOT NULL,
  attempt INTEGER NOT NULL, agent_id TEXT NOT NULL, action TEXT NOT NULL,
  request_id TEXT NOT NULL, input_hash TEXT NOT NULL,
  status TEXT NOT NULL, send_intent INTEGER NOT NULL DEFAULT 0,
  usage_status TEXT, usage_tokens INTEGER, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_step_outputs (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_key TEXT NOT NULL,
  attempt INTEGER NOT NULL, call_id TEXT NOT NULL, action TEXT NOT NULL,
  input_hash TEXT NOT NULL, output_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL, payload_bytes INTEGER NOT NULL,
  result_status TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE (run_id, step_key, attempt)
);
CREATE TABLE IF NOT EXISTS usage_ledger (
  run_id TEXT PRIMARY KEY, calls_reserved INTEGER NOT NULL DEFAULT 0,
  normal_calls INTEGER NOT NULL DEFAULT 0, tech_retries INTEGER NOT NULL DEFAULT 0,
  calls_completed INTEGER NOT NULL DEFAULT 0, tokens_known INTEGER NOT NULL DEFAULT 0,
  unknown_usage_calls INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS workflow_gates (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL, kind TEXT NOT NULL,
  subject_json TEXT NOT NULL, subject_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', decision_key TEXT,
  decision_json TEXT, decision_at TEXT, created_at TEXT NOT NULL,
  UNIQUE (run_id, kind, subject_hash)
);
CREATE TABLE IF NOT EXISTS workflow_commands (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL, gate_id TEXT,
  kind TEXT NOT NULL, idempotency_key TEXT NOT NULL,
  payload_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL, UNIQUE (run_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS audience_sessions (
  id TEXT PRIMARY KEY, preview_id TEXT NOT NULL, persona_id TEXT NOT NULL,
  next_ordinal INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audience_events (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
  segment_id TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE (session_id, ordinal)
);
CREATE TABLE IF NOT EXISTS task_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, run_id TEXT,
  kind TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


class Repository:
    def __init__(self, db_path: str | Path = ":memory:"):
        self._db_path = str(db_path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ util
    def _exec(self, sql: str, params: Iterable = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur

    def _one(self, sql: str, params: Iterable = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchone()

    def _all(self, sql: str, params: Iterable = ()) -> list:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchall()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict | None:
        return dict(row) if row is not None else None

    # ------------------------------------------------------------------ tasks
    def create_task(self, task_id: str, account_id: str, payload: dict) -> dict:
        self._exec(
            "INSERT INTO tasks (id, account_id, status, payload_json, row_version, created_at) "
            "VALUES (?,?,?,?,0,?)",
            (task_id, account_id, "OPEN", json.dumps(payload, ensure_ascii=False), _now()))
        self.log_event(task_id, None, "task_created", {"payload": payload})
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict:
        row = self._one("SELECT * FROM tasks WHERE id=?", (task_id,))
        if row is None:
            raise NotFoundError(f"task {task_id}")
        out = self._row(row)
        out["payload"] = json.loads(out.pop("payload_json"))
        return out

    def bump_task_row_version(self, task_id: str, expected: int) -> int:
        cur = self._exec(
            "UPDATE tasks SET row_version=row_version+1 WHERE id=? AND row_version=?",
            (task_id, expected))
        if cur.rowcount != 1:
            raise ConflictError("task row_version CAS failed")
        return expected + 1

    def add_material(self, task_id: str, material_id: str, text: str, kind: str = "text") -> dict:
        self._exec("INSERT INTO materials (id, task_id, kind, text, created_at) VALUES (?,?,?,?,?)",
                   (material_id, task_id, kind, text, _now()))
        return {"id": material_id, "kind": kind, "text": text}

    def save_task_payload(self, task_id: str, payload: dict) -> dict:
        self._exec("UPDATE tasks SET payload_json=?, row_version=row_version+1 WHERE id=?",
                   (json.dumps(payload, ensure_ascii=False), task_id))
        return self.get_task(task_id)

    def list_materials(self, task_id: str) -> list[dict]:
        return [self._row(r) for r in self._all("SELECT * FROM materials WHERE task_id=? ORDER BY created_at", (task_id,))]

    # ----------------------------------------------------------------- briefs
    def save_brief(self, task_id: str, payload: dict, open_questions: list) -> dict:
        brief_hash = object_hash(payload)
        prev = self._one("SELECT MAX(brief_version) AS v FROM briefs WHERE task_id=?", (task_id,))
        version = (prev["v"] or 0) + 1
        self._exec(
            "INSERT INTO briefs (task_id, brief_version, brief_hash, payload_json, "
            "open_questions_json, confirmed_at, row_version, created_at) VALUES (?,?,?,?,?,NULL,0,?)",
            (task_id, version, brief_hash, json.dumps(payload, ensure_ascii=False),
             json.dumps(open_questions, ensure_ascii=False), _now()))
        return {"task_id": task_id, "brief_version": version, "brief_hash": brief_hash,
                "payload": payload, "open_questions": open_questions}

    def get_brief(self, task_id: str, brief_version: int) -> dict:
        row = self._one("SELECT * FROM briefs WHERE task_id=? AND brief_version=?", (task_id, brief_version))
        if row is None:
            raise NotFoundError(f"brief {task_id}#{brief_version}")
        out = self._row(row)
        out["payload"] = json.loads(out.pop("payload_json"))
        out["open_questions"] = json.loads(out.pop("open_questions_json"))
        return out

    def latest_brief(self, task_id: str) -> dict | None:
        row = self._one("SELECT * FROM briefs WHERE task_id=? ORDER BY brief_version DESC LIMIT 1", (task_id,))
        if row is None:
            return None
        out = self._row(row)
        out["payload"] = json.loads(out.pop("payload_json"))
        out["open_questions"] = json.loads(out.pop("open_questions_json"))
        return out

    def confirm_brief(self, task_id: str, brief_version: int, brief_hash: str,
                      expected_row_version: int) -> dict:
        brief = self.get_brief(task_id, brief_version)
        if brief["brief_hash"] != brief_hash:
            raise ConflictError("brief_hash mismatch")
        if brief["open_questions"]:
            raise DomainError("cannot confirm brief with open_questions", "INPUT_MISSING")
        cur = self._exec(
            "UPDATE briefs SET confirmed_at=?, row_version=row_version+1 "
            "WHERE task_id=? AND brief_version=? AND brief_hash=? AND row_version=? AND confirmed_at IS NULL",
            (_now(), task_id, brief_version, brief_hash, expected_row_version))
        if cur.rowcount != 1:
            raise ConflictError("confirm_brief CAS failed")
        self.log_event(task_id, None, "brief_confirmed", {"brief_version": brief_version, "brief_hash": brief_hash})
        return self.get_brief(task_id, brief_version)

    # ---------------------------------------------------------------- versions
    def save_version(self, version_id: str, task_id: str, run_id: str, base_version_id: str | None,
                     payload: dict, status: str = "candidate") -> dict:
        content_hash = object_hash(payload)
        existing = self._one("SELECT * FROM content_versions WHERE id=?", (version_id,))
        if existing is not None:
            if existing["content_hash"] != content_hash:
                raise IdempotencyConflict(f"version {version_id} already committed with different content")
            return self.get_version(version_id)
        self._exec(
            "INSERT INTO content_versions (id, task_id, run_id, base_version_id, content_hash, status, "
            "payload_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (version_id, task_id, run_id, base_version_id, content_hash, status,
             json.dumps(payload, ensure_ascii=False), _now()))
        return self.get_version(version_id)

    def get_version(self, version_id: str) -> dict:
        row = self._one("SELECT * FROM content_versions WHERE id=?", (version_id,))
        if row is None:
            raise NotFoundError(f"version {version_id}")
        out = self._row(row)
        out["payload"] = json.loads(out.pop("payload_json"))
        return out

    def set_version_status(self, version_id: str, status: str, expected: str | tuple[str, ...]) -> dict:
        expected_set = (expected,) if isinstance(expected, str) else tuple(expected)
        row = self.get_version(version_id)
        if row["status"] not in expected_set:
            raise ConflictError(f"version {version_id} status {row['status']} not in {expected_set}")
        self._exec("UPDATE content_versions SET status=? WHERE id=?", (status, version_id))
        return self.get_version(version_id)

    def list_versions(self, task_id: str) -> list[dict]:
        return [dict(r) for r in self._all(
            "SELECT id, base_version_id, content_hash, status, created_at FROM content_versions "
            "WHERE task_id=? ORDER BY created_at", (task_id,))]

    # ---------------------------------------------------------------- artifacts
    def save_artifact(self, artifact_id: str, task_id: str, run_id: str, kind: str, payload: dict) -> dict:
        existing = self._one("SELECT * FROM artifacts WHERE id=?", (artifact_id,))
        if existing is not None:
            if object_hash(json.loads(existing["payload_json"])) != object_hash(payload):
                raise IdempotencyConflict(f"artifact {artifact_id} exists with different payload")
            return {"id": artifact_id, "kind": kind, "payload": payload}
        self._exec("INSERT INTO artifacts (id, task_id, run_id, kind, payload_json, created_at) VALUES (?,?,?,?,?,?)",
                   (artifact_id, task_id, run_id, kind, json.dumps(payload, ensure_ascii=False), _now()))
        return {"id": artifact_id, "kind": kind, "payload": payload}

    def get_artifact(self, artifact_id: str) -> dict:
        row = self._one("SELECT * FROM artifacts WHERE id=?", (artifact_id,))
        if row is None:
            raise NotFoundError(f"artifact {artifact_id}")
        out = self._row(row)
        out["payload"] = json.loads(out.pop("payload_json"))
        return out

    def find_artifacts(self, task_id: str, kind: str) -> list[dict]:
        rows = self._all("SELECT * FROM artifacts WHERE task_id=? AND kind=? ORDER BY created_at", (task_id, kind))
        out = []
        for row in rows:
            item = self._row(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            out.append(item)
        return out

    # -------------------------------------------------------------------- runs
    def create_run(self, run_id: str, task_id: str, kind: str, parent_run_id: str | None = None) -> dict:
        self._exec("INSERT INTO runs (id, task_id, kind, status, epoch, resume_step, parent_run_id, created_at, updated_at) "
                   "VALUES (?,?,?,'QUEUED',0,'start',?,?,?)",
                   (run_id, task_id, kind, parent_run_id, _now(), _now()))
        self._exec("INSERT OR IGNORE INTO usage_ledger (run_id) VALUES (?)", (run_id,))
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict:
        row = self._one("SELECT * FROM runs WHERE id=?", (run_id,))
        if row is None:
            raise NotFoundError(f"run {run_id}")
        return self._row(row)

    def set_run_status(self, run_id: str, status: str, resume_step: str | None = None,
                       error: dict | None = None) -> dict:
        run = self.get_run(run_id)
        if run["status"] in ("CANCELLED",) and status != "CANCELLED":
            raise ConflictError("cancelled run cannot transition")
        self._exec("UPDATE runs SET status=?, resume_step=COALESCE(?, resume_step), "
                   "error_json=COALESCE(?, error_json), updated_at=? WHERE id=?",
                   (status, resume_step, json.dumps(error, ensure_ascii=False) if error else None, _now(), run_id))
        return self.get_run(run_id)

    def bump_epoch(self, run_id: str) -> int:
        self._exec("UPDATE runs SET epoch=epoch+1, updated_at=? WHERE id=?", (_now(), run_id))
        return self.get_run(run_id)["epoch"]

    def log_event(self, task_id: str, run_id: str | None, kind: str, payload: dict) -> None:
        self._exec("INSERT INTO task_events (task_id, run_id, kind, payload_json, created_at) VALUES (?,?,?,?,?)",
                   (task_id, run_id, kind, json.dumps(payload, ensure_ascii=False), _now()))

    def list_events(self, task_id: str, kind: str | None = None) -> list[dict]:
        rows = self._all("SELECT * FROM task_events WHERE task_id=? ORDER BY id", (task_id,))
        out = []
        for row in rows:
            item = self._row(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            if kind is None or item["kind"] == kind:
                out.append(item)
        return out

    # ------------------------------------------------------- calls & receipts
    def reserve_call(self, call_id: str, run_id: str, step_key: str, attempt: int, agent_id: str,
                     action: str, request_id: str, input_hash: str) -> str:
        self._exec(
            "INSERT INTO model_calls (id, run_id, step_key, attempt, agent_id, action, request_id, "
            "input_hash, status, send_intent, usage_status, usage_tokens, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,'reserved',0,NULL,NULL,?)",
            (call_id, run_id, step_key, attempt, agent_id, action, request_id, input_hash, _now()))
        return call_id

    def mark_send_intent(self, call_id: str) -> None:
        self._exec("UPDATE model_calls SET send_intent=1, status='sent' WHERE id=?", (call_id,))

    def complete_call(self, call_id: str, step_key: str, run_id: str, attempt: int, action: str,
                      input_hash: str, result: dict, usage: dict, output_id: str) -> dict:
        """Atomically persist typed output + call received + usage (single domain tx)."""
        payload_bytes = len(canonical_json(result))
        output_hash = object_hash(result)
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.execute(
                    "INSERT INTO workflow_step_outputs (id, run_id, step_key, attempt, call_id, action, "
                    "input_hash, output_hash, payload_json, payload_bytes, result_status, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (output_id, run_id, step_key, attempt, call_id, action, input_hash, output_hash,
                     json.dumps(result, ensure_ascii=False), payload_bytes, result["status"], _now()))
                self._conn.execute(
                    "UPDATE model_calls SET status='received', usage_status=?, usage_tokens=? WHERE id=?",
                    (usage["status"], usage["total_tokens"], call_id))
                if usage["status"] == "known":
                    self._conn.execute(
                        "UPDATE usage_ledger SET calls_completed=calls_completed+1, "
                        "tokens_known=tokens_known+? WHERE run_id=?", (usage["total_tokens"], run_id))
                else:
                    self._conn.execute(
                        "UPDATE usage_ledger SET calls_completed=calls_completed+1, "
                        "unknown_usage_calls=unknown_usage_calls+1 WHERE run_id=?", (run_id,))
                self._conn.execute(
                    "UPDATE usage_ledger SET calls_reserved=calls_reserved+1, "
                    "normal_calls=normal_calls+?, tech_retries=tech_retries+? WHERE run_id=?",
                    (1 if attempt == 1 else 0, 0 if attempt == 1 else 1, run_id))
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return {"output_id": output_id, "output_hash": output_hash, "payload_bytes": payload_bytes}

    def fail_call(self, call_id: str, run_id: str, attempt: int, status: str) -> None:
        """Record a failed attempt that never produced typed output (pre-send/protocol)."""
        with self._lock:
            self._conn.execute("UPDATE model_calls SET status=? WHERE id=?", (status, call_id))
            self._conn.execute(
                "UPDATE usage_ledger SET calls_reserved=calls_reserved+1, "
                "normal_calls=normal_calls+?, tech_retries=tech_retries+? WHERE run_id=?",
                (1 if attempt == 1 else 0, 0 if attempt == 1 else 1, run_id))
            self._conn.commit()

    def interrupt_call(self, call_id: str, run_id: str, attempt: int, usage: dict | None = None) -> None:
        """Sent but result unknown: INTERRUPTED; usage stays unknown unless provider echoed."""
        usage_status, usage_tokens = ("unknown", None) if usage is None else (usage["status"], usage["total_tokens"])
        with self._lock:
            self._conn.execute("UPDATE model_calls SET status='interrupted', usage_status=?, usage_tokens=? WHERE id=?",
                               (usage_status, usage_tokens, call_id))
            self._conn.execute(
                "UPDATE usage_ledger SET calls_reserved=calls_reserved+1, "
                "normal_calls=normal_calls+?, tech_retries=tech_retries+?, "
                "unknown_usage_calls=unknown_usage_calls+? WHERE run_id=?",
                (1 if attempt == 1 else 0, 0 if attempt == 1 else 1, 1 if (usage is None or usage["status"] == "unknown") else 0, run_id))
            self._conn.commit()

    def discard_call(self, call_id: str, reason: str, usage: dict | None = None) -> None:
        """Late/cancelled result: record usage as discarded, do not advance versions."""
        usage_status, usage_tokens = ("unknown", None) if usage is None else (usage["status"], usage["total_tokens"])
        with self._lock:
            self._conn.execute("UPDATE model_calls SET status='discarded', usage_status=?, usage_tokens=? WHERE id=?",
                               (usage_status, usage_tokens, call_id))
            self._conn.commit()

    def get_call(self, call_id: str) -> dict:
        row = self._one("SELECT * FROM model_calls WHERE id=?", (call_id,))
        if row is None:
            raise NotFoundError(f"call {call_id}")
        return self._row(row)

    def list_calls(self, run_id: str) -> list[dict]:
        return [self._row(r) for r in self._all(
            "SELECT * FROM model_calls WHERE run_id=? ORDER BY created_at, attempt", (run_id,))]

    def get_step_output(self, run_id: str, step_key: str) -> dict | None:
        row = self._one(
            "SELECT * FROM workflow_step_outputs WHERE run_id=? AND step_key=? ORDER BY attempt DESC LIMIT 1",
            (run_id, step_key))
        if row is None:
            return None
        out = self._row(row)
        out["payload"] = json.loads(out.pop("payload_json"))
        return out

    def get_usage(self, run_id: str) -> dict:
        row = self._one("SELECT * FROM usage_ledger WHERE run_id=?", (run_id,))
        return self._row(row) or {"run_id": run_id, "calls_reserved": 0, "normal_calls": 0,
                                  "tech_retries": 0, "calls_completed": 0, "tokens_known": 0,
                                  "unknown_usage_calls": 0}

    # ------------------------------------------------------------ gates/commands
    def prepare_gate(self, gate_id: str, run_id: str, kind: str, subject: dict) -> dict:
        subject_hash = object_hash(subject)
        existing = self._one("SELECT * FROM workflow_gates WHERE run_id=? AND kind=? AND subject_hash=?",
                             (run_id, kind, subject_hash))
        if existing is not None:
            return self._row(existing)
        self._exec(
            "INSERT INTO workflow_gates (id, run_id, kind, subject_json, subject_hash, status, created_at) "
            "VALUES (?,?,?,?,?,'pending',?)",
            (gate_id, run_id, kind, json.dumps(subject, ensure_ascii=False), subject_hash, _now()))
        return self._row(self._one("SELECT * FROM workflow_gates WHERE id=?", (gate_id,)))

    def get_gate(self, gate_id: str) -> dict:
        row = self._one("SELECT * FROM workflow_gates WHERE id=?", (gate_id,))
        if row is None:
            raise NotFoundError(f"gate {gate_id}")
        return self._row(row)

    def pending_gates(self, run_id: str) -> list[dict]:
        return [self._row(r) for r in self._all(
            "SELECT * FROM workflow_gates WHERE run_id=? AND status='pending' ORDER BY created_at", (run_id,))]

    def apply_gate_decision(self, gate_id: str, decision: dict, idempotency_key: str,
                            expected_decision_key: str | None = None) -> dict:
        """Commit an authenticated user decision as a domain command (CAS + idempotent).

        decision: {"decision_key": str, "approved": bool, "payload": {...frozen refs...}}
        """
        gate = self.get_gate(gate_id)
        if gate["status"] == "approved" and gate["decision_key"] == decision.get("decision_key"):
            return self._row(self._one("SELECT * FROM workflow_gates WHERE id=?", (gate_id,)))
        if gate["status"] != "pending":
            raise ConflictError(f"gate {gate_id} is {gate['status']}")
        if decision.get("approved") is not True:
            # rejected decisions supersede the gate and obsoletes pending commands
            with self._lock:
                self._conn.execute("UPDATE workflow_gates SET status='rejected', decision_key=?, "
                                   "decision_json=?, decision_at=? WHERE id=? AND status='pending'",
                                   (decision.get("decision_key"), json.dumps(decision, ensure_ascii=False), _now(), gate_id))
                self._conn.execute("UPDATE workflow_commands SET status='obsolete' WHERE gate_id=? AND status='pending'",
                                   (gate_id,))
                self._conn.commit()
            return self.get_gate(gate_id)
        payload_hash = object_hash(decision["payload"])
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                cur = self._conn.execute(
                    "UPDATE workflow_gates SET status='approved', decision_key=?, decision_json=?, decision_at=? "
                    "WHERE id=? AND status='pending'",
                    (decision.get("decision_key"), json.dumps(decision, ensure_ascii=False), _now(), gate_id))
                if cur.rowcount != 1:
                    self._conn.rollback()
                    raise ConflictError("gate decision CAS failed")
                cmd_id = "cmd_" + object_hash({"gate_id": gate_id, "key": idempotency_key})[:24]
                self._conn.execute(
                    "INSERT INTO workflow_commands (id, run_id, gate_id, kind, idempotency_key, payload_hash, status, created_at) "
                    "VALUES (?,?,?,?,?,?, 'pending', ?)",
                    (cmd_id, gate["run_id"], gate_id, "resume",
                     idempotency_key, payload_hash, _now()))
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                self._conn.rollback()
                raise IdempotencyConflict(f"command idempotency conflict: {exc}") from exc
            except Exception:
                self._conn.rollback()
                raise
        return self.get_gate(gate_id)

    def consume_gate_resume(self, gate_id: str, decision_key: str) -> dict:
        """Validate a graph resume value against the committed gate decision (authority check)."""
        gate = self.get_gate(gate_id)
        if gate["status"] != "approved" or gate["decision_key"] != decision_key:
            raise DomainError("resume value is not a committed approved decision", "ORIGIN_DENIED")
        decision = json.loads(gate["decision_json"])
        self._exec("UPDATE workflow_commands SET status='applied' WHERE gate_id=? AND status='pending'", (gate_id,))
        return decision

    def obsolete_pending_commands(self, run_id: str, reason: str) -> None:
        self._exec("UPDATE workflow_commands SET status='obsolete' WHERE run_id=? AND status='pending'", (run_id,))

    # ----------------------------------------------------------------- audience
    def create_session(self, session_id: str, preview_id: str, persona_id: str) -> dict:
        self._exec("INSERT INTO audience_sessions (id, preview_id, persona_id, next_ordinal, status, created_at) "
                   "VALUES (?,?,?,0,'active',?)", (session_id, preview_id, persona_id, _now()))
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> dict:
        row = self._one("SELECT * FROM audience_sessions WHERE id=?", (session_id,))
        if row is None:
            raise NotFoundError(f"session {session_id}")
        return self._row(row)

    def sessions_for_preview(self, preview_id: str) -> list[dict]:
        return [self._row(r) for r in self._all(
            "SELECT * FROM audience_sessions WHERE preview_id=? ORDER BY created_at", (preview_id,))]

    def save_event_and_advance(self, session_id: str, ordinal: int, segment_id: str,
                               payload: dict, next_status: str | None) -> dict:
        """Atomic: event + cursor advance (+ optional terminal session status)."""
        event_id = f"evt_{session_id}_{ordinal}"
        existing = self._one("SELECT * FROM audience_events WHERE id=?", (event_id,))
        if existing is not None:
            if json.loads(existing["payload_json"]) != payload:
                raise IdempotencyConflict(f"event {event_id} exists with different payload")
            return {"event_id": event_id, "replayed": True}
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.execute(
                    "INSERT INTO audience_events (id, session_id, ordinal, segment_id, payload_json, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (event_id, session_id, ordinal, segment_id, json.dumps(payload, ensure_ascii=False), _now()))
                if next_status is None:
                    self._conn.execute("UPDATE audience_sessions SET next_ordinal=? WHERE id=?",
                                       (ordinal + 1, session_id))
                else:
                    self._conn.execute("UPDATE audience_sessions SET next_ordinal=?, status=? WHERE id=?",
                                       (ordinal + 1, next_status, session_id))
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                self._conn.rollback()
                raise IdempotencyConflict(f"event already committed: {exc}") from exc
            except Exception:
                self._conn.rollback()
                raise
        return {"event_id": event_id}

    def mark_session_incomplete(self, session_id: str) -> dict:
        self._exec("UPDATE audience_sessions SET status='incomplete' WHERE id=? AND status='active'", (session_id,))
        return self.get_session(session_id)

    def session_events(self, session_id: str) -> list[dict]:
        rows = self._all("SELECT * FROM audience_events WHERE session_id=? ORDER BY ordinal", (session_id,))
        out = []
        for row in rows:
            item = self._row(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            out.append(item)
        return out

    def preview_events(self, preview_id: str) -> list[dict]:
        rows = self._all(
            "SELECT e.* FROM audience_events e JOIN audience_sessions s ON e.session_id=s.id "
            "WHERE s.preview_id=? ORDER BY s.created_at, e.ordinal", (preview_id,))
        out = []
        for row in rows:
            item = self._row(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            out.append(item)
        return out
