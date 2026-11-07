"""Smoke: content main chain happy path with Mock adapters (dev mode).

Run: python tools/smoke_main_chain.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.workflow.five_agent.driver import OrchestrationDriver
from backend.workflow.five_agent.repository import Repository


def main() -> int:
    repo = Repository(":memory:")
    driver = OrchestrationDriver(repo, mode="mock")
    driver.create_task("task1", {"goal": "写一篇新手拍照入门图文", "user_input": "写一篇新手拍照入门图文",
                                 "input_mode": "idea", "purpose": "content",
                                 "flags": {"traffic_enabled": False, "goal_clear": True}})
    driver.add_material("task1", "mat1", "拍照入门：先学会构图三分法，再练光线。")

    snap = driver.start_content_run("task1", user_input="写一篇新手拍照入门图文", input_mode="idea")
    print("after start:", snap["status"], "gates:", [g["kind"] for g in snap["pending_gates"]])
    assert snap["status"] == "WAITING" and snap["pending_gates"][0]["kind"] == "confirm_brief", snap

    gate = snap["pending_gates"][0]
    brief_ref = snap["state"]["brief_ref"]
    snap = driver.decide(snap["run_id"], gate["id"], approved=True,
                         payload={"brief_version": brief_ref["brief_version"],
                                  "brief_hash": brief_ref["brief_hash"]})
    print("after confirm:", snap["status"], "terminal:", snap["state"]["terminal"],
          "gates:", [g["kind"] for g in snap["pending_gates"]])
    assert snap["status"] == "WAITING" and snap["pending_gates"][0]["kind"] == "accept_delivery", snap

    gate = snap["pending_gates"][0]
    snap = driver.decide(snap["run_id"], gate["id"], approved=True, payload={})
    print("after accept:", snap["status"], "usage:", snap["usage"])
    assert snap["status"] == "READY", snap
    versions = repo.list_versions("task1")
    print("versions:", [(v["id"], v["status"]) for v in versions])
    assert versions[-1]["status"] == "accepted"
    print("SMOKE PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
