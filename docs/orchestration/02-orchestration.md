# 交付物 3 · LangGraph 编排与 Adapter

代码根：`backend/workflow/five_agent/`（本 checkout 即团队工作仓；交接包建议的
`birthco-local/` 前缀不存在，按“工作根目录为当前 checkout”落位——决策 D-01）。

## 1. 模块职责

| 模块 | 职责 |
|---|---|
| [contracts.py](../../backend/workflow/five_agent/contracts.py) | AgentCall/AgentResult 数据类、canonical JSON、input_hash、契约校验器 |
| [registry.py](../../backend/workflow/five_agent/registry.py) | 五角色/七 action/预算档/step_key 规则/闸门种类 |
| [repository.py](../../backend/workflow/five_agent/repository.py) | SQLite 领域事实源：任务/材料/Brief(复合键)/版本/artifact/runs/调用与回执/usage/闸门/命令/观众会话事件 |
| [gateway.py](../../backend/workflow/five_agent/gateway.py) | 中央 Gateway：回执重放→预算预留→发送意图→Adapter→结果校验→原子落库；技术重试池；INTERRUPTED；取消 epoch fence |
| [projection.py](../../backend/workflow/five_agent/projection.py) | 各 action 输入投影、AudienceInput 四字段与未来/跨会话泄漏断言 |
| [program.py](../../backend/workflow/five_agent/program.py) | content-rules-v1 规则、预览指标计算、局部修订 scope 校验（零模型） |
| [adapters.py](../../backend/workflow/five_agent/adapters.py) | AgentAdapter 协议、五个可脚本化 MockAgent、真实实现占位（AGENT_UNAVAILABLE）、路由（live 永不回退 Mock） |
| [graphstate.py](../../backend/workflow/five_agent/graphstate.py) | GraphState（仅引用+程序控制字段；禁 Key/连接/消息累积）、Services 注入 |
| [nodes.py](../../backend/workflow/five_agent/nodes.py) | 节点函数（幂等）+ 条件路由（读合法状态，非模型输出） |
| [graph.py](../../backend/workflow/five_agent/graph.py) | 按 run.kind 编译固定图（content/preview/revision/scout/export）+ resume_step 入口路由 |
| [driver.py](../../backend/workflow/five_agent/driver.py) | 运行驱动：单 worker 槽、闸门决策受理、Command(resume)、取消、断点重入 |

## 2. 一次调用的完整路径（step 协议）

```
节点 → Gateway.invoke(run_id, step_key, action, input)
  1 查 (run_id, step_key) 已提交回执 → 直接重放（0 调用）
  2 run guard（取消/epoch）→ 预算闸门（正常/重试/总量/token）
  3 构造 AgentCall（context 服务端生成）→ 契约校验
  4 reserve 调用行 → 发送意图标记 → adapter.invoke
  5 结果校验（关联键/usage 语义/输出 DTO/引用）
  6 workflow_step_outputs + call received + usage 同事务落库
  7 返回 StepOutcome；节点做领域提交（版本/事件/artifact，幂等键落库）
```

失败分类：发送前技术失败/协议失败 → 共享重试池（attempt+1，逻辑 step_key 不变）；
发送后结果未知 → INTERRUPTED（usage 未知保留，不自动重发，用户确认费用风险后显式重发）；
取消后迟到结果 → epoch fence 拒绝提交，只记 usage=discarded。

## 3. Adapter 与 Mock

```python
AgentAdapter.invoke(AgentCall) -> AgentResult   # 唯一边界
```

- **MockAgent**（开发模式）：确定性行为 + 可脚本队列（ok / needs_input / error /
  发送前失败 / 发送后 unknown / 协议垃圾）。默认生成器产出满足 DTO 的合成产物；
  `gen_revision` 按 finding/issue 两类 scope 只改授权片段；`gen_analysis` 的
  observation_refs 引用真实已提交事件 id。每次调用记录 `model_visible_input`
  （= call.input 投影）供隔离断言。
- **RealAdapterStub**（正式模式）：`awaiting_owner_handoff` → 抛
  `AGENT_UNAVAILABLE`，**绝不静默换 Mock**（agent-interface.json 约束）。
- 适配真实入口时：Adapter 解析 Ref（Repository 再校验）→ 组装队员入口所需参数
  → 封装 Python 函数或 HTTP；隐藏重试/自动修 JSON/换模型/多加调用一律禁止，
  内部多次调用必须逐次过中央预算。

## 4. 状态与图

- GraphState 只存：run 绑定（account/task/run/kind/workflow_version/graph_state_schema/
  resume_step）+ typed refs（brief/version/rule/review/gate/preview/revision/cursor/
  artifact_batch/error）+ 程序控制（route_decision/repair_count/terminal）。
- 领域状态/预算/权限每次从 Repository 重读；state 中的旧快照不授予权限。
- 节点形状 `node(state, services) -> StatePatch`；patch 过 `validate_state_patch`
  （禁字段检查）。恢复时节点可能从头执行 → 幂等在业务层落实（回执、闸门 subject hash、
  artifact/版本确定性 id）。
- 四张固定图 + START 入口按持久化 resume_step 路由（`graph.py: ENTRY_MAP`），
  重启不重复执行已提交步骤。

## 5. 单 worker 与恢复边界

- `global_running_limit=1`：driver 持执行槽；等待用户时释放（WAITING 不占槽）。
- 崩溃恢复：领域回执是事实源；`driver.reinvoke(run_id, {resume_step, refs})` 从
  resume_step 重入，Gateway 自动回执重放（测试 `test_restart_replays_committed_receipts_zero_new_calls`）。
- 框架 checkpoint 现用 `MemorySaver`（进程内）。**缺口**：`langgraph-checkpoint-sqlite`
  未安装，跨进程断点依赖领域回执 + 显式 reinvoke；接入 LG02 owner 后换 SqliteSaver
  （graph.sqlite），不做自研 Saver。

## 6. 决策记录（实现取舍）

| # | 决策 | 理由 |
|---|---|---|
| D-01 | 代码落位仓库根 `backend/workflow/five_agent/` | 当前 checkout 无 birthco-local；交接单允许集成负责人绑定真实目录 |
| D-02 | 流量捕捉记账在显式 scout 子 run（内容图内分支） | “独立显式 run、不暗塞入内容 3 次”与“主链内分支”两者兼顾 |
| D-03 | 观众 unknown/超时 → 会话 incomplete + 继续其他会话（仅 read_segment） | 交互设计 §9 示例；其余 action 的 unknown 仍 run 级 INTERRUPTED |
| D-04 | metadata_update 修订条目豁免 finding/issue 引用检查（标题/封面仍受 allow_* 限制） | Revision DTO change_log minItems=1；纯元数据修改的合法表达 |
| D-05 | 版本/artifact/会话 id 用内容哈希截断（≤64 字符） | 满足 Id pattern；同 step 重放得同 id（幂等） |
| D-06 | 闸门拒绝也走 resume 回节点再终态；拒绝决策同样幂等 | 保持单一 resume 通道与“拒绝→停止”语义 |
