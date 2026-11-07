# 七角色编排 · 使用说明（怎么用）

两种用法，按需选择：

| 用法 | 是什么 | 入口 |
|---|---|---|
| **A. 编排层 API（推荐）** | LangGraph 状态机把七角色串成一条业务流：闸门确认、预算、版本、恢复全自动管理 | 本仓库 `backend/workflow/five_agent/`（本文 §3-§5） |
| **B. 七角色单独运行** | 每个角色一个 CLI，文件交接，互不编排（并行任务的“众幕 AI”组件） | `birthco-local/tools/run_*.py`，说明见 `birthco-local/完整使用说明.md` |

两者是同一套七角色定义；B 的 CLI 是将来 A 的“真实 Adapter”候选入口（§5）。

## 1. 七角色一览（seven-agent.v0.1）

| # | 角色 | agent_id | action | 在流程里的位置 |
|---|---|---|---|---|
| 1 | 商单需求分析员 | pr_analyst | analyze_request | 商单任务最前（运营官之前） |
| 2 | 运营官 | operations_officer | prepare_brief | 整理 Brief（等你确认） |
| 3 | 内容主创 | content_creator | draft / revise | 写初稿、一次定向修订、局部改稿 |
| 4 | 审稿员 | editorial_reviewer | assess_content | 独立上下文审校 |
| 5 | 流量捕捉者 | traffic_scout | capture_opportunities | 可选：发现选题（独立预算） |
| 6 | 数据分析师 | data_analyst | diagnose_preview | 可选试映后的片段诊断 |
| 7 | 模拟观众 | simulated_audience | read_segment | 可选试映：逐段阅读反馈 |

普通内容任务走 2→3→4（+可选 5/6/7）；商单任务先走 1，其输出的客户硬性要求自动并入 Brief。

## 2. 环境准备（一次即可）

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install langgraph==1.1.10 jsonschema pytest
```

需要 Python 3.13。无 API Key、不联网也能跑（Mock 模式默认）。

## 3. 三分钟上手

```powershell
# 全部验证（55 项：契约/主链/分支/恢复预算/七角色）
python -m pytest tests/five_agent -q

# 端到端演示：主链 → 3 人试映 → 局部改稿 → 双版本导出，输出 evidence/mock-flow-evidence.json
python run_mock_demo.py
```

两个命令都应退出码 0。产物说明见 [04-verification.md](04-verification.md)。

## 4. 在代码里驱动完整流程

下面是一个可直接复制运行的脚本（保存为 `my_run.py` 放仓库根执行），
走**商单链**：商单分析 → 运营官 → 你确认 Brief → 主创 → 审稿 → 导出 → 你接受：

```python
from backend.workflow.five_agent.adapters import AdapterRouter
from backend.workflow.five_agent.driver import OrchestrationDriver
from backend.workflow.five_agent.repository import Repository

repo = Repository("data/app.sqlite")            # 持久化；":memory:" 只做实验
driver = OrchestrationDriver(repo, mode="mock") # mode="live" 走真实 Adapter（未接入则 AGENT_UNAVAILABLE）

# ① 建任务（purpose="commercial_order" 或带 client_brief 即走商单链）
driver.create_task("t1", {
    "goal": "品牌X新品推广文案", "user_input": "品牌X新品推广文案",
    "input_mode": "idea", "purpose": "commercial_order",
    "client_brief": "品牌X新品推广；要求：文案必须出现品牌名",
    "flags": {"traffic_enabled": False, "goal_clear": True}})
driver.add_material("t1", "mat1", "品牌X：主打便携与耐用。")

# ② 起内容 run，跑到第一个闸门（这里应是 confirm_brief）
snap = driver.start_content_run("t1")
print(snap["status"], [g["kind"] for g in snap["pending_gates"]])

# ③ 处理闸门：每个闸门都绑定具体版本/hash，决策带幂等键
gate = snap["pending_gates"][0]
brief = snap["state"]["brief_ref"]
snap = driver.decide(snap["run_id"], gate["id"], approved=True,
                     payload={"brief_version": brief["brief_version"],
                              "brief_hash": brief["brief_hash"]},
                     idempotency_key="confirm-1")

# ④ 接受交付 → 版本置 accepted
snap = driver.decide(snap["run_id"], snap["pending_gates"][0]["id"], approved=True,
                     payload={}, idempotency_key="accept-1")
