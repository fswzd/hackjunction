"""Local operator account partitions."""
from uuid import uuid4

from flask import Blueprint, current_app

from backend.api import existing_response, fingerprint, json_body, request_id, save_response, success
from backend.domain.errors import DomainError
from backend.domain.schemas import AccountCreate, AccountRead, AccountUpdate
from backend.security.session import require_write
from backend.storage.db import connect, immediate

blueprint = Blueprint("accounts", __name__)
_SCOPE = "local_operator"


@blueprint.get("/api/v1/accounts")
def list_accounts():
    with connect(current_app.config["DB_PATH"]) as db:
        rows = db.execute(
            "SELECT id,name,creator_stage,row_version FROM accounts ORDER BY name,id LIMIT 100"
        ).fetchall()
    return success(
        [
            AccountRead(
                account_id=row["id"],
                name=row["name"],
                creator_stage=row["creator_stage"],
                row_version=row["row_version"],
            ).model_dump()
            for row in rows
        ]
    )


@blueprint.post("/api/v1/accounts")
def create_account():
    _, key = require_write()
    raw = json_body()
    payload = AccountCreate.model_validate(raw)
    digest = fingerprint(raw)
    with connect(current_app.config["DB_PATH"]) as db:
        with immediate(db):
            previous = existing_response(db, _SCOPE, key, digest)
            if previous:
                return previous
            account_id = "a_" + uuid4().hex
            db.execute(
                "INSERT INTO accounts(id,name,creator_stage) VALUES(?,?,?)",
                (account_id, payload.name, payload.creator_stage),
            )
            result = AccountRead(
                account_id=account_id,
                name=payload.name,
                creator_stage=payload.creator_stage,
                row_version=0,
            ).model_dump()
            response = {"data": result, "request_id": request_id()}
            save_response(db, _SCOPE, key, digest, response, 201)
    return success(result, 201)


@blueprint.put("/api/v1/accounts/<account_id>")
def update_account(account_id):
    _, key = require_write()
    raw = json_body()
    payload = AccountUpdate.model_validate(raw)
    digest = fingerprint(raw)
    with connect(current_app.config["DB_PATH"]) as db:
        with immediate(db):
            previous = existing_response(db, _SCOPE, key, digest)
            if previous:
                return previous
            row = db.execute(
                "SELECT id,name,creator_stage,row_version FROM accounts WHERE id=?",
                (account_id,),
            ).fetchone()
            if row is None:
                raise DomainError("NOT_FOUND", "Account not found", "Select an existing account")
            if row["row_version"] != payload.expected_row_version:
                raise DomainError(
                    "VERSION_CONFLICT",
                    "Account changed since it was read",
                    "Reload the workspace and save again",
                    current_row_version=row["row_version"],
                )
            db.execute(
                "UPDATE accounts SET name=?,creator_stage=?,row_version=row_version+1 WHERE id=? AND row_version=?",
                (payload.name, payload.creator_stage, account_id, payload.expected_row_version),
            )
            result = AccountRead(
                account_id=account_id,
                name=payload.name,
                creator_stage=payload.creator_stage,
                row_version=payload.expected_row_version + 1,
            ).model_dump()
            response = {"data": result, "request_id": request_id()}
            save_response(db, _SCOPE, key, digest, response, 200)
    return success(result, 200)
