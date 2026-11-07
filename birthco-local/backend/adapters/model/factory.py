"""统一 live 模型后端工厂：全部专家 agent 的真实调用经 MiMo（mimo-v2.6-pro）。

方式 A（Python 直调 + 依赖注入）：各 CLI/编排适配器用 `create_live_adapter()`
构造实例后注入 agent；agent 业务代码零改动。
"""

from __future__ import annotations

import os

from .mimo import DEFAULT_MODEL_ID, MiMoAdapter


def create_live_adapter(**kwargs) -> MiMoAdapter:
    return MiMoAdapter(**kwargs)


def live_model_id() -> str:
    return os.environ.get("MIMO_MODEL_ID") or DEFAULT_MODEL_ID
