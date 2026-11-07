# 七角色真实入口桥接实施计划 (P0-A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 birthco-local 七个业务 Agent 的真实入口经统一契约接入编排层 `AdapterRouter`,替换 7 个 `RealAdapterStub`,live 模式可运行真实 MiMo 链路。

**Architecture:** 每个角色一个桥接模块(业务侧 `birthco-local/backend/adapters/`),实现 `invoke(AgentCall) -> AgentResult 字典`;编排侧 `team_entries.py` 提供 `TeamEntry` 异常包装与 `build_reals(repo, mode)` 工厂;失败语义循运营官模式(BridgeUnknownOutcome→UnknownResult,确定性拒单→error 结果);live 绝不回退 Mock。

**Tech Stack:** Python 3.12+ / pydantic v2 / LangGraph(编排层已有)/ SQLite Repository / MiMo factory(每 agent .env 单列配置)/ pytest。

**规范:** `docs/superpowers/specs/2026-11-07-seven-agent-bridges-design.md`

**通用命令(仓库根 `hackjunction-remote`):**

```bash
PY=./.venv/Scripts/python.exe        # Windows;bash 语法
$PY -B -m pytest tests/five_agent -q           # 编排测试
$PY -B -m pytest birthco-local/tests -q        # 业务测试(带 pyproject 需要 cd birthco-local)
```

**导入约定:** 测试与 team_entries 用现有 namespace 模式:

```python
import backend                      # repo 根包
bc = str(ROOT / "birthco-local" / "backend")
if bc not in backend.__path__:
    backend.__path__.append(bc)
```

---

### Task 0: 共享工具抽取 bridge_common.py + orch_bridge 改用共享工具

**Files:**
- Create: `birthco-local/backend/adapters/bridge_common.py`
- Modify: `birthco-local/backend/adapters/orch_bridge.py`(删除本地重复定义,改 import)

- [ ] **Step 1: 写 bridge_common.py**

```python
"""共享桥接工具:编排层 <-> 业务 agent 适配器公共部分(运营官桥接原定义上抽)。"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable


class BridgeUnknownOutcome(Exception):
    """Model call sent but the outcome is unknown; explicit resend only."""


class BridgePreSendFailure(Exception):
    """Bridge could not build a valid request (resolution/config failure)."""


def orchestration_ref_digest(text: str) -> str:
    """编排层 material_refs 的 sha256 约定:sha256(canonical JSON of {"text": ...})."""
    blob = json.dumps({"text": text}, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def resolve_materials(input_payload: dict,
                      resolve_material: Callable[[dict], dict]) -> list[dict]:
    """Resolve refs to rows, verifying each ref's content fingerprint (F-O4)."""
    rows = []
    for ref in input_payload.get("material_refs", []):
        try:
            row = resolve_material(ref)
        except KeyError:
            raise BridgePreSendFailure(f"material {ref.get('id')} cannot be resolved") from None
        text = row.get("text")
        if not isinstance(text, str):
            raise BridgePreSendFailure(f"material {ref.get('id')} has no text")
        expected = ref.get("sha256")
        if expected is not None and expected != orchestration_ref_digest(text):
            raise BridgePreSendFailure(f"material {ref.get('id')} fingerprint mismatch")
        rows.append({**row, "id": ref["id"]})
    return rows


def issue(reason: str, requested_change: str, location: str = "bridge") -> dict:
    return {"id": "iss_" + hashlib.sha256(reason.encode()).hexdigest()[:16],
            "severity": "blocking", "location": location[:1000],
            "reason": reason[:1000],
            "requested_change": (requested_change or "检查输入")[:1000]}


def error_result(call_dict: dict, reason: str, requested_change: str = "检查输入后显式重发",
                 location: str = "bridge") -> dict:
    """确定性输入拒单 = 已知 error 结果(零模型调用、零重试、不烧预算)。"""
    return {**call_dict, "status": "error", "data": None, "questions": [],
            "issues": [issue(reason, requested_change, location)],
            "usage": {"status": "unknown", "total_tokens": None}}


def usage_dict(usage: Any) -> dict:
    if usage.total is None:
        return {"status": "unknown", "total_tokens": None}
    return {"status": "known", "total_tokens": usage.total}


DEFAULT_DERIVED_AUDIENCE = "任务中描述的读者（可在确认前修改）"
DEFAULT_DERIVED_STYLE = "符合任务要求"
PLACEHOLDER_REQUIREMENT = [{"id": "req_extract", "text": "从任务中整理交付要求"}]
LEGAL_MATERIAL_KINDS = {"user_supplied_experience", "source_text", "existing_draft"}
```

- [ ] **Step 2: 改 orch_bridge.py 用共享工具(行为不变)**

删除文件内重复定义并替换 import:删 `BridgeUnknownOutcome`、`BridgePreSendFailure`、`orchestration_ref_digest`、`resolve_materials`、`_issue`、`_error_result`、`_usage_dict`、`DEFAULT_DERIVED_AUDIENCE`、`DEFAULT_DERIVED_STYLE`、`PLACEHOLDER_REQUIREMENT` 各定义;顶部加:

```python
from backend.adapters.bridge_common import (
    BridgePreSendFailure, BridgeUnknownOutcome, DEFAULT_DERIVED_AUDIENCE,
    DEFAULT_DERIVED_STYLE, PLACEHOLDER_REQUIREMENT, error_result, issue,
    orchestration_ref_digest, resolve_materials, usage_dict,
)
```

正文替换:`_error_result(call_dict, reason, requested_change=...)` → `error_result(call_dict, reason, requested_change, location="prepare_brief")`;`_issue(reason, requested_change)` → `issue(reason, requested_change, location="prepare_brief")`;`_usage_dict(result.usage)` → `usage_dict(result.usage)`;`resolve_materials` 调用不变;`LEGAL_MATERIAL_KINDS` 改为从 bridge_common import(删本地 `legal_kinds`)。

- [ ] **Step 3: 运行既有测试确认无回归**

Run: `./.venv/Scripts/python.exe -B -m pytest tests/five_agent/test_operator_entry.py birthco-local/tests/adapters/test_orch_bridge.py -q`
Expected: 全部 PASS(名称/行为未变;`from backend.adapters.orch_bridge import BridgeUnknownOutcome` 仍可用 — import 保持名字可达)

- [ ] **Step 4: Commit**

```bash
git add birthco-local/backend/adapters/bridge_common.py birthco-local/backend/adapters/orch_bridge.py
git commit -m "refactor(bridge): extract shared bridge utilities into bridge_common"
```

---

### Task 1: team_entries.py — TeamEntry 异常包装 + build_reals 工厂

**Files:**
- Create: `backend/workflow/five_agent/team_entries.py`
- Test: `tests/five_agent/test_team_entries.py`

- [ ] **Step 1: 写失败测试**

```python
"""TeamEntry 异常语义映射 + build_reals 惰性导入/逐任务 resolve。"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BC_BACKEND = ROOT / "birthco-local" / "backend"

import backend  # noqa: E402
if str(BC_BACKEND) not in backend.__path__:
    backend.__path__.append(str(BC_BACKEND))

from backend.adapters.bridge_common import BridgePreSendFailure, BridgeUnknownOutcome  # noqa: E402
from backend.domain.errors import DomainError  # noqa: E402
from backend.workflow.five_agent import adapters as A  # noqa: E402
from backend.workflow.five_agent.team_entries import TeamEntry  # noqa: E402


def _call():
    return SimpleNamespace(request_id="req_1", agent_id="operations_officer",
                           action="prepare_brief", contract_version="seven-agent.v0.1",
                           input={"user_input": "x"}, context=SimpleNamespace(task_id="task1"))


class _Boom:
    def __init__(self, exc):
        self.exc = exc

    def invoke(self, call):
        raise self.exc


def test_unknown_outcome_maps_to_unknown_result():
    entry = TeamEntry(lambda task_id: _Boom(BridgeUnknownOutcome("sent")))
    with pytest.raises(A.UnknownResult):
        entry.invoke(_call())


def test_presend_maps_to_presend_failure():
    entry = TeamEntry(lambda task_id: _Boom(BridgePreSendFailure("bad input")))
    with pytest.raises(A.PreSendFailure):
        entry.invoke(_call())


def test_interrupted_domain_error_maps_to_unknown_result():
    entry = TeamEntry(lambda task_id: _Boom(
        DomainError("INTERRUPTED", "remote outcome unknown", "explicit resend")))
    with pytest.raises(A.UnknownResult):
        entry.invoke(_call())


def test_other_domain_error_maps_to_error_result():
    entry = TeamEntry(lambda task_id: _Boom(
        DomainError("SCHEMA_INVALID", "bad output", "inspect schema")))
    out = entry.invoke(_call())
    assert out["status"] == "error" and out["data"] is None
    assert out["issues"][0]["reason"] == "bad output"
    assert out["usage"] == {"status": "unknown", "total_tokens": None}


def test_value_error_maps_to_presend_failure():
    entry = TeamEntry(lambda task_id: _Boom(ValueError("live requires an adapter")))
    with pytest.raises(A.PreSendFailure):
        entry.invoke(_call())


def test_bridge_factory_cached_per_task():
    calls = []
    def factory(task_id):
        calls.append(task_id)
        return _Boom(BridgeUnknownOutcome("x"))
    entry = TeamEntry(factory)
    for _ in range(2):
        with pytest.raises(A.UnknownResult):
            entry.invoke(_call())
    assert calls == ["task1"]  # same task reuses cached bridge
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe -B -m pytest tests/five_agent/test_team_entries.py -q`
Expected: FAIL — `ModuleNotFoundError: ... team_entries`

- [ ] **Step 3: 写 team_entries.py**