print(snap["status"])                            # READY
version = repo.get_version(snap["state"]["version_ref"]["id"])
batch = repo.get_artifact(f"batch_{version['id']}")["payload"]
print(version["status"], batch["files"].keys())  # accepted dict_keys(['article.md', 'article.txt'])
```

常用 API（`OrchestrationDriver`）：

| 方法 | 用途 |
|---|---|
| `create_task / add_material` | 建任务、加授权材料 |
| `start_content_run` | 主链（含可选商单/流量分支） |
| `start_pr_analysis_run / start_scout_run` | 独立商单分析 / 独立选题发现 |
| `start_preview_run(task_id, version_id)` | 合格版本进入试映（下一步闸门确认场景+预算） |
| `start_revision_run(task_id, revision_request_id)` | 按用户选中的 finding 局部改稿 |
| `decide(run_id, gate_id, approved, payload, idempotency_key)` | 用户决策（确认/接受/选择）；重复提交同幂等键不重复计费 |
| `reject(run_id, gate_id)` | 拒绝闸门（可下载版本保留） |
| `cancel_run(run_id)` | 取消（迟到结果自动作废，不覆盖版本） |
| `confirm_interrupted_resend(run_id, cost_risk_confirmed=True)` | 调用结果未知时，确认费用风险后显式重发 |
| `reinvoke(run_id, {...})` | 崩溃恢复：按 resume_step 重入，已提交步骤零重复调用 |
| `snapshot(run_id)` | 状态/闸门/调用/用量一览 |

试映场景（确认 `preview_conditions` 闸门时放入 payload）：

```python
scenario = {"medium": "text", "segmenter_version": "paragraph-v1", "max_segments": 8,
            "requested_seed": None,
            "personas": [{"id": "p_exit_first", "goal": "随便看看", "knowledge": "零基础", "preferences": []},
                         {"id": "p_full", "goal": "学会拍照", "knowledge": "新手", "preferences": ["图文"]}]}
psnap = driver.start_preview_run("t1", version_id)
psnap = driver.decide(psnap["run_id"], psnap["pending_gates"][0]["id"], approved=True,
                      payload={"scenario": scenario, "budget_ack": True})
# 试映结束停在 select_findings：读 analysis，选 finding 后自动建 revision run
preview_id = psnap["state"]["preview_ref"]["id"]
analysis = repo.get_artifact(f"analysis_{preview_id}")["payload"]
psnap = driver.decide(psnap["run_id"], psnap["pending_gates"][0]["id"], approved=True,
                      payload={"finding_ids": [analysis["findings"][0]["id"]],
                               "allow_title_change": False, "allow_cover_change": False})
rev = driver.start_revision_run("t1", psnap["state"]["revision_ref"]["id"])
```

## 5. 换成真实队员实现（真实 Adapter）

当前七角色都是 Mock（`mode="mock"`）与 `AGENT_UNAVAILABLE` 占位（`mode="live"`）。
接入一位队员的真实实现只需两步（不动其他六个）：

1. 队员按 [01-contract.md](01-contract.md) §4 交接单提供：入口（可导入 Python 符号或
   受控 HTTP）、每个 action 的输入输出样例（含 needs_input/error）、调用次数/重试、
   usage 口径、凭据来源、依赖锁。
2. 在 `adapters.py` 写一个 `invoke(AgentCall) -> AgentResult` 的适配器（内部解析 Ref、
   调队员入口、映射字段），注册进 `AdapterRouter.reals`；跑同一套 `tests/five_agent/`
   契约测试即完成联调标记。

birthco-local 的 `tools/run_pr_analyst.py` 等七个 CLI（文件交接、Mock/`--live` 可切）
是现成的候选入口：用 Adapter 调它们的输入/输出文件即可，无需改队员代码。
约束不变：内部多次调用必须逐次过中央预算、不许隐藏重试/自动修 JSON/换模型、
live 模式绝不回退 Mock。

## 6. 常见问题

- **想跳过商单分析**：任务不用 `purpose="commercial_order"`、不带 `client_brief` 即可（普通任务零商单调用）。
- **想跳过试映**：不调 `start_preview_run`；未选 finding 不会自动改稿。
- **调用结果未知 / 费用风险**：run 停在 INTERRUPTED，`snapshot` 里看 call 记录，
  确认后 `confirm_interrupted_resend`。不会自动重发。
- **Mock 想模拟失败/缺料**：`AdapterRouter(scripts={("pr_analyst", "analyze_request"): [needs_input(...), ok(...)]})`
  脚本队列按调用顺序出牌（behaviour：`ok / needs_input / error / tech_error / protocol_garbage`）。
- **预算**：内容链 5 正常+2 技术重试上限、试映 53 次、流量 3+2、商单分析 3+1（各记各的账）；
  超限报 `BUDGET_EXCEEDED`，回执重放不计费。

## 7. 相关文档

- [00-overview.md](00-overview.md) 流程图与条件边表 · [01-contract.md](01-contract.md) 契约与接入清单
- [02-orchestration.md](02-orchestration.md) 编排实现 · [03-control.md](03-control.md) 确认/版本/预算/恢复
- [04-verification.md](04-verification.md) 验证与缺口 · `birthco-local/完整使用说明.md` 七角色 CLI 用法
