"""Playwright 扫码会话管理（xiaohongshu-session）。凭据只落受限本地目录。"""
from __future__ import annotations

from pathlib import Path

from backend.integrations.browser_session import (
    load_session, save_session, session_fingerprint, session_path as session_paths,
)

CREATOR_URL = "https://creator.xiaohongshu.com/"
LOGIN_WAIT_SECONDS = 600  # 扫码/验证码登录给人留足时间，到点前窗口不关


class PlaywrightNotInstalled(RuntimeError):
    """未安装 playwright：给出安装指引，不影响 manual 通道。"""


def _playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - 环境相关
        raise PlaywrightNotInstalled(
            "未安装 playwright。安装：python -m pip install playwright && "
            "python -m playwright install chromium；或改用 manual 导入通道"
        ) from exc
    return sync_playwright


def _launch_browser(pw, *, headless: bool = False):
    """登录优先用系统真实 Chrome/Edge（平台风控对自动化浏览器更不友好），
    未安装则回退 Playwright Chromium。"""
    last_error: Exception | None = None
    for channel in ("chrome", "msedge", "chromium"):
        try:
            return pw.chromium.launch(headless=headless, channel=channel)
        except Exception as exc:  # 缺该发行版则试下一个
            last_error = exc
    raise PlaywrightNotInstalled(
        f"无可用浏览器（chrome/msedge/chromium 均启动失败）：{last_error}")


def login_interactive(external_account_id: str, *, headless: bool = False,
                      session_file: Path | None = None) -> Path:
    """打开小红书创作服务平台登录页，扫码登录成功后保存 storage_state。

    判定标准：posted 接口 success=true，或（兜底）页面已渲染且不再是登录页
    （无短信登录/扫码登录表单）——避免在扫码生效前提前保存半截会话。
    """
    sync_playwright = _playwright()
    target = session_file or session_paths(external_account_id)
    with sync_playwright() as pw:
        browser = _launch_browser(pw, headless=headless)
        context = browser.new_context(accept_downloads=False)
        page = context.new_page()
        page.goto(CREATOR_URL, wait_until="domcontentloaded")
        try:
            page.wait_for_function(
                r"""async () => {
                    try {
                        const response = await fetch(
                            '/api/galaxy/user/posted?page=1&page_size=1&sort=created_desc',
                            { signal: AbortSignal.timeout(5000) });
                        const payload = await response.json();
                        if (payload && payload.success === true) return true;
                    } catch (err) { /* 接口不可用时看页面信号 */ }
                    const text = (document.body && document.body.innerText) || '';
                    return location.origin === 'https://creator.xiaohongshu.com'
                        && !location.pathname.includes('login')
                        && !/短信登录|扫码登录|登\s+录/.test(text)
                        && /笔记管理|作品管理/.test(text);
                }""",
                timeout=LOGIN_WAIT_SECONDS * 1000)
        except Exception as exc:
            browser.close()
            raise RuntimeError(
                f"登录等待超时：请在 {LOGIN_WAIT_SECONDS // 60} 分钟内完成扫码/验证码登录；"
                "若页面被平台弹回登录页，请重试或改用 manual 通道") from exc
        # 登录跳转/下发 cookie 可能异步进行，稍等再存，避免存下过渡态
        page.wait_for_timeout(2500)
        save_session(context, target)
        browser.close()
    return target


def verify_session(external_account_id: str) -> bool:
    """用已有 storage_state 打开创作者平台，未跳登录页即认为会话有效。"""
    path = session_paths(external_account_id)
    state = load_session(path)
    if not state:
        return False
    sync_playwright = _playwright()
    with sync_playwright() as pw:
        browser = _launch_browser(pw, headless=True)
        context = browser.new_context(storage_state=state)
        page = context.new_page()
        try:
            page.goto(CREATOR_URL, wait_until="domcontentloaded")
            page.wait_for_function(
                "() => !location.pathname.includes('login')", timeout=15000)
            return True
        except Exception:
            return False
        finally:
            browser.close()
