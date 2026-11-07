"""Shared API envelope and input handling."""
import json
from uuid import uuid4

from flask import g, jsonify, request
from pydantic import ValidationError
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from backend.domain.errors import DomainError
from backend.domain.hashing import sha256_json


def request_id() -> str:
    if not hasattr(g, "request_id"):
        g.request_id = "req_" + uuid4().hex
    return g.request_id


def success(data, status: int = 200):
    response = jsonify({"data": data, "request_id": request_id()})
    response.status_code = status
    return response


def error(code: str, status: int, cause: str, action: str, *, retryable=False, current_row_version=None, field_errors=None):
    return jsonify({"error": {"code": code, "retryable": retryable, "cause_hint": cause, "next_action": action, "field_errors": field_errors or [], "current_row_version": current_row_version}, "request_id": request_id()}), status


def json_body():
    if not request.is_json:
        raise DomainError("SCHEMA_INVALID", "JSON body required", "Send application/json")
    try:
        value = request.get_json()
    except RequestEntityTooLarge:
        raise
    except Exception as exc:
        raise BadRequest("Malformed JSON") from exc
    if not isinstance(value, dict):
        raise DomainError("SCHEMA_INVALID", "JSON object required", "Correct the request body")
    return value


def fingerprint(body, mode=None):
    return sha256_json({"method": request.method, "path": request.path, "body": body, "mode": mode})


def existing_response(db, scope, key, digest):
    row = db.execute("SELECT request_hash,http_status,response_json FROM idempotency WHERE scope=? AND operation=? AND key=?", (scope, request.method + " " + request.path, key)).fetchone()
    if row is None:
        return None
    if row["request_hash"] != digest:
        raise DomainError("IDEMPOTENCY_CONFLICT", "Key already used with different input", "Use a new key for changed input")
    return jsonify(json.loads(row["response_json"])), row["http_status"]


def save_response(db, scope, key, digest, body, status):
    from backend.storage.db import utc_now
    db.execute("INSERT INTO idempotency(scope,operation,key,request_hash,http_status,response_json,created_at) VALUES(?,?,?,?,?,?,?)", (scope, request.method + " " + request.path, key, digest, status, json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")), utc_now()))
