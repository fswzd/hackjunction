"""Integration storage: 增量幂等 DDL + 外部账号/作品导入读写。

表结构（additive；待收编进 002 迁移）：
- external_accounts：已存在平台账号的接入登记（会话凭据只存本地受限目录，
  库里仅 session_ref 与指纹）
- imported_videos：从 adapter / manual 导入的作品实绩（含 top 评论）
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from backend.storage.db import connect, immediate, migrate, utc_now

DDL = """
CREATE TABLE IF NOT EXISTS external_accounts (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  handle TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  profile_url TEXT,
  session_status TEXT NOT NULL DEFAULT 'none',
  session_ref TEXT,
  session_fingerprint TEXT,
  baseline_plays INTEGER,
  imported_count INTEGER NOT NULL DEFAULT 0,
  meta_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (platform, handle)
);
CREATE TABLE IF NOT EXISTS imported_videos (
  id TEXT PRIMARY KEY,
  external_account_id TEXT NOT NULL REFERENCES external_accounts(id),
  platform_video_id TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  published_at TEXT,
  plays INTEGER, likes INTEGER, comments INTEGER, shares INTEGER, favorites INTEGER,
  top_comments_json TEXT NOT NULL DEFAULT '[]',
  source TEXT NOT NULL,
  raw_hash TEXT NOT NULL,
  material_id TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (external_account_id, platform_video_id)
);
CREATE INDEX IF NOT EXISTS idx_imported_videos_account
  ON imported_videos(external_account_id, published_at);
"""


def _db_file(db_path: Path | str) -> Path:
    """接受数据目录或 sqlite 文件两种路径。"""
    path = Path(db_path)
    return path if path.suffix == ".sqlite" else path / "db.sqlite"


def ensure_integration_tables(db_path: Path | str) -> None:
    migrate(_db_file(db_path).parent)  # 幂等：未迁移则初始化
    with connect(_db_file(db_path)) as db:
        # executescript 自带提交，不能套 immediate 事务
        db.executescript(DDL)


def _fingerprint(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode("utf-8")).hexdigest()


def register_external_account(db_path, *, account_id: str, platform: str, handle: str,
                              display_name: str = "", profile_url: str | None = None) -> dict:
    ensure_integration_tables(db_path)
    now = utc_now()
    ext_id = "ext_" + _fingerprint({"platform": platform, "handle": handle})[:24]
    with connect(_db_file(db_path)) as db:
        with immediate(db):
            existing = db.execute("SELECT * FROM external_accounts WHERE platform=? AND handle=?",
                                  (platform, handle)).fetchone()
            if existing:
                return dict(existing)
            db.execute(
                "INSERT INTO external_accounts(id,account_id,platform,handle,display_name,"
                "profile_url,session_status,meta_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?, 'none','{}',?,?)",
                (ext_id, account_id, platform, handle, display_name, profile_url, now, now))
            row = db.execute("SELECT * FROM external_accounts WHERE id=?", (ext_id,)).fetchone()
            return dict(row)


def get_external_account(db_path, external_account_id: str) -> dict:
    with connect(_db_file(db_path)) as db:
        row = db.execute("SELECT * FROM external_accounts WHERE id=?", (external_account_id,)).fetchone()
    if row is None:
        raise KeyError(external_account_id)
    return dict(row)


def list_external_accounts(db_path, account_id: str | None = None) -> list[dict]:
    ensure_integration_tables(db_path)
    with connect(_db_file(db_path)) as db:
        if account_id:
            rows = db.execute("SELECT * FROM external_accounts WHERE account_id=? ORDER BY created_at",
                              (account_id,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM external_accounts ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


def set_session_state(db_path, external_account_id: str, *, status: str,
                      session_ref: str | None = None, fingerprint: str | None = None) -> dict:
    with connect(_db_file(db_path)) as db:
        with immediate(db):
            db.execute(
                "UPDATE external_accounts SET session_status=?, session_ref=COALESCE(?,session_ref), "
                "session_fingerprint=COALESCE(?,session_fingerprint), updated_at=? WHERE id=?",
                (status, session_ref, fingerprint, utc_now(), external_account_id))
            row = db.execute("SELECT * FROM external_accounts WHERE id=?", (external_account_id,)).fetchone()
    if row is None:
        raise KeyError(external_account_id)
    return dict(row)


def upsert_imported_videos(db_path, external_account_id: str, videos: list[dict],
                           source: str) -> list[dict]:
    """幂等导入：同 (账号, 平台作品 ID) 不重复；返回新增行。"""
    ensure_integration_tables(db_path)
    now = utc_now()
    inserted = []
    with connect(_db_file(db_path)) as db:
        with immediate(db):
            for video in videos:
                raw_hash = _fingerprint(video)
                vid = "vid_" + _fingerprint({"account": external_account_id,
                                             "pid": video["platform_video_id"]})[:24]
                existing = db.execute(
                    "SELECT id FROM imported_videos WHERE external_account_id=? AND platform_video_id=?",
                    (external_account_id, video["platform_video_id"])).fetchone()
                if existing:
                    continue
                db.execute(
                    "INSERT INTO imported_videos(id,external_account_id,platform_video_id,title,"
                    "published_at,plays,likes,comments,shares,favorites,top_comments_json,source,"
                    "raw_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (vid, external_account_id, video["platform_video_id"], video.get("title", ""),
                     video.get("published_at"), video.get("plays"), video.get("likes"),
                     video.get("comments"), video.get("shares"), video.get("favorites"),
                     json.dumps(video.get("top_comments", []), ensure_ascii=False),
                     source, raw_hash, now))
                inserted.append({"id": vid, **video})
            if inserted:
                rows = db.execute(
                    "SELECT plays FROM imported_videos WHERE external_account_id=? "
                    "AND plays IS NOT NULL ORDER BY plays", (external_account_id,)).fetchall()
                plays = [r["plays"] for r in rows]
                median = plays[len(plays) // 2] if plays else None
                total = db.execute(
                    "SELECT COUNT(*) AS n FROM imported_videos WHERE external_account_id=?",
                    (external_account_id,)).fetchone()["n"]
                db.execute(
                    "UPDATE external_accounts SET imported_count=?, "
                    "baseline_plays=CASE WHEN ? IS NOT NULL THEN ? ELSE baseline_plays END, "
                    "updated_at=? WHERE id=?",
                    (total, median, median, utc_now(), external_account_id))
    return inserted


def list_imported_videos(db_path, external_account_id: str) -> list[dict]:
    with connect(_db_file(db_path)) as db:
        rows = db.execute(
            "SELECT * FROM imported_videos WHERE external_account_id=? ORDER BY published_at DESC, id",
            (external_account_id,)).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["top_comments"] = json.loads(item.pop("top_comments_json") or "[]")
        out.append(item)
    return out
