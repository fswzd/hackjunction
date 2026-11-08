"""One-click desktop launcher for the 众幕 AI workbench.

Starts the loopback Flask API, the durable worker and the static+proxy
workbench server, then opens a chromeless Edge/Chrome app window. All state
lives under this folder; nothing is installed system-wide and nothing needs
administrator approval.

Usage:
    pythonw.exe desktop/launch.py           # normal desktop launch
    python desktop/launch.py --no-window   # services only (diagnostics)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = Path(__file__).resolve().parent
BC = ROOT / "birthco-local"
RUN_DIR = ROOT / ".run"
DATA_DIR = ROOT / "birthco-local" / "data"
VENV = ROOT / ".venv"
REQUIREMENTS = BC / "requirements-dev.lock"
API_PORT = int(os.environ.get("BIRTHCO_PORT", "5210"))
WEB_PORT = int(os.environ.get("BIRTHCO_FRONTEND_PORT", "4273"))
MODEL_MODE = os.environ.get("BIRTHCO_MODEL_MODE", "mock")

WINDOWS = os.name == "nt"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Detach child services from the launcher's console/job so they keep running
# after this script exits (double-clicking the .vbs must not be required to
# stay resident). CREATE_BREAKAWAY_FROM_JOB may be refused by a restrictive
# parent job, so spawn() retries with progressively simpler flag sets.
BREAKAWAY = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
DETACHED = (getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))

# Loopback probes must never go through HTTP_PROXY/HTTPS_PROXY. Some desktop
# environments inject a system proxy (Clash, WorkBuddy, corporate agents) that
# answers 502 "upstream connect failed" for 127.0.0.1 and would make a healthy
# local app look broken. External model calls still use the configured proxy.
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_LOOPBACK_NO_PROXY = "127.0.0.1,localhost,::1"


def log(message: str) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    with (RUN_DIR / "desktop.log").open("a", encoding="utf-8") as stream:
        stream.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")


def url() -> str:
    return f"http://127.0.0.1:{WEB_PORT}/"


def python_exe() -> str:
    if VENV.exists():
        candidate = VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def ensure_venv() -> str:
    exe = python_exe()
    if VENV.exists():
        return exe
    log("creating local virtual environment (first launch only)")
    subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    exe = python_exe()
    subprocess.run([exe, "-m", "pip", "install", "--disable-pip-version-check",
                    "-q", "-r", str(REQUIREMENTS)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return exe


def ensure_deps(exe: str) -> None:
    probe = subprocess.run([exe, "-c", "import flask, httpx, pydantic"],
                           capture_output=True)
    if probe.returncode == 0:
        return
    log("installing Python dependencies (first launch only)")
    subprocess.run([exe, "-m", "pip", "install", "--disable-pip-version-check",
                    "-q", "-r", str(REQUIREMENTS)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def port_open(port: int) -> bool:
    probe = socket.socket()
    probe.settimeout(0.3)
    try:
        return probe.connect_ex(("127.0.0.1", port)) == 0
    finally:
        probe.close()


def _direct_json(address: str, timeout: float = 1.5):
    """GET a loopback URL without any proxy; return parsed JSON or None."""
    try:
        with _DIRECT.open(address, timeout=timeout) as response:
            if response.status != 200:
                return None
            return json.loads(response.read())
    except Exception:
        return None


def health() -> bool:
    body = _direct_json(f"http://127.0.0.1:{API_PORT}/api/v1/health")
    return bool(body and body.get("data", {}).get("status") == "ok")


def web_health(port: int | None = None) -> bool:
    """Verify the web port belongs to THIS app, not a stale Vite/Clash proxy."""
    target = WEB_PORT if port is None else port
    body = _direct_json(f"http://127.0.0.1:{target}/__desktop/ping", timeout=1.0)
    return bool(body and body.get("app") == "zhongmu-desktop")


def wait_health(seconds: float = 40.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if health():
            return True
        time.sleep(0.4)
    return False


def wait_web(seconds: float = 30.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if web_health():
            return True
        time.sleep(0.3)
    return False


def choose_web_port() -> int:
    """Reuse our own server, otherwise pick the first free port near 4273."""
    global WEB_PORT
    base = WEB_PORT
    for candidate in range(base, base + 20):
        if web_health(candidate):
            WEB_PORT = candidate
            log(f"reusing existing workbench server on port {candidate}")
            return candidate
        if not port_open(candidate):
            WEB_PORT = candidate
            if candidate != base:
                log(f"port {base} occupied by another program; using {candidate}")
            return candidate
    raise SystemExit(f"端口 {base}~{base + 19} 都被占用，请设置 BIRTHCO_FRONTEND_PORT 后重试。")


def env() -> dict[str, str]:
    value = dict(os.environ)
    value.update({
        "BIRTHCO_PORT": str(API_PORT),
        "BIRTHCO_FRONTEND_PORT": str(WEB_PORT),
        "BIRTHCO_DATA_DIR": str(DATA_DIR),
        "BIRTHCO_MODEL_MODE": MODEL_MODE,
        "BIRTHCO_HOST": "127.0.0.1",
        "VITE_DATA_MODE": "api",
        "NO_PROXY": _LOOPBACK_NO_PROXY,
        "no_proxy": _LOOPBACK_NO_PROXY,
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
    })
    return value


def spawn(exe: str, args: list[str], cwd: Path, name: str) -> int:
    out = (RUN_DIR / f"{name}.log").open("ab", buffering=0)
    err = (RUN_DIR / f"{name}.err.log").open("ab", buffering=0)
    flag_sets = ([DETACHED | BREAKAWAY, DETACHED, NO_WINDOW] if WINDOWS else [0])
    process = None
    for flags in flag_sets:
        try:
            process = subprocess.Popen([exe, *args], cwd=str(cwd), env=env(),
                                       stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                       creationflags=flags, close_fds=True)
            break
        except OSError:
            continue
    if process is None:
        raise SystemExit(f"无法启动 {name} 服务进程。")
    (RUN_DIR / f"{name}.pid").write_text(str(process.pid), encoding="ascii")
    return process.pid


def browser() -> str | None:
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which("msedge") or shutil.which("chrome")


def open_window() -> None:
    exe = browser()
    profile = RUN_DIR / "browser-profile"
    if exe:
        args = [exe, f"--app={url()}", "--window-size=1440,920", "--no-first-run",
                "--no-default-browser-check", f"--user-data-dir={profile}",
                "--no-proxy-server", "--disable-features=msEdgeIdentityFRE"]
        try:
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=NO_WINDOW if WINDOWS else 0, close_fds=True)
            log(f"opened app window with {Path(exe).name}")
            return
        except OSError as exc:
            log(f"browser launch failed: {exc}")
    if WINDOWS:
        os.startfile(url())  # noqa: S606 - local loopback URL only
    else:
        import webbrowser
        webbrowser.open(url())
    log("opened default browser")


def check_writable() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    probe = DATA_DIR / ".write-test"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise SystemExit(f"数据目录不可写：{DATA_DIR}\n{exc}\n请把应用放到有写权限的目录（例如桌面）再启动。")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-window", action="store_true", help="only start services")
    args = parser.parse_args()

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    check_writable()
    exe = ensure_venv()
    ensure_deps(exe)

    api_ready = health()
    if api_ready and web_health():
        log(f"services already running; reusing them at {url()}")
    else:
        if port_open(API_PORT) and not api_ready:
            raise SystemExit(f"端口 {API_PORT} 被其他程序占用（不是本应用）。请先关闭它，或设置 BIRTHCO_PORT。")

        if not api_ready:
            log("migrating database")
            result = subprocess.run([exe, "-m", "backend.manage", "migrate",
                                     "--data-dir", str(DATA_DIR)],
                                    cwd=str(BC), env=env(), capture_output=True)
            if result.returncode != 0:
                # bytes + tolerant decode: Chinese Windows consoles emit GBK,
                # strict UTF-8 decoding would crash the launcher instead of
                # reporting the real migration failure.
                detail = (result.stderr or b"").decode("utf-8", errors="replace")
                log("migrate failed: " + detail[-1500:])
                raise SystemExit("数据库迁移失败，详见 .run/desktop.log")
            spawn(exe, ["-m", "backend.app"], BC, "api")
            spawn(exe, ["-m", "backend.manage", "worker", "--data-dir", str(DATA_DIR)], BC, "worker")

        choose_web_port()
        if not web_health():
            spawn(exe, [str(DESKTOP / "server.py")], ROOT, "web")

        if not wait_health():
            log("backend did not become healthy in time")
            raise SystemExit("后端未在 40 秒内就绪，详见 .run/api.err.log")
        if not wait_web():
            log("web server did not become healthy in time")
            raise SystemExit("工作台页面未在 30 秒内就绪，详见 .run/web.err.log")
        log(f"ready: {url()} (api {API_PORT}, mode {MODEL_MODE})")

    if not args.no_window:
        open_window()
    print(f"众幕 AI 工作台已启动：{url()}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit as exc:
        if exc.code not in (0, None):
            log(f"launch aborted: {exc}")
        raise
    except Exception:
        import traceback
        log("launch failed:\n" + traceback.format_exc())
        raise