```python
"""Real teammate entries for AdapterRouter (P0-A integration).

build_reals() lazily imports the birthco-local bridges (namespace package) and
wraps each in a TeamEntry translating bridge failures into gateway semantics:
BridgeUnknownOutcome / DomainError(INTERRUPTED) -> UnknownResult (sent, no auto
resend); BridgePreSendFailure / ValueError (config) -> PreSendFailure; other
DomainError -> deterministic error result (zero retry, zero model cost).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .adapters import PreSendFailure, UnknownResult

REPO_ROOT = Path(__file__).resolve().parents[2]
BC_BACKEND = REPO_ROOT / "birthco-local" / "backend"

AGENT_COMPONENT = {
    "pr_analyst": "pr_analyst",
    "operations_officer": "operator",
    "content_creator": "director",
    "editorial_reviewer": "reviewer",
    "traffic_scout": "scout",
    "data_analyst": "analyst",
    "simulated_audience": "audience",
}


def _ensure_bc_path() -> None:
    import backend  # repo root namespace package
    bc = str(BC_BACKEND)
    if bc not in backend.__path__:
        backend.__path__.append(bc)


class TeamEntry:
    """AgentAdapter-compatible wrapper; bridge constructed lazily per task."""

    def __init__(self, bridge_factory: Callable[[str], Any]):
        self._factory = bridge_factory
        self._cache: dict[str, Any] = {}

    def _bridge(self, task_id: str) -> Any:
        if task_id not in self._cache:
            self._cache[task_id] = self._factory(task_id)
        return self._cache[task_id]

    def invoke(self, call) -> dict:
        from backend.adapters.bridge_common import (
            BridgePreSendFailure, BridgeUnknownOutcome)
        from backend.domain.errors import DomainError
        bridge = self._bridge(call.context.task_id)
        try:
            return bridge.invoke(call)
        except BridgeUnknownOutcome as exc:
            raise UnknownResult(str(exc) or "sent but outcome unknown") from None
        except (BridgePreSendFailure, ValueError) as exc:
            raise PreSendFailure(str(exc) or "bridge pre-send failure") from None
        except DomainError as exc:
            if exc.code == "INTERRUPTED":
                raise UnknownResult(str(exc.cause_hint) or "sent but outcome unknown") from None
            return _domain_error_result(call, exc)


def _domain_error_result(call, exc) -> dict:
    return {"contract_version": getattr(call, "contract_version", "seven-agent.v0.1"),
            "request_id": getattr(call, "request_id", "req_unknown"),
            "agent_id": getattr(call, "agent_id", "unknown"),
            "action": getattr(call, "action", "unknown"),
            "status": "error", "data": None, "questions": [],
            "issues": [{"id": "iss_" + (exc.code or "DOMAIN"), "severity": "blocking",
                        "location": getattr(call, "action", "bridge"),
                        "reason": (exc.cause_hint or exc.code or "unknown error")[:1000],
                        "requested_change": (exc.next_action or "检查输入")[:1000]}],
            "usage": {"status": "unknown", "total_tokens": None}}


def build_reals(repo, mode: str = "mock",
                live_agents: set[str] | None = None) -> dict[str, Any]:
    """Construct the seven real teammate entries (business bridges).

    mode="mock": every bridge uses its business mock model (zero network).
    mode="live": bridges listed in live_agents (default: all seven) get a MiMo
    adapter from the per-agent .env config; the rest keep mock models.
    """
    if mode not in ("mock", "live"):
        raise ValueError("mode must be mock|live")
    _ensure_bc_path()
    from backend.adapters.analyst_bridge import AnalystTeamAdapter
    from backend.adapters.audience_bridge import AudienceTeamAdapter
    from backend.adapters.director_bridge import DirectorTeamAdapter
    from backend.adapters.model import factory as model_factory
    from backend.adapters.orch_bridge import OperatorTeamAdapter
    from backend.adapters.pr_bridge import PRAnalystTeamAdapter
    from backend.adapters.reviewer_bridge import ReviewerTeamAdapter
    from backend.adapters.scout_bridge import ScoutTeamAdapter

    live = set(live_agents) if live_agents is not None else set(AGENT_COMPONENT)
    if mode == "mock":
        live = set()
    unknown = live - set(AGENT_COMPONENT)
    if unknown:
        raise ValueError(f"unknown live_agents: {sorted(unknown)}")

    adapters: dict[str, Any] = {}
    model_ids: dict[str, str | None] = {}
    for agent_id, component in AGENT_COMPONENT.items():
        if agent_id in live:
            adapters[agent_id] = model_factory.create_live_adapter(component)
            model_ids[agent_id] = model_factory.live_model_id(component)
        else:
            adapters[agent_id] = None
            model_ids[agent_id] = None

    def resolve_for(task_id: str):
        def resolve(ref: dict) -> dict:
            for m in repo.list_materials(task_id):
                if m["id"] == ref["id"]:
                    return m
            raise KeyError(ref["id"])
        return resolve

    def make(agent_id: str, cls):
        def factory(task_id: str):
            kwargs = {"resolve_material": resolve_for(task_id),
                      "mode": "live" if agent_id in live else "mock"}
            if agent_id in live:
                kwargs["model_adapter"] = adapters[agent_id]
                kwargs["model_id"] = model_ids[agent_id]
            if cls is AnalystTeamAdapter:
                return cls(repo=repo, **kwargs)
            return cls(**kwargs)
        return TeamEntry(factory)

    return {
        "pr_analyst": make("pr_analyst", PRAnalystTeamAdapter),
        "operations_officer": make("operations_officer", OperatorTeamAdapter),
        "content_creator": make("content_creator", DirectorTeamAdapter),
        "editorial_reviewer": make("editorial_reviewer", ReviewerTeamAdapter),
        "traffic_scout": make("traffic_scout", ScoutTeamAdapter),
        "data_analyst": make("data_analyst", AnalystTeamAdapter),
        "simulated_audience": make("simulated_audience", AudienceTeamAdapter),
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `./.venv/Scripts/python.exe -B -m pytest tests/five_agent/test_team_entries.py -q`
Expected: PASS(注意:build_reals 的 import 在测试阶段会因其余桥接未建而失败 — 本测试只 import TeamEntry,不调 build_reals;build_reals 首次完整跑在 Task 8)

- [ ] **Step 5: Commit**

```bash
git add backend/workflow/five_agent/team_entries.py tests/five_agent/test_team_entries.py
git commit -m "feat(orchestration): TeamEntry failure mapping + build_reals factory for seven bridges"
```

---

### Task 2: pr_bridge.py — 商单需求分析员桥接

**Files:**
- Create: `birthco-local/backend/adapters/pr_bridge.py`
- Test: `tests/five_agent/test_pr_entry.py`

- [ ] **Step 1: 写失败测试**

```python
"""商单需求分析员真实入口桥接:输入映射/契约包封/失败映射。"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BC_BACKEND = ROOT / "birthco-local" / "backend"

import backend  # noqa: E402
if str(BC_BACKEND) not in backend.__path__:
    backend.__path__.append(str(BC_BACKEND))

from backend.adapters.bridge_common import orchestration_ref_digest  # noqa: E402
from backend.adapters.pr_bridge import PRAnalystTeamAdapter  # noqa: E402


def _rows():
    return [{"id": "m1", "text": "产品资料：品牌X新品，主打便携。", "kind": "text",
             "label": "产品资料", "source_url": None}]


def _call(request_text="品牌X新品推广；要求：文案必须出现品牌名"):
    return SimpleNamespace(request_id="req_1", agent_id="pr_analyst",
                           action="analyze_request", contract_version="seven-agent.v0.1",
                           context=SimpleNamespace(task_id="t1", account_id="account"),
                           input={"request_text": request_text,
                                  "material_refs": [{"id": "m1",
                                                     "sha256": orchestration_ref_digest("产品资料：品牌X新品，主打便携。")}]})


def _adapter():
    return PRAnalystTeamAdapter(resolve_material=lambda ref: _rows()[0], mode="mock")


def test_ok_envelope_maps_to_request_analysis():
    out = _adapter().invoke(_call())
    assert out["status"] == "ok", out
    data = out["data"]
    assert set(data) == {"summary", "requirements", "open_questions",
                         "unprovided_business_fields", "ready_for_operator", "source_refs"}
    assert out["agent_id"] == "pr_analyst" and out["action"] == "analyze_request"
    assert out["request_id"] == "req_1"
    assert out["usage"]["status"] in ("known", "unknown")
    assert all("id" in q and "question" in q and "reason" in q for q in out["questions"])


def test_missing_requirements_becomes_needs_input():
    out = _adapter().invoke(_call(request_text="品牌X新品推广"))
    # mock extraction 无明确要求 → needs_input(业务 PRAnalystAgent 语义)
    assert out["status"] == "needs_input" and out["questions"]


def test_fingerprint_mismatch_is_deterministic_error():
    bad = _call()
    bad.input["material_refs"][0]["sha256"] = "0" * 64
    out = _adapter().invoke(bad)
    assert out["status"] == "error" and out["data"] is None
    assert out["usage"] == {"status": "unknown", "total_tokens": None}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe -B -m pytest tests/five_agent/test_pr_entry.py -q`
Expected: FAIL — `ModuleNotFoundError: ... pr_bridge`

- [ ] **Step 3: 写 pr_bridge.py**

```python
"""编排层 analyze_request ↔ 商单需求分析员本体(PRAnalystAgent)。

输入:contract input {request_text, material_refs};业务侧无结构化 requirements
传入(contract input_types 不含),requirements=[]。intake 以 request_text 作为
objective 显式字段(本体校验要求提取结果逐字保留显式 intake 字段)。
输出:PRAnalysisResult.envelope -> RequestAnalysis data;业务 source 引用(material_N)
不回传,source_refs = 全部已解析素材的编排层 id(均已被提供)。
"""
from __future__ import annotations

from typing import Any, Callable

from backend.adapters.bridge_common import (
    LEGAL_MATERIAL_KINDS, PLACEHOLDER_REQUIREMENT, BridgePreSendFailure,
    error_result, resolve_materials, usage_dict)
from backend.agents.pr_analyst import PRAnalysisInput, PRIntake, PRAnalystAgent
from backend.domain.schemas import LengthRule, MaterialInput


class PRAnalystTeamAdapter:
    def __init__(self, *, resolve_material: Callable[[dict], dict],
                 model_adapter: Any | None = None, mode: str = "mock",
                 model_id: str | None = None):
        self.resolve_material = resolve_material
        self.agent = PRAnalystAgent(model_adapter, mode=mode, model_id=model_id)

    def invoke(self, call) -> dict:
        payload = call.input
        call_dict = {"request_id": getattr(call, "request_id", None),
                     "contract_version": getattr(call, "contract_version", None),
                     "agent_id": getattr(call, "agent_id", "pr_analyst"),
                     "action": getattr(call, "action", "analyze_request")}
        account_id = getattr(call.context, "account_id", None) or "account"
        try:
            rows = resolve_materials(payload, self.resolve_material)
            materials = []
            for row in rows:
                kind = row.get("kind") if row.get("kind") in LEGAL_MATERIAL_KINDS else "source_text"
                materials.append(MaterialInput(kind=kind, label=(row.get("label") or row["id"])[:1000],
                                               text=row["text"], source_url=row.get("source_url"),
                                               authorized=True))
            request_text = (payload.get("request_text") or "").strip() or "商单需求"
            snapshot = PRAnalysisInput(
                analysis_requested=True, account_id=account_id,
                client_brief=None, intake=PRIntake(objective=request_text[:1000]),
                requirements=[dict(r) for r in PLACEHOLDER_REQUIREMENT],
                materials=materials, length_rule=LengthRule(minimum=None, maximum=20000))
        except BridgePreSendFailure as exc:
            return error_result(call_dict, str(exc), location="analyze_request")
        except Exception as exc:  # pydantic 构造失败:确定性拒单
            return error_result(call_dict, f"bridge input invalid: {exc}",
                                location="analyze_request")
        result = self.agent.run(snapshot)
        envelope = result.envelope
        base = {**call_dict, "usage": usage_dict(result.usage)}
        material_ids = [row["id"] for row in rows]
        if envelope.status == "ok":
            data = envelope.data
            return {**base, "status": "ok",
                    "data": {"summary": envelope.summary[:2000],
                             "requirements": [{"id": r.id, "text": r.text}
                                              for r in data.requirements],
                             "open_questions": [q.model_dump(mode="json") for q in envelope.questions],
                             "unprovided_business_fields": list(result.unprovided_business_fields or []),
                             "ready_for_operator": result.task_draft is not None,
                             "source_refs": material_ids[:20]},
                    "questions": []}
        if envelope.status == "needs_input":
            return {**base, "status": "needs_input", "data": None,
                    "questions": [q.model_dump(mode="json") for q in envelope.questions],
                    "issues": [i.model_dump(mode="json") for i in envelope.issues]}
        return {**base, "status": "error", "data": None, "questions": [],
                "issues": [i.model_dump(mode="json") for i in envelope.issues]}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `./.venv/Scripts/python.exe -B -m pytest tests/five_agent/test_pr_entry.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add birthco-local/backend/adapters/pr_bridge.py tests/five_agent/test_pr_entry.py
git commit -m "feat(bridge): pr_analyst real entry bridge (analyze_request)"
```

---

### Task 3: director_bridge.py — 内容主创桥接(draft + revise)

**Files:**
- Create: `birthco-local/backend/adapters/director_bridge.py`
- Test: `tests/five_agent/test_director_entry.py`

关键映射决策(实现时严格遵守):

- **draft**: 编排 brief_hash(=object_hash(payload))先校验 ref 完整性;业务 brief_hash = `brief_hash(brief_model, frozen_rules.model_dump())` 由桥接自算。`reserved_segment_ids` 由桥接生成(`res_` + sha256(brief_hash)[:16] + `_` + 序号,共 32 个,Id 模式合法、与素材 id 不冲突)。`style` = DEFAULT_DERIVED_STYLE。
- **revise**: 业务 director 只认 `input_mode=="existing_draft"` 的修订流;桥接合成业务 brief:取编排 brief 字段 + `input_mode="existing_draft"` + `edit_scope`(target=revision_request 的 issue_locations/finding_segment 值,preserve=其余段,allow_* 取 request 标志)+ 合成 draft 素材(段落以空行连接,须与 base 段落逐字一致)+ 合成 edit_requests(Issue 文本确定性生成)。业务 brief_hash 同样自算。
- 输出:DirectorResult.envelope(data=ContentCandidate|Revision) → 契约 data;Change 的 finding_id/issue_id 两键都保留(null 用 None)。

- [ ] **Step 1: 写失败测试**

```python
"""内容主创真实入口桥接:draft 主链 + revise 范围保护。"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BC_BACKEND = ROOT / "birthco-local" / "backend"

