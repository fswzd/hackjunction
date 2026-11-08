"""Stop only the processes started by this desktop app (PID-scoped, safe).

PID files are the primary handle, but they can go stale when a crash, a task
manager kill or a sandbox reclaims the launcher. So we also look up the owners
of our two loopback ports and (best effort) scan process command lines for
this app's own directory. Every candidate is verified before it is killed;
unrelated processes are never touched.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / ".run"
NAMES = ("api", "worker", "web")
PORTS = (
    int(os.environ.get("BIRTHCO_PORT", "5210")),
    int(os.environ.get("BIRTHCO_FRONTEND_PORT", "4273")),
)
# A process must name one of our own modules to be considered ours. Matching
# only the install directory would also catch shells/scripts that merely
# mention the path in their arguments.
MARKERS = ("backend.app", "backend.manage", "desktop\\server.py",
           "desktop\\launch.py", "desktop\\stop.py")


def log_line(message: str) -> None:
    with (RUN_DIR / "desktop.log").open("a", encoding="utf-8") as stream:
        stream.write(message + "\n")


def output_text(result: subprocess.CompletedProcess) -> str:
    """Decode Windows console output safely.

    netstat / PowerShell emit the local ANSI code page (GBK on Chinese
    Windows), so UTF-8 strict decoding blows up. All tokens we care about
    (LISTENING, port numbers, PIDs, module names) are ASCII, hence replacing
    undecodable bytes is both safe and lossless for our purposes.
    """
    raw = result.stdout or b""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def belongs_to_app(pid: int) -> bool:
    """Never kill an unrelated process that happens to reuse a stale PID."""
    if os.name != "nt":
        return True
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine"],
            capture_output=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    low = output_text(result).lower()
    if not any(marker in low for marker in MARKERS):
        return False
    return str(ROOT).lower() in low or ".venv\\scripts\\python" in low


def listening_pids() -> set[int]:
    """Owners of our two loopback ports (authoritative even with stale PIDs)."""
    try:
        result = subprocess.run(["netstat", "-ano", "-p", "tcp"],
                                capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return set()
    found: set[int] = set()
    for line in output_text(result).splitlines():
        if "LISTENING" not in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        local = parts[1]
        if ":" not in local or not parts[-1].isdigit():
            continue
        try:
            port = int(local.rsplit(":", 1)[-1])
        except ValueError:
            continue
        if port in PORTS:
            found.add(int(parts[-1]))
    return found


def app_pids() -> set[int]:
    """Best-effort scan for python processes whose command line names this app."""
    if os.name != "nt":
        return set()
    marker = str(ROOT).replace("'", "''")
    conditions = " -or ".join(
        f"$_.CommandLine -like '*{item}*'" for item in MARKERS
    )
    script = (
        "Get-CimInstance Win32_Process -Filter "
        "\"Name='python.exe' OR Name='pythonw.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{marker}*' -and ({conditions}) }} | "
        "Select-Object -ExpandProperty ProcessId"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    return {int(token) for token in output_text(result).split()
            if token.strip().isdigit()}


def main() -> int:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    candidates: set[int] = set()
    for name in NAMES:
        pid_file = RUN_DIR / f"{name}.pid"
        if not pid_file.is_file():
            continue
        try:
            candidates.add(int(pid_file.read_text(encoding="ascii").strip()))
        except (ValueError, OSError):
            pass
        pid_file.unlink(missing_ok=True)

    port_owners = listening_pids()
    scanned = app_pids()
    candidates |= port_owners | scanned
    # If stop.py itself was invoked with an absolute path, its command line
    # also contains ROOT. Never terminate the stopper mid-run.
    candidates.discard(os.getpid())

    stopped = []
    for pid in sorted(candidates):
        # Port owners are unambiguous (the ports belong to this app); anything
        # else must additionally pass the command-line ownership check.
        if pid not in port_owners and pid not in scanned and not belongs_to_app(pid):
            continue
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            try:
                os.kill(pid, 15)
            except ProcessLookupError:
                pass
        stopped.append(str(pid))

    message = ("已停止：" + "、".join(stopped) if stopped
               else "桌面应用当前未在运行。")
    print(message)
    log_line(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
