"""Loopback-only Flask app factory; startup never runs migrations or a worker."""
import os
import sqlite3

from flask import Flask, request
from pydantic import ValidationError
from werkzeug.exceptions import BadRequest, HTTPException, RequestEntityTooLarge

from backend.api import error, success
from backend.config import AppConfig, session_secret
from backend.domain.errors import DomainError
from backend.security.session import validate_origin, require_session, require_write
from backend.storage.db import connect


def create_app(overrides: dict | None = None) -> Flask:
    settings = AppConfig.load(overrides)
    db_path = settings.data_dir / "db.sqlite"
    with connect(db_path):
        pass
    app = Flask(__name__, static_folder=None)
    allowed_origins = {settings.origin}
    for item in os.environ.get("BIRTHCO_ALLOWED_ORIGINS", "").split(","):
        value = item.strip().rstrip("/")
        if value:
            allowed_origins.add(value)
    app.config.update(DB_PATH=db_path, DATA_DIR=settings.data_dir, MODEL_MODE=settings.model_mode,
                      SESSION_SECRET=session_secret(settings.data_dir), MAX_CONTENT_LENGTH=1048576,
                      JSON_AS_ASCII=False, PROPAGATE_EXCEPTIONS=False,
                      BIND_HOST=settings.host, BIND_PORT=settings.port, ALLOWED_ORIGINS=allowed_origins)

    @app.before_request
    def boundary():
        if request.path.startswith("/api/"):
            validate_origin()
            if not (request.method == "GET" and request.path == "/api/v1/session"):
                require_write() if request.method in {"POST", "PUT", "PATCH", "DELETE"} else require_session()

    @app.errorhandler(DomainError)
    def domain_failure(exc: DomainError):
        code = exc.code
        status = {"SCHEMA_INVALID": 422, "INPUT_MISSING": 422, "SESSION_REQUIRED": 401,
                  "ORIGIN_DENIED": 403, "SCOPE_DENIED": 403, "NOT_FOUND": 404,
                  "OUTPUT_TOO_LARGE": 413, "STORAGE_UNAVAILABLE": 503}.get(code, 409)
        return error(code, status, exc.cause_hint, exc.next_action, retryable=exc.retryable,
                     current_row_version=exc.current_row_version, field_errors=list(exc.field_errors))

    @app.errorhandler(ValidationError)
    def validation_failure(exc: ValidationError):
        fields = [".".join(map(str, item["loc"])) for item in exc.errors()][:30]
        return error("SCHEMA_INVALID", 422, "Request fields are invalid", "Correct the listed fields", field_errors=fields)

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_):
        return error("OUTPUT_TOO_LARGE", 413, "Request exceeds 1 MiB", "Reduce the request size")

    @app.errorhandler(BadRequest)
    def bad_request(_):
        return error("SCHEMA_INVALID", 400, "Malformed request", "Correct the JSON body")

    @app.errorhandler(sqlite3.Error)
    def storage_failure(_):
        return error("STORAGE_UNAVAILABLE", 503, "Local storage unavailable", "Retry with the same request key", retryable=True)

    @app.errorhandler(HTTPException)
    def http_failure(exc: HTTPException):
        if request.path.startswith("/api/"):
            code = "NOT_FOUND" if exc.code == 404 else "SCHEMA_INVALID"
            return error(code, exc.code or 400, "API route unavailable", "Check the API path and method")
        return exc

    @app.errorhandler(Exception)
    def unexpected_failure(_):
        return error("STORAGE_UNAVAILABLE", 503, "Service unavailable", "Retry with the same request key", retryable=True)

    @app.get("/")
    def index():
        return success({"service": "众幕 AI Agent backend", "mode": settings.model_mode})

    from backend.security.session import blueprint as session_blueprint
    from backend.api.accounts import blueprint as accounts_blueprint
    from backend.api.task_create import blueprint as create_blueprint
    from backend.api.task_reads import blueprint as reads_blueprint
    from backend.api.task_actions import blueprint as actions_blueprint
    from backend.api.external_accounts import blueprint as external_accounts_blueprint
    from backend.api.previews import blueprint as previews_blueprint
    for blueprint in (session_blueprint, accounts_blueprint, create_blueprint, reads_blueprint, actions_blueprint, previews_blueprint, external_accounts_blueprint):
        app.register_blueprint(blueprint)
    return app


if __name__ == "__main__":
    settings = AppConfig.load()
    create_app().run(host=settings.host, port=settings.port, debug=False, use_reloader=False)