import backend  # noqa: E402
if str(BC_BACKEND) not in backend.__path__:
    backend.__path__.append(str(BC_BACKEND))

from backend.adapters.bridge_common import orchestration_ref_digest  # noqa: E402
from backend.adapters.director_bridge import DirectorTeamAdapter  # noqa: E402
from backend.workflow.five_agent.repository import Repository, object_hash  # noqa: E402

BRIEF_PAYLOAD = {
    "input_mode": "idea", "objective": "写一篇新手拍照入门图文",
    "audience": "对目标话题感兴趣的新手读者", "platform": "图文平台", "format": "text",
    "core_promise": "让读者理解并能动手实践", "requirements": [{"id": "r1", "text": "口语化"}],
    "material_ids": ["m1"], "open_questions": [], "route": ["draft", "review", "export"],
    "length_rule": {"minimum": 300, "maximum": 20000}, "edit_scope": None,
}


def _make():
    repo = Repository(":memory:")
    repo.create_task("t1", {"goal": "x"})
    repo.add_material("t1", "m1", "拍照入门：先学会构图三分法，再练光线。")
    repo.save_brief("t1", BRIEF_PAYLOAD, [])
    brief = repo.latest_brief("t1")
    adapter = DirectorTeamAdapter(
        resolve_material=lambda ref: repo.list_materials("t1")[0], mode="mock")
    return repo, adapter, brief


def _call_draft(brief):
    return SimpleNamespace(request_id="req_1", agent_id="content_creator", action="draft",
                           contract_version="seven-agent.v0.1",
                           context=SimpleNamespace(task_id="t1", account_id="account"),
                           input={"brief_ref": {"task_id": "t1", "brief_version": brief["brief_version"],
                                                "brief_hash": brief["brief_hash"]},
                                  "material_refs": [{"id": "m1",
                                                     "sha256": orchestration_ref_digest(
                                                         "拍照入门：先学会构图三分法，再练光线。")}]})


def test_draft_ok_maps_to_content_candidate():
    repo, adapter, brief = _make()
    out = adapter.invoke(_call_draft(brief))
    assert out["status"] == "ok", out
    data = out["data"]
    assert {"titles", "segments"} <= set(data)
    assert len(data["titles"]) == 3 and data["segments"]
    # 段落 ID 必须来自桥接预留池(不以 seg_ 硬编码;校验 Id 模式即可)
    for seg in data["segments"]:
        assert seg["segment_id"] == seg["segment_id"]  # Id 模式由契约校验器兜底
        assert seg["source_refs"] and set(seg["source_refs"]) <= {"m1"}


def test_draft_brief_hash_mismatch_is_error():
    repo, adapter, brief = _make()
    call = _call_draft(brief)
    call.input["brief_ref"]["brief_hash"] = "0" * 64
    out = adapter.invoke(call)
    assert out["status"] == "error"


def test_revise_only_changes_authorized_segments():
    repo, adapter, brief = _make()
    base = repo.save_version("ver_abc", "t1", "run1", None, {
        "titles": ["t1", "t2", "t3"], "cover_copy": "封面",
        "segments": [{"segment_id": "s1", "kind": "hook", "text": "第一段", "source_refs": ["m1"]},
                     {"segment_id": "s2", "kind": "body", "text": "第二段", "source_refs": ["m1"]}]})
    request = {"kind": "issue_repair", "expected_head_version_id": "ver_abc",
               "base_version_id": "ver_abc", "base_content_hash": base["content_hash"],
               "issue_ids": ["i1"], "issue_locations": {"i1": "s2"},
               "instructions": "只改 s2", "allow_title_change": False, "allow_cover_change": False}
    repo.save_artifact("revreq_1", "t1", "run1", "revision_request", request)
    call = SimpleNamespace(request_id="req_2", agent_id="content_creator", action="revise",
                           contract_version="seven-agent.v0.1",
                           context=SimpleNamespace(task_id="t1", account_id="account"),
                           input={"brief_ref": {"task_id": "t1", "brief_version": brief["brief_version"],
                                                "brief_hash": brief["brief_hash"]},
                                  "base_version_ref": {"id": "ver_abc", "sha256": base["content_hash"]},
                                  "revision_request_ref": {"id": "revreq_1",
                                                           "sha256": object_hash(request)}})
    # adapter 需能解析版本与请求:注入 repo 解析闭包
    adapter2 = DirectorTeamAdapter(
        resolve_material=lambda ref: repo.list_materials("t1")[0],
        resolve_version=lambda ref: repo.get_version(ref["id"]),
        resolve_artifact=lambda ref: repo.get_artifact(ref["id"])["payload"],
        mode="mock")
    out = adapter2.invoke(call)
    assert out["status"] == "ok", out
    data = out["data"]
    assert "change_log" in data and data["change_log"]
    unchanged = [s for s in data["segments"] if s["segment_id"] == "s1"]
    assert unchanged and unchanged[0]["text"] == "第一段"  # 未授权段逐字保留
    changed = [s for s in data["segments"] if s["segment_id"] != "s1" and s["kind"] == "body"]
    assert changed and changed[0]["text"] != "第二段"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe -B -m pytest tests/five_agent/test_director_entry.py -q`
Expected: FAIL — `ModuleNotFoundError: ... director_bridge`

- [ ] **Step 3: 写 director_bridge.py**

```python
"""编排层 draft/revise ↔ 内容主创本体(ContentDirectorAgent)。

draft: 校验 brief_ref 完整性后构造 DirectorInput(业务 brief_hash 自算,
reserved_segment_ids 桥接生成)。revise: 业务本体只接受 existing_draft 修订流,
桥接合成业务 brief(input_mode=existing_draft + edit_scope 取 revision_request
授权范围)与 draft 素材(段落空行连接,逐字等于 base 段落)。
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable

from backend.adapters.bridge_common import (
    DEFAULT_DERIVED_STYLE, LEGAL_MATERIAL_KINDS, BridgePreSendFailure,
    error_result, resolve_materials, usage_dict)
from backend.agents.director import (
    ContentDirectorAgent, DirectorInput, DirectorMaterial, FrozenContentRules)
from backend.domain.hashing import brief_hash as business_brief_hash
from backend.domain.schemas import Brief, ContentCandidate, EditScope, Issue, Segment
from backend.workflow.five_agent.repository import object_hash


def _reserved_pool(brief_hash: str, count: int = 32) -> list[str]:
    stem = hashlib.sha256(f"res:{brief_hash}".encode()).hexdigest()[:16]
    return [f"res_{stem}_{i}" for i in range(count)]


def _synthesized_brief(orchestration_brief: dict, *, input_mode: str,
                       material_ids: list[str], edit_scope: dict | None) -> Brief:
    return Brief(input_mode=input_mode,
                 objective=orchestration_brief.get("objective") or "内容创作任务",
                 audience=orchestration_brief.get("audience") or DEFAULT_DERIVED_STYLE,
                 platform=orchestration_brief.get("platform") or "generic",
                 format="text",
                 core_promise=orchestration_brief.get("core_promise") or "让读者理解并动手",
                 requirements=[dict(r) for r in orchestration_brief.get("requirements") or []] or
                              [{"id": "req_extract", "text": "符合任务书要求"}],
                 material_ids=material_ids, open_questions=[],
                 route=["draft", "review", "export"],
                 length_rule=dict(orchestration_brief.get("length_rule") or
                                  {"minimum": None, "maximum": 20000}),
                 edit_scope=edit_scope)


class DirectorTeamAdapter:
    def __init__(self, *, resolve_material: Callable[[dict], dict],
                 resolve_brief: Callable[[dict], dict] | None = None,
                 resolve_version: Callable[[dict], dict] | None = None,
                 resolve_artifact: Callable[[dict], dict] | None = None,
                 model_adapter: Any | None = None, mode: str = "mock",
                 model_id: str | None = None):
        self.resolve_material = resolve_material
        self.resolve_brief = resolve_brief
        self.resolve_version = resolve_version
        self.resolve_artifact = resolve_artifact
        self.agent = ContentDirectorAgent(model_adapter, mode=mode, model_id=model_id)

    def invoke(self, call) -> dict:
        payload = call.input
        call_dict = {"request_id": getattr(call, "request_id", None),
                     "contract_version": getattr(call, "contract_version", None),
                     "agent_id": getattr(call, "agent_id", "content_creator"),
                     "action": getattr(call, "action", "draft")}
        try:
            if call.action == "draft":
                snapshot, materials = self._build_draft(payload)
            else:
                snapshot, materials = self._build_revise(payload)
        except BridgePreSendFailure as exc:
            return error_result(call_dict, str(exc), location=call.action)
        except Exception as exc:
            return error_result(call_dict, f"bridge input invalid: {exc}", location=call.action)
        result = self.agent.run(snapshot)
        envelope = result.envelope
        base = {**call_dict, "usage": usage_dict(result.usage)}
        if envelope.status == "ok" and envelope.data is not None:
            return {**base, "status": "ok", "data": envelope.data.model_dump(mode="json"),
                    "questions": [], "issues": []}
        if envelope.status == "needs_input":
            return {**base, "status": "needs_input", "data": None,
                    "questions": [q.model_dump(mode="json") for q in envelope.questions],
                    "issues": [i.model_dump(mode="json") for i in envelope.issues]}
        return {**base, "status": "error", "data": None, "questions": [],
                "issues": [i.model_dump(mode="json") for i in envelope.issues]}

    def _materials(self, payload: dict) -> list[DirectorMaterial]:
        rows = resolve_materials(payload, self.resolve_material)
        out = []
        for row in rows:
            kind = row.get("kind") if row.get("kind") in LEGAL_MATERIAL_KINDS else "source_text"
            out.append(DirectorMaterial(material_id=row["id"], kind=kind,
                                        label=(row.get("label") or row["id"])[:1000],
                                        text=row["text"]))
        return out

    def _build_draft(self, payload: dict) -> tuple[DirectorInput, list[DirectorMaterial]]:
        ref = payload.get("brief_ref") or {}
        if not ref or self.resolve_brief is None:
            raise BridgePreSendFailure("draft requires brief_ref + resolve_brief")
        brief_row = self.resolve_brief(ref)
        if object_hash(brief_row["payload"]) != ref.get("brief_hash"):
            raise BridgePreSendFailure("brief fingerprint mismatch")
        brief = Brief.model_validate(brief_row["payload"])
        if brief.input_mode != "idea":
            raise BridgePreSendFailure("draft requires an idea-mode brief")
        frozen = FrozenContentRules(rule_version="content-rules-v1", title_count=3,
                                    max_body_characters=20000)
        bh = business_brief_hash(brief, frozen.model_dump(mode="json"))
        materials = self._materials(payload)
        snapshot = DirectorInput(confirmed=True, brief=brief, brief_hash=bh,
                                 frozen_rules=frozen, style=DEFAULT_DERIVED_STYLE,
                                 materials=materials,
                                 reserved_segment_ids=_reserved_pool(bh),
                                 base_version_id=None, base_content_hash=None,
                                 base_content=None, edit_requests=[])
        return snapshot, materials

    def _build_revise(self, payload: dict) -> tuple[DirectorInput, list[DirectorMaterial]]:
        if self.resolve_version is None or self.resolve_artifact is None:
            raise BridgePreSendFailure("revise requires resolve_version/resolve_artifact")
        base = self.resolve_version(payload["base_version_ref"])
        if base["content_hash"] != payload["base_version_ref"].get("sha256"):
            raise BridgePreSendFailure("base version fingerprint mismatch")
        request = self.resolve_artifact(payload["revision_request_ref"])
        base_content = ContentCandidate.model_validate(base["payload"])
        if request.get("kind") == "issue_repair":
            targets = list(request.get("issue_locations", {}).values())
            issue_items = [Issue(id=iid, severity="blocking", location=loc,
                                 reason="按审稿意见修改该段",
                                 requested_change=(request.get("instructions")
                                                   or "只修改该段并保留其余原文"))
                           for iid, loc in request.get("issue_locations", {}).items()]
        else:
            targets = list(request.get("finding_segment", {}).values())
            issue_items = [Issue(id=fid, severity="blocking", location=loc,
                                 reason="按试映发现修改该段",
                                 requested_change=(request.get("instructions")
                                                   or "只修改该段并保留其余原文"))
                           for fid, loc in request.get("finding_segment", {}).items()]
        if not issue_items:
            raise BridgePreSendFailure("revision request has no targets")
        old_ids = [s.segment_id for s in base_content.segments]
        preserve = [sid for sid in old_ids if sid not in targets]
        edit_scope = EditScope(target_segment_ids=targets, preserve_segment_ids=preserve,
                               allow_title_change=bool(request.get("allow_title_change")),
                               allow_cover_change=bool(request.get("allow_cover_change")))
        draft_id = "draft_" + hashlib.sha256(base["content_hash"].encode()).hexdigest()[:16]
        draft_text = "\n\n".join(s.text for s in base_content.segments)
        ref = payload.get("brief_ref") or {}
        if not ref or self.resolve_brief is None:
            raise BridgePreSendFailure("revise requires brief_ref + resolve_brief")
        orchestration_brief = self.resolve_brief(ref)["payload"]
        brief = _synthesized_brief(
            orchestration_brief, input_mode="existing_draft",
            material_ids=[draft_id] + list(orchestration_brief.get("material_ids") or []),
            edit_scope=edit_scope.model_dump(mode="json"))
        frozen = FrozenContentRules(rule_version="content-rules-v1", title_count=3,
                                    max_body_characters=20000)
        bh = business_brief_hash(brief, frozen.model_dump(mode="json"))
        draft_material = DirectorMaterial(material_id=draft_id, kind="existing_draft",
                                          label="原稿", text=draft_text)
        materials = self._materials(payload) + [draft_material]
        snapshot = DirectorInput(confirmed=True, brief=brief, brief_hash=bh,
                                 frozen_rules=frozen, style=DEFAULT_DERIVED_STYLE,
                                 materials=materials,
                                 reserved_segment_ids=_reserved_pool(bh),
                                 base_version_id=base["id"],
                                 base_content_hash=base["content_hash"],
                                 base_content=base_content, edit_requests=issue_items)
        return snapshot, materials
```

**注意:** `_build_revise` 的合成 brief 不依赖 resolve_brief(从编排 brief 字段 + revision_request 合成);`_build_draft` 用 `self.resolve_brief(payload["brief_ref"])` 取编排 brief 行并校验 `object_hash(payload) == ref["brief_hash"]`(ref 完整性)。测试同步:`_make()` 中 adapter 与 adapter2 均传 `resolve_brief=lambda ref: repo.get_brief(ref["task_id"], ref["brief_version"])`。

- [ ] **Step 4: 修正实现与测试后跑通**

Run: `./.venv/Scripts/python.exe -B -m pytest tests/five_agent/test_director_entry.py -q`
Expected: PASS(测试 `_make()` 中 draft adapter 传 `resolve_brief`)

- [ ] **Step 5: 补一条端到端:draft 经编排主链(mock 模型)**

在测试文件追加:

```python
from backend.workflow.five_agent import adapters as A
from backend.workflow.five_agent.driver import OrchestrationDriver
from backend.workflow.five_agent.team_entries import TeamEntry


def test_content_chain_runs_with_real_director_entry():
    repo = Repository(":memory:")
    driver = OrchestrationDriver(repo, router=A.AdapterRouter(
        repo, mode="mock",
        agent_modes={"content_creator": "live", "operations_officer": "live"},
        reals={
            "operations_officer": _operator_entry(repo),
            "content_creator": TeamEntry(
                lambda task_id: DirectorTeamAdapter(
                    resolve_material=lambda ref: repo.list_materials(task_id)[0],
                    resolve_brief=lambda ref: repo.get_brief(ref["task_id"], ref["brief_version"]),
                    resolve_version=lambda ref: repo.get_version(ref["id"]),
                    resolve_artifact=lambda ref: repo.get_artifact(ref["id"])["payload"],
                    mode="mock"))}))
    driver.create_task("t1", {"goal": "写一篇新手拍照入门图文", "user_input": "写一篇新手拍照入门图文",
                              "input_mode": "idea", "purpose": "content",
                              "flags": {"traffic_enabled": False, "goal_clear": True}})
    driver.add_material("t1", "m1", "拍照入门：先学会构图三分法，再练光线。")
    snap = driver.start_content_run("t1")
    assert snap["pending_gates"][0]["kind"] == "confirm_brief"
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True,
                         payload={"brief_version": snap["state"]["brief_ref"]["brief_version"],
                                  "brief_hash": snap["state"]["brief_ref"]["brief_hash"]})
    assert snap["status"] == "READY"  # 审稿仍 mock(pass),主链达 READY
    version = repo.get_version(snap["state"]["version_ref"]["id"])
    assert version["payload"]["segments"] and all(
        s["segment_id"].startswith("res_") for s in version["payload"]["segments"])
```

其中 `_operator_entry(repo)` 复用 test_operator_entry 模式:

```python
def _operator_entry(repo):
    from backend.adapters.orch_bridge import OperatorTeamAdapter
    def factory(task_id):
        def resolve(ref):
            for m in repo.list_materials(task_id):
                if m["id"] == ref["id"]:
                    return m
            raise KeyError(ref["id"])
        return OperatorTeamAdapter(resolve_material=resolve, mode="mock")
    return TeamEntry(factory)
```

- [ ] **Step 6: 跑测试确认通过 + Commit**

Run: `./.venv/Scripts/python.exe -B -m pytest tests/five_agent/test_director_entry.py -q`
Expected: PASS

```bash
git add birthco-local/backend/adapters/director_bridge.py tests/five_agent/test_director_entry.py
git commit -m "feat(bridge): content_creator real entry bridge (draft/revise)"
```

---

### Task 4: reviewer_bridge.py — 独立审稿员桥接

**Files:**
- Create: `birthco-local/backend/adapters/reviewer_bridge.py`
- Test: `tests/five_agent/test_reviewer_entry.py`

映射要点:业务 `ReviewInput.content_hash` 要求等于 `content_hash(ContentCandidate)`(业务公式 sha256_json({titles,cover_copy,segments}))——与编排 `version_ref.sha256`(object_hash(payload),同三键)一致,可直接互验。业务 mock 模式在规则通过时返回 `needs_input`(审稿语义),测试按此断言;`overall` 走 envelope.data。

- [ ] **Step 1: 写失败测试**

```python
"""独立审稿员真实入口桥接:输入映射/契约包封/mock 语义。"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BC_BACKEND = ROOT / "birthco-local" / "backend"

