"""接入管线：注册既有账号 → 导入历史作品（adapter / manual）→ 派生 baseline。

语义与 cheat-on-content 对齐：导入失败不阻塞；manual 永久可用；
baseline_plays = 已导入作品播放数中位数；不伪造任何未抓到的数据。
"""
from __future__ import annotations

from pathlib import Path

from backend.integrations import storage
from backend.integrations.types import ExternalAccountCreate, ManualImport, PerfVideo


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


def attach_session(db_path, external_account_id: str, session_path: Path) -> dict:
    """扫码登录完成后：登记会话引用与指纹（凭据文件不入库）。"""
    from backend.integrations.douyin import session as douyin_session  # noqa: PLC0415
    fingerprint = douyin_session.session_fingerprint(session_path)
    if fingerprint is None:
        raise FileNotFoundError(session_path)
    return storage.set_session_state(db_path, external_account_id, status="logged_in",
                                     session_ref=str(session_path), fingerprint=fingerprint)
