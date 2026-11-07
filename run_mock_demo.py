"""End-to-end Mock demo of the five-agent workflow: main chain -> preview ->
scoped revision -> export, with evidence output.

Evidence class: MOCK FLOW ONLY (dev mode). No teammate implementations, no live
models, no real users.  Run: python run_mock_demo.py
Writes evidence/mock-flow-evidence.json and prints a summary.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from backend.workflow.five_agent.adapters import AdapterRouter
from backend.workflow.five_agent.driver import OrchestrationDriver
from backend.workflow.five_agent.repository import Repository


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    repo = Repository(":memory:")
    router = AdapterRouter(repo, mode="mock")
    driver = OrchestrationDriver(repo, router=router, mode="mock")

    trace: list[dict] = []

    def step(name: str, snap: dict):
        trace.append({"step": name, "run_id": snap["run_id"], "status": snap["status"],
                      "terminal": (snap.get("state") or {}).get("terminal"),
                      "pending_gates": [g["kind"] for g in snap["pending_gates"]],
                      "usage": {k: snap["usage"][k] for k in
                                ("normal_calls", "tech_retries", "calls_completed",
                                 "tokens_known", "unknown_usage_calls")}})

    # ---------------------------------------------------------------- main chain
    driver.create_task("demo_task", {
        "goal": "写一篇新手拍照入门图文", "user_input": "写一篇新手拍照入门图文",
        "input_mode": "idea", "purpose": "content",
        "flags": {"traffic_enabled": False, "goal_clear": True}})
    driver.add_material("demo_task", "mat1", "拍照入门：先学会构图三分法，再练光线。")

    snap = driver.start_content_run("demo_task", user_input="写一篇新手拍照入门图文")
    step("start_content_run", snap)
    gate = snap["pending_gates"][0]
    brief_ref = snap["state"]["brief_ref"]
    snap = driver.decide(snap["run_id"], gate["id"], approved=True,
                         payload={"brief_version": brief_ref["brief_version"],
                                  "brief_hash": brief_ref["brief_hash"]})
    step("confirm_brief", snap)
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True, payload={})
    step("accept_delivery", snap)
    assert snap["status"] == "READY"

    version_id = snap["state"]["version_ref"]["id"]
    version = repo.get_version(version_id)
    batch = repo.get_artifact(f"batch_{version_id}")["payload"]

    # ------------------------------------------------------------------- preview
    psnap = driver.start_preview_run("demo_task", version_id)
    step("start_preview_run", psnap)
    scenario = {"medium": "text", "segmenter_version": "paragraph-v1", "max_segments": 8,
                "requested_seed": None,
                "personas": [
                    {"id": "p_exit_first", "goal": "随便看看", "knowledge": "零基础", "preferences": []},
                    {"id": "p_full", "goal": "学会拍照", "knowledge": "新手", "preferences": ["图文"]},
                    {"id": "p_timeout_mid", "goal": "快速了解", "knowledge": "新手", "preferences": []},
                ]}
    psnap = driver.decide(psnap["run_id"], psnap["pending_gates"][0]["id"], approved=True,
                          payload={"scenario": scenario, "budget_ack": True})
    step("preview_run", psnap)
    preview_id = psnap["state"]["preview_ref"]["id"]
    metrics = repo.get_artifact(f"metrics_{preview_id}")["payload"]
    analysis = repo.get_artifact(f"analysis_{preview_id}")["payload"]

    body_findings = [f for f in analysis["findings"] if f["segment_id"] != "cover_v1"]
    picked = (body_findings or analysis["findings"])[0]
    psnap = driver.decide(psnap["run_id"], psnap["pending_gates"][0]["id"], approved=True,
                          payload={"finding_ids": [picked["id"]], "allow_title_change": False,
                                   "allow_cover_change": False, "instructions": "只改选中片段"})
    step("select_findings", psnap)

    # ----------------------------------------------------------- scoped revision
    rev = driver.start_revision_run("demo_task", psnap["state"]["revision_ref"]["id"])
    step("start_revision_run", rev)
    rev = driver.decide(rev["run_id"], rev["pending_gates"][0]["id"], approved=True, payload={})
    step("accept_revision", rev)
    assert rev["status"] == "READY"
    new_version = repo.get_version(rev["state"]["version_ref"]["id"])

    # ------------------------------------------------------------------ evidence
    runs = {}
    for run_id in [snap["run_id"], psnap["run_id"], rev["run_id"]]:
        run = repo.get_run(run_id)
        runs[run_id] = {
            "kind": run["kind"], "status": run["status"],
            "calls": [{"action": c["action"], "attempt": c["attempt"], "status": c["status"],
                       "usage_tokens": c["usage_tokens"]} for c in repo.list_calls(run_id)],
            "usage": repo.get_usage(run_id),
        }
    report = {
        "evidence_kind": "mock_flow_end_to_end",
        "mode": "mock_dev_no_live_model_no_teammate_code_no_real_user",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "command": "python run_mock_demo.py",
        "cwd": str(ROOT),
        "exit_code": 0,
        "trace": trace,
        "runs": runs,
        "versions": {
            "v1": {"id": version_id, "status": version["status"], "content_hash": version["content_hash"],
                   "titles": version["payload"]["titles"], "export_files": sorted(batch["files"])},
            "v2": {"id": new_version["id"], "status": new_version["status"],
                   "base_version_id": new_version["base_version_id"],
                   "content_hash": new_version["content_hash"],
                   "change_log": new_version["payload"]["change_log"]},
            "v1_preserved": repo.get_version(version_id)["content_hash"] == version["content_hash"],
        },
        "preview": {
            "preview_id": preview_id,
            "metrics": {"started": metrics["started"], "completed": metrics["completed"],
                        "exited": metrics["exited"], "incomplete": metrics["incomplete"]},
            "analysis_findings": analysis["findings"],
            "selected_finding": picked["id"],
        },
        "isolation_audit": {
            agent_id: [{"action": inv["action"],
                        "model_visible_input_keys": sorted(inv["model_visible_input"]),
                        "context_seen_by_model": inv["context_seen_by_model"]}
                       for inv in router.mocks[agent_id].invocations]
            for agent_id in router.mocks
        },
        "not_tested_here": [
            "five owner real entry points (awaiting_owner_handoff)",
            "live models / real token cost",
            "real user confirmations via Flask/React UI",
            "langgraph-checkpoint-sqlite persistence (plugin not installed)",
        ],
    }
    out = ROOT / "evidence" / "mock-flow-evidence.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("MOCK FLOW PASS")
    for t in trace:
        print(f"  {t['step']:<22} {t['status']:<10} gates={t['pending_gates']} usage={t['usage']}")
    print(f"evidence: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