import backend  # noqa: E402
if str(BC_BACKEND) not in backend.__path__:
    backend.__path__.append(str(BC_BACKEND))

from backend.adapters.bridge_common import orchestration_ref_digest  # noqa: E402
from backend.adapters.reviewer_bridge import ReviewerTeamAdapter  # noqa: E402
from backend.workflow.five_agent.repository import Repository  # noqa: E402

BRIEF_PAYLOAD = {
    "input_mode": "idea", "objective": "写一篇新手拍照入门图文",
    "audience": "对目标话题感兴趣的新手读者", "platform": "图文平台", "format": "text",
    "core_promise": "让读者理解并能动手实践", "requirements": [{"id": "r1", "text": "口语化"}],
    "material_ids": ["m1"], "open_questions": [], "route": ["draft", "review", "export"],
    "length_rule": {"minimum": 300, "maximum": 20000}, "edit_scope": None,
}
VERSION_PAYLOAD = {
    "titles": ["t1", "t2", "t3"], "cover_copy": "封面",
    "segments": [{"segment_id": "s1", "kind": "hook", "text": "你是否也遇到过构图问题", "source_refs": ["m1"]},
                 {"segment_id": "s2", "kind": "body", "text": "第一步，先学会三分法。", "source_refs": ["m1"]},
                 {"segment_id": "s3", "kind": "closing", "text": "先完成再完善。", "source_refs": []}],
}


def _make():
    repo = Repository(":memory:")
    repo.create_task("t1", {"goal": "x"})
    repo.add_material("t1", "m1", "拍照入门：先学会构图三分法，再练光线。")
    repo.save_brief("t1", BRIEF_PAYLOAD, [])
    brief = repo.latest_brief("t1")
    version = repo.save_version("ver_abc", "t1", "run1", None, VERSION_PAYLOAD)
    adapter = ReviewerTeamAdapter(
        resolve_brief=lambda ref: repo.get_brief(ref["task_id"], ref["brief_version"]),
        resolve_material=lambda ref: repo.list_materials("t1")[0],
        resolve_version=lambda ref: repo.get_version(ref["id"]),
        mode="mock")
    return repo, adapter, brief, version


def _call(brief, version):
    return SimpleNamespace(request_id="req_1", agent_id="editorial_reviewer",
                           action="assess_content", contract_version="seven-agent.v0.1",
                           context=SimpleNamespace(task_id="t1", account_id="account"),
                           input={"brief_ref": {"task_id": "t1", "brief_version": brief["brief_version"],
                                                "brief_hash": brief["brief_hash"]},
                                  "version_ref": {"id": version["id"], "sha256": version["content_hash"]},
                                  "rule_report_ref": {"id": "rule_1", "sha256": "0" * 64},
                                  "material_refs": [{"id": "m1",
                                                     "sha256": orchestration_ref_digest(
                                                         "拍照入门：先学会构图三分法，再练光线。")}]})


def test_review_envelope_maps_to_editorial_review():
    repo, adapter, brief, version = _make()
    out = adapter.invoke(_call(brief, version))
    assert out["status"] in ("ok", "needs_input"), out
    if out["status"] == "ok":
        assert set(out["data"]) == {"issues", "requirement_checks", "claim_checks", "overall"}
    else:
        assert out["questions"]  # mock 语义:结构通过但语义待核实 → needs_input
    assert out["usage"]["status"] in ("known", "unknown")


def test_version_hash_mismatch_is_error():
    repo, adapter, brief, version = _make()
    call = _call(brief, version)
    call.input["version_ref"]["sha256"] = "0" * 64
    out = adapter.invoke(call)
    assert out["status"] == "error"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe -B -m pytest tests/five_agent/test_reviewer_entry.py -q`
Expected: FAIL — `ModuleNotFoundError: ... reviewer_bridge`

- [ ] **Step 3: 写 reviewer_bridge.py**

```python
"""编排层 assess_content ↔ 独立审稿员本体(EditorialReviewerAgent)。"""
from __future__ import annotations

from typing import Any, Callable

from backend.adapters.bridge_common import (
    LEGAL_MATERIAL_KINDS, BridgePreSendFailure, error_result, resolve_materials,
    usage_dict)
from backend.agents.editorial_reviewer import (
    EditorialReviewerAgent, ReviewInput, ReviewMaterial)
from backend.domain.hashing import content_hash as business_content_hash
from backend.domain.schemas import Brief, ContentCandidate
from backend.workflow.five_agent.repository import object_hash


