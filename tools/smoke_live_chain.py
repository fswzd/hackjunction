"""P0-A live 冒烟:七角色真实入口 + MiMo 每角色 1 次调用,证据 JSON 不存 Key。

用法:
  ./.venv/Scripts/python.exe tools/smoke_live_chain.py [--agent pr_analyst|operator|scout|audience]
      [--out evidence/live-smoke.json]

首版覆盖无需仓库痕迹的四角色;director/reviewer/analyst 需仓库痕迹,用
tests/five_agent/test_*_entry.py 的 mock 痕迹 + live adapter 扩展。退出码 0=全成功。
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import backend  # noqa: E402
BC = str(ROOT / "birthco-local" / "backend")
if BC not in backend.__path__:
    backend.__path__.append(BC)

from backend.adapters.model import factory  # noqa: E402
from backend.adapters.bridge_common import orchestration_ref_digest  # noqa: E402


def _digest(text):
    return orchestration_ref_digest(text)


def smoke_agent(component: str) -> dict:
    adapter = factory.create_live_adapter(component)
    model_id = factory.live_model_id(component)
    call = SimpleNamespace(request_id="smoke_1", contract_version="seven-agent.v0.1",
                           context=SimpleNamespace(task_id="smoke_t", account_id="smoke_a"))
    if component == "pr_analyst":
        from backend.adapters.pr_bridge import PRAnalystTeamAdapter
        call.agent_id, call.action = "pr_analyst", "analyze_request"
        call.input = {"request_text": "品牌X新品推广；要求：文案必须出现品牌名",
                      "material_refs": [{"id": "m1", "sha256": _digest("产品资料：品牌X新品，主打便携。")}]}
        bridge = PRAnalystTeamAdapter(
            resolve_material=lambda ref: {"id": "m1", "text": "产品资料：品牌X新品，主打便携。",
                                          "kind": "text", "label": "产品资料", "source_url": None},
            model_adapter=adapter, mode="live", model_id=model_id)
    elif component == "operator":
        from backend.adapters.orch_bridge import OperatorTeamAdapter
        call.agent_id, call.action = "operations_officer", "prepare_brief"
        call.input = {"user_input": "写一篇新手拍照入门图文", "input_mode": "idea",
                      "material_refs": [{"id": "m1", "sha256": _digest("拍照入门：先学会构图三分法，再练光线。")}],
                      "selected_opportunity_ref": None}
        bridge = OperatorTeamAdapter(
            resolve_material=lambda ref: {"id": "m1", "text": "拍照入门：先学会构图三分法，再练光线。",
                                          "kind": "text", "label": "素材", "source_url": None},
            model_adapter=adapter, mode="live", model_id=model_id)
    elif component == "scout":
        from backend.adapters.scout_bridge import ScoutTeamAdapter
        call.agent_id, call.action = "traffic_scout", "capture_opportunities"
        call.input = {"goal": "写一篇新手拍照入门图文",
                      "material_refs": [{"id": "m1", "sha256": _digest("拍照入门：先学会构图三分法，再练光线。")}]}
        bridge = ScoutTeamAdapter(
            resolve_material=lambda ref: {"id": "m1", "text": "拍照入门：先学会构图三分法，再练光线。",
                                          "kind": "text", "label": "素材", "source_url": None},
            model_adapter=adapter, mode="live", model_id=model_id)
    elif component == "audience":
        from backend.adapters.audience_bridge import AudienceTeamAdapter
        call.agent_id, call.action = "simulated_audience", "read_segment"
        call.input = {"persona": {"id": "p1", "goal": "想学会拍照", "knowledge": "摄影新手",
                                  "preferences": ["喜欢具体步骤"]},
                      "current_segment": {"segment_id": "cover_v1", "kind": "cover",
                                          "text": "三步上手，少走弯路"},
                      "visible_history": [], "own_previous_reactions": []}
        bridge = AudienceTeamAdapter(model_adapter=adapter, mode="live", model_id=model_id)
    else:
        raise NotImplementedError(f"{component} 需要仓库痕迹,先用 mock 痕迹扩展")
    return {"component": component, "model_id": model_id,
            "result": bridge.invoke(call), "at": datetime.now(timezone.utc).isoformat()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", default=None)
    parser.add_argument("--out", default=str(ROOT / "evidence" / "live-smoke.json"))
    args = parser.parse_args()
    components = [args.agent] if args.agent else ["pr_analyst", "operator", "scout", "audience"]
    report = {"at": datetime.now(timezone.utc).isoformat(), "results": []}
    failed = 0
    for component in components:
        try:
            report["results"].append(smoke_agent(component))
        except Exception as exc:
            failed += 1
            report["results"].append({"component": component,
                                      "error": f"{type(exc).__name__}: {exc}"})
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return failed


if __name__ == "__main__":
    sys.exit(main())
