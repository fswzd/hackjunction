"""Opaque local sessions and request-bound CSRF tokens."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets

from flask import Blueprint, current_app, g, request

from backend.domain.errors import DomainError
from backend.storage.db import connect, immediate

blueprint = Blueprint("session", __name__)
COOKIE = "birthco_session"
KEY_PATTERN = re.compile(r"^[\x20-\x7e]{16,128}$")


def _digest(value: str) -> str:
    return hmac.new(current_app.config["SESSION_SECRET"], value.encode(), hashlib.sha256).hexdigest()


def validate_origin() -> None:
    expected = "127.0.0.1:5000"
    if request.host != expected:
        raise DomainError("ORIGIN_DENIED", "Unexpected local host", "Open the local workbench address")
    origin = request.headers.get("Origin")
    if origin and origin != "http://" + expected:
        raise DomainError("ORIGIN_DENIED", "Cross-origin request", "Use the local workbench")
    site = request.headers.get("Sec-Fetch-Site")
    if site and site != "same-origin":
        raise DomainError("ORIGIN_DENIED", "Cross-site request", "Use the local workbench")
    referer = request.headers.get("Referer")
    if referer and not referer.startswith("http://" + expected + "/"):
        raise DomainError("ORIGIN_DENIED", "Cross-origin referrer", "Use the local workbench")


def require_session():
    cookie = request.cookies.get(COOKIE)
    if not cookie:
        raise DomainError("SESSION_REQUIRED", "Session required", "Open the workbench and reload")
    with connect(current_app.config["DB_PATH"]) as db:
        row = db.execute("SELECT id,csrf_hash,capability,expires_at FROM app_sessions WHERE id=?", (_digest(cookie),)).fetchone()
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if row is None or row["expires_at"] <= now:
            raise DomainError("SESSION_REQUIRED", "Session expired", "Reload the workbench")
        g.local_session = dict(row)
        return g.local_session


def require_write():
    session = require_session()
    csrf = request.headers.get("X-CSRF-Token", "")
    if not csrf or not hmac.compare_digest(_digest(csrf), session["csrf_hash"]):
        raise DomainError("SESSION_REQUIRED", "CSRF token invalid", "Reload the workbench")
    key = request.headers.get("Idempotency-Key", "")
    if not KEY_PATTERN.fullmatch(key):
        raise DomainError("SCHEMA_INVALID", "Idempotency key must be 16-128 printable ASCII characters", "Provide a new request key")
    return session, key


@blueprint.get("/api/v1/session")
def bootstrap():
    from backend.api import success
    cookie = request.cookies.get(COOKIE)
    session_id = _digest(cookie) if cookie else None
    csrf = secrets.token_urlsafe(32)
    new_cookie = cookie or secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expiry = (now + timedelta(hours=12)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    with connect(current_app.config["DB_PATH"]) as db:
        with immediate(db):
            existing = db.execute("SELECT id,expires_at FROM app_sessions WHERE id=?", (session_id,)).fetchone() if session_id else None
            if existing and existing["expires_at"] > now.isoformat(timespec="milliseconds").replace("+00:00", "Z"):
                db.execute("UPDATE app_sessions SET csrf_hash=?,expires_at=? WHERE id=?", (_digest(csrf), expiry, session_id))
            else:
                new_cookie = secrets.token_urlsafe(32)
                session_id = _digest(new_cookie)
                db.execute("INSERT INTO app_sessions(id,csrf_hash,capability,expires_at) VALUES(?,?,'creator',?)", (session_id, _digest(csrf), expiry))
    response = success({"session_id": session_id, "csrf_token": csrf, "capabilities": ["creator"]})
    response.set_cookie(COOKIE, new_cookie, httponly=True, samesite="Strict", secure=False, path="/", max_age=12 * 3600)
    return response