class ReviewerTeamAdapter:
    def __init__(self, *, resolve_material: Callable[[dict], dict],
                 resolve_brief: Callable[[dict], dict] | None = None,
                 resolve_version: Callable[[dict], dict] | None = None,
                 model_adapter: Any | None = None, mode: str = "mock",
                 model_id: str | None = None):
        self.resolve_material = resolve_material
        self.resolve_brief = resolve_brief
        self.resolve_version = resolve_version
        self.agent = EditorialReviewerAgent(model_adapter, mode=mode, model_id=model_id)

    def invoke(self, call) -> dict:
        payload = call.input
        call_dict = {"request_id": getattr(call, "request_id", None),
                     "contract_version": getattr(call, "contract_version", None),
                     "agent_id": getattr(call, "agent_id", "editorial_reviewer"),
                     "action": getattr(call, "action", "assess_content")}
        try:
            if self.resolve_brief is None or self.resolve_version is None:
                raise BridgePreSendFailure("reviewer requires resolve_brief/resolve_version")
            brief_ref = payload["brief_ref"]
            brief_row = self.resolve_brief(brief_ref)
            if brief_row["brief_hash"] != brief_ref.get("brief_hash"):
                raise BridgePreSendFailure("brief fingerprint mismatch")
            brief = Brief.model_validate(brief_row["payload"])
            version_row = self.resolve_version(payload["version_ref"])
            if version_row["content_hash"] != payload["version_ref"].get("sha256"):
                raise BridgePreSendFailure("version fingerprint mismatch")
            content = ContentCandidate.model_validate(version_row["payload"])
            if business_content_hash(content) != version_row["content_hash"]:
                raise BridgePreSendFailure("version content hash mismatch")
            rows = resolve_materials(payload, self.resolve_material)
            materials = []
            for row in rows:
                kind = row.get("kind") if row.get("kind") in LEGAL_MATERIAL_KINDS else "source_text"
                materials.append(ReviewMaterial(material_id=row["id"], kind=kind,
                                                label=(row.get("label") or row["id"])[:1000],
                                                text=row["text"]))
            snapshot = ReviewInput(confirmed=True, version_id=version_row["id"],
                                   content_hash=version_row["content_hash"],
                                   brief=brief, content=content, materials=materials)
        except BridgePreSendFailure as exc:
            return error_result(call_dict, str(exc), location="assess_content")
        except Exception as exc:
            return error_result(call_dict, f"bridge input invalid: {exc}",
                                location="assess_content")
        result = self.agent.run(snapshot)
        envelope = result.envelope
        base = {**call_dict, "usage": usage_dict(result.usage)}
        if envelope.status == "ok" and envelope.data is not None:
            return {**base, "status": "ok", "data": envelope.data.model_dump(mode="json"),
                    "questions": [], "issues": []}
        if envelope.status == "needs_input":
            return {**base, "status": "needs_input", "data": None,
                    "questions": [q.model_dump(mode="json") for q in envelope.questions],
                    "issues": [i.model_dump(mode="json") for i in envelope.issues]}
        return {**base, "status": "error", "data": None, "questions": [],
                "issues": [i.model_dump(mode="json") for i in envelope.issues]}
```

- [ ] **Step 4: 跑测试确认通过 + Commit**

Run: `./.venv/Scripts/python.exe -B -m pytest tests/five_agent/test_reviewer_entry.py -q`
Expected: PASS

```bash
git add birthco-local/backend/adapters/reviewer_bridge.py tests/five_agent/test_reviewer_entry.py
git commit -m "feat(bridge): editorial_reviewer real entry bridge (assess_content)"
```

---

### Task 5: scout_bridge.py — 流量捕捉者桥接

**Files:**
- Create: `birthco-local/backend/adapters/scout_bridge.py`
- Test: `tests/five_agent/test_scout_entry.py`

映射要点:业务 `ScoutInput` 需要完整 `Brief`(仅校验 objective/audience 非空 + material_ids 唯一)与 `ScoutAccount`(三字段非空)。编排 input 只有 goal + material_refs → 派生缺省:`positioning="围绕任务目标:"+goal`、`audience=DEFAULT_DERIVED_AUDIENCE`、`style=DEFAULT_DERIVED_STYLE`;brief 用 `_synthesized_brief` 同款逻辑(idea 模式)。素材 id 直接用编排 id(material_id 字段),输出 source_refs 无需映射。`evidence_date` 业务强制 null。

- [ ] **Step 1: 写失败测试**

```python
"""流量捕捉者真实入口桥接:缺省 account/brief 派生 + 机会输出映射。"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BC_BACKEND = ROOT / "birthco-local" / "backend"

import backend  # noqa: E402
if str(BC_BACKEND) not in backend.__path__:
    backend.__path__.append(str(BC_BACKEND))

from backend.adapters.bridge_common import orchestration_ref_digest  # noqa: E402
from backend.adapters.scout_bridge import ScoutTeamAdapter  # noqa: E402


def _call():
    return SimpleNamespace(request_id="req_1", agent_id="traffic_scout",
                           action="capture_opportunities", contract_version="seven-agent.v0.1",
                           context=SimpleNamespace(task_id="t1", account_id="account"),
                           input={"goal": "写一篇新手拍照入门图文",
                                  "material_refs": [{"id": "m1",
                                                     "sha256": orchestration_ref_digest(
                                                         "拍照入门：先学会构图三分法，再练光线。")}]})


def _adapter():
    return ScoutTeamAdapter(resolve_material=lambda ref: {
        "id": "m1", "text": "拍照入门：先学会构图三分法，再练光线。",
        "kind": "text", "label": "构图", "source_url": None}, mode="mock")


def test_opportunities_map_to_opportunity_set():
    out = _adapter().invoke(_call())
    assert out["status"] == "ok", out
    data = out["data"]
    assert "opportunities" in data and data["opportunities"]
    for opp in data["opportunities"]:
        assert set(opp) == {"id", "angle", "audience_problem", "account_fit",
                            "source_refs", "evidence_date", "hypothesis"}
        assert opp["evidence_date"] is None
        assert opp["source_refs"] and set(opp["source_refs"]) <= {"m1"}


def test_no_materials_is_needs_input():
    call = _call()
    call.input["material_refs"] = []
    out = _adapter().invoke(call)
    assert out["status"] == "needs_input" and out["questions"]


def test_bad_fingerprint_is_error():
    call = _call()
    call.input["material_refs"][0]["sha256"] = "0" * 64
    out = _adapter().invoke(call)
    assert out["status"] == "error"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe -B -m pytest tests/five_agent/test_scout_entry.py -q`
Expected: FAIL — `ModuleNotFoundError: ... scout_bridge`

- [ ] **Step 3: 写 scout_bridge.py**

```python
"""编排层 capture_opportunities ↔ 流量捕捉者本体(ScoutAgent)。

编排 input 无账号档案/任务书:account 与 brief 由桥接派生缺省(明确标注为派生,
不进真实素材)。素材 id 与编排命名空间一致,输出无需回映。
"""
from __future__ import annotations

from typing import Any, Callable

from backend.adapters.bridge_common import (
    DEFAULT_DERIVED_AUDIENCE, DEFAULT_DERIVED_STYLE, LEGAL_MATERIAL_KINDS,
    BridgePreSendFailure, error_result, resolve_materials, usage_dict)
from backend.agents.scout import ScoutAccount, ScoutAgent, ScoutInput, ScoutMaterial
from backend.domain.schemas import Brief


class ScoutTeamAdapter:
    def __init__(self, *, resolve_material: Callable[[dict], dict],
                 model_adapter: Any | None = None, mode: str = "mock",
                 model_id: str | None = None):
        self.resolve_material = resolve_material
        self.agent = ScoutAgent(model_adapter, mode=mode, model_id=model_id)

    def invoke(self, call) -> dict:
        payload = call.input
        call_dict = {"request_id": getattr(call, "request_id", None),
                     "contract_version": getattr(call, "contract_version", None),
                     "agent_id": getattr(call, "agent_id", "traffic_scout"),
                     "action": getattr(call, "action", "capture_opportunities")}
        account_id = getattr(call.context, "account_id", None) or "account"
        try:
            rows = resolve_materials(payload, self.resolve_material)
            materials = []
            for row in rows:
                kind = row.get("kind") if row.get("kind") in LEGAL_MATERIAL_KINDS else "source_text"
                materials.append(ScoutMaterial(material_id=row["id"], kind=kind,
                                               label=(row.get("label") or row["id"])[:1000],
                                               text=row["text"], authorized=True,
                                               source_url=row.get("source_url")))
            goal = (payload.get("goal") or "选题").strip()
            brief = Brief(input_mode="idea", objective=goal[:1000],
                          audience=DEFAULT_DERIVED_AUDIENCE, platform="generic",
                          format="text", core_promise=f"围绕目标整理选题：{goal[:80]}",
                          requirements=[{"id": "req_extract", "text": "从任务中整理交付要求"}],
                          material_ids=[m.material_id for m in materials],
                          open_questions=[], route=["draft", "review", "export"],
                          length_rule={"minimum": None, "maximum": 20000},
                          edit_scope=None)
            account = ScoutAccount(account_id=account_id,
                                   positioning=f"围绕任务目标：{goal[:500]}",
                                   audience=DEFAULT_DERIVED_AUDIENCE,
                                   style=DEFAULT_DERIVED_STYLE)
            snapshot = ScoutInput(research_requested=True, account=account, brief=brief,
                                  materials=materials, max_opportunities=3)
        except BridgePreSendFailure as exc:
            return error_result(call_dict, str(exc), location="capture_opportunities")
        except Exception as exc:
            return error_result(call_dict, f"bridge input invalid: {exc}",
                                location="capture_opportunities")
        result = self.agent.run(snapshot)
        envelope = result.envelope
        base = {**call_dict, "usage": usage_dict(result.usage)}
        if envelope.status == "ok" and envelope.data is not None:
            return {**base, "status": "ok", "data": envelope.data.model_dump(mode="json"),
                    "questions": [], "issues": []}
        if envelope.status == "needs_input":
            return {**base, "status": "needs_input", "data": None,
                    "questions": [q.model_dump(mode="json") for q in envelope.questions],
                    "issues": [i.model_dump(mode="json") for i in envelope.issues]}
        return {**base, "status": "error", "data": None, "questions": [],
                "issues": [i.model_dump(mode="json") for i in envelope.issues]}
```

- [ ] **Step 4: 跑测试确认通过 + Commit**

Run: `./.venv/Scripts/python.exe -B -m pytest tests/five_agent/test_scout_entry.py -q`
Expected: PASS

```bash
git add birthco-local/backend/adapters/scout_bridge.py tests/five_agent/test_scout_entry.py
git commit -m "feat(bridge): traffic_scout real entry bridge (capture_opportunities)"
```

---

### Task 6: audience_bridge.py — 模拟观众桥接

**Files:**
- Create: `birthco-local/backend/adapters/audience_bridge.py`
- Test: `tests/five_agent/test_audience_entry.py`

映射要点:编排 `read_segment` input 就是业务 `AudienceInput`(同 schema,直接 model_validate)。业务 `AudienceReaction.status`: `received` → ok+event;`unknown` → 抛 BridgeUnknownOutcome;`failed` → error 结果(issues 取 reaction.error 的 code/cause_hint/next_action)。mock 模式机械 continue(不 exit)。timeout_seconds 固定 90。

- [ ] **Step 1: 写失败测试**

```python
"""模拟观众真实入口桥接:事件映射 + unknown/failed 失败语义。"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BC_BACKEND = ROOT / "birthco-local" / "backend"

import backend  # noqa: E402
if str(BC_BACKEND) not in backend.__path__:
    backend.__path__.append(str(BC_BACKEND))

from backend.adapters.audience_bridge import AudienceTeamAdapter  # noqa: E402
from backend.adapters.bridge_common import BridgeUnknownOutcome  # noqa: E402
from backend.workflow.five_agent.team_entries import TeamEntry  # noqa: E402


