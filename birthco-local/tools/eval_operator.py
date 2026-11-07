"""运营官评测 CLI。mock 默认零网络零费用；--live 显式走 MiMo（每案至多一次调用，无自动重试）。"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.evaluation.operator_eval import format_report, load_dataset, repeat_dataset

DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "operator_eval" / "dataset.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, help="write the JSON report here")
    parser.add_argument("--live", action="store_true",
                        help="Explicit billable MiMo calls (mimo-v2.6-pro); no automatic retry")
    parser.add_argument("--max-calls", type=int, default=8,
                        help="hard cap on live provider calls; remaining cases are skipped")
    parser.add_argument("--repeat", type=int, default=1,
                        help="explicit repeats (not retries) to measure pass@k")
    args = parser.parse_args()
    dataset = load_dataset(args.dataset)
    if args.live:
        from backend.adapters.model.factory import create_live_adapter, live_model_id
        with create_live_adapter("operator") as adapter:
            report = repeat_dataset(dataset, repeats=args.repeat, mode="live",
                                    model_adapter=adapter, model_id=live_model_id("operator"),
                                    max_calls=args.max_calls)
    else:
        report = repeat_dataset(dataset, repeats=args.repeat, mode="mock")
    text = format_report(report)
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(text)
    if "repeats" in report:
        raise SystemExit(0 if report[f"pass_hat_{report['repeats']}"] == 1.0 else 1)
    raise SystemExit(0 if report["passed"] == report["graded"] else 1)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        print(f"Eval configuration invalid: {exc}", file=sys.stderr)
        raise SystemExit(2)
