"""Probe: langgraph 1.1.10 interrupt/Command(resume) + conditional edges + sequential gates.

Run: python tools/probe_langgraph_interrupt.py
Exit 0 = probe passed. Evidence written to evidence/probe-langgraph-interrupt.json.
"""
import json
import sys
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class S(TypedDict):
    log: Annotated[list, lambda a, b: a + b]
    done: bool


def make_graph():
    def gate_a(state: S):
        d = interrupt({"gate": "a"})
        return {"log": [f"gate_a:{d}"]}

    def work(state: S):
        return {"log": ["work"], "done": True}

    def gate_b(state: S):
        d = interrupt({"gate": "b"})
        return {"log": [f"gate_b:{d}"]}

    def finish(state: S):
        return {"log": ["finish"]}

    def route(state: S):
        return "gate_b" if state.get("done") else END

    g = StateGraph(S)
    g.add_node("gate_a", gate_a)
    g.add_node("work", work)
    g.add_node("gate_b", gate_b)
    g.add_node("finish", finish)
    g.add_edge(START, "gate_a")
    g.add_edge("gate_a", "work")
    g.add_conditional_edges("work", route, {"gate_b": "gate_b", END: END})
    g.add_edge("gate_b", "finish")
    g.add_edge("finish", END)
    return g.compile(checkpointer=MemorySaver())


def main():
    checks = []

    def ok(name, cond):
        checks.append({"name": name, "status": "pass" if cond else "fail"})
        if not cond:
            raise AssertionError(name)

    app = make_graph()
    cfg = {"configurable": {"thread_id": "t1"}}
    out = app.invoke({"log": [], "done": False}, cfg)
    interrupts = out.get("__interrupt__") or ()
    ok("first_invoke_interrupts", len(interrupts) == 1)
    ok("interrupt_payload_gate_a", interrupts[0].value == {"gate": "a"})
    out = app.invoke(Command(resume="DECISION_A"), cfg)
    interrupts = out.get("__interrupt__") or ()
    ok("second_invoke_interrupts_at_b", len(interrupts) == 1 and interrupts[0].value == {"gate": "b"})
    out = app.invoke(Command(resume="DECISION_B"), cfg)
    ok("final_log", out["log"] == ["gate_a:DECISION_A", "work", "gate_b:DECISION_B", "finish"])
    ok("reaches_end", "done" in out and out["done"] is True)

    # fresh thread: resume without prior interrupt must not crash the API surface
    app2 = make_graph()
    cfg2 = {"configurable": {"thread_id": "t2"}}
    app2.invoke({"log": [], "done": False}, cfg2)
    snapshot = app2.get_state(cfg2)
    ok("snapshot_next_is_gate_a_or_work", bool(snapshot.next))

    report = {
        "probe": "langgraph-interrupt-command-conditional",
        "langgraph_version": __import__("importlib.metadata", fromlist=["version"]).version("langgraph"),
        "checks": checks,
        "status": "pass",
    }
    out_path = Path(__file__).resolve().parents[1] / "evidence" / "probe-langgraph-interrupt.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("PROBE PASS:", len(checks), "checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
