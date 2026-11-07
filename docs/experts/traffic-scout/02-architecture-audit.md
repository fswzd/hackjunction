# traffic_scout 架构审计报告（12 层 Agent 栈）

- schema: `hackjunction.agent-architecture-audit.report.v1`
- 审计对象：traffic_scout（流量捕捉者）全链路 —— `backend/workflow/five_agent/` 编排层 + `birthco-local/backend/agents/scout.py` 本体
- 代码基线：`evidence/source-snapshot.json`（git_head `809af8a085`，63 文件 sha256）
- 结论：**high_risk** —— 4 个疑似缺陷全部证实；其中 2 个直接威胁即将开展的新能力（真实 Adapter 接入、收据重放正确性）

## 总裁决

| 项 | 结论 |
|---|---|
| overall_health | high_risk |
| primary_failure_mode | 持久化层陈旧状态被当作活证据（指纹缺口 + 子 run 泄漏 + 在途记账不可见） |
| most_urgent_fix | 按 agent 的 mock/live 路由（不修则真实 Adapter 无法单角色接入） |

## 按严重度排序的发现

### F-01 [high] step_key 指纹不含素材内容 hash，收据重放可返回陈旧结果
- 层：12 persistence（叠加 2 session history）
- 机制：收据查找只按 `(run_id, step_key)` 命中即回放，不比对 `input_hash`；而 step_key 指纹只含 goal + 素材 ID 列表，不含素材正文 sha256。素材正文在同 ID 下被修改后，重跑/恢复会静默重放旧机会卡。
- 证据：`nodes.py:213`（`_fp({"goal": goal, "materials": [r["id"]...]})`，对比 `nodes.py:200-201` 素材实际带 sha256）、`gateway.py:129-133`（receipt 命中直接回放）、`repository.py:450-453`（`get_step_output` 无 input_hash 条件）。同型问题：`nodes.py:148-149`（pr）、`nodes.py:307`（brief）。
- 根因：指纹分层错误——把「寻址键」当「内容承诺」。
- 修复（code-first）：① 指纹纳入 `material sha256`（及 brief 的 selected opportunity hash）；② 回放前校验 `receipt["input_hash"] == frozen_input_hash(input)`，不一致按新步骤处理。两道都上，②兜底。
- 置信度：0.95

### F-02 [high] scout 子 run 创建后永不终结（RUNNING 泄漏）
- 层：12 persistence
- 机制：内容 run 内的流量分支创建 `{run_id}_scout` 子 run 并置 RUNNING，此后 ok / needs_input / error 三条出口都只对 `state["run_id"]` 写终态，子 run 永远停在 RUNNING（仅 INTERRUPTED 路径经 gateway 会终结它）。
- 证据：`nodes.py:205-210`（create + RUNNING）、`nodes.py:227-243`（出口状态补丁均不含 scout_run_id 的 set_run_status）、`gateway.py:167`（仅中断路径）。
- 根因：子 run 生命周期没有归属节点。
- 修复：在 `node_traffic` 全部出口映射子 run 终态（ok→READY、needs_input→WAITING_INPUT、error→NEEDS_REVIEW），并补一条「子 run 终结」回归测试。
- 置信度：0.92

### F-03 [high] AdapterRouter live 全有或全无，单角色灰度不可能
- 层：6 tool selection（wrapper regression）
- 机制：路由只有一个全局 `mode`，live 时七个角色全部指向 RealAdapterStub；接入 traffic_scout 真实 Adapter 会把其余角色一并切到不可用。
- 证据：`adapters.py:468-473`（单 mode）、`adapters.py:544-549`（`adapter_for` 仅按 mode 二选一）、`adapters.py:518-526`（reals 全 stub）。
- 修复：按 agent_id 的模式映射（`{agent_id: mock|live|stub}`，默认 mock），registry 单点配置；这同时是「新能力先行」路线的接入前置。
- 置信度：0.97

