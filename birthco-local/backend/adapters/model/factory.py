"""统一 live 模型后端工厂：每个专家 agent 单列环境变量接口配置，缺省回退通用默认。

环境变量约定（只经运行时进程环境注入；代码不落盘、不读取任何配置文件）：

    MIMO_API_KEY / MIMO_BASE_URL / MIMO_MODEL_ID      # 通用默认（MiMo）
    PR_ANALYST_API_KEY / _BASE_URL / _MODEL_ID        # 各 agent 单列，可独立覆盖
    OPERATOR_ / DIRECTOR_ / REVIEWER_ / SCOUT_ / ANALYST_ / AUDIENCE_

解析顺序：agent 单列项（非空）→ 通用 MIMO_* → 内置默认
（mimo-v2.6-pro @ https://api.xiaomimimo.com/anthropic）。

用法（方式 A 注入，专家 agent 业务代码零改动）：

    with create_live_adapter("audience") as adapter:
        agent = AudienceAgent(adapter, mode="live", model_id=live_model_id("audience"))

agent_id 接受组件名（pr_analyst/operator/director/reviewer/scout/analyst/audience）
与契约角色名（operations_officer/content_creator/editorial_reviewer/traffic_scout/
data_analyst/simulated_audience），二者映射到同一份配置。
"""

from __future__ import annotations

import os

from .mimo import DEFAULT_BASE_URL, DEFAULT_MODEL_ID, MiMoAdapter

AGENT_ENV_PREFIXES: dict[str, str] = {
    # 组件名
    "pr_analyst": "PR_ANALYST",
    "operator": "OPERATOR",
    "director": "DIRECTOR",
    "reviewer": "REVIEWER",
    "scout": "SCOUT",
    "analyst": "ANALYST",
    "audience": "AUDIENCE",
    # 契约角色名（seven-agent.v0.1）→ 同一份配置
    "operations_officer": "OPERATOR",
    "content_creator": "DIRECTOR",
    "editorial_reviewer": "REVIEWER",
    "traffic_scout": "SCOUT",
    "data_analyst": "ANALYST",
    "simulated_audience": "AUDIENCE",
}

AGENT_IDS = tuple(sorted({p for p in AGENT_ENV_PREFIXES.values()}))


def _prefix(agent_id: str | None) -> str | None:
    if agent_id is None or not str(agent_id).strip():
        return None
    key = str(agent_id).strip().lower()
    if key not in AGENT_ENV_PREFIXES:
        raise ValueError(f"unknown agent_id: {agent_id!r}")
    return AGENT_ENV_PREFIXES[key]


def _resolve(suffix: str, prefix: str | None, fallback_env: str, default: str | None) -> str | None:
    if prefix:
        value = os.environ.get(f"{prefix}_{suffix}")
        if value and value.strip():
            return value.strip()
    value = os.environ.get(fallback_env)
    if value and value.strip():
        return value.strip()
    return default


def create_live_adapter(agent_id: str | None = None, **kwargs) -> MiMoAdapter:
    """按 agent 解析环境变量单列配置构造 MiMo 适配器；显式 kwargs 优先级最高。"""
    prefix = _prefix(agent_id)
    api_key = kwargs.pop("api_key", None) or _resolve("API_KEY", prefix, "MIMO_API_KEY", None)
    base_url = kwargs.pop("base_url", None) or _resolve("BASE_URL", prefix, "MIMO_BASE_URL", DEFAULT_BASE_URL)
    model_id = (kwargs.pop("configured_model_id", None)
                or _resolve("MODEL_ID", prefix, "MIMO_MODEL_ID", DEFAULT_MODEL_ID))
    return MiMoAdapter(api_key=api_key, base_url=base_url,
                       configured_model_id=model_id, **kwargs)


def live_model_id(agent_id: str | None = None) -> str:
    prefix = _prefix(agent_id)
    return _resolve("MODEL_ID", prefix, "MIMO_MODEL_ID", DEFAULT_MODEL_ID) or DEFAULT_MODEL_ID


def live_config_report(agent_id: str | None = None) -> dict:
    """脱敏配置一览（永不返回密钥），供检查工具/诊断使用。"""
    prefix = _prefix(agent_id)
    api_key = _resolve("API_KEY", prefix, "MIMO_API_KEY", None)
    return {
        "agent_id": agent_id,
        "env_prefix": prefix or "MIMO（通用默认）",
        "api_key_configured": bool(api_key),
        "base_url": _resolve("BASE_URL", prefix, "MIMO_BASE_URL", DEFAULT_BASE_URL),
        "model_id": _resolve("MODEL_ID", prefix, "MIMO_MODEL_ID", DEFAULT_MODEL_ID),
    }


# ---------------------------------------------------------------------------
# 七角色统一接入层（工作台使用）
#
# 之前工作台在 live 模式给所有角色硬编码同一个 Qwen/DashScope 适配器，七个
# Agent 的接口配置形同虚设。这里按角色解析 provider / endpoint / model / key，
# 让每个 Agent 都能单独接不同的模型服务；未配置任何凭据时统一回落到离线
# Mock，绝不偷偷联网、绝不静默回退。
# ---------------------------------------------------------------------------