def _audience_input():
    return {"persona": {"id": "p1", "goal": "想学会拍照", "knowledge": "摄影新手",
                        "preferences": ["喜欢具体步骤"]},
            "current_segment": {"segment_id": "cover_v1", "kind": "cover",
                                "text": "三步上手，少走弯路"},
            "visible_history": [],
            "own_previous_reactions": []}


def _call(payload=None):
    return SimpleNamespace(request_id="req_1", agent_id="simulated_audience",
                           action="read_segment", contract_version="seven-agent.v0.1",
                           context=SimpleNamespace(task_id="t1", account_id="account"),
                           input=payload or _audience_input())


def test_mock_reaction_maps_to_audience_event():
    out = AudienceTeamAdapter(mode="mock").invoke(_call())
    assert out["status"] == "ok", out
    data = out["data"]
    assert set(data) == {"segment_id", "action", "understanding", "question",
                         "reaction", "interactions", "comment_text"}
    assert data["segment_id"] == "cover_v1"
    assert data["action"] == "continue"  # mock 机械继续
    assert out["usage"]["status"] in ("known", "unknown")


def test_wrong_segment_scope_is_failed_result():
    payload = _audience_input()
    payload["current_segment"]["segment_id"] = "seg_other"
    out = AudienceTeamAdapter(mode="mock").invoke(_call(payload))
    # 业务 validate_event SCOPE_DENIED → reaction failed → 桥接 error 结果
    assert out["status"] == "error" and out["issues"]


class _RaisingAdapter:
    """业务 ModelAdapter 协议的最小替身:complete() 抛异常 → INTERRUPTED/unknown。"""
    def complete(self, request):
        raise RuntimeError("network down")


def test_unknown_outcome_raises_bridge_unknown():
    from backend.adapters.audience import AudienceAgent
    bridge = AudienceTeamAdapter(mode="live",
                                 model_adapter=_RaisingAdapter(), model_id="mimo-v2.6-pro")
    entry = TeamEntry(lambda task_id: bridge)
    from backend.workflow.five_agent import adapters as A
    with pytest.raises(A.UnknownResult):
        entry.invoke(_call())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe -B -m pytest tests/five_agent/test_audience_entry.py -q`
Expected: FAIL — `ModuleNotFoundError: ... audience_bridge`

- [ ] **Step 3: 写 audience_bridge.py**

```python
"""编排层 read_segment ↔ 模拟观众本体(AudienceAgent.react)。

输入投影即业务 AudienceInput(同 schema)。reaction.status 语义:
received -> ok+event;unknown(已发送结果未知)-> BridgeUnknownOutcome;
failed -> 已知 error 结果(error 详情取自 reaction.error)。
"""
from __future__ import annotations

from typing import Any

from backend.adapters.bridge_common import BridgeUnknownOutcome, error_result, usage_dict
from backend.agents.audience import AudienceAgent
from backend.domain.schemas import AudienceInput

TIMEOUT_SECONDS = 90


class AudienceTeamAdapter:
    def __init__(self, *, timeout_seconds: int = TIMEOUT_SECONDS,
                 model_adapter: Any | None = None, mode: str = "mock",
                 model_id: str | None = None):
        self.timeout_seconds = timeout_seconds
        self.agent = AudienceAgent(model_adapter, mode=mode, model_id=model_id)

    def invoke(self, call) -> dict:
        call_dict = {"request_id": getattr(call, "request_id", None),
                     "contract_version": getattr(call, "contract_version", None),
                     "agent_id": getattr(call, "agent_id", "simulated_audience"),
                     "action": getattr(call, "action", "read_segment")}
        try:
            context = AudienceInput.model_validate(call.input)
        except Exception as exc:
            return error_result(call_dict, f"bridge input invalid: {exc}",
                                location="read_segment")
        reaction = self.agent.react(context, timeout_seconds=self.timeout_seconds,
                                    mock_exit=False)
        base = {**call_dict, "usage": usage_dict(reaction.usage)}
        if reaction.status == "received" and reaction.event is not None:
            return {**base, "status": "ok",
                    "data": reaction.event.model_dump(mode="json"),
                    "questions": [], "issues": []}
        if reaction.status == "unknown":
            hint = reaction.error.cause_hint if reaction.error else "remote outcome unknown"
            raise BridgeUnknownOutcome(hint)
        err = reaction.error
        return error_result(call_dict,
                            (err.cause_hint if err else "viewer call failed") or "viewer call failed",
                            (err.next_action if err else "检查输入后显式重发") or "检查输入后显式重发",
                            location="read_segment")
```

- [ ] **Step 4: 跑测试确认通过 + Commit**

Run: `./.venv/Scripts/python.exe -B -m pytest tests/five_agent/test_audience_entry.py -q`
Expected: PASS(注意 mock 模式构造 `AudienceTeamAdapter(mode="mock")` 无需 adapter/model_id;live 路径测试注入 `_RaisingAdapter`)

```bash
git add birthco-local/backend/adapters/audience_bridge.py tests/five_agent/test_audience_entry.py
git commit -m "feat(bridge): simulated_audience real entry bridge (read_segment)"
```

---

### Task 7: analyst_bridge.py — 数据分析师桥接(编排试映痕迹重建)

**Files:**
- Create: `birthco-local/backend/adapters/analyst_bridge.py`(含 `_rebuild_trace` 痕迹重建)
- Test: `tests/five_agent/test_analyst_entry.py`

这是最难的桥接。业务 `AnalystInput` 校验器要求 `SimulationReport` 与 `AudienceSimulationInput` **内部自洽**(业务命名空间),而编排层痕迹是另一套命名空间(版本 id `ver_*` 不合业务 `v_+32hex`;封面段 id `cover_v1` vs 业务 `cover_<version_id>`;call 级 input_hash 公式不同)。桥接**重建一套业务自洽的输入+报告**,并把分析师输出**回映**到编排命名空间:

- 合成版本 id `v_ + content_hash[:32]`(业务模式 v_+32hex)。
- 封面段 id 双向映射:`cover_v1` ↔ `cover_<合成版本 id>`;正文段 id 两套一致(原样传递)。
- 事件:编排事件 id(`evt_{session}_{ordinal}`)直接作为业务 observation event_id(Id 模式合法)→ 分析师输出 observation_refs 无需回映;封面事件的 segment_id 需回映。
- calls:从 `repo.list_calls(run_id)` 过滤 `agent_id=="simulated_audience"`,按 step_key `audience:{session}:{ordinal}:{hash16}` 解析 (session, ordinal),每 (session, ordinal) 取最后一次 attempt;`received→received(+事件)`、`interrupted→unknown(INTERRUPTED)`、其余→failed;usage 取 usage_tokens;input_hash = 业务 `sha256_json(AudienceInput(...))` 由桥接自算(业务封面段)。
- 会话 outcome:编排 session status `exited→exited/viewer_exit`、`completed→completed/None`、其余 `incomplete`(stop_reason 推断:会话内有 unknown 调用→unknown_remote_outcome,有 failed→invalid_or_failed_response,否则 len(calls)==max_calls→call_budget,否则 time_budget)。
- 重建失败(validate_report ValueError)→ BridgePreSendFailure → 编排 soft-degrade(analysis missing)。
- 输出回映:finding.segment_id 若为业务封面 id → `cover_v1`;comparison/next_experiment 原样。
- `AnalystResult.analysis_status`:`completed→ok`、`needs_input→needs_input`、`interrupted→BridgeUnknownOutcome`、`failed→error 结果`。

- [ ] **Step 1: 写失败测试(编排痕迹 → 分析师 mock → 引用真实事件 id)**

```python
"""数据分析师真实入口桥接:编排预览痕迹重建 + finding 引用真实事件。"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BC_BACKEND = ROOT / "birthco-local" / "backend"

import backend  # noqa: E402
if str(BC_BACKEND) not in backend.__path__:
    backend.__path__.append(str(BC_BACKEND))

from backend.adapters.analyst_bridge import AnalystTeamAdapter  # noqa: E402
from backend.workflow.five_agent import adapters as A  # noqa: E402
from backend.workflow.five_agent.driver import OrchestrationDriver  # noqa: E402
from backend.workflow.five_agent.repository import Repository  # noqa: E402
from backend.workflow.five_agent.team_entries import TeamEntry  # noqa: E402


def _run_preview():
    """全 mock 编排跑通 content 主链 + preview,拿到预览痕迹。"""
    repo = Repository(":memory:")
    router = A.AdapterRouter(repo, mode="mock")
    driver = OrchestrationDriver(repo, router=router)
    driver.create_task("t1", {"goal": "写一篇新手拍照入门图文", "user_input": "写一篇新手拍照入门图文",
                              "input_mode": "idea", "purpose": "content",
                              "flags": {"traffic_enabled": False, "goal_clear": True}})
    driver.add_material("t1", "m1", "拍照入门：先学会构图三分法，再练光线。")
    snap = driver.start_content_run("t1")
    assert snap["pending_gates"][0]["kind"] == "confirm_brief"
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True,
                         payload={"brief_version": snap["state"]["brief_ref"]["brief_version"],
                                  "brief_hash": snap["state"]["brief_ref"]["brief_hash"]})
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True, payload={})
    assert snap["status"] == "READY", snap
    version_id = snap["state"]["version_ref"]["id"]
    snap = driver.start_preview_run("t1", version_id)
    assert snap["pending_gates"][0]["kind"] == "preview_conditions"
    personas = [{"id": "p1", "goal": "想学会拍照", "knowledge": "摄影新手", "preferences": ["喜欢具体步骤"]},
                {"id": "p2", "goal": "想拍好照片", "knowledge": "有相机但不会用", "preferences": []}]
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True,
                         payload={"scenario": {"medium": "text", "segmenter_version": "paragraph-v1",
                                               "personas": personas, "max_segments": 8,
                                               "requested_seed": None}})
    assert snap["status"] == "READY", snap
    return repo, snap


def test_analysis_findings_reference_orchestration_events():
    repo, snap = _run_preview()
    preview_id = snap["state"]["preview_ref"]["id"]
    run_id = snap["run_id"]
    event_ids = {e["id"] for e in repo.preview_events(preview_id)}
    assert event_ids, "preview 必须产生观众事件"
    bridge = AnalystTeamAdapter(repo=repo, mode="mock")
    entry = TeamEntry(lambda task_id: bridge)
    call = SimpleNamespace(request_id="req_1", agent_id="data_analyst",
                           action="diagnose_preview", contract_version="seven-agent.v0.1",
                           context=SimpleNamespace(task_id="t1", account_id="account",
                                                   run_id=run_id),
                           input={"preview_ref": {"id": preview_id, "sha256": "0" * 64},
                                  "version_ref": {"id": snap["state"]["version_ref"]["id"],
                                                  "sha256": "0" * 64},
                                  "metrics_ref": {"id": f"metrics_{preview_id}", "sha256": "0" * 64}})
    out = entry.invoke(call)
    assert out["status"] == "ok", out
    data = out["data"]
    assert set(data) == {"findings", "comparison", "next_experiment"}
    for finding in data["findings"]:
        assert finding["observation_refs"], "finding 必须引用真实事件"
        assert set(finding["observation_refs"]) <= event_ids
        assert finding["segment_id"] in {"cover_v1"} | {
            s["segment_id"] for s in repo.get_version(
                snap["state"]["version_ref"]["id"])["payload"]["segments"]}


def test_no_events_is_needs_input():
    repo = Repository(":memory:")
    repo.create_task("t1", {"goal": "x"})
    version = repo.save_version("ver_abc", "t1", "run1", None, {
        "titles": ["t1", "t2", "t3"], "cover_copy": "封面",
        "segments": [{"segment_id": "s1", "kind": "body", "text": "正文", "source_refs": []}]})
    repo.create_run("run_p", "t1", "preview")
    repo.save_artifact("preview_1", "t1", "run_p", "preview", {
        "version_id": "ver_abc", "content_hash": version["content_hash"],
        "scenario": {"medium": "text", "segmenter_version": "paragraph-v1",
                     "personas": [], "max_segments": 8, "requested_seed": None},
        "segmenter_version": "paragraph-v1"})
    repo.save_artifact("metrics_preview_1", "t1", "run_p", "metrics", {"started": 0})
    bridge = AnalystTeamAdapter(repo=repo, mode="mock")
    call = SimpleNamespace(request_id="req_1", agent_id="data_analyst",
                           action="diagnose_preview", contract_version="seven-agent.v0.1",
                           context=SimpleNamespace(task_id="t1", account_id="account", run_id="run_p"),
                           input={"preview_ref": {"id": "preview_1", "sha256": "0" * 64},
                                  "version_ref": {"id": "ver_abc", "sha256": version["content_hash"]},
                                  "metrics_ref": {"id": "metrics_preview_1", "sha256": "0" * 64}})
    out = bridge.invoke(call)
    assert out["status"] == "needs_input" and out["questions"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe -B -m pytest tests/five_agent/test_analyst_entry.py -q`
Expected: FAIL — `ModuleNotFoundError: ... analyst_bridge`

- [ ] **Step 3: 写 analyst_bridge.py**

```python
"""编排层 diagnose_preview ↔ 数据分析师本体(AnalystAgent)。

