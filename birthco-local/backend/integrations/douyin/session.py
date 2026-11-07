"""Playwright 扫码会话管理（douyin-session）。凭据只落受限本地目录。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

CREATOR_URL = "https://creator.douyin.com/"
LOGIN_WAIT_SECONDS = 600  # 扫码登录给人留足时间，到点前窗口不关


def session_dir() -> Path:
    root = Path(os.environ.get("BIRTHCO_SESSION_DIR")
                or Path(__file__).resolve().parents[3] / "data" / "sessions")
    root.mkdir(parents=True, exist_ok=True)
    return root


def session_paths(external_account_id: str) -> Path:
    return session_dir() / f"{external_account_id}.storage_state.json"


def session_fingerprint(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_session(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


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


def login_interactive(external_account_id: str, *, headless: bool = False) -> Path:
    """打开创作者中心登录页，等待扫码登录成功后保存 storage_state。

    交互式：需要用户用抖音 App 扫码；登录成功（进入创作者中心）即保存退出。
    """
    sync_playwright = _playwright()
    target = session_paths(external_account_id)
    with sync_playwright() as pw:
        browser = _launch_browser(pw, headless=headless)
        context = browser.new_context(accept_downloads=False)
        page = context.new_page()
        page.goto(CREATOR_URL, wait_until="domcontentloaded")
        try:
            # 等待扫码完成：创作者中心登录后会出现工作台/内容管理入口
            page.wait_for_url("**/creator-micro/**", timeout=LOGIN_WAIT_SECONDS * 1000)
        except Exception as exc:
            browser.close()
            raise RuntimeError(
                f"登录等待超时：请在 {LOGIN_WAIT_SECONDS // 60} 分钟内完成扫码登录；"
                "若页面被平台弹回登录页，请重试或改用 manual 通道") from exc
        context.storage_state(path=str(target))
        browser.close()
    return target


def verify_session(external_account_id: str) -> bool:
    """用已有 storage_state 打开创作者中心，能进入工作台即认为会话有效。"""
    path = session_paths(external_account_id)
    state = load_session(path)
    if not state:
        return False
    sync_playwright = _playwright()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, channel="chromium")
        context = browser.new_context(storage_state=str(path))
        page = context.new_page()
        try:
            page.goto(CREATOR_URL, wait_until="domcontentloaded")
            page.wait_for_url("**/creator-micro/**", timeout=15000)
            return True
        except Exception:
            return False
        finally:
            browser.close()
