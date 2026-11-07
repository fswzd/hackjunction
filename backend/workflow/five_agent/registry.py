"""Static registry: five roles, seven actions, run kinds, budgets, step-key rules.

Roles/actions mirror agent-interface.json (contract five-agent.v0.2). Budget
profiles follow the five-agent interaction design (§2/§3) and lg-0.1 limits:
content run 5 normal + 2 shared tech retries = 7 total / 1 business repair /
60k tokens; preview 48 audience + 1 analysis + 4 retries = 53 / 200k; scout 3
+ 2 retries = 5 / 20k; export zero model calls.  Revision run is its own run
with the original 7/1/2 ceiling (2 normal revise+assess, one auto-repair pair).
"""
from __future__ import annotations

from dataclasses import dataclass

CONTRACT_VERSION = "seven-agent.v0.1"
WORKFLOW_VERSION = "seven-agent.v0.1"
GRAPH_STATE_SCHEMA = "seven-agent.v0.1.state"
PROMPT_SCHEMA_VERSION = "seven-agent.v0.1.prompt"
RULE_VERSION = "content-rules-v1"
RULE_SCHEMA_HASH = "a" * 64  # content-rules-v1 is deterministic program code
REVIEW_PROMPT_SCHEMA_HASH = "658c498f36362de652ef314f1c241e33a04015676447032b657283ba0f0e4b0e"
# ^ owner 冻结（2026-11-07）：sha256(canonical_json({system, output_schema}))，
#   system = birthco-local backend/agents/editorial_reviewer.py SYSTEM，
#   output_schema = Envelope[EditorialReview].model_json_schema()。
#   校验：python tools/check_review_prompt_hash.py（两树哈希不一致即失效）。
SEGMENTER_VERSION = "paragraph-v1"

ROLES: dict[str, str] = {
    "pr_analyst": "商单需求分析员",
    "content_creator": "内容主创",
    "operations_officer": "运营官",
    "editorial_reviewer": "审稿员",
    "traffic_scout": "流量捕捉者",
    "data_analyst": "数据分析师",
    "simulated_audience": "模拟观众",
}

ACTIONS: dict[str, str] = {
    "analyze_request": "pr_analyst",
    "draft": "content_creator",
    "revise": "content_creator",
    "prepare_brief": "operations_officer",
    "assess_content": "editorial_reviewer",
    "capture_opportunities": "traffic_scout",
    "diagnose_preview": "data_analyst",
    "read_segment": "simulated_audience",
}

OUTPUT_SCHEMA: dict[str, str] = {
    "analyze_request": "RequestAnalysis",
    "draft": "ContentCandidate",
    "revise": "Revision",
    "prepare_brief": "Brief",
    "assess_content": "EditorialReview",
    "capture_opportunities": "OpportunitySet",
    "diagnose_preview": "Analysis",
    "read_segment": "AudienceEvent",
}

RUN_KINDS = ("content", "preview", "revision", "scout", "pr_intake", "export")

MAX_BUSINESS_REPAIRS = 1


@dataclass(frozen=True)
class BudgetProfile:
    kind: str
    max_normal_calls: int
    max_business_repairs: int
    max_tech_retries: int
    max_total_calls: int
    max_total_tokens: int


BUDGETS: dict[str, BudgetProfile] = {
    # normal: prepare_brief + draft + assess_content = 3; with one repair pair +2 = 5.
    "content": BudgetProfile("content", 5, 1, 2, 7, 60_000),
    # local scoped revision: revise + assess = 2; one auto-repair pair +2 = 4; 7/1/2 ceiling kept.
    "revision": BudgetProfile("revision", 4, 1, 2, 7, 60_000),
    # up to 6 personas x 8 segments = 48 audience calls + 1 analysis + 4 retries.
    "preview": BudgetProfile("preview", 49, 0, 4, 53, 200_000),
    "scout": BudgetProfile("scout", 3, 0, 2, 5, 20_000),
    # commercial-intake analysis: explicit sub-run; 1 call per analysis, pool covers
    # resupplied replans (≤3 normal) + 1 shared technical retry (PR_ANALYST budget)
    "pr_intake": BudgetProfile("pr_intake", 3, 0, 1, 4, 30_000),
    "export": BudgetProfile("export", 0, 0, 0, 0, 0),
}

# Domain limits from implementation-design/limits.json that the program enforces.
LIMITS = {
    "id_characters": 64,
    "material_characters_each": 20000,
    "material_count": 20,
    "body_non_whitespace_characters": 20000,
    "body_segments": 32,
    "title_characters_each": 1000,
    "cover_characters": 1000,
    "requirements": 30,
    "personas": 6,
    "preview_segments_including_cover": 8,
    "history_segments": 7,
    "artifact_bytes": 1048576,
}

TERMINALS = ("READY", "NEEDS_REVIEW", "WAITING_INPUT", "CANCELLED", "FAILED", "INTERRUPTED", "EXPORTED")

# Gate kinds (user confirmations), each bound to a frozen subject hash.
GATE_KINDS = (
    "select_opportunity",   # after scout: pick an opportunity or continue original goal
    "supply_input",         # prepare_brief needs_input / open questions
    "confirm_brief",        # confirm exact Brief version
    "accept_delivery",      # accept exported version
    "preview_conditions",   # freeze version + scenario + budget for preview
    "select_findings",      # choose findings/scope/budget for scoped revision
    "accept_revision",      # accept revised export
)


def step_key_brief(planning_fingerprint: str) -> str:
    return f"brief:{planning_fingerprint}"


def step_key_draft(brief_fingerprint: str) -> str:
    return f"draft:{brief_fingerprint}"


def step_key_rule(version_id: str) -> str:
    return f"rule:{version_id}:{RULE_SCHEMA_HASH[:16]}"


def step_key_review(version_id: str) -> str:
    return f"review:{version_id}:{REVIEW_PROMPT_SCHEMA_HASH[:16]}"


def step_key_repair(base_version_id: str, scope_fingerprint: str) -> str:
    return f"repair:{base_version_id}:{scope_fingerprint}"


def step_key_audience(session_id: str, ordinal: int, projection_hash: str) -> str:
    return f"audience:{session_id}:{ordinal}:{projection_hash[:16]}"


def step_key_analysis(preview_id: str, version_id: str, metrics_hash: str) -> str:
    return f"analysis:{preview_id}:{version_id}:{metrics_hash[:16]}"


def step_key_scout(goal_fingerprint: str) -> str:
    return f"scout:{goal_fingerprint}"


def step_key_pr(request_fingerprint: str) -> str:
    return f"pr:{request_fingerprint}"


def step_key_export(version_id: str, batch_id: str) -> str:
    return f"export:{version_id}:{batch_id}:exporter-v1"