### F-04 [medium] 预算记账在途不可见；崩溃窗口丢 attempt
- 层：12 persistence
- 机制：`record_reservation` 是空操作（注释称记账随 completion/failure 原子提交）；`reserve_call` 只写 `model_calls` 行不动 `usage_ledger`。send 后、complete 前进程崩溃 → 该 attempt 永不计数，`model_calls` 滞留 `sent`，后续预算检查（`check_and_reserve` 读 usage_ledger）少算，3+2 调用上限可被突破。
- 证据：`gateway.py:95-97`（no-op）、`repository.py:362-369`（reserve 不记账）、`repository.py:374-430`（三处终态才 +1）。
- 修复：启动扫描滞留 `sent` 行转 INTERRUPTED 并补记；或 reserve 即预记 + 终态结算差额。
- 置信度：0.85（常规路径原子性良好，缺陷窗口限崩溃/并发）

### F-05 [medium] 错误诊断丢失：error_ref 占位 + raise-from-None
- 层：9 answer shaping / 12
- 机制：发现模式失败分支的 `error_ref` 是占位符（指向 run_id 而非诊断记录），issues 不落库；本体校验失败 `from None` 丢弃原始 ValidationError 链（有意防泄漏，但未留受控诊断码）。
- 证据：`nodes.py:220-222`、`scout.py:139`。
- 修复：校验失败落「错误码清单」（不含原文）到 artifact/event；error_ref 指向真实诊断产物。
- 置信度：0.80

### F-06 [medium] 同一角色双实现漂移（mock 生成器 vs 本体）
- 层：1 system prompt / 6
- 机制：编排层 `MockAgent(gen_opportunities)` 与 `birthco-local ScoutAgent` 是同一角色的两套实现：输入形状不同（`{goal, material_refs}` vs `ScoutInput`）、输出包裹不同（`OpportunitySet` 直出 vs `Envelope[OpportunitySet]`）、校验深度不同。评测与真实接入之间口径会漂。
- 证据：`adapters.py:501-505`、`scout.py:37-55`、`resources/agent-interface-seven.json`（input_types）。
- 修复：已决策建桥接夹具；补一条「权威契约单一来源」约束 + mock 生成器走同一 schema 校验。
- 置信度：0.90

### F-07 [medium] evidence/ 基线陈旧/不可复现，有被当活证据的风险
- 层：4 distillation（伪事实回流）
- 证据：`evidence/mock-flow-evidence.json` 的 traffic_scout 隔离审计为空（演示以 traffic_enabled=false 运行）；`evidence/baseline-interface-checks.json` 为 five-agent.v0.2、来自仓库外 cwd 的路径清单，本树不可复现。
- 修复：已决策重建 benchmark（traffic_enabled=true 重跑 + seven-agent.v0.1 重建基线）；凭据-指纹绑定，源码变动即失效。
- 置信度：0.95

### F-08 [high·security] an.py 明文模型 Key
- 证据：`an.py:6-10`（base_url + model + 明文 key）。
- 修复：任何 live 接线（含 MiMo transport）之前轮换 Key 并移入环境配置；仓库保留 `.env.example`。
- 置信度：1.0

### F-09 [low] prompt-only 约束与 code-enforced 约束未分层声明
- 层：1/6（tool discipline）
- 机制：SYSTEM 提示词的「不编造热点/不自作选择/不改 Brief」等靠模型自觉；`_validate()` 只强制结构不变量（引用边界、计数、evidence_date=null、非空、去重）。二者混在一段提示词里，验收时会误把 prompt-only 当硬保证。
- 证据：`scout.py:58-63`（SYSTEM）对比 `scout.py:143-166`（_validate 实际强制项）。
- 修复：契约文档显式列出「code-enforced vs prompt-only」两栏；prompt-only 项进评测集。
- 置信度：0.75

