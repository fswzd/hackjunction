"""小红书创作服务平台笔记抓取与归一化（xiaohongshu-session）。

字段归一约定（与 PerfVideo 对齐）：
  plays=view/read 阅读或观看、likes=点赞、comments=评论、shares=分享、
  favorites=收藏（小红书核心指标）。normalize_* 以夹具测试锁定；抓取失败
  明确指向 manual 通道，绝不伪造数据。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlsplit

from backend.integrations.browser_session import read_json, save_session
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
    if raw.get("success") is False or raw.get("code") not in (None, 0, "0"):
        message = raw.get("msg") or raw.get("message") or ""
        if raw.get("code") in (401, "401") or (isinstance(message, str) and any(
                term in message for term in ("未登录", "登录过期", "登录已过期"))):
            raise FetchError("小红书登录已过期，请重新授权。")
        raise FetchError("小红书未返回可读取的笔记列表，请稍后重试。")
    data = raw.get("data")
    if data is None:
        data = raw
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError as exc:
            raise FetchError("小红书返回的笔记数据格式异常。") from exc
    if isinstance(data, dict):
        data = next((data[key] for key in ("notes", "list", "items") if key in data), None)
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise FetchError("未识别到小红书笔记列表。")
    return data


def _fetch_plain(path, state, count: int, with_comments: bool) -> list[PerfVideo]:
    """通道 A：会话 cookie + 裸 fetch 直连平台接口。"""
    from backend.integrations.xiaohongshu import session as xhs_session  # noqa: PLC0415

    sync_playwright = xhs_session._playwright()
    works: list[PerfVideo] = []
    with sync_playwright() as pw:
        browser = xhs_session._launch_browser(pw, headless=True)
        context = browser.new_context(storage_state=state)
        page = context.new_page()
        page.goto("https://creator.xiaohongshu.com/publish/publish-manage",
                  wait_until="domcontentloaded")
        if "/login" in page.url:
            raise FetchError("小红书登录已过期，请重新授权。")
        raw = read_json(page, NOTES_API.format(count=count))
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
        save_session(context, path)
        browser.close()
    return works


def _intercept_notes(path, state, count: int) -> list[dict]:
    """通道 B：裸 fetch 被拒（缺签名/接口变化）时，收平台页面自带请求的响应。

    页面自己的 JS 会带全签名头请求笔记列表，我们只旁听它拿到的 JSON，
    不伪造任何签名，也不碰写操作。
    """
    from backend.integrations.xiaohongshu import session as xhs_session  # noqa: PLC0415

    sync_playwright = xhs_session._playwright()
    captured: list = []
    with sync_playwright() as pw:
        browser = xhs_session._launch_browser(pw, headless=True)
        context = browser.new_context(storage_state=state)
        page = context.new_page()

        def on_response(response):
            location = urlsplit(response.url)
            if (location.hostname != "creator.xiaohongshu.com" or not response.ok
                    or not location.path.startswith("/api/")
                    or not any(key in location.path for key in ("user/posted", "note/list", "note/manage"))):
                return
            try:
                captured.append(response.json())
            except Exception:
                pass

        page.on("response", on_response)
        page.goto("https://creator.xiaohongshu.com/", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        hrefs = page.evaluate(
            """() => Array.from(document.querySelectorAll('a'))
                .map(a => a.getAttribute('href') || '')
                .filter(h => h && /publish|manage|note|content/i.test(h))""")
        candidates = ["/publish/publish-manage", "/publish/publish-manage/note",
                      "/new/note-manager", "/publish/manage", "/content-manage"]
        for href in list(dict.fromkeys(list(hrefs) + candidates))[:8]:
            target = href if href.startswith("/") else "/" + href
            try:
                page.goto("https://creator.xiaohongshu.com" + target,
                          wait_until="domcontentloaded")
                page.wait_for_timeout(4000)
            except Exception:
                continue
            for payload in captured:
                try:
                    items = _extract_notes(payload)
                except FetchError:
                    continue
                if items or isinstance(payload, dict) and payload.get('success') is True:
                    save_session(context, path)
                    browser.close()
                    return items[:count]
        browser.close()
    raise FetchError("未能从平台页面捕获笔记列表（路由/接口已变化）；请改用 manual 通道")


def fetch_recent_works(external_account_id: str, *, count: int = 10,
                       with_comments: bool = True, session_file=None) -> list[PerfVideo]:
    """用已登录会话抓取最近 count 条笔记（含 top 评论）。

    双通道：先裸 fetch；被拒则旁听平台页面自带的签名请求兜底。
    两通道都不通时给出可操作错误，绝不伪造数据。
    """
    from backend.integrations.xiaohongshu import session as xhs_session  # noqa: PLC0415

    if not 1 <= count <= 50:
        raise FetchError("count must be between 1 and 50")
    path = session_file or xhs_session.session_paths(external_account_id)
    state = xhs_session.load_session(path)
    if not state:
        raise FetchError("会话不存在或未登录；请先 login 或使用 manual 通道")
    try:
        return _fetch_plain(path, state, count, with_comments)
    except Exception as plain_error:
        if '登录已过期' in str(plain_error):
            raise FetchError(str(plain_error)) from plain_error
        try:
            items = _intercept_notes(path, state, count)
        except Exception as intercept_error:
            raise FetchError(f"{plain_error}；页面捕获兜底：{intercept_error}") from intercept_error
        works = [normalize_note(item) for item in items]
        return works[:count]
