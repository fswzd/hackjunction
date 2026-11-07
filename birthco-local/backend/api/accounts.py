"""Local operator account partitions."""
from uuid import uuid4

from flask import Blueprint, current_app

from backend.api import existing_response, fingerprint, json_body, request_id, save_response, success
from backend.domain.hashing import canonical_bytes
from backend.domain.schemas import AccountCreate, AccountRead
from backend.security.session import require_write
from backend.storage.db import connect, immediate, utc_now

blueprint = Blueprint("accounts", __name__)


@blueprint.get("/api/v1/accounts")
def list_accounts():
    with connect(current_app.config["DB_PATH"]) as db:
        rows = db.execute("SELECT id,name,row_version FROM accounts ORDER BY name,id LIMIT 100").fetchall()
    return success([AccountRead(account_id=row["id"], name=row["name"], row_version=row["row_version"]).model_dump() for row in rows])


@blueprint.post("/api/v1/accounts")
def create_account():
    _, key = require_write()
    raw = json_body()
    payload = AccountCreate.model_validate(raw)
    digest = fingerprint(raw)
    scope = "local_operator"
    with connect(current_app.config["DB_PATH"]) as db:
        with immediate(db):
            previous = existing_response(db, scope, key, digest)
            if previous:
                return previous
            account_id = "a_" + uuid4().hex
            db.execute("INSERT INTO accounts(id,name) VALUES(?,?)", (account_id, payload.name))
            result = AccountRead(account_id=account_id, name=payload.name, row_version=0).model_dump()
            response = {"data": result, "request_id": request_id()}
            save_response(db, scope, key, digest, response, 201)
    return success(result, 201)