AGENT_ROLES: dict[str, dict[str, str]] = {
    "pr_analyst":          {"label": "商单需求分析员", "component": "pr_analyst",  "prefix": "PR_ANALYST"},
    "operations_officer":  {"label": "运营官",         "component": "operator",    "prefix": "OPERATOR"},
    "content_creator":     {"label": "内容主创",       "component": "director",    "prefix": "DIRECTOR"},
    "editorial_reviewer":  {"label": "审稿员",         "component": "reviewer",    "prefix": "REVIEWER"},
    "traffic_scout":       {"label": "流量捕捉者",     "component": "scout",       "prefix": "SCOUT"},
    "data_analyst":        {"label": "数据分析师",     "component": "analyst",     "prefix": "ANALYST"},
    "simulated_audience":  {"label": "模拟观众",       "component": "audience",    "prefix": "AUDIENCE"},
}

PROVIDERS = ("auto", "mock", "openai", "mimo", "qwen")
_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _agent_value(role: str, suffix: str, fallback: str = "") -> str:
    prefix = AGENT_ROLES[role]["prefix"]
    return _env(f"{prefix}_{suffix}") or _env(fallback)


def _configured_provider() -> str | None:
    """Detect which provider family the environment supplies, in priority order."""
    if _env("AGENT_API_KEY") or _env("OPENAI_API_KEY") or _env("AGENT_BASE_URL") or _env("OPENAI_BASE_URL"):
        return "openai"
    if _env("MIMO_API_KEY"):
        return "mimo"
    if _env("DASHSCOPE_API_KEY"):
        return "qwen"
    return None


def resolve_agent(role: str) -> dict:
    """Return a redacted, ready-to-display descriptor for one of the 7 roles."""
    if role not in AGENT_ROLES:
        raise ValueError(f"unknown agent role: {role!r}")
    meta = AGENT_ROLES[role]
    prefix = meta["prefix"]
    requested = (_env(f"{prefix}_PROVIDER") or _env("AGENT_PROVIDER") or "auto").lower()
    if requested not in PROVIDERS:
        requested = "auto"
    detected = _configured_provider()
    effective = (detected or "mock") if requested == "auto" else requested
    key = (_agent_value(role, "API_KEY", "AGENT_API_KEY")
           or _agent_value(role, "API_KEY", "OPENAI_API_KEY")
           or _env("MIMO_API_KEY") or _env("DASHSCOPE_API_KEY"))
    if effective == "mimo":
        base = _agent_value(role, "BASE_URL", "MIMO_BASE_URL") or DEFAULT_BASE_URL
        model = _agent_value(role, "MODEL_ID", "MIMO_MODEL_ID") or DEFAULT_MODEL_ID
    elif effective == "qwen":
        base = _agent_value(role, "BASE_URL", "QWEN_BASE_URL") or _QWEN_BASE_URL
        model = _agent_value(role, "MODEL_ID", "QWEN_MODEL_ID") or "qwen-plus"
    elif effective == "openai":
        base = _agent_value(role, "BASE_URL", "OPENAI_BASE_URL") or "https://api.openai.com/v1"
        model = _agent_value(role, "MODEL_ID", "OPENAI_MODEL_ID") or "gpt-4o-mini"
    else:
        base, model = "offline", "mock-local-v1"
    loopback = base.startswith(("http://127.0.0.1", "http://localhost"))
    ready = effective == "mock" or bool(key) or loopback
    return {
        "agent_id": role,
        "label": meta["label"],
        "component": meta["component"],
        "env_prefix": prefix,
        "provider": effective,
        "requested_provider": requested,
        "model_id": model,
        "base_url": base,
        "api_key_configured": bool(key),
        "configured": ready,
        "offline": effective == "mock",
        "source": "env" if detected or requested != "auto" else "default",
    }


def agent_registry() -> list[dict]:
    """All seven agent interfaces at once; never includes any credential value."""
    return [resolve_agent(role) for role in AGENT_ROLES]


def create_agent_adapter(role: str):
    """Build the transport for one role. Returns None for the offline provider.

    Raises ValueError with an actionable (credential-free) message when live is
    requested but the provider is not configured -- never silently falls back.
    """
    info = resolve_agent(role)
    provider = info["provider"]
    if provider == "mock":
        return None
    key = (_agent_value(role, "API_KEY", "AGENT_API_KEY")
           or _agent_value(role, "API_KEY", "OPENAI_API_KEY")
           or _env("MIMO_API_KEY") or _env("DASHSCOPE_API_KEY"))
    if provider == "mimo":
        return MiMoAdapter(api_key=key, base_url=info["base_url"],
                           configured_model_id=info["model_id"])
    from .openai_compatible import OpenAICompatibleAdapter
    if not key and not info["base_url"].startswith(("http://127.0.0.1", "http://localhost")):
        raise ValueError(
            f"{role} 的 {provider} 接口未配置密钥：请设置 {info['env_prefix']}_API_KEY "
            f"或 AGENT_API_KEY（凭据只走进程环境变量，不落盘）")
    return OpenAICompatibleAdapter(api_key=key or None, base_url=info["base_url"],
                                   model_id=info["model_id"])


def agent_model_id(role: str) -> str:
    return resolve_agent(role)["model_id"]