### F-10 [low] mock 自足生成路径需保持标签纪律
- 层：7 tool execution（模拟执行）
- 机制：无 adapter 时先内联生成 envelope 再经 `MockAdapter` 回放走完校验——当前输出带 Mock 标记（summary/hypothesis/mode），且 live 强制显式 adapter（`scout.py:90-93`），风险受控；但若未来放宽 live 门禁会变自证循环。
- 修复：保持 live 显式 adapter 门禁为不变量；mock 产物必须携带 mode 标记（已具备，回归锁定）。
- 置信度：0.70

### F-11 [low] 失败分支未测：预算耗尽、INTERRUPTED→重发、scout 独立图
- `BudgetProfile(3+2/20k)` 耗尽路径、`confirm_interrupted_resend`（`driver.py:236-241`）、`start_scout_run` 独立图（traffic→stop）均无测试覆盖。→ 评测/回归阶段建夹具。
- 置信度：0.85

## 4 个疑似缺陷的裁定

| 疑似缺陷 | 裁定 | 说明 |
|---|---|---|
| step_key 指纹不含素材内容 hash | **证实**（F-01） | 收据回放不比对 input_hash，机制成立 |
| scout 子 run 不终结 | **证实**（F-02） | 仅中断路径会终结子 run |
| BudgetGate.record_reservation 空操作 | **证实但降级为 medium**（F-04） | 注释显示是有意设计；真实缺口限崩溃窗口 |
| live 路由全有或全无 | **证实**（F-03） | 单 mode 二选一，无法单角色灰度 |

## 架构诊断（哪层污染了什么）

持久化层（12）是重灾区：指纹缺口使「历史结果」冒充「当前结果」（F-01），子 run 泄漏使「未完成」冒充「运行中」（F-02），在途记账缺失使「已花费」不可见（F-04）。工具选择层（6）的单模式路由把「接入一个角色」变成「切换全部角色」（F-03）。双实现（F-06）+ 陈旧证据（F-07）构成包装回归温床：mock 结果与真实本体结果不同源、不同严，评测口径会漂。提示词层（1）本身无指令冲突，但 prompt-only 与 code-enforced 未分层（F-09）。无隐藏修复环（技术重试走显式预算、live 绝不回退 mock，这两处纪律是好的）。

## 有序修复计划（code-first）

| 序 | 修复 | 为什么现在 | 预期效果 |
|---|---|---|---|
| 1 | F-03 按 agent 路由模式 | 阻塞「新能力先行」的真实 Adapter 接入 | 可单角色灰度 traffic_scout |
| 2 | F-01 指纹+回放 input_hash 校验；F-02 子 run 终结 | 直接决定真实 Adapter 产出的正确性，建议随接入一并修（RFC-2 走评审） | 重放不再返回陈旧机会卡 |
| 3 | F-08 Key 轮换 + env 化 | 任何 live 前置 | 消除泄漏面 |
| 4 | F-04 滞留 sent 归宿 + 预记账 | RFC-2 批次 | 预算上限可信 |
| 5 | F-05 诊断码落库 | RFC-2 批次 | 失败可定位 |
| 6 | F-06 桥接夹具 + 契约单一来源；F-07 重建 benchmark；F-11 夹具 | 已决策，随评测阶段 | 口径统一、基线可复现 |
| 7 | F-09/F-10 契约分层声明 + 回归锁定 | 文档/评测层 | 保证边界不被误述 |

## 快速诊断问答

| # | 问题 | 结论 |
|---|---|---|
| 1 | 模型能否跳过必需工具仍出答案？ | 无工具面；prompt-only 约束可绕过 → F-09 |
| 2 | 旧内容会进新轮次吗？ | 会——收据重放路径 → F-01 |
| 3 | 同一信息多处注入？ | 轻微（system schema + user context） |
| 4 | 平台有二次 LLM 修复 pass？ | 无；技术重试显式计数，mock 回退显式标注 |
| 5 | 内部生成与交付不一致？ | 未发现渲染层改动 |
| 6 | 「必须用 X」只写在提示词？ | 是（行为类约束） → F-09 |
| 7 | 独白会进持久记忆？ | 无记忆系统；产物为 typed artifact，暂无污染路径 |
