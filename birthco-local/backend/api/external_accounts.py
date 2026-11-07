"""既有平台账号接入管理 API（抖音 / 小红书）。

注册的是用户已存在的账号，不是新建账号；会话凭据不经过 API 传输。
登录走后台线程（弹出本地浏览器窗口扫码），状态与经验库可轮询查询。
"""
from __future__ import annotations

import threading

from flask import Blueprint, current_app, request

from backend.api import existing_response, fingerprint, json_body, request_id, save_response, success
from backend.integrations import intake, storage
from backend.integrations.types import ExternalAccountCreate, ExternalAccountRead, ManualImport
from backend.security.session import require_write

blueprint = Blueprint("external_accounts", __name__)

_login_jobs: dict[str, threading.Thread] = {}


@blueprint.get("/api/v1/accounts/external")
def list_external_accounts():
    account_id = request.args.get("account_id") or None
    storage.ensure_integration_tables(current_app.config["DB_PATH"])
    rows = storage.list_external_accounts(current_app.config["DB_PATH"], account_id)
    return success([ExternalAccountRead(
        external_account_id=r["id"], account_id=r["account_id"], platform=r["platform"],
        handle=r["handle"], display_name=r["display_name"], profile_url=r["profile_url"],
        session_status=r["session_status"], baseline_plays=r["baseline_plays"],
        imported_count=r["imported_count"]).model_dump() for r in rows])


@blueprint.post("/api/v1/accounts/external")
def register_external_account():
    _, key = require_write()
    raw = json_body()
    payload = ExternalAccountCreate.model_validate(raw)
    digest = fingerprint(raw)
    scope = "external_account_register"
    storage.ensure_integration_tables(current_app.config["DB_PATH"])
    # 注册本身幂等（platform+handle 唯一）；idempotency 记录随后落库，
    # 避免嵌套事务互锁
    row = intake.register_account(current_app.config["DB_PATH"], payload)
    result = ExternalAccountRead(
        external_account_id=row["id"], account_id=row["account_id"],
        platform=row["platform"], handle=row["handle"],
        display_name=row["display_name"], profile_url=row["profile_url"],
        session_status=row["session_status"], baseline_plays=row["baseline_plays"],
        imported_count=row["imported_count"]).model_dump()
    from backend.storage.db import connect, immediate
    with connect(current_app.config["DB_PATH"]) as db:
        with immediate(db):
            previous = existing_response(db, scope, key, digest)
            if previous:
                return previous
            response = {"data": result, "request_id": request_id()}
            save_response(db, scope, key, digest, response, 201)
    return success(result, 201)


@blueprint.post("/api/v1/accounts/external/<external_account_id>/import")
def import_history(external_account_id: str):
    _, key = require_write()
    raw = json_body()
    digest = fingerprint(raw)
    scope = "external_account_import"
    source = raw.get("source", "manual")
    try:
        if source == "manual":
            payload = ManualImport.model_validate(raw)
            result = intake.import_manual(current_app.config["DB_PATH"],
                                          external_account_id, payload)
        elif source == "adapter":
            result = intake.import_via_adapter(
                current_app.config["DB_PATH"], external_account_id,
                count=int(raw.get("count", 10)))
        else:
            raise ValueError("source must be manual or adapter")
    except KeyError:
        return success({"error": {"code": "NOT_FOUND", "detail": "unknown external account"}}, 404)
    except ValueError as exc:
        return success({"error": {"code": "SCHEMA_INVALID", "detail": str(exc)}}, 400)
    except Exception as exc:  # adapter 抓取失败等：保留可操作提示，不产生半截数据
        storage.mark_pending_adapter(current_app.config["DB_PATH"], external_account_id)
        return success({"error": {"code": "MODEL_UNAVAILABLE",
                                  "detail": f"import failed: {exc}; manual 通道仍可用"}}, 502)
    return success({"external_account_id": external_account_id, **result}, 201)


@blueprint.get("/api/v1/accounts/external/<external_account_id>/videos")
def list_videos(external_account_id: str):
    try:
        videos = storage.list_imported_videos(current_app.config["DB_PATH"], external_account_id)
    except Exception:
        return success({"error": {"code": "NOT_FOUND", "detail": "unknown external account"}}, 404)
    return success(videos)


@blueprint.post("/api/v1/accounts/external/<external_account_id>/login")
def login_external_account(external_account_id: str):
    """启动扫码登录（后台线程弹出浏览器窗口），成功后自动抓取实绩写入经验库。"""
    require_write()
    db_path = current_app.config["DB_PATH"]
    storage.ensure_integration_tables(db_path)
    try:
        storage.get_external_account(db_path, external_account_id)
    except KeyError:
        return success({"error": {"code": "NOT_FOUND", "detail": "unknown external account"}}, 404)
    running = _login_jobs.get(external_account_id)
    if running and running.is_alive():
        return success({"external_account_id": external_account_id,
                        "session_status": "logging_in"}, 202)
    storage.set_session_state(db_path, external_account_id, status="logging_in")

    def _run():
        try:
            intake.login_and_import(db_path, external_account_id, count=10)
        except Exception:
            # 错误已写入 meta（login_error）；不允许卡在 logging_in
            try:
                current = storage.get_external_account(db_path, external_account_id)
                if current["session_status"] == "logging_in":
                    storage.set_session_state(db_path, external_account_id, status="none")
            except Exception:
                pass
        finally:
            _login_jobs.pop(external_account_id, None)

    thread = threading.Thread(target=_run, name=f"login-{external_account_id}", daemon=True)
    _login_jobs[external_account_id] = thread
    thread.start()
    return success({
        "external_account_id": external_account_id,
        "session_status": "logging_in",
        "next_action": "在弹出的浏览器窗口中扫码登录；登录成功后会自动抓取最近作品实绩写入经验库",
    }, 202)


@blueprint.get("/api/v1/accounts/external/<external_account_id>/status")
def external_account_status(external_account_id: str):
    storage.ensure_integration_tables(current_app.config["DB_PATH"])
    try:
        return success(intake.status(current_app.config["DB_PATH"], external_account_id))
    except KeyError:
        return success({"error": {"code": "NOT_FOUND", "detail": "unknown external account"}}, 404)


@blueprint.get("/api/v1/accounts/external/<external_account_id>/experience")
def external_account_experience(external_account_id: str):
    """经验库聚合：作品实绩汇总、baseline 与热评，供后续分析与选题引用。"""
    storage.ensure_integration_tables(current_app.config["DB_PATH"])
    try:
        return success(intake.experience(current_app.config["DB_PATH"], external_account_id))
    except KeyError:
        return success({"error": {"code": "NOT_FOUND", "detail": "unknown external account"}}, 404)
