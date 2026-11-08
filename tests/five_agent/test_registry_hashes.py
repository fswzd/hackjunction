"""收据指纹绑定（F-A5）：prompt_schema_version / 输入变更即收据失效。

新版契约（合并自新版工作台）：
- frozen_input_hash(payload, prompt_schema_version) 把 prompt/schema 冻结版本
  纳入 hash；step_key 的隔离性由收据键 (run_id, step_key, input_hash, attempt)
  结构性保证（见 test_prompt_or_step_change_misses_receipt）。
- step_key_review(version_id) 绑定 REVIEW_PROMPT_SCHEMA_HASH；brief 内容变更
  走 input_hash 门拦截（同 step_key 不同输入不重放），防陈旧审稿/分析重放。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BC_BACKEND = ROOT / "birthco-local" / "backend"

import backend  # noqa: E402
if str(BC_BACKEND) not in backend.__path__:
    backend.__path__.append(str(BC_BACKEND))

from backend.workflow.five_agent import adapters as A  # noqa: E402
from backend.workflow.five_agent.contracts import frozen_input_hash  # noqa: E402
from backend.workflow.five_agent.gateway import AgentGateway  # noqa: E402
from backend.workflow.five_agent.registry import step_key_review  # noqa: E402
from backend.workflow.five_agent.repository import Repository  # noqa: E402

BRIEF_PAYLOAD = {
    "input_mode": "idea", "objective": "目标", "audience": "读者",
    "platform": "图文", "format": "text", "core_promise": "承诺",
    "requirements": [{"id": "r1", "text": "t"}], "material_ids": [],
    "open_questions": [], "route": ["draft"], "length_rule": {},
    "edit_scope": None,
}


def test_frozen_input_hash_binds_prompt_schema_version():
    payload = {"brief_ref": {"task_id": "t1"}}
    base = frozen_input_hash(payload, "seven-agent.v0.1.prompt")
    assert frozen_input_hash(payload, "seven-agent.v0.1.prompt") == base
    # prompt 变更 → hash 变化（收据失效）
    assert frozen_input_hash(payload, "seven-agent.v0.2.prompt") != base
    # 输入变化仍失效（既有不变量）
    assert frozen_input_hash({"brief_ref": {"task_id": "t2"}}, "seven-agent.v0.1.prompt") != base
    # step_key 的失效性由收据键结构保证（不在 hash 内）：见
    # test_prompt_or_step_change_misses_receipt


def test_step_key_review_binds_prompt_schema_hash(monkeypatch):
    from backend.workflow.five_agent import registry
    key_a = step_key_review("ver_1")
    assert key_a == step_key_review("ver_1")
    assert key_a.startswith("review:ver_1:")
    assert key_a == f"review:ver_1:{registry.REVIEW_PROMPT_SCHEMA_HASH[:16]}"
    # prompt/schema 冻结版本变更 → 派生键变化（陈旧审稿收据不得命中）
    monkeypatch.setattr(registry, "REVIEW_PROMPT_SCHEMA_HASH", "f" * 64)
    assert step_key_review("ver_1") != key_a


def _gateway_with_run():
    repo = Repository(":memory:")
    repo.create_task("t1", "acc", {"goal": "g"})
    repo.save_brief("t1", BRIEF_PAYLOAD, [])
    repo.create_run("r1", "t1", "content")
    router = A.AdapterRouter(repo, mode="mock")
    router.bind_task("t1")
    return repo, AgentGateway(repo, router)


def test_brief_change_misses_stale_review_receipt():
    repo, gw = _gateway_with_run()
    payload = {"brief_ref": {"task_id": "t1", "brief_version": 1, "brief_hash": "b" * 64},
               "material_refs": []}
    key = step_key_review("ver_1")
    out1 = gw.invoke("r1", key, "draft", payload,
                     account_id="acc", task_id="t1", prompt_schema_version="v1")
    assert out1.status == "ok" and not out1.replayed
    out2 = gw.invoke("r1", key, "draft", payload,
                     account_id="acc", task_id="t1", prompt_schema_version="v1")
    assert out2.replayed and out2.attempts_used == 0, "同一 key + 同一输入应回放收据"
    # brief 内容变化（brief_hash 变）→ input_hash 门拦截：同 step_key 也不得重放旧收据
    payload_changed = {"brief_ref": {"task_id": "t1", "brief_version": 1, "brief_hash": "c" * 64},
                       "material_refs": []}
    out3 = gw.invoke("r1", key, "draft", payload_changed,
                     account_id="acc", task_id="t1", prompt_schema_version="v1")
    assert not out3.replayed and out3.attempts_used >= 1, "brief 变更后旧收据不得重放"


def test_prompt_or_step_change_misses_receipt():
    repo, gw = _gateway_with_run()
    payload = {"brief_ref": {"task_id": "t1", "brief_version": 1, "brief_hash": "b" * 64},
               "material_refs": []}
    base = gw.invoke("r1", "step_a", "draft", payload,
                     account_id="acc", task_id="t1", prompt_schema_version="v1")
    assert base.status == "ok" and not base.replayed
    again = gw.invoke("r1", "step_a", "draft", payload,
                      account_id="acc", task_id="t1", prompt_schema_version="v1")
    assert again.replayed and again.attempts_used == 0
    # prompt_schema_version 变化 → 不命中
    prompt_changed = gw.invoke("r1", "step_a", "draft", payload,
                               account_id="acc", task_id="t1", prompt_schema_version="v2")
    assert not prompt_changed.replayed, "prompt 变更后旧收据不得重放"
    # step_key 变化 → 不命中
    step_changed = gw.invoke("r1", "step_b", "draft", payload,
                             account_id="acc", task_id="t1", prompt_schema_version="v1")
    assert not step_changed.replayed, "step_key 变更后旧收据不得重放"
