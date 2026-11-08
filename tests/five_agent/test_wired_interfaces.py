"""Regression: no expert-agent interface is left as an owner-handoff stub."""
from backend.workflow.five_agent.adapters import AdapterRouter, RealAdapterStub
from backend.workflow.five_agent.repository import Repository


def test_all_seven_real_entries_are_wired():
    repo = Repository(":memory:")
    router = AdapterRouter(repo, mode="mock")
    assert len(router.reals) == 7
    for agent_id, entry in router.reals.items():
        assert not isinstance(entry, RealAdapterStub), f"{agent_id} is still a stub"
    assert router.reals["pr_analyst"].mode == "live"
    assert router.reals["simulated_audience"].mode == "live"


def test_explicit_reals_override_still_wins():
    repo = Repository(":memory:")
    sentinel = RealAdapterStub("operations_officer", ("prepare_brief",))
    router = AdapterRouter(repo, mode="live", reals={"operations_officer": sentinel})
    assert router.reals["operations_officer"] is sentinel
