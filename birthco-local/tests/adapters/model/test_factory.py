"""Per-agent .env resolution tests for the unified live model factory.

No network, no real credentials: environment is monkeypatched.
"""
from __future__ import annotations

import pytest

from backend.adapters.model.factory import (
    AGENT_ENV_PREFIXES, create_live_adapter, live_config_report, live_model_id,
)
from backend.adapters.model.mimo import DEFAULT_MODEL_ID


@pytest.fixture()
def clean_env(monkeypatch):
    import backend.adapters.model.factory as factory_mod
    import backend.adapters.model.mimo as mimo_mod
    # 禁用 .env 文件加载：本组测试只验证解析顺序，不受仓库根真实 .env 污染
    monkeypatch.setattr(factory_mod, "_load_env_file", lambda: None)
    monkeypatch.setattr(mimo_mod, "_load_env_file", lambda: None)
    for key in list(__import__("os").environ):
        if key.startswith(("MIMO_", "PR_ANALYST_", "OPERATOR_", "DIRECTOR_",
                           "REVIEWER_", "SCOUT_", "ANALYST_", "AUDIENCE_")):
            monkeypatch.delenv(key, raising=False)
    yield monkeypatch


def test_agent_id_accepts_component_and_contract_names(clean_env):
    assert AGENT_ENV_PREFIXES["operator"] == AGENT_ENV_PREFIXES["operations_officer"] == "OPERATOR"
    assert AGENT_ENV_PREFIXES["content_creator"] == "DIRECTOR"
    assert AGENT_ENV_PREFIXES["simulated_audience"] == "AUDIENCE"
    for name in ("pr_analyst", "operator", "director", "reviewer", "scout",
                 "analyst", "audience", "operations_officer", "traffic_scout"):
        adapter = create_live_adapter(name, api_key="k", configured_model_id="m")
        adapter.close()


def test_unknown_agent_id_rejected(clean_env):
    with pytest.raises(ValueError):
        create_live_adapter("translator")


def test_per_agent_overrides_beat_generic(clean_env):
    clean_env.setenv("MIMO_API_KEY", "generic-key")
    clean_env.setenv("MIMO_MODEL_ID", "generic-model")
    clean_env.setenv("AUDIENCE_API_KEY", "audience-key")
    clean_env.setenv("AUDIENCE_MODEL_ID", "audience-model")
    clean_env.setenv("SCOUT_MODEL_ID", "scout-model")
    assert live_model_id("audience") == "audience-model"
    assert live_model_id("scout") == "scout-model"
    assert live_model_id("analyst") == "generic-model"      # 无单列 → 回退通用
    assert live_model_id() == "generic-model"               # 无 agent → 通用
    with create_live_adapter("audience") as adapter:
        assert adapter._model_id == "audience-model"
        assert adapter._api_key == "audience-key"
    with create_live_adapter("analyst") as adapter:
        assert adapter._api_key == "generic-key"


def test_blank_agent_entry_falls_back_to_generic(clean_env):
    clean_env.setenv("MIMO_MODEL_ID", "generic-model")
    clean_env.setenv("OPERATOR_MODEL_ID", "   ")            # 空白视为未配置
    assert live_model_id("operator") == "generic-model"


def test_builtin_defaults_without_any_env(clean_env):
    clean_env.setenv("MIMO_API_KEY", "k")                   # 仅有密钥
    assert live_model_id("audience") == DEFAULT_MODEL_ID == "mimo-v2.6-pro"
    with create_live_adapter("director") as adapter:
        assert adapter._model_id == DEFAULT_MODEL_ID
        assert adapter._base_url == "https://api.xiaomimimo.com/anthropic"


def test_missing_key_everywhere_is_configuration_error(clean_env):
    from backend.adapters.model.mimo import ModelConfigurationError
    with pytest.raises(ModelConfigurationError):
        create_live_adapter("audience")


def test_config_report_never_leaks_key(clean_env):
    clean_env.setenv("REVIEWER_API_KEY", "super-secret-key")
    report = live_config_report("reviewer")
    assert report["api_key_configured"] is True
    assert "super-secret-key" not in str(report)
    assert report["env_prefix"] == "REVIEWER"


def test_explicit_kwargs_win_over_env(clean_env):
    clean_env.setenv("SCOUT_API_KEY", "env-key")
    with create_live_adapter("scout", api_key="explicit-key",
                             configured_model_id="explicit-model") as adapter:
        assert adapter._api_key == "explicit-key"
        assert adapter._model_id == "explicit-model"
