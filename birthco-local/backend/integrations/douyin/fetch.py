"""创作者中心作品抓取与归一化（douyin-session）。

接口形状可能随平台变化：normalize_* 以夹具测试保证字段归一正确；
抓取层失败给出明确错误并建议 manual 通道，绝不伪造数据。
"""
from __future__ import annotations

from datetime import datetime, timezone

from backend.integrations.types import PerfVideo

WORKS_API = ("https://creator.douyin.com/web/api/media/aweme/post/"
             "?status=&count={count}&cursor={cursor}")


class FetchError(RuntimeError):
    """抓取失败（会话失效/接口变化/网络）。不产生任何半截数据。"""


def normalize_work(item: dict) -> PerfVideo:
    """创作者中心作品条目 → PerfVideo（字段名兼容常见变体）。"""
    stats = item.get("statistics") or item.get("stats") or {}
    video_id = str(item.get("aweme_id") or item.get("item_id") or item.get("id") or "")
    if not video_id:
        raise FetchError("work item missing platform video id")
    created = item.get("create_time") or item.get("publish_time")
    published_at = None
    if isinstance(created, (int, float)):
        published_at = datetime.fromtimestamp(created, tz=timezone.utc).isoformat()
    elif isinstance(created, str):
        published_at = created[:40] or None
    return PerfVideo.model_validate({
        "platform_video_id": video_id,
        "title": (item.get("desc") or item.get("title") or "")[:200],
        "published_at": published_at,
        "plays": _count(stats, "play_count", "view_count"),
        "likes": _count(stats, "digg_count", "like_count"),
        "comments": _count(stats, "comment_count"),
        "shares": _count(stats, "share_count"),
        "favorites": _count(stats, "collect_count", "favorite_count"),
        "top_comments": [],
        "source_ref": f"douyin:{video_id}",
    })


def _count(stats: dict, *keys: str) -> int | None:
    for key in keys:
        value = stats.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


def normalize_comments(payload: dict, video_id: str) -> list[dict]:
    """评论条目 → top 评论（按点赞数排序取前 20）。"""
    raw = payload.get("comments") or payload.get("data") or []
    comments = []
    for item in raw:
        text = (item.get("text") or item.get("content") or "")[:1000]
        likes = item.get("digg_count") or item.get("like_count") or 0
        if text and isinstance(likes, int) and likes >= 0:
            comments.append({"text": text, "likes": likes})
    comments.sort(key=lambda c: c["likes"], reverse=True)
    return comments[:20]


def fetch_recent_works(external_account_id: str, *, count: int = 10,
                       with_comments: bool = True) -> list[PerfVideo]:
    """用已登录会话抓取最近 count 条作品（含 top 评论）。"""
    from backend.integrations.douyin import session as douyin_session  # noqa: PLC0415

    if not 1 <= count <= 50:
        raise FetchError("count must be between 1 and 50")
    state = douyin_session.load_session(douyin_session.session_paths(external_account_id))
    if not state:
        raise FetchError("会话不存在或未登录；请先 login 或使用 manual 通道")
    sync_playwright = douyin_session._playwright()
    works: list[PerfVideo] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(storage_state=str(douyin_session.session_paths(external_account_id)))
            page = context.new_page()
            page.goto("https://creator.douyin.com/creator-micro/content/manage",
                      wait_until="domcontentloaded")
            cursor = 0
            while len(works) < count:
                url = WORKS_API.format(count=min(20, count - len(works)), cursor=cursor)
                raw = page.evaluate("async (url) => (await (await fetch(url)).json())", url)
                aweme_list = raw.get("aweme_list") or raw.get("data") or []
                if not aweme_list:
                    break
                for item in aweme_list:
                    video = normalize_work(item)
                    if with_comments:
                        try:
                            comments_raw = page.evaluate(
                                "async (id) => (await (await fetch("
                                "'/web/api/comment/list/?item_id='+id+'&count=20')).json())",
                                video.platform_video_id)
                            comments = normalize_comments(comments_raw, video.platform_video_id)
                            video = video.model_copy(update={"top_comments": comments})
                        except Exception:
                            pass  # 评论抓取失败不阻断作品数据（记录为空）
                    works.append(video)
                    if len(works) >= count:
                        break
                if not raw.get("has_more") and not aweme_list:
                    break
                cursor = raw.get("cursor") or (cursor + len(aweme_list))
                if not raw.get("has_more"):
                    break
            browser.close()
    except FetchError:
        raise
    except Exception as exc:
        raise FetchError(f"抓取失败：{exc}；可改用 manual 通道导入") from exc
    return works
