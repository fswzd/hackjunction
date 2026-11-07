"""Run one isolated review. Default Mock makes no provider requests."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.agents.editorial_reviewer import EditorialReviewerAgent,ReviewInput
from backend.domain.errors import DomainError


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",type=Path,required=True)
    parser.add_argument("--output",type=Path)
    parser.add_argument("--live",action="store_true",help="Make at most one billable call, with no automatic retry")
    args=parser.parse_args()
    if args.input.stat().st_size>1048576:parser.error("input exceeds 1 MiB")
    snapshot=ReviewInput.model_validate_json(args.input.read_text(encoding="utf-8"))
    if args.live:
        from backend.adapters.model.factory import create_live_adapter, live_model_id
        with create_live_adapter() as adapter:
            result=EditorialReviewerAgent(adapter,mode="live",model_id=live_model_id()).run(snapshot)
    else:result=EditorialReviewerAgent().run(snapshot)
    text=json.dumps(result.as_dict(),ensure_ascii=False,indent=2)+"\n"
    if args.output:args.output.write_text(text,encoding="utf-8")
    else:print(text)


if __name__=="__main__":
    try:main()
    except DomainError as exc:
        print(json.dumps({"error":exc.detail().model_dump()},ensure_ascii=False),file=sys.stderr);raise SystemExit(1)
    except (ValueError,KeyError,OSError):
        print("Input or model configuration is invalid. Check the local example.",file=sys.stderr);raise SystemExit(2)
