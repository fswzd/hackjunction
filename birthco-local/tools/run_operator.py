"""Run one standalone Operator call. Default is a zero-network Mock demo."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.agents.operator import OperatorAgent
from backend.domain.schemas import CreateTask, EditScope


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--live", action="store_true", help="Make one billable provider call; no automatic retry")
    args = parser.parse_args()
    if args.input.stat().st_size > 1048576:
        parser.error("input exceeds 1 MiB")
    document = json.loads(args.input.read_text(encoding="utf-8"))
    task = CreateTask.model_validate(document["task"])
    scope = EditScope.model_validate(document["edit_scope"]) if document.get("edit_scope") else None
    if args.live:
        from backend.adapters.model.qwen import QwenAdapter
        with QwenAdapter() as adapter:
            result = OperatorAgent(adapter, mode="live", model_id=os.environ.get("QWEN_MODEL_ID")).run(task, edit_scope=scope)
    else:
        result = OperatorAgent().run(task, edit_scope=scope)
    text = json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    from backend.domain.errors import DomainError
    from pydantic import ValidationError
    try:
        main()
    except DomainError as exc:
        print(json.dumps({"error": exc.detail().model_dump()}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
    except (ValueError, KeyError, OSError, ValidationError):
        print('Input or model configuration is invalid. Check the example and local configuration.', file=sys.stderr)
        raise SystemExit(2)
