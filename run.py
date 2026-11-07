#!/usr/bin/env python3
"""run.py — 本地一键启动器（start.ps1 的跨平台 Python 版）。

用法（仓库根执行，Python 3.13）：

    python run.py                   # 迁移 + Flask API(5001) + 前端 Vite(4173)
    python run.py --skip-frontend   # 只起后端 API
    python run.py --skip-api        # 只起前端
    python run.py --data-dir X:\\data
    python run.py --detach          # 后台启动后立即返回（配 stop.ps1 停止）

默认前台运行：Ctrl+C 连带停止全部子进程（按进程树清理，避免端口残留）。
只使用进程环境变量（BIRTHCO_* / MIMO_* 等），**不读取任何 .env 文件**；
真实模型凭据按“用完即弃”注入进程环境（如 $env:MIMO_API_KEY='…'），不落盘、不入库。
日志与 PID 写入 .run/（api.pid / frontend.pid 与 stop.ps1 约定一致）。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUN_DIR = ROOT / ".run"
API_DIR = ROOT / "birthco-local"
FRONTEND_DIR = ROOT / "frontend"


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


def run_migration(env: dict[str, str]) -> None:
    print(f"[db ] migrate --data-dir {env['BIRTHCO_DATA_DIR']}")
    result = subprocess.run([sys.executable, "-m", "backend.manage", "migrate",
                             "--data-dir", env["BIRTHCO_DATA_DIR"]],
                            cwd=str(API_DIR), env=env)
    if result.returncode != 0:
        raise SystemExit("database migrate failed")


def npm_command(args: list[str]) -> tuple[list[str] | str, bool]:
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("未找到 npm：请先安装 Node.js（前端需要）")
    if os.name == "nt":
        # 交给 cmd.exe，配合 taskkill /T 可整树清理
        return f'"{npm}" {" ".join(args)}', True
    return [npm, *args], False


def spawn_logged(command, cwd: Path, log: Path, err_log: Path,
                 env: dict[str, str], shell: bool = False) -> subprocess.Popen:
    out = open(log, "wb")
    err = open(err_log, "wb")
    process = subprocess.Popen(command, cwd=str(cwd), env=env, shell=shell,
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


def main() -> int:
    args = build_parser().parse_args()
    env = configure_env(args.data_dir)
    print(f"[cfg] HOST={env.get('BIRTHCO_HOST', '127.0.0.1')} PORT={env['BIRTHCO_PORT']} "
          f"DATA={env['BIRTHCO_DATA_DIR']} MODEL_MODE={env.get('BIRTHCO_MODEL_MODE', 'mock')}")

    RUN_DIR.mkdir(exist_ok=True)
    run_migration(env)

    services: list[tuple[str, subprocess.Popen, str]] = []
    if not args.skip_api:
        api = spawn_logged([sys.executable, "-m", "backend.app"], API_DIR,
                           RUN_DIR / "api.log", RUN_DIR / "api.err.log", env)
        write_pid("api", api)
        services.append(("api", api, "api"))
        print(f"[api] 启动中 pid={api.pid} → http://127.0.0.1:{env['BIRTHCO_PORT']}  "
              f"日志 {RUN_DIR / 'api.log'}")

    if not args.skip_frontend:
        if not (FRONTEND_DIR / "node_modules").exists():
            print("[fe ] 首次启动：npm install（可能需要几分钟）")
            install_cmd, shell = npm_command(["install"])
            installed = subprocess.run(install_cmd, cwd=str(FRONTEND_DIR),
                                       env=env, shell=shell)
            if installed.returncode != 0:
                raise SystemExit("npm install failed")
        command, shell = npm_command(["run", "dev"])
        frontend = spawn_logged(command, FRONTEND_DIR,
                                RUN_DIR / "frontend.log", RUN_DIR / "frontend.err.log",
                                env, shell=shell)
        write_pid("frontend", frontend)
        services.append(("frontend", frontend, "frontend"))
        print(f"[fe ] 启动中 pid={frontend.pid} → http://127.0.0.1:4173  "
              f"日志 {RUN_DIR / 'frontend.log'}")

    print()
    print("=== 启动完成 ===")
    print("前端工作台  http://127.0.0.1:4173   （默认演示适配器，无需后端也可体验）")
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
                    return process.returncode or 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[run] Ctrl+C：停止全部进程…")
        return 0
    finally:
        for name, process, pid_name in services:
            stop_process(process)
            remove_pid(pid_name)
            handles = getattr(process, "_runpy_handles", ())
            for handle in handles:
                handle.close()


if __name__ == "__main__":
    sys.exit(main())
