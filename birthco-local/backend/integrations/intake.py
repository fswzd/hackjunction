"""接入管线：注册既有账号 → 导入历史作品（adapter / manual）→ 派生 baseline。

语义与 cheat-on-content 对齐：导入失败不阻塞；manual 永久可用；
baseline_plays = 已导入作品播放数中位数；不伪造任何未抓到的数据。
"""
from __future__ import annotations

import json
from pathlib import Path

from backend.integrations import storage
from backend.integrations.types import ExternalAccountCreate, ManualImport, PerfVideo


def _platform_session(platform: str):
    if platform == "douyin":
        from backend.integrations.douyin import session as platform_session  # noqa: PLC0415
    elif platform == "xiaohongshu":
        from backend.integrations.xiaohongshu import session as platform_session  # noqa: PLC0415
    else:
        raise ValueError(f"unsupported platform: {platform}")
    return platform_session


def register_account(db_path, payload: ExternalAccountCreate) -> dict:
    if payload.platform not in ("douyin", "xiaohongshu"):
        raise ValueError(f"unsupported platform: {payload.platform}")
    return storage.register_external_account(
        db_path, account_id=payload.account_id, platform=payload.platform,
        handle=payload.handle, display_name=payload.display_name,
        profile_url=payload.profile_url)


def import_manual(db_path, external_account_id: str, payload: ManualImport) -> dict:
    videos = [v.model_dump() for v in payload.videos]
    inserted = storage.upsert_imported_videos(db_path, external_account_id, videos,
                                              source=payload.source)
    account = storage.get_external_account(db_path, external_account_id)
    return {"imported": len(inserted), "skipped_duplicates": len(videos) - len(inserted),
            "baseline_plays": account["baseline_plays"],
            "imported_count": account["imported_count"]}


def import_via_adapter(db_path, external_account_id: str, *, count: int = 10) -> dict:
    """douyin-session 适配器抓取导入；会话缺失/抓取失败给出可操作错误。"""
    from backend.integrations.douyin import fetch as douyin_fetch  # noqa: PLC0415
    account = storage.get_external_account(db_path, external_account_id)
    if account["platform"] == "douyin":
        fetch = douyin_fetch
    elif account["platform"] == "xiaohongshu":
        from backend.integrations.xiaohongshu import fetch as xhs_fetch  # noqa: PLC0415
        fetch = xhs_fetch
    else:
        raise ValueError(f"adapter import does not support {account['platform']}")
    works: list[PerfVideo] = fetch.fetch_recent_works(external_account_id, count=count)
    inserted = storage.upsert_imported_videos(
        db_path, external_account_id, [w.model_dump() for w in works], source="adapter")
    account = storage.get_external_account(db_path, external_account_id)
    storage.set_session_state(db_path, external_account_id, status="logged_in")
    return {"imported": len(inserted), "baseline_plays": account["baseline_plays"],
            "imported_count": account["imported_count"]}


def mark_pending_adapter(db_path, external_account_id: str) -> dict:
    return storage.set_session_state(db_path, external_account_id,
                                     status="pending_adapter_setup")


def delete_account(db_path, external_account_id: str) -> dict:
    """回滚接入登记：删除账号行、经验库数据与本地会话文件（登录失败后调用）。"""
    account = storage.get_external_account(db_path, external_account_id)
    result = storage.delete_external_account(db_path, external_account_id)
    try:
        session_file = Path(_platform_session(account["platform"])
                            .session_paths(external_account_id))
        session_file.unlink(missing_ok=True)
    except Exception:
        pass  # 会话文件清理尽力而为，不影响删除结果
    return result


def attach_session(db_path, external_account_id: str, session_path: Path) -> dict:
    """扫码登录完成后：登记会话引用与指纹（凭据文件不入库）。"""
    account = storage.get_external_account(db_path, external_account_id)
    fingerprint = _platform_session(account["platform"]).session_fingerprint(session_path)
    if fingerprint is None:
        raise FileNotFoundError(session_path)
    return storage.set_session_state(db_path, external_account_id, status="logged_in",
                                     session_ref=str(session_path), fingerprint=fingerprint)


def login_and_import(db_path, external_account_id: str, *, count: int = 10) -> dict:
    """扫码登录（弹出浏览器窗口）→ 登记会话 → 自动抓取最近实绩写入经验库。

    供后台线程调用。失败会把可操作错误写进 meta（login_error / import_error），
    不产生半截数据；manual 通道始终可用。
    """
    account = storage.get_external_account(db_path, external_account_id)
    platform_session = _platform_session(account["platform"])
    storage.set_session_state(db_path, external_account_id, status="logging_in")
    storage.update_meta(db_path, external_account_id,
                        {"login_error": None, "import_error": None})
    try:
        session_path = platform_session.login_interactive(external_account_id)
    except Exception as exc:
        previous = storage.get_external_account(db_path, external_account_id)["session_status"]
        # 先写错误再翻状态：轮询看到终态时 login_error 必已可见
        storage.update_meta(db_path, external_account_id, {"login_error": str(exc)})
        storage.set_session_state(
            db_path, external_account_id,
            status="expired" if previous == "logged_in" else "none")
        raise
    attach_session(db_path, external_account_id, session_path)
    try:
        return import_via_adapter(db_path, external_account_id, count=count)
    except Exception as exc:
        # 会话已建立，仅实绩抓取失败：记录错误，可稍后用 import 重试或 manual 补录
        storage.update_meta(db_path, external_account_id, {"import_error": str(exc)})
        latest = storage.get_external_account(db_path, external_account_id)
        return {"imported": 0, "import_error": str(exc),
                "baseline_plays": latest["baseline_plays"],
                "imported_count": latest["imported_count"]}


def status(db_path, external_account_id: str) -> dict:
    """账号接入状态 + 最近一次登录/导入的可操作错误。"""
    account = storage.get_external_account(db_path, external_account_id)
    meta = json.loads(account.get("meta_json") or "{}")
    return {
        "external_account_id": account["id"],
        "platform": account["platform"],
        "handle": account["handle"],
        "session_status": account["session_status"],
        "login_error": meta.get("login_error"),
        "import_error": meta.get("import_error"),
        "imported_count": account["imported_count"],
        "baseline_plays": account["baseline_plays"],
    }


def experience(db_path, external_account_id: str) -> dict:
    """经验库视图：已导入作品实绩的聚合，是后续选题/审稿/数据分析的历史依据。"""
    account = storage.get_external_account(db_path, external_account_id)
    videos = storage.list_imported_videos(db_path, external_account_id)

    def _total(field: str) -> int:
        return sum(v[field] for v in videos if v.get(field) is not None)

    top_comments = sorted(
        ({"text": c["text"], "likes": c.get("likes", 0),
          "platform_video_id": v["platform_video_id"]}
         for v in videos for c in v.get("top_comments", [])),
        key=lambda c: c["likes"], reverse=True)[:10]
    return {
        "external_account_id": account["id"],
        "platform": account["platform"],
        "handle": account["handle"],
        "session_status": account["session_status"],
        "imported_count": account["imported_count"],
        "baseline_plays": account["baseline_plays"],
        "totals": {"plays": _total("plays"), "likes": _total("likes"),
                   "comments": _total("comments"), "shares": _total("shares"),
                   "favorites": _total("favorites")},
        "top_comments": top_comments,
        "recent_videos": [
            {key: v.get(key) for key in
             ("platform_video_id", "title", "published_at",
              "plays", "likes", "comments", "shares", "favorites")}
            for v in videos[:20]],
    }
