"""小红书创作服务平台笔记抓取与归一化（xiaohongshu-session）。

字段归一约定（与 PerfVideo 对齐）：
  plays=view/read 阅读或观看、likes=点赞、comments=评论、shares=分享、
  favorites=收藏（小红书核心指标）。normalize_* 以夹具测试锁定；抓取失败
  明确指向 manual 通道，绝不伪造数据。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from backend.integrations.types import PerfVideo

NOTES_API = ("https://creator.xiaohongshu.com/api/galaxy/user/posted?"
             "page=1&page_size={count}&sort=created_desc")


class FetchError(RuntimeError):
    """抓取失败（会话失效/接口变化/网络）。不产生任何半截数据。"""


def normalize_note(item: dict) -> PerfVideo:
    """创作服务平台笔记条目 → PerfVideo（兼容常见字段变体）。"""
    stats = item.get("interact_info") or item.get("stat") or item.get("note_stats") or {}
    note_id = str(item.get("note_id") or item.get("id") or item.get("oid") or "")
    if not note_id:
        raise FetchError("note item missing platform video id")
    created = item.get("create_time") or item.get("time") or item.get("publish_time")
    published_at = None
    if isinstance(created, (int, float)):
        # 小红书部分接口用毫秒时间戳
        ts = created / 1000 if created > 10 ** 11 else created
        published_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    elif isinstance(created, str):
        published_at = created[:40] or None
    return PerfVideo.model_validate({
        "platform_video_id": note_id,
        "title": (item.get("display_title") or item.get("title") or item.get("desc") or "")[:200],
        "published_at": published_at,
        "plays": _count(stats, "view_count", "read_count", "impression_count"),
        "likes": _count(stats, "liked_count", "like_count", "digg_count"),
        "comments": _count(stats, "comment_count"),
        "shares": _count(stats, "share_count"),
        "favorites": _count(stats, "collected_count", "collect_count", "favorite_count"),
        "top_comments": [],
        "source_ref": f"xiaohongshu:{note_id}",
    })


def _count(stats: dict, *keys: str) -> int | None:
    for key in keys:
        value = stats.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


def normalize_comments(payload: dict, note_id: str) -> list[dict]:
    """评论条目 → top 评论（按点赞数排序取前 20）。"""
    raw = payload.get("comments") or payload.get("data") or []
    comments = []
    for item in raw:
        text = (item.get("content") or item.get("text") or "")[:1000]
        likes = item.get("like_count") or item.get("liked_count") or 0
        if text and isinstance(likes, int) and likes >= 0:
            comments.append({"text": text, "likes": likes})
    comments.sort(key=lambda c: c["likes"], reverse=True)
    return comments[:20]


def _extract_notes(raw) -> list:
    """兼容平台接口返回形态：data 可能是对象、列表或二次编码的 JSON 字符串。"""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError as exc:
            raise FetchError(f"接口返回非 JSON（{raw[:80]!r}）；平台接口可能已变化") from exc
    if not isinstance(raw, dict):
        raise FetchError(f"接口返回结构异常（{type(raw).__name__}）；平台接口可能已变化")
    if raw.get("success") is False:
        raise FetchError(f"接口返回失败：{raw.get('msg') or raw.get('message') or raw}；"
                         "请重新登录或改用 manual 通道")
    data = raw.get("data")
    if data is None:
        data = raw.get("notes") or raw.get("list") or raw.get("items") or []
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError as exc:
            # 常见于未登录/风控时返回提示字符串
            raise FetchError(f"接口返回数据异常（{data[:80]!r}）；请重新登录或改用 manual 通道") from exc
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [item for item in (data.get("notes") or data.get("list")
                                  or data.get("items") or []) if isinstance(item, dict)]
    raise FetchError(f"接口返回数据异常（{type(data).__name__}）；平台接口可能已变化")


def fetch_recent_works(external_account_id: str, *, count: int = 10,
                       with_comments: bool = True) -> list[PerfVideo]:
    """用已登录会话抓取最近 count 条笔记（含 top 评论）。"""
    from backend.integrations.xiaohongshu import session as xhs_session  # noqa: PLC0415

    if not 1 <= count <= 50:
        raise FetchError("count must be between 1 and 50")
    state = xhs_session.load_session(xhs_session.session_paths(external_account_id))
    if not state:
        raise FetchError("会话不存在或未登录；请先 login 或使用 manual 通道")
    sync_playwright = xhs_session._playwright()
    works: list[PerfVideo] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, channel="chromium")
            context = browser.new_context(
                storage_state=str(xhs_session.session_paths(external_account_id)))
            page = context.new_page()
            page.goto("https://creator.xiaohongshu.com/publish/publish-manage",
                      wait_until="domcontentloaded")
            raw = page.evaluate(
                "async (url) => (await (await fetch(url)).json())",
                NOTES_API.format(count=min(50, count)))
            items = _extract_notes(raw)
            for item in items:
                video = normalize_note(item)
                if with_comments:
                    try:
                        comments_raw = page.evaluate(
                            "async (id) => (await (await fetch("
                            "'/api/comment/page?note_id='+id+'&page_size=20')).json())",
                            video.platform_video_id)
                        comments = normalize_comments(comments_raw, video.platform_video_id)
                        video = video.model_copy(update={"top_comments": comments})
                    except Exception:
                        pass  # 评论抓取失败不阻断笔记数据
                works.append(video)
                if len(works) >= count:
                    break
            browser.close()
    except FetchError:
        raise
    except Exception as exc:
        raise FetchError(f"抓取失败：{exc}；可改用 manual 通道导入") from exc
    return works
