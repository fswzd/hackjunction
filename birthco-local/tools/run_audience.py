"""Run a local, sequential text-viewer simulation; Mock by default."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.agents.audience import AudienceAgent
from backend.simulation.audience_session import AudienceSimulator,AudienceSimulationInput
from backend.domain.errors import DomainError


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",type=Path,required=True)
    parser.add_argument("--output",type=Path)
    parser.add_argument("--live",action="store_true",help="Up to max_calls billable MiMo requests, sequential, no retries")
    parser.add_argument("--mock-exit-after",type=int,help="Mock only: exit after this zero-based segment ordinal (cover is 0)")
    args=parser.parse_args()
    if args.live and args.mock_exit_after is not None:parser.error("Mock exit controls cannot be used with --live")
    if args.input.stat().st_size>1048576:parser.error("input exceeds 1 MiB")
    snapshot=AudienceSimulationInput.model_validate_json(args.input.read_text(encoding="utf-8"))
    if args.live:
        from backend.adapters.model.factory import create_live_adapter, live_model_id
        with create_live_adapter() as adapter:
            result=AudienceSimulator(AudienceAgent(adapter,mode="live",model_id=live_model_id())).run(snapshot)
    else:result=AudienceSimulator(mock_exit_after=args.mock_exit_after).run(snapshot)
    text=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
    if args.output:args.output.write_text(text,encoding="utf-8")
    else:print(text)
    return 0 if result["status"]=="COMPLETED" else 3


if __name__=="__main__":
    try:raise SystemExit(main())
    except DomainError as exc:
        print(json.dumps({"error":exc.detail().model_dump()},ensure_ascii=False),file=sys.stderr);raise SystemExit(1)
    except (ValueError,KeyError,OSError):
        print("Input or model configuration is invalid. Check the frozen content and budget.",file=sys.stderr);raise SystemExit(2)
