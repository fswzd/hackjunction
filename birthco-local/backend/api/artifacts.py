"""Artifact listing and download for accepted content versions.

The asset pipeline is anchored on the accepted version: a task only exposes
artifacts once its frozen version is accepted. Rows registered by an export
batch are served from disk after a real hash/size verification; when no export
batch registered a file yet, the accepted version itself is rendered as a
deterministic Markdown artifact so acceptance always yields a downloadable
asset whose listed ``file_hash`` matches the downloaded bytes.
"""
import hashlib
import json
from pathlib import Path

from flask import Blueprint, Response, current_app, send_file

from backend.api import success
from backend.domain.errors import DomainError
from backend.storage.db import connect

blueprint = Blueprint("artifacts", __name__)

_RESERVED_WINDOWS_NAMES = {"CON", "PRN", "AUX", "NUL",
                           *(f"COM{i}" for i in range(1, 10)),
                           *(f"LPT{i}" for i in range(1, 10))}


def _safe_artifact(root: Path, relative: str) -> Path:
    """Resolve a registered artifact path inside the data directory."""
    path = Path(relative)
    if (path.is_absolute() or not path.parts or path.parts[0] != "artifacts"
            or any(part in {"..", "."} or ":" in part or "\\" in part
                   or part.rstrip(" .") != part
                   or part.split(".")[0].upper() in _RESERVED_WINDOWS_NAMES
                   for part in path.parts)):
        raise DomainError("ARTIFACT_MISSING", "Registered artifact path is invalid", "Reconcile local storage")
    resolved = (root / path).resolve()
    if root.resolve() not in resolved.parents:
        raise DomainError("ARTIFACT_MISSING", "Artifact escapes the data directory", "Reconcile local storage")
    return resolved


def _render_markdown(content: dict) -> bytes:
    titles = content.get("titles") or []
    segments = content.get("segments") or []
    lines: list[str] = []
    if titles:
        lines.append(f"# {titles[0]}")
        lines.append("")
    cover = content.get("cover_copy")
    if cover:
        lines.append(f"> {cover}")
        lines.append("")
    for segment in segments:
        text = (segment.get("text") or "").strip()
        if text:
            lines.append(text)
            lines.append("")
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def _task(db, task_id):
    row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if row is None:
        raise DomainError("NOT_FOUND", "Task not found", "Reload tasks")
    return row


def _synthetic_artifact(task_id: str, version_row, content: dict) -> dict:
    body = _render_markdown(content)
    file_hash = hashlib.sha256(body).hexdigest()
    return {
        "artifact_id": f"art_syn_{version_row['id']}",
        "task_id": task_id,
        "version_id": version_row["id"],
        "content_hash": version_row["content_hash"],
        "file_hash": file_hash,
        "format": "md",
        "byte_size": len(body),
        "status": "available",
        "relative_path": f"artifacts/{version_row['id']}.md",
        "download_url": f"/api/v1/artifacts/art_syn_{version_row['id']}/download",
    }


def _registered_artifact(db, row, content_hash: str) -> dict:
    return {
        "artifact_id": row["id"],
        "task_id": row["task_id"],
        "version_id": row["version_id"],
        "content_hash": content_hash,
        "file_hash": row["file_hash"],
        "format": row["format"],
        "byte_size": row["byte_size"],
        "status": row["status"],
        "relative_path": row["relative_path"],
        "download_url": f"/api/v1/artifacts/{row['id']}/download",
    }


def _accepted_version(db, task):
    version_id = task["accepted_version_id"]
    if not version_id:
        return None
    return db.execute("SELECT * FROM content_versions WHERE id=? AND task_id=?",
                      (version_id, task["id"])).fetchone()


@blueprint.get("/api/v1/tasks/<task_id>/artifacts")
def list_artifacts(task_id):
    """List downloadable artifacts of the accepted version (empty otherwise)."""
    with connect(current_app.config["DB_PATH"]) as db:
        task = _task(db, task_id)
        version = _accepted_version(db, task)
        if version is None:
            return success([])
        rows = db.execute(
            "SELECT * FROM artifacts WHERE task_id=? AND version_id=? ORDER BY format,id",
            (task_id, version["id"])).fetchall()
        values = [_registered_artifact(db, row, version["content_hash"]) for row in rows]
        if not values:
            content = json.loads(version["content_json"])
            values = [_synthetic_artifact(task_id, version, content)]
    return success(values)


def _find_artifact(db, artifact_id):
    row = db.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
    if row is not None:
        return row, None
    if not artifact_id.startswith("art_syn_"):
        return None, None
    version_id = artifact_id[len("art_syn_"):]
    version = db.execute("SELECT * FROM content_versions WHERE id=?", (version_id,)).fetchone()
    return None, version


@blueprint.get("/api/v1/artifacts/<artifact_id>/download")
def download_artifact(artifact_id):
    """Stream one artifact after verifying its registered hash and size."""
    with connect(current_app.config["DB_PATH"]) as db:
        row, version = _find_artifact(db, artifact_id)
        if row is None and version is None:
            raise DomainError("NOT_FOUND", "Artifact not found", "Reload the asset list")
        if row is not None:
            task = _task(db, row["task_id"])
            if task["accepted_version_id"] != row["version_id"]:
                raise DomainError("NOT_FOUND", "Artifact is not from an accepted version", "Accept the content first")
            root = Path(current_app.config["DATA_DIR"])
            path = _safe_artifact(root, row["relative_path"])
            if not path.is_file():
                raise DomainError("ARTIFACT_MISSING", "Registered artifact is missing on disk", "Reconcile local storage")
            blob = path.read_bytes()
            if len(blob) != row["byte_size"] or hashlib.sha256(blob).hexdigest() != row["file_hash"]:
                raise DomainError("ARTIFACT_MISSING", "Registered artifact failed hash verification", "Reconcile local storage")
            response = send_file(path, mimetype="text/markdown" if row["format"] == "md" else "text/plain",
                                 as_attachment=True, download_name=path.name)
            response.headers["X-File-Hash"] = row["file_hash"]
            return response
        task = _task(db, version["task_id"])
        if task["accepted_version_id"] != version["id"]:
            raise DomainError("NOT_FOUND", "Artifact is not from an accepted version", "Accept the content first")
        blob = _render_markdown(json.loads(version["content_json"]))
        file_hash = hashlib.sha256(blob).hexdigest()
    return Response(blob, mimetype="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{version["id"]}.md"',
                             "X-File-Hash": file_hash})
