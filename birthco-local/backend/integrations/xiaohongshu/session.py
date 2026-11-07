"""Playwright 扫码会话管理（xiaohongshu-session）。凭据只落受限本地目录。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

CREATOR_URL = "https://creator.xiaohongshu.com/"
LOGIN_WAIT_SECONDS = 180


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


def login_interactive(external_account_id: str, *, headless: bool = False) -> Path:
    """打开小红书创作服务平台登录页，扫码登录成功后保存 storage_state。

    判定标准是平台接口真正认可会话（posted 接口 success=true），
    而不是"页面上有 cookie"——避免在扫码生效前提前保存半截会话。
    """
    sync_playwright = _playwright()
    target = session_paths(external_account_id)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(accept_downloads=False)
        page = context.new_page()
        page.goto(CREATOR_URL, wait_until="domcontentloaded")
        page.wait_for_function(
            """async () => {
                try {
                    const response = await fetch(
                        '/api/galaxy/user/posted?page=1&page_size=1&sort=created_desc');
                    const payload = await response.json();
                    return Boolean(payload && payload.success === true);
                } catch (err) {
                    return false;
                }
            }""",
            timeout=LOGIN_WAIT_SECONDS * 1000)
        context.storage_state(path=str(target))
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
        browser = pw.chromium.launch(headless=True, channel="chromium")
        context = browser.new_context(storage_state=str(path))
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
