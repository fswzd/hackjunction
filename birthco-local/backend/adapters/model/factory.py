"""统一 live 模型后端工厂：每个专家 agent 单列 .env 接口配置，缺省回退通用默认。

.env 约定（详见仓库根 .env）：

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

from .mimo import DEFAULT_BASE_URL, DEFAULT_MODEL_ID, MiMoAdapter, _load_env_file

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
    """按 agent 解析 .env 单列配置构造 MiMo 适配器；显式 kwargs 优先级最高。"""
    _load_env_file()
    prefix = _prefix(agent_id)
    api_key = kwargs.pop("api_key", None) or _resolve("API_KEY", prefix, "MIMO_API_KEY", None)
    base_url = kwargs.pop("base_url", None) or _resolve("BASE_URL", prefix, "MIMO_BASE_URL", DEFAULT_BASE_URL)
    model_id = (kwargs.pop("configured_model_id", None)
                or _resolve("MODEL_ID", prefix, "MIMO_MODEL_ID", DEFAULT_MODEL_ID))
    return MiMoAdapter(api_key=api_key, base_url=base_url,
                       configured_model_id=model_id, **kwargs)


def live_model_id(agent_id: str | None = None) -> str:
    _load_env_file()
    prefix = _prefix(agent_id)
    return _resolve("MODEL_ID", prefix, "MIMO_MODEL_ID", DEFAULT_MODEL_ID) or DEFAULT_MODEL_ID


def live_config_report(agent_id: str | None = None) -> dict:
    """脱敏配置一览（永不返回密钥），供检查工具/诊断使用。"""
    _load_env_file()
    prefix = _prefix(agent_id)
    api_key = _resolve("API_KEY", prefix, "MIMO_API_KEY", None)
    return {
        "agent_id": agent_id,
        "env_prefix": prefix or "MIMO（通用默认）",
        "api_key_configured": bool(api_key),
        "base_url": _resolve("BASE_URL", prefix, "MIMO_BASE_URL", DEFAULT_BASE_URL),
        "model_id": _resolve("MODEL_ID", prefix, "MIMO_MODEL_ID", DEFAULT_MODEL_ID),
    }
