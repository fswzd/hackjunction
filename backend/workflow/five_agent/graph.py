"""StateGraph assembly: one fixed graph per run kind (ADR-LG-02).

content:   route -> [traffic -> wait_opportunity] -> brief -> wait_input/wait_brief_confirm
           -> draft -> rules -> review -> repair*1 -> export -> wait_accept
preview:   wait_conditions -> project -> audience_step -> commit_event -> advance
           -> metrics -> analysis -> show -> wait_suggestions
revision:  draft(scoped revise) -> rules -> review -> repair*1 -> export -> wait_accept
scout:     traffic -> stop
export:    export -> wait_accept (standalone)

Entry routing honours persisted resume_step so a restart re-enters at the
committed step instead of re-running earlier nodes (design.md §7).
"""
from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from . import nodes as N
from .graphstate import FiveAgentState, Services

ENTRY_MAP = {
    "start": "route", "route": "route", "traffic": "traffic",
    "pr_analysis": "pr_analysis", "brief": "brief",
    "wait_input": "wait_input", "wait_brief_confirm": "wait_brief_confirm",
    "draft": "draft", "draft_scoped": "draft", "rules": "rules", "review": "review",
    "repair": "repair", "export": "export", "wait_accept": "wait_accept",
}
PREVIEW_ENTRY_MAP = {
    "start": "wait_conditions", "wait_conditions": "wait_conditions", "project": "project",
    "audience_step": "audience_step", "commit_event": "commit_event", "advance": "advance",
    "metrics": "metrics", "analysis": "analysis", "show": "show",
    "wait_suggestions": "wait_suggestions",
}


def _entry_router(mapping: dict, default: str):
    def route(state: FiveAgentState) -> str:
        step = state.get("resume_step") or "start"
        return mapping.get(step, default)
    return route


def _wrap(fn, svc: Services):
    return lambda state: fn(state, svc)


