"""现有账号接入 CLI（douyin / xiaohongshu，perf-data adapter + manual 降级）。

用法（birthco-local/ 下）：
  python tools/run_account_intake.py register --platform xiaohongshu --account-id a_xxx --handle 小红书号
  python tools/run_account_intake.py login --external-id ext_xxx        # 扫码（需 playwright）
  python tools/run_account_intake.py import-adapter --external-id ext_xxx [--count 10]
  python tools/run_account_intake.py import-manual --external-id ext_xxx --file videos.json
  python tools/run_account_intake.py status

退出码：0 成功；2 输入/配置错误；3 导入失败但已登记 pending_adapter_setup（manual 仍可用）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.integrations import intake, storage  # noqa: E402
from backend.integrations.browser_session import session_path  # noqa: E402
from backend.integrations.types import ExternalAccountCreate, ManualImport  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path,
                        default=Path(__file__).resolve().parents[1] / "data")
    sub = parser.add_subparsers(dest="command", required=True)

    reg = sub.add_parser("register")
    reg.add_argument("--platform", choices=("douyin", "xiaohongshu"), default="douyin")
    reg.add_argument("--account-id", required=True)
    reg.add_argument("--handle", required=True)
    reg.add_argument("--name", default="")
    reg.add_argument("--profile-url", default=None)

    login = sub.add_parser("login")
    login.add_argument("--external-id", required=True)

    imp_a = sub.add_parser("import-adapter")
    imp_a.add_argument("--external-id", required=True)
    imp_a.add_argument("--count", type=int, default=10)

    imp_m = sub.add_parser("import-manual")
    imp_m.add_argument("--external-id", required=True)
    imp_m.add_argument("--file", type=Path, required=True)

    sub.add_parser("status")

    args = parser.parse_args(argv)
    db = args.data_dir
    try:
        if args.command == "register":
            row = intake.register_account(db, ExternalAccountCreate.model_validate({
                "account_id": args.account_id, "platform": args.platform,
                "handle": args.handle, "display_name": args.name,
                "profile_url": args.profile_url}))
            print(json.dumps({"external_account_id": row["id"],
                              "session_status": row["session_status"]}, ensure_ascii=False))
            return 0
        if args.command == "login":
            account = storage.get_external_account(db, args.external_id)
            if account["platform"] == "xiaohongshu":
                from backend.integrations.xiaohongshu import session as platform_session
            else:
                from backend.integrations.douyin import session as platform_session
            try:
                path = platform_session.login_interactive(
                    args.external_id, session_file=session_path(args.external_id, db))
            except platform_session.PlaywrightNotInstalled as exc:
                print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
                return 2
            intake.attach_session(db, args.external_id, path)
            print(json.dumps({"status": "logged_in", "session_ref": str(path)}, ensure_ascii=False))
            return 0
        if args.command == "import-adapter":
            try:
                result = intake.import_via_adapter(db, args.external_id, count=args.count)
            except Exception as exc:
                intake.mark_pending_adapter(db, args.external_id)
                print(json.dumps({"error": str(exc), "next_action": "改用 import-manual"},
                                 ensure_ascii=False), file=sys.stderr)
                return 3
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "import-manual":
            raw = json.loads(args.file.read_text(encoding="utf-8"))
            result = intake.import_manual(db, args.external_id, ManualImport.model_validate(raw))
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "status":
            rows = storage.list_external_accounts(db)
            print(json.dumps([{"external_account_id": r["id"], "platform": r["platform"],
                               "handle": r["handle"], "session_status": r["session_status"],
                               "imported_count": r["imported_count"],
                               "baseline_plays": r["baseline_plays"]} for r in rows],
                            ensure_ascii=False, indent=2))
            return 0
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
