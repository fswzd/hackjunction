"""校验 REVIEW_PROMPT_SCHEMA_HASH 冻结值（F-02）。

两树同名 backend 包不可同进程导入，故哈希计算放子进程（cwd=birthco-local），
registry 侧取值用文本解析。退出码 0=一致，1=不一致/缺失。
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUSINESS = ROOT / "birthco-local"
REGISTRY = ROOT / "backend" / "workflow" / "five_agent" / "registry.py"

COMPUTE = (
    "from backend.agents.editorial_reviewer import SYSTEM; "
    "from backend.domain.hashing import sha256_json; "
    "from backend.domain.schemas import Envelope, EditorialReview; "
    "print(sha256_json({'system': SYSTEM, "
    "'output_schema': Envelope[EditorialReview].model_json_schema()}))"
)


def main() -> int:
    result = subprocess.run([sys.executable, "-c", COMPUTE], cwd=str(BUSINESS),
                            capture_output=True, text=True)
    if result.returncode != 0:
        print("计算失败（业务侧）:", result.stderr.strip(), file=sys.stderr)
        return 1
    actual = result.stdout.strip()
    text = REGISTRY.read_text(encoding="utf-8")
    match = re.search(r'REVIEW_PROMPT_SCHEMA_HASH = "([0-9a-f]{64})"', text)
    if not match:
        print("registry 中未找到已冻结的 REVIEW_PROMPT_SCHEMA_HASH", file=sys.stderr)
        return 1
    frozen = match.group(1)
    if frozen != actual:
        print(f"哈希不一致：registry={frozen} 业务侧={actual}", file=sys.stderr)
        print("prompt/schema 已变更——请重新申报冻结并评估既有审稿收据是否作废。", file=sys.stderr)
        return 1
    print(f"OK: REVIEW_PROMPT_SCHEMA_HASH={frozen}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
