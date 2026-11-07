"""兼容入口：抖音账号接入。通用入口见 run_account_intake.py（支持 --platform）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.run_account_intake import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
