#!/usr/bin/env python3
"""run.py — 本地一键启动器（start.ps1 的跨平台 Python 版）。

用法（仓库根执行，Python 3.10+）：

    python run.py                   # 自检依赖 + 迁移 + Flask API(5001) + 前端 Vite(4173)
    python run.py --skip-frontend   # 只起后端 API
    python run.py --skip-api        # 只起前端
    python run.py --data-dir X:\\data
    python run.py --detach          # 后台启动后立即返回（配 stop.ps1 停止）

换新机器"直接 python run.py"即可：缺 Python 依赖自动安装（requirements-dev.lock），
缺 node_modules 自动 npm install（失败自动换国内镜像重试）；起不来时打印
服务日志尾部和可操作提示，而不是让你对着 404 猜。
只使用进程环境变量（BIRTHCO_* / MIMO_* 等），**不读取任何 .env 文件**；
真实模型凭据按"用完即弃"注入进程环境（如 $env:MIMO_API_KEY='…'），不落盘、不入库。
日志与 PID 写入 .run/（api.pid / frontend.pid 与 stop.ps1 约定一致）。
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUN_DIR = ROOT / ".run"
API_DIR = ROOT / "birthco-local"
FRONTEND_DIR = ROOT / "frontend"
REQUIREMENTS = API_DIR / "requirements-dev.lock"
NPM_MIRROR = "https://registry.npmmirror.com"
NODE_DOWNLOAD = "https://nodejs.org/zh-cn （国内镜像 https://npmmirror.com/mirrors/node/）"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="本地一键启动器（迁移 + Flask API + 前端）")
    parser.add_argument("--skip-api", action="store_true", help="不启动 Flask API")
    parser.add_argument("--skip-frontend", action="store_true", help="不启动前端 Vite")
    parser.add_argument("--data-dir", default="", help="数据目录（默认 birthco-local/data）")
    parser.add_argument("--detach", action="store_true", help="后台启动后立即返回")
    return parser


def configure_env(data_dir: str) -> dict[str, str]:
    """只继承进程环境变量；不读取任何 .env 文件（去 Key 化口径）。"""
    env = dict(os.environ)
    env["BIRTHCO_DATA_DIR"] = (data_dir or env.get("BIRTHCO_DATA_DIR")
                               or str(API_DIR / "data"))
    env.setdefault("BIRTHCO_PORT", "5001")
    return env


# ---------- 环境自检：换机器直接跑得起来 ----------

def ensure_python_deps(env: dict[str, str]) -> None:
    try:
        import flask  # noqa: F401
        import pydantic  # noqa: F401
        return
    except ImportError:
        pass
    print(f"[env ] 缺少 Python 依赖，按 {REQUIREMENTS.name} 自动安装…")
    result = subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)],
                            env=env)
    if result.returncode != 0:
        raise SystemExit(
            "[env ] Python 依赖安装失败。手动执行：\n"
            f"      python -m pip install -r {REQUIREMENTS}"
        )


def ensure_node() -> bool:
    """Node/npm 是前端的前提；缺失时明确报缺并允许只跑后端。"""
    if not shutil.which("npm"):
        print("[env ] 未找到 npm，前端无法启动。")
        print(f"      安装 Node.js LTS（18+）：{NODE_DOWNLOAD}")
        print("      安装后重新运行 python run.py；或加 --skip-frontend 只起后端。")
        return False
    node = shutil.which("node")
    if node:
        try:
            version = subprocess.run([node, "--version"], capture_output=True, text=True)
            major = int(version.stdout.strip().lstrip("v").split(".")[0] or 0)
            if major < 18:
                print(f"[env ] Node 版本过低（v{major}，Vite 需要 18+），前端可能起不来。")
                print(f"      升级 Node.js LTS：{NODE_DOWNLOAD}")
        except (ValueError, OSError):
            pass
    return True


def npm_command(args: list[str]) -> list[str]:
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit(f"[env ] 未找到 npm。安装 Node.js LTS：{NODE_DOWNLOAD}")
    if os.name == "nt":
        # 用参数列表交给 cmd.exe：避免「带空格的 npm.cmd 路径」的引号截断坑
        return ["cmd.exe", "/c", npm, *args]
    return [npm, *args]


def npm_install(env: dict[str, str]) -> None:
    print("[fe ] 首次启动：npm install（可能需要几分钟）")
    for label, command in (
        ("默认源", npm_command(["install"])),
        ("国内镜像", npm_command(["install", f"--registry={NPM_MIRROR}"])),
    ):
        result = subprocess.run(command, cwd=str(FRONTEND_DIR), env=env)
        if result.returncode == 0:
            return
        print(f"[fe ] npm install（{label}）失败")
    raise SystemExit(
        "[fe ] npm install 失败。手动执行：\n"
        f"      cd frontend\n"
        f"      npm config set registry {NPM_MIRROR}\n"
        "      npm install"
    )


# ---------- 进程与端口 ----------

def run_migration(env: dict[str, str]) -> None:
    print(f"[db ] migrate --data-dir {env['BIRTHCO_DATA_DIR']}")
    result = subprocess.run([sys.executable, "-m", "backend.manage", "migrate",
                             "--data-dir", env["BIRTHCO_DATA_DIR"]],
                            cwd=str(API_DIR), env=env)
    if result.returncode != 0:
        raise SystemExit("database migrate failed")


def ensure_port_free(port: str | int, name: str) -> None:
    """只认「真有监听」才算占用：刚停的服务会留 TIME_WAIT 连接，bind 探测会误报。"""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.3)
    try:
        if probe.connect_ex(("127.0.0.1", int(port))) == 0:
            raise SystemExit(
                f"[run] 端口 {port} 已被占用（疑似残留 {name} 实例）。\n"
                f"      先停止：.\\stop.ps1  或  taskkill /T /F /PID <占用者>（netstat -ano | findstr :{port} 查 PID）"
            )
    finally:
        probe.close()


def spawn_logged(command: list[str], cwd: Path, log: Path, err_log: Path,
                 env: dict[str, str]) -> subprocess.Popen:
    out = open(log, "wb")
    err = open(err_log, "wb")
    process = subprocess.Popen(command, cwd=str(cwd), env=env,
                               stdout=out, stderr=err)
    process._runpy_handles = (out, err)  # 保持句柄存活到进程结束
    return process


def write_pid(name: str, process: subprocess.Popen) -> None:
    (RUN_DIR / f"{name}.pid").write_text(str(process.pid), encoding="ascii")


def remove_pid(name: str) -> None:
    try:
        (RUN_DIR / f"{name}.pid").unlink()
    except FileNotFoundError:
        pass


def stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def wait_for_port(process: subprocess.Popen, port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(0.3)
        try:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return True
        finally:
            probe.close()
        time.sleep(0.4)
    return False


def dump_log(path: Path, lines: int = 15) -> None:
    try:
        rows = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for row in rows[-lines:]:
        print(f"      | {row}")


def cleanup(services: list[tuple[str, subprocess.Popen, str]]) -> None:
    for name, process, pid_name in services:
        stop_process(process)
        remove_pid(pid_name)
        handles = getattr(process, "_runpy_handles", ())
        for handle in handles:
            handle.close()


# ---------- 主流程 ----------

def main() -> int:
    args = build_parser().parse_args()
    env = configure_env(args.data_dir)
    print(f"[cfg] HOST={env.get('BIRTHCO_HOST', '127.0.0.1')} PORT={env['BIRTHCO_PORT']} "
          f"DATA={env['BIRTHCO_DATA_DIR']} MODEL_MODE={env.get('BIRTHCO_MODEL_MODE', 'mock')}")

    RUN_DIR.mkdir(exist_ok=True)
    ensure_python_deps(env)
    run_migration(env)

    services: list[tuple[str, subprocess.Popen, str]] = []
    fe_port = env.get("BIRTHCO_FRONTEND_PORT") or "4173"
    try:
        if not args.skip_api:
            ensure_port_free(env["BIRTHCO_PORT"], "API")
            api = spawn_logged([sys.executable, "-m", "backend.app"], API_DIR,
                               RUN_DIR / "api.log", RUN_DIR / "api.err.log", env)
            write_pid("api", api)
            services.append(("api", api, "api"))
            print(f"[api] 启动中 pid={api.pid} → http://127.0.0.1:{env['BIRTHCO_PORT']}  "
                  f"日志 {RUN_DIR / 'api.log'}")
            if wait_for_port(api, int(env["BIRTHCO_PORT"]), 30):
                print("[api] 就绪 ✓")
            else:
                print("[api] 30s 内未就绪，日志尾部：")
                dump_log(RUN_DIR / "api.err.log")
                dump_log(RUN_DIR / "api.log")

        if not args.skip_frontend:
            if ensure_node():
                if not (FRONTEND_DIR / "node_modules").exists():
                    npm_install(env)
                ensure_port_free(fe_port, "前端 Vite")
                frontend = spawn_logged(
                    npm_command(["run", "dev", "--", "--port", fe_port]), FRONTEND_DIR,
                    RUN_DIR / "frontend.log", RUN_DIR / "frontend.err.log", env)
                write_pid("frontend", frontend)
                services.append(("frontend", frontend, "frontend"))
                print(f"[fe ] 启动中 pid={frontend.pid} → http://127.0.0.1:{fe_port}  "
                      f"日志 {RUN_DIR / 'frontend.log'}")
                if wait_for_port(frontend, int(fe_port), 60):
                    print(f"[fe ] 就绪 ✓  打开 http://127.0.0.1:{fe_port}")
                else:
                    print("[fe ] 60s 内未就绪（打不开页面的原因在这里），日志尾部：")
                    dump_log(RUN_DIR / "frontend.err.log")
                    dump_log(RUN_DIR / "frontend.log")
                    print(f"      常见原因：Node 版本 < 18、npm install 未完成、{fe_port} 被其他程序占用。")
    except BaseException:
        # 启动中途失败不留孤儿进程
        cleanup(services)
        raise

    print()
    print("=== 启动完成 ===")
    print(f"前端工作台  http://127.0.0.1:{fe_port}   （默认演示适配器，无需后端也可体验）")
    if not args.skip_api:
        print(f"后端 API    http://127.0.0.1:{env['BIRTHCO_PORT']}")
    print("停止服务    Ctrl+C（本进程连带清理）或 stop.ps1")
    print("已知边界：自动执行 worker 未接入（评审 F-01），业务推进用：")
    print("  python run_mock_demo.py                                    # 编排 Mock 全流程")
    print("  cd birthco-local; python tools/run_operator.py --input examples/operator-task.json --output out.json")

    if not services:
        print("[run] 无服务需要启动（迁移已完成）")
        return 0
    if args.detach:
        print("[run] 已后台运行（--detach）；停止用 stop.ps1")
        return 0

    try:
        while True:
            for name, process, pid_name in services:
                if process.poll() is not None:
                    print(f"[run] {name} 退出（code={process.returncode}），停止其余进程")
                    if process.returncode not in (0, None):
                        print(f"[run] {name} 日志尾部：")
                        dump_log(RUN_DIR / f"{name}.err.log")
                        dump_log(RUN_DIR / f"{name}.log")
                    return process.returncode or 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[run] Ctrl+C：停止全部进程…")
        return 0
    finally:
        cleanup(services)


if __name__ == "__main__":
    sys.exit(main())