def build_graph(run_kind: str, svc: Services):
    if run_kind not in ("content", "preview", "revision", "scout", "pr_intake", "export"):
        raise ValueError(f"unknown run_kind {run_kind}")
    g = StateGraph(FiveAgentState)

    if run_kind in ("content", "export"):
        g.add_node("route", _wrap(N.node_route, svc))
        g.add_node("pr_analysis", _wrap(N.node_pr_analysis, svc))
        g.add_node("traffic", _wrap(N.node_traffic, svc))
        g.add_node("wait_opportunity", _wrap(N.node_wait_opportunity, svc))
        g.add_node("brief", _wrap(N.node_brief, svc))
        g.add_node("wait_input", _wrap(N.node_wait_input, svc))
        g.add_node("wait_brief_confirm", _wrap(N.node_wait_brief_confirm, svc))
        g.add_node("draft", _wrap(N.node_draft, svc))
        g.add_node("rules", _wrap(N.node_rules, svc))
        g.add_node("review", _wrap(N.node_review, svc))
        g.add_node("repair", _wrap(N.node_repair, svc))
        g.add_node("export", _wrap(N.node_export, svc))
        g.add_node("wait_accept", _wrap(N.node_wait_accept, svc))
        g.add_node("needs_review", _wrap(N.node_needs_review, svc))
        g.add_node("stop", _wrap(N.node_stop, svc))
        g.add_conditional_edges(START, _entry_router(ENTRY_MAP, "route"),
                                {k: k for k in ("route", "traffic", "pr_analysis", "wait_opportunity", "brief",
                                                "wait_input", "wait_brief_confirm", "draft", "rules", "review",
                                                "repair", "export", "wait_accept")})
        g.add_conditional_edges("route", N.route_generic,
                                {"traffic": "traffic", "pr_analysis": "pr_analysis", "brief": "brief"})
        g.add_conditional_edges("pr_analysis", N.route_generic,
                                {"brief": "brief", "wait_input": "wait_input",
                                 "needs_review": "needs_review", "stop": "stop"})
        g.add_conditional_edges("traffic", N.route_generic,
                                {"wait_opportunity": "wait_opportunity", "brief": "brief",
                                 "needs_review": "needs_review", "stop": "stop"})
        g.add_conditional_edges("wait_opportunity", N.route_generic,
                                {"brief": "brief", "stop": "stop"})
        g.add_conditional_edges("brief", N.route_generic,
                                {"wait_input": "wait_input", "wait_brief_confirm": "wait_brief_confirm",
                                 "needs_review": "needs_review"})
        g.add_conditional_edges("wait_input", N.route_generic,
                                {"brief": "brief", "pr_analysis": "pr_analysis", "stop": "stop"})
        g.add_conditional_edges("wait_brief_confirm", N.route_generic, {"draft": "draft", "stop": "stop"})
        g.add_conditional_edges("draft", N.route_generic,
                                {"rules": "rules", "stop": "stop", "needs_review": "needs_review"})
        g.add_conditional_edges("rules", N.route_generic,
                                {"review": "review", "repair": "repair", "needs_review": "needs_review"})
        g.add_conditional_edges("review", N.route_generic,
                                {"export": "export", "repair": "repair",
                                 "needs_review": "needs_review", "stop": "stop"})
        g.add_conditional_edges("repair", N.route_generic,
                                {"rules": "rules", "needs_review": "needs_review"})
        g.add_conditional_edges("export", N.route_generic, {"wait_accept": "wait_accept"})
        g.add_conditional_edges("wait_accept", N.route_generic, {"stop": "stop"})
        g.add_edge("needs_review", "stop")
        g.add_edge("stop", END)

    elif run_kind == "revision":
        revision_entry = dict(ENTRY_MAP, start="draft")
        g.add_node("draft", _wrap(N.node_draft, svc))
        g.add_node("rules", _wrap(N.node_rules, svc))
        g.add_node("review", _wrap(N.node_review, svc))
        g.add_node("repair", _wrap(N.node_repair, svc))
        g.add_node("export", _wrap(N.node_export, svc))
        g.add_node("wait_accept", _wrap(N.node_wait_accept, svc))
        g.add_node("needs_review", _wrap(N.node_needs_review, svc))
        g.add_node("stop", _wrap(N.node_stop, svc))
        g.add_conditional_edges(START, _entry_router(revision_entry, "draft"),
                                {k: k for k in ("draft", "rules", "review", "repair", "export", "wait_accept")})
        g.add_conditional_edges("draft", N.route_generic,
                                {"rules": "rules", "stop": "stop", "needs_review": "needs_review"})
        g.add_conditional_edges("rules", N.route_generic,
                                {"review": "review", "repair": "repair", "needs_review": "needs_review"})
        g.add_conditional_edges("review", N.route_generic,
                                {"export": "export", "repair": "repair",
                                 "needs_review": "needs_review", "stop": "stop"})
        g.add_conditional_edges("repair", N.route_generic,
                                {"rules": "rules", "needs_review": "needs_review"})
        g.add_conditional_edges("export", N.route_generic, {"wait_accept": "wait_accept"})
        g.add_conditional_edges("wait_accept", N.route_generic, {"stop": "stop"})
        g.add_edge("needs_review", "stop")
        g.add_edge("stop", END)

    elif run_kind == "preview":
        g.add_node("wait_conditions", _wrap(N.node_wait_conditions, svc))
        g.add_node("project", _wrap(N.node_project, svc))
        g.add_node("audience_step", _wrap(N.node_audience_step, svc))
        g.add_node("commit_event", _wrap(N.node_commit_event, svc))
        g.add_node("advance", _wrap(N.node_advance, svc))
        g.add_node("metrics", _wrap(N.node_metrics, svc))
        g.add_node("analysis", _wrap(N.node_analysis, svc))
        g.add_node("show", _wrap(N.node_show_suggestions, svc))
        g.add_node("wait_suggestions", _wrap(N.node_wait_suggestions, svc))
        g.add_node("needs_review", _wrap(N.node_needs_review, svc))
        g.add_node("stop", _wrap(N.node_stop, svc))
        g.add_conditional_edges(START, _entry_router(PREVIEW_ENTRY_MAP, "wait_conditions"),
                                {k: k for k in ("wait_conditions", "project", "audience_step",
                                                "commit_event", "advance", "metrics", "analysis",
                                                "show", "wait_suggestions")})
        g.add_conditional_edges("wait_conditions", N.route_generic, {"project": "project", "stop": "stop"})
        g.add_conditional_edges("project", N.route_generic, {"audience_step": "audience_step"})
        g.add_conditional_edges("audience_step", N.route_generic,
                                {"commit_event": "commit_event", "advance": "advance",
                                 "needs_review": "needs_review", "stop": "stop"})
        g.add_conditional_edges("commit_event", N.route_generic, {"advance": "advance"})
        g.add_conditional_edges("advance", N.route_generic, {"project": "project", "metrics": "metrics"})
        g.add_edge("metrics", "analysis")
        g.add_edge("analysis", "show")
        g.add_conditional_edges("show", N.route_generic, {"wait_suggestions": "wait_suggestions"})
        g.add_conditional_edges("wait_suggestions", N.route_generic, {"stop": "stop"})
        g.add_edge("needs_review", "stop")
        g.add_edge("stop", END)

    elif run_kind == "pr_intake":
        pr_entry = {"start": "pr_analysis", "pr_analysis": "pr_analysis", "stop": "stop"}
        g.add_node("pr_analysis", _wrap(N.node_pr_analysis, svc))
        g.add_node("needs_review", _wrap(N.node_needs_review, svc))
        g.add_node("stop", _wrap(N.node_stop, svc))
        g.add_conditional_edges(START, _entry_router(pr_entry, "pr_analysis"),
                                {"pr_analysis": "pr_analysis", "stop": "stop"})
        g.add_conditional_edges("pr_analysis", N.route_generic,
                                {"stop": "stop", "needs_review": "needs_review",
                                 "brief": "stop", "wait_input": "stop"})
        g.add_edge("needs_review", "stop")
        g.add_edge("stop", END)

    else:  # scout
        scout_entry = {"start": "traffic", "traffic": "traffic", "stop": "stop"}
        g.add_node("traffic", _wrap(N.node_traffic, svc))
        g.add_node("needs_review", _wrap(N.node_needs_review, svc))
        g.add_node("stop", _wrap(N.node_stop, svc))
        g.add_conditional_edges(START, _entry_router(scout_entry, "traffic"),
                                {"traffic": "traffic", "stop": "stop"})
        g.add_conditional_edges("traffic", N.route_generic,
                                {"stop": "stop", "needs_review": "needs_review",
                                 "brief": "stop", "wait_opportunity": "stop"})
        g.add_edge("needs_review", "stop")
        g.add_edge("stop", END)

    return g.compile(checkpointer=MemorySaver())
