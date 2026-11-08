"""Store creator-centre sessions next to their owning workspace database."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile


def session_path(external_id: str, data_dir: Path | None = None) -> Path:
    folder = Path(os.environ.get("BIRTHCO_SESSION_DIR") or
                  (data_dir or Path(__file__).resolve().parents[2] / "data") / "sessions")
    return folder / f"{external_id}.storage_state.json"


def workspace_session_path(db_path, account: dict) -> Path:
    db = Path(db_path)
    canonical = session_path(account["id"], db.parent if db.suffix == ".sqlite" else db)
    if canonical.is_file():
        return canonical
    ref = Path(account["session_ref"]) if account.get("session_ref") else None
    # Reuse the legacy path bound to this database row. Do not search another
    # checkout's sessions by handle or read the user's default browser profile.
    if ref and ref.is_absolute() and ref.name == canonical.name and ref.is_file():
        return ref
    return canonical


def session_fingerprint(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def load_session(path: Path) -> dict | None:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeError):
        return None
    return state if isinstance(state, dict) and {"cookies", "origins"} <= state.keys() else None


def save_session(context, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                     prefix=".session-", suffix=".tmp", delete=False) as output:
        temporary = Path(output.name)
        try:
            json.dump(context.storage_state(indexed_db=True), output, ensure_ascii=False)
            output.close()
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)


def read_json(page, url: str) -> dict:
    response = page.evaluate("""async (url) => {
      const result = await fetch(url, { signal: AbortSignal.timeout(10000) });
      if (!result.ok) return { status: result.status };
      try { return { status: result.status, body: await result.json() }; }
      catch { return { status: result.status }; }
    }""", url)
    if response["status"] == 401:
        raise RuntimeError("平台登录已过期，请重新授权。")
    if not isinstance(response.get("body"), dict):
        raise RuntimeError(f"平台未返回可读取的数据（HTTP {response['status']}）。")
    return response["body"]