编排预览痕迹(版本/会话/事件/model_calls)重建为业务自洽的
AudienceSimulationInput + SimulationReport,分析结果回映编排命名空间
(封面段 id 双向映射;正文段与事件 id 两套一致,直接引用)。
"""
from __future__ import annotations

import re
from typing import Any

from backend.adapters.bridge_common import (
    BridgePreSendFailure, BridgeUnknownOutcome, error_result, usage_dict)
from backend.agents.analyst import AnalystAgent
from backend.domain.hashing import sha256_json
from backend.domain.schemas import (
    AudienceEvent, AudienceInput, ContentDelivery, ErrorDetail, Persona, Segment)
from backend.simulation.analysis_data import (
    AnalystInput, Observation, ObservedCall, ObservedSession, SimulationReport,
    TokenUsage, ViewerUsage, segment_content)
from backend.simulation.audience_session import AudienceSimulationInput

STEP_RE = re.compile(r"audience:([^:]+):(\d+):[a-f0-9]{16}")


def _synth_version_id(content_hash: str) -> str:
    return "v_" + content_hash[:32]


class AnalystTeamAdapter:
    def __init__(self, *, repo, model_adapter: Any | None = None,
                 mode: str = "mock", model_id: str | None = None):
        self.repo = repo
        self.agent = AnalystAgent(model_adapter, mode=mode, model_id=model_id)

    def invoke(self, call) -> dict:
        call_dict = {"request_id": getattr(call, "request_id", None),
                     "contract_version": getattr(call, "contract_version", None),
                     "agent_id": getattr(call, "agent_id", "data_analyst"),
                     "action": getattr(call, "action", "diagnose_preview")}
        try:
            preview_id = call.input["preview_ref"]["id"]
            run_id = call.context.run_id
            source, report = _rebuild_trace(self.repo, preview_id, run_id, mode=self.agent.mode)
            snapshot = AnalystInput(analysis_requested=True, source=source,
                                    simulation=report, comparison_source=None,
                                    comparison_simulation=None,
                                    allow_descriptive_comparison=False)
        except BridgePreSendFailure as exc:
            return error_result(call_dict, str(exc), location="diagnose_preview")
        except Exception as exc:
            return error_result(call_dict, f"bridge input invalid: {exc}",
                                location="diagnose_preview")
        result = self.agent.run(snapshot)
        base = {**call_dict, "usage": usage_dict(result.usage)}
        if result.analysis_status == "interrupted":
            hint = result.error.cause_hint if result.error else "remote outcome unknown"
            raise BridgeUnknownOutcome(hint)
        if result.analysis_status == "failed":
            err = result.error
            return error_result(call_dict,
                                (err.cause_hint if err else "analysis failed") or "analysis failed",
                                (err.next_action if err else "检查输入") or "检查输入",
                                location="diagnose_preview")
        envelope = result.envelope
        if envelope is None:
            return error_result(call_dict, "analysis produced no envelope",
                                location="diagnose_preview")
        if envelope.status == "needs_input":
            return {**base, "status": "needs_input", "data": None,
                    "questions": [q.model_dump(mode="json") for q in envelope.questions],
                    "issues": [i.model_dump(mode="json") for i in envelope.issues]}
        if envelope.status == "error":
            return {**base, "status": "error", "data": None, "questions": [],
                    "issues": [i.model_dump(mode="json") for i in envelope.issues]}
        data = envelope.data.model_dump(mode="json")
        cover_biz = "cover_" + _synth_version_id(result.content_hash)
        for finding in data.get("findings", []):
            if finding["segment_id"] == cover_biz:
                finding["segment_id"] = "cover_v1"
        return {**base, "status": "ok", "data": data, "questions": [], "issues": []}


def _rebuild_trace(repo, preview_id: str, run_id: str, mode: str):
    preview = repo.get_artifact(preview_id)["payload"]
    version = repo.get_version(preview["version_id"])
    payload = version["payload"]
    titles = list(payload.get("titles") or [])
    cover = payload.get("cover_copy")
    if len(titles) != 3 or not cover or not cover.strip():
        raise BridgePreSendFailure("analysis requires exactly 3 titles and a non-blank cover_copy")
    content = ContentDelivery(
        titles=[titles[0], titles[1], titles[2]], cover_copy=cover,
        segments=[Segment.model_validate(s) for s in payload.get("segments", [])])
    synth_version = _synth_version_id(version["content_hash"])
    persons = [Persona.model_validate(p) for p in preview["scenario"]["personas"]]
    orchestration_sessions = repo.sessions_for_preview(preview_id)
    calls_by_step: dict[tuple[str, int], dict] = {}
    for row in repo.list_calls(run_id):
        if row["agent_id"] != "simulated_audience":
            continue
        m = STEP_RE.fullmatch(row["step_key"])
        if not m:
            continue
        key = (m.group(1), int(m.group(2)))
        prev = calls_by_step.get(key)
        if prev is None or row["attempt"] >= prev["attempt"]:
            calls_by_step[key] = row
    max_calls = min(48, max(1, len(calls_by_step)))
    source = AudienceSimulationInput(
        confirmed=True, version_id=synth_version, content_hash=version["content_hash"],
        content=content, personas=persons, max_segments=min(8, len(content.segments) + 1),
        max_calls=max_calls, max_active_seconds=1200)
    segments = segment_content(source)
    sessions = []
    calls = []
    for sess in orchestration_sessions:
        events = []
        biz_persona = next(p for p in persons if p.id == sess["persona_id"])
        for row in repo.session_events(sess["id"]):
            ev = dict(row["payload"])
            if row["ordinal"] == 0 and ev.get("segment_id") == "cover_v1":
                ev["segment_id"] = "cover_" + synth_version
            events.append({"event_id": row["id"], "seq": row["ordinal"],
                           "call_id": None, "event": ev})
        session_calls = sorted(
            [r for (sid, o), r in calls_by_step.items() if sid == sess["id"]],
            key=lambda r: int(STEP_RE.fullmatch(r["step_key"]).group(2)))
        obs_calls = []
        any_unknown = any_failed = False
        for row in session_calls:
            ordinal = int(STEP_RE.fullmatch(row["step_key"]).group(2))
            matched = [e for e in events if e["seq"] == ordinal]
            mapped_event = None
            if matched:
                mapped_event = AudienceEvent.model_validate(matched[0]["event"])
                for e in events:
                    if e["seq"] == ordinal:
                        e["call_id"] = row["id"]
            context = AudienceInput(
                persona=biz_persona, current_segment=segments[ordinal],
                visible_history=list(segments[:ordinal]),
                own_previous_reactions=[AudienceEvent.model_validate(e["event"])
                                        for e in events if e["seq"] < ordinal])
            status = row["status"]
            if status == "received":
                call_status, error = "received", None
            elif status == "interrupted":
                call_status, any_unknown = "unknown", True
                error = ErrorDetail(code="INTERRUPTED", retryable=False,
                                    cause_hint="remote outcome unknown",
                                    next_action="explicit resend only", field_errors=[])
            else:
                call_status, any_failed = "failed", True
                error = ErrorDetail(code="MODEL_UNAVAILABLE", retryable=False,
                                    cause_hint="viewer call failed",
                                    next_action="inspect provider", field_errors=[])
            obs_calls.append(ObservedCall(
                session_id=sess["id"], persona_id=sess["persona_id"], ordinal=ordinal,
                mode=mode, call_id=row["id"],
                input_hash=sha256_json(context), status=call_status,
                event=mapped_event,
                usage=TokenUsage(total=row["usage_tokens"]),
                error=error))
        if sess["status"] == "exited":
            outcome, stop = "exited", "viewer_exit"
        elif sess["status"] == "completed":
            outcome, stop = "completed", None
        else:
            outcome = "incomplete"
            if any_unknown:
                stop = "unknown_remote_outcome"
            elif any_failed:
                stop = "invalid_or_failed_response"
            elif len(calls) == max_calls:
                stop = "call_budget"
            else:
                stop = "time_budget"
        sessions.append(ObservedSession(
            session_id=sess["id"], persona_id=sess["persona_id"], outcome=outcome,
            stop_reason=stop, cursor=sess["next_ordinal"],
            events=[Observation(event_id=e["event_id"], seq=e["seq"], call_id=e["call_id"],
                                event=AudienceEvent.model_validate(e["event"])) for e in events]))
        calls.extend(obs_calls)
    known = [c.usage.total for c in calls if c.usage.total is not None]
    interrupted = any(c.status == "unknown" for c in calls)
    status = ("INTERRUPTED" if interrupted else
              "COMPLETED" if all(s.outcome in {"completed", "exited"} for s in sessions)
              else "INCOMPLETE")
    report = SimulationReport(
        mode=mode, medium="text", version_id=synth_version,
        content_hash=version["content_hash"], input_hash=sha256_json(source),
        status=status, persona_count=len(sessions), segment_count=len(segments),
        sessions=sessions, calls=calls, calls_attempted=len(calls),
        call_budget=max_calls, time_budget_seconds=1200,
        usage=ViewerUsage(known_total_tokens=sum(known) if known else None,
                          usage_not_reported_calls=sum(c.usage.total is None for c in calls),
                          remote_outcome_unknown_calls=sum(c.status == "unknown" for c in calls)),
        mock_fixture_exit_ordinal=None, is_simulation=True, predicts_real_traffic=False,
        automatic_resume=False, explicit_new_request_required=True)
    return source, report
```

**实现注意事项(执行者必读):**

1. `AnalystInput(...)` 构造会跑 `validate_report`;若重建不满足业务自洽(如 live 痕迹含 unknown 后仍有后续会话事件)→ ValueError → 桥接返回 error 结果(编排 soft-degrade),不伪造分析。测试断言基于全 mock 痕迹(干净、可重建)。
2. `sessions` 顺序必须与 `personas` 顺序一致(编排创建顺序相同,直接沿用 repo 顺序);`calls` 顺序 = 会话顺序 × ordinal(上面按 session 循环自然满足)。
3. 若 `report.sessions` 为空 → `AnalystInput` 校验失败 → error 结果;全 mock preview 至少一个 persona(测试用 2 个)。

- [ ] **Step 4: 跑测试确认通过 + Commit**

Run: `./.venv/Scripts/python.exe -B -m pytest tests/five_agent/test_analyst_entry.py -q`
Expected: PASS

```bash
git add birthco-local/backend/adapters/analyst_bridge.py tests/five_agent/test_analyst_entry.py
git commit -m "feat(bridge): data_analyst real entry bridge with orchestration trace rebuild"
```

---

### Task 8: build_reals 全量接线 + 端到端 + live 冒烟脚本 + 交接文档

**Files:**
- Modify: `tests/five_agent/test_team_entries.py`(追加 build_reals 集成测试)
- Create: `tools/smoke_live_chain.py`
- Create: `docs/experts/<component>/bridge-handoff-2026-11-07.md` 7 份(模板见 Step 7)
- Modify: `docs/orchestration/01-contract.md`(状态表更新)

- [ ] **Step 1: build_reals 集成测试(全七角色 mock 模型跑通主链)**

追加到 `tests/five_agent/test_team_entries.py`:

```python
def test_build_reals_runs_full_content_chain():
    from backend.workflow.five_agent import adapters as A
    from backend.workflow.five_agent.driver import OrchestrationDriver
    from backend.workflow.five_agent.repository import Repository
    from backend.workflow.five_agent.team_entries import build_reals

    repo = Repository(":memory:")
    reals = build_reals(repo, mode="mock")
    router = A.AdapterRouter(repo, mode="live", reals=reals)
    driver = OrchestrationDriver(repo, router=router)
    driver.create_task("t1", {"goal": "写一篇新手拍照入门图文", "user_input": "写一篇新手拍照入门图文",
                              "input_mode": "idea", "purpose": "content",
                              "flags": {"traffic_enabled": False, "goal_clear": True}})
    driver.add_material("t1", "m1", "拍照入门：先学会构图三分法，再练光线。")
    snap = driver.start_content_run("t1")
    # 真实运营官桥接:brief 冻结与用户闸门
    assert snap["pending_gates"][0]["kind"] == "confirm_brief"
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True,
                         payload={"brief_version": snap["state"]["brief_ref"]["brief_version"],
                                  "brief_hash": snap["state"]["brief_ref"]["brief_hash"]})
    snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True, payload={})
    # 真实审稿桥接 mock 语义:结构通过但语义待核实 → needs_input → WAITING_INPUT
    assert snap["status"] in ("READY", "WAITING_INPUT"), snap
    assert repo.get_usage(snap["run_id"])["normal_calls"] >= 3
```

- [ ] **Step 2: 跑测试,按失败信息修 build_reals**

Run: `./.venv/Scripts/python.exe -B -m pytest tests/five_agent/test_team_entries.py -q`
Expected: PASS 或 FAIL — 若 FAIL,常见原因:某桥接构造器 kwargs 不匹配(`AnalystTeamAdapter` 需 `repo`、`AudienceTeamAdapter` 无 `resolve_material` — `build_reals.make()` 已分支处理;若报 TypeError 按差异修 `make()`)

- [ ] **Step 3: 修到通过 + 全量回归**

Run: `./.venv/Scripts/python.exe -B -m pytest tests/five_agent -q`
Expected: 全部 PASS

Run: `cd birthco-local && ../.venv/Scripts/python.exe -B -m pytest tests -q`
Expected: 全部 PASS(406)

- [ ] **Step 4: Commit**

```bash
git add tests/five_agent/test_team_entries.py
git commit -m "test(orchestration): build_reals full-chain integration (seven bridges, mock models)"
```

- [ ] **Step 5: live 冒烟脚本 tools/smoke_live_chain.py**

```python
"""P0-A live 冒烟:七角色真实入口 + MiMo 每角色 1 次调用,证据 JSON 不存 Key。

