"""Validate an Audience trace, compute metrics, then optionally use one model call."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.agents.analyst import AnalystAgent,configuration_failure
from backend.simulation.analysis_data import AnalystInput
from backend.domain.errors import DomainError


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",type=Path,required=True)
    parser.add_argument("--output",type=Path)
    parser.add_argument("--live",action="store_true",help="At most one billable analysis call; viewer metrics never depend on it")
    args=parser.parse_args()
    if args.input.stat().st_size>1048576:parser.error("input exceeds 1 MiB")
    snapshot=AnalystInput.model_validate_json(args.input.read_text(encoding="utf-8"))
    if args.live:
        from backend.adapters.model.qwen import QwenAdapter
        try:adapter=QwenAdapter()
        except (ValueError,OSError):result=configuration_failure(snapshot)
        else:
            with adapter:result=AnalystAgent(adapter,mode="live",model_id=os.environ.get("QWEN_MODEL_ID")).run(snapshot)
    else:result=AnalystAgent().run(snapshot)
    text=json.dumps(result.as_dict(),ensure_ascii=False,indent=2)+"\n"
    if args.output:args.output.write_text(text,encoding="utf-8")
    else:print(text)
    return 0 if result.analysis_status in {"completed","needs_input"} else 3


if __name__=="__main__":
    try:raise SystemExit(main())
    except DomainError as exc:
        print(json.dumps({"error":exc.detail().model_dump()},ensure_ascii=False),file=sys.stderr);raise SystemExit(1)
    except (ValueError,KeyError,OSError):
        print("Input or model configuration is invalid. Check the complete frozen viewer trace.",file=sys.stderr);raise SystemExit(2)
