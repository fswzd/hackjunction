"""Analyze a customer brief; optionally write a new pending Operator input."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.agents.pr_analyst import PRAnalystAgent, PRAnalysisInput


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--handoff-output", type=Path, help="New file only; written only when no gaps or conflicts remain")
    parser.add_argument("--live", action="store_true", help="At most one billable MiMo request; no automatic retries")
    args = parser.parse_args()
    paths = [args.input.resolve(), args.output.resolve()]
    if args.handoff_output:
        paths.append(args.handoff_output.resolve())
    if len(set(paths)) != len(paths):
        parser.error("input, analysis and handoff paths must be distinct")
    for path in paths[1:]:
        if path.exists() or not path.parent.is_dir():
            parser.error("choose new output files inside existing directories")
    if args.input.stat().st_size > 1048576:
        parser.error("input exceeds 1 MiB")
    source = PRAnalysisInput.model_validate_json(args.input.read_text(encoding="utf-8"))
    if args.live:
        from backend.adapters.model.factory import create_live_adapter, live_model_id
        with create_live_adapter() as adapter:
            result = PRAnalystAgent(adapter, mode="live", model_id=live_model_id()).run(source)
    else:
        result = PRAnalystAgent().run(source)
    # Exclusive creation protects old runs; missing-input/error never creates handoff.
    with args.output.open("x", encoding="utf-8") as output:
        output.write(json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n")
    if result.task_draft is not None and args.handoff_output:
        with args.handoff_output.open("x", encoding="utf-8") as output:
            output.write(json.dumps({"task": result.task_draft.model_dump(mode="json")}, ensure_ascii=False, indent=2) + "\n")
    print("Saved PR analysis; " + ("pending Operator input available, user review required." if result.task_draft else "no Operator handoff; inspect questions or errors."))
    return 3 if result.envelope.status == "error" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, OSError):
        print("Check customer input, new output paths and local model configuration. No automatic retry was made.", file=sys.stderr)
        raise SystemExit(2)
