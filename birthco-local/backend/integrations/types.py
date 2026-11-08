"""Integration DTOs（严格校验，禁止未知字段）。"""
from __future__ import annotations

from pydantic import Field

from backend.domain.schemas import Model

PLATFORMS = ("douyin", "xiaohongshu")
SESSION_STATUSES = ("none", "pending_adapter_setup", "logging_in", "logged_in", "expired")


class TopComment(Model):
    text: str = Field(min_length=1, max_length=1000)
    likes: int = Field(default=0, ge=0)


class PerfVideo(Model):
    """一条已发作品的实绩数据（adapter 与 manual 共用的归一化记录）。"""
    platform_video_id: str = Field(min_length=1, max_length=64)
    title: str = Field(default="", max_length=200)
    published_at: str | None = Field(default=None, max_length=40)
    plays: int | None = Field(default=None, ge=0)
    likes: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)
    favorites: int | None = Field(default=None, ge=0)
    top_comments: list[TopComment] = Field(default_factory=list, max_length=20)
    source_ref: str | None = Field(default=None, max_length=500)


class ExternalAccountCreate(Model):
    """注册一个已存在的平台账号（不新建账号，只做接入管理）。"""
    account_id: str = Field(min_length=1, max_length=64)   # 绑定本地业务分区
    platform: str = Field(min_length=1, max_length=32)      # douyin | xiaohongshu
    handle: str = Field(min_length=1, max_length=64)        # 抖音号/主页标识
    display_name: str = Field(default="", max_length=64)
    profile_url: str | None = Field(default=None, max_length=500)


class ExternalAccountRead(Model):
    external_account_id: str = Field(min_length=1, max_length=64)
    account_id: str = Field(min_length=1, max_length=64)
    platform: str = Field(min_length=1, max_length=32)
    handle: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=64)
    profile_url: str | None = Field(default=None, max_length=500)
    session_status: str = Field(min_length=1, max_length=32)
    baseline_plays: int | None = Field(default=None, ge=0)
    imported_count: int = Field(default=0, ge=0)
    login_error: str | None = None
    import_error: str | None = None
    last_synced_at: str | None = None
    last_sync_count: int | None = None


class ManualImport(Model):
    source: str = Field(default="manual", max_length=16)     # manual | adapter
    videos: list[PerfVideo] = Field(min_length=1, max_length=200)