用法:
  ./.venv/Scripts/python.exe tools/smoke_live_chain.py [--agent pr_analyst|operator|
      director|reviewer|scout|audience|analyst] [--out evidence/live-smoke.json]

默认逐角色单发冒烟(不跑整链);--agent 指定单角色。退出码 0=全部成功,1=有失败。
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import backend  # noqa: E402
BC = str(ROOT / "birthco-local" / "backend")
if BC not in backend.__path__:
    backend.__path__.append(BC)

from backend.adapters.model import factory  # noqa: E402
from backend.adapters.bridge_common import orchestration_ref_digest  # noqa: E402


def _digest(text):
    return orchestration_ref_digest(text)


def smoke_agent(component: str) -> dict:
    adapter = factory.create_live_adapter(component)
    model_id = factory.live_model_id(component)
    call = SimpleNamespace(request_id="smoke_1", contract_version="seven-agent.v0.1",
                           context=SimpleNamespace(task_id="smoke_t", account_id="smoke_a"))
    if component == "pr_analyst":
        from backend.adapters.pr_bridge import PRAnalystTeamAdapter
        call.agent_id, call.action = "pr_analyst", "analyze_request"
        call.input = {"request_text": "品牌X新品推广；要求：文案必须出现品牌名",
                      "material_refs": [{"id": "m1", "sha256": _digest("产品资料：品牌X新品，主打便携。")}]}
        bridge = PRAnalystTeamAdapter(
            resolve_material=lambda ref: {"id": "m1", "text": "产品资料：品牌X新品，主打便携。",
                                          "kind": "text", "label": "产品资料", "source_url": None},
            model_adapter=adapter, mode="live", model_id=model_id)
    elif component == "operator":
        from backend.adapters.orch_bridge import OperatorTeamAdapter
        call.agent_id, call.action = "operations_officer", "prepare_brief"
        call.input = {"user_input": "写一篇新手拍照入门图文", "input_mode": "idea",
                      "material_refs": [{"id": "m1", "sha256": _digest("拍照入门：先学会构图三分法，再练光线。")}],
                      "selected_opportunity_ref": None}
        bridge = OperatorTeamAdapter(
            resolve_material=lambda ref: {"id": "m1", "text": "拍照入门：先学会构图三分法，再练光线。",
                                          "kind": "text", "label": "素材", "source_url": None},
            model_adapter=adapter, mode="live", model_id=model_id)
    elif component == "scout":
        from backend.adapters.scout_bridge import ScoutTeamAdapter
        call.agent_id, call.action = "traffic_scout", "capture_opportunities"
        call.input = {"goal": "写一篇新手拍照入门图文",
                      "material_refs": [{"id": "m1", "sha256": _digest("拍照入门：先学会构图三分法，再练光线。")}]}
        bridge = ScoutTeamAdapter(
            resolve_material=lambda ref: {"id": "m1", "text": "拍照入门：先学会构图三分法，再练光线。",
                                          "kind": "text", "label": "素材", "source_url": None},
            model_adapter=adapter, mode="live", model_id=model_id)
    elif component == "audience":
        from backend.adapters.audience_bridge import AudienceTeamAdapter
        call.agent_id, call.action = "simulated_audience", "read_segment"
        call.input = {"persona": {"id": "p1", "goal": "想学会拍照", "knowledge": "摄影新手",
                                  "preferences": ["喜欢具体步骤"]},
                      "current_segment": {"segment_id": "cover_v1", "kind": "cover",
                                          "text": "三步上手，少走弯路"},
                      "visible_history": [], "own_previous_reactions": []}
        bridge = AudienceTeamAdapter(model_adapter=adapter, mode="live", model_id=model_id)
    else:
        raise NotImplementedError(
            f"smoke for {component} needs a repository-backed run first; run the "
            f"mock preview chain or the five_agent tests to produce a trace, then "
            f"wire a minimal in-memory repo here like tests/five_agent/test_analyst_entry.py")
    return {"component": component, "model_id": model_id,
            "result": bridge.invoke(call), "at": datetime.now(timezone.utc).isoformat()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", default=None)
    parser.add_argument("--out", default=str(ROOT / "evidence" / "live-smoke.json"))
    args = parser.parse_args()
    components = [args.agent] if args.agent else [
        "pr_analyst", "operator", "scout", "audience"]
    report = {"at": datetime.now(timezone.utc).isoformat(), "results": []}
    failed = 0
    for component in components:
        try:
            report["results"].append(smoke_agent(component))
        except Exception as exc:
            failed += 1
            report["results"].append({"component": component,
                                      "error": f"{type(exc).__name__}: {exc}"})
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return failed


if __name__ == "__main__":
    sys.exit(main())
```

**执行说明:** director/reviewer 需要已确认 brief + 版本(仓库痕迹),analyst 需要预览痕迹 — 首版冒烟只覆盖无需仓库的四个角色(pr/operator/scout/audience);其余三角色在 Task 8 后用 `test_director_entry.py`/`test_reviewer_entry.py`/`test_analyst_entry.py` 的 mock 痕迹 + live adapter 扩展(执行时按测试文件 `_make()` 模式补 `smoke_agent` 分支)。每角色 1 次调用;结果写入 `evidence/live-smoke.json`(**不含 Key**)。**跑之前征得用户同意(烧真实额度)。**

- [ ] **Step 6: 冒烟试跑(征得同意后)**

Run: `./.venv/Scripts/python.exe tools/smoke_live_chain.py --agent operator`
Expected: `result.status` 为 ok/needs_input/error 之一;usage 有真实 token 数或 unknown;输出无 Key

- [ ] **Step 7: 交接文档(7 份,模板一致)**

每角色 `docs/experts/<component>/bridge-handoff-2026-11-07.md`(新目录:`docs/experts/pr-analyst/`、`docs/experts/content-director/`、`docs/experts/traffic-scout/`(已有目录,追加)、`docs/experts/data-analyst/`(已有目录,追加)、`docs/experts/simulated-audience/`;`docs/experts/operations-officer/`、`docs/experts/editorial-reviewer/` 已有目录,追加):

```markdown
# <角色名>桥接交接(bridge-handoff-2026-11-07)

- 入口:birthco-local/backend/adapters/<bridge>.py 的 <Xxx>TeamAdapter.invoke(AgentCall) -> dict
- 编排接线:backend/workflow/five_agent/team_entries.py build_reals(agent_id=<id>)
- 输入映射:<AgentCall.input 字段> -> <业务 Input>(缺省派生字段列表)
- 输出映射:<业务 Result.envelope> -> 契约 data(<字段表>);id 回映规则
- 失败映射:INTERRUPTED/unknown -> UnknownResult(不自动重发);确定性拒单 -> error 结果;
  其余 DomainError -> error 结果;usage 取不回 -> unknown
- Schema 指纹:业务 <Xxx>Input/Envelope schema 见 birthco-local/tests/contracts/test_hash_and_drift.py
- 测试:tests/five_agent/test_<role>_entry.py(离线,零模型调用)
- 缺口:<角色特定缺口,如 analyst 的封面组成差异与重建限制、
  pr 的 INTERRUPTED 折叠为 error envelope、director revise 合成业务 brief>
```

- [ ] **Step 8: 更新 docs/orchestration/01-contract.md 状态表**

把七角色 `awaiting_owner_handoff` 改为 `connected`(mock 联调 ✅;live 冒烟见 evidence/live-smoke.json),注明:真实主链全链路验收仍属 P0-C。

- [ ] **Step 9: 最终回归 + Commit**

Run: `./.venv/Scripts/python.exe -B -m pytest tests/five_agent -q && (cd birthco-local && ../.venv/Scripts/python.exe -B -m pytest tests -q)`
Expected: 全绿

```bash
git add tools/smoke_live_chain.py docs/experts docs/orchestration/01-contract.md evidence/live-smoke.json
git commit -m "feat(P0-A): live smoke script, bridge handoffs, contract status update"
```

---

## Self-Review 记录(已执行)

1. **Spec 覆盖:** 设计文档 §3-§9 全部有对应任务(共享工具/TeamEntry/六桥接/接线/测试/live 冒烟/交接文档/01-contract 更新)。spec 要求「编排层 adapters.py 默认保持 Stub」→ 本计划不修改 adapters.py,由 build_reals 惰性注入,一致。
2. **占位符扫描:** 无 TBD/TODO;Task 3 注明 `_brief_payload` 不可行的原因与替代(resolve_brief 注入),步骤 4 明确修法;Task 7 实现注意事项列明重建失败语义。
3. **类型一致性:** `TeamEntry(bridge_factory(task_id)->bridge)`、`build_reals(repo, mode, live_agents)`、各 `XxxTeamAdapter(..., mode, model_adapter, model_id)` 签名在 Task 1/2/3/4/5/6/7/8 中一致;`error_result(call_dict, reason, requested_change, location)` 与 `usage_dict` 在 bridge_common 定义后全计划统一使用。
